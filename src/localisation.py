"""Wraps gettext, to localise all UI text."""
import io
from typing import (
    AsyncIterator, Callable, Dict, Iterable, Iterator, List, Mapping, Sequence, TYPE_CHECKING,
    Tuple, TypeVar,
    Union,
    cast,
)

from srctools.filesys import RawFileSystem
from typing_extensions import ParamSpec, Final, TypeAlias
from weakref import WeakKeyDictionary, WeakSet
import gettext as gettext_mod
import locale
import sys

import trio
import attrs
from srctools import EmptyMapping, FileSystem, logger

from config.gen_opts import GenOptions
import config
import utils

if TYPE_CHECKING:  # Don't import at runtime, we don't want TK in the compiler.
    import tkinter as tk
    from tkinter import ttk
    import packages

__all__ = [
    'TransToken', 'load_basemodui',
    'DUMMY', 'Language', 'set_language', 'load_package_langs',
    'setup', 'expand_langcode',
]

LOGGER = logger.get_logger(__name__)
P = ParamSpec('P')

NS_UI: Final = '<BEE2>'  # Our UI translations.
NS_GAME: Final = '<PORTAL2>'   # Lookup from basemodui.txt
NS_UNTRANSLATED: Final = '<NOTRANSLATE>'  # Legacy values which don't have translation
# The prefix for all Valve's editor keys.
PETI_KEY_PREFIX: Final = 'PORTAL2_PuzzleEditor'

# The loaded translations from basemodui.txt
GAME_TRANSLATIONS: Dict[str, str] = {}

# Widgets that have a 'text' property.
TextWidget: TypeAlias = Union[
    'tk.Label', 'tk.LabelFrame', 'tk.Button', 'tk.Radiobutton', 'tk.Checkbutton',
    'ttk.Label', 'ttk.LabelFrame', 'ttk.Button', 'ttk.Radiobutton', 'ttk.Checkbutton'
]
TextWidgetT = TypeVar('TextWidgetT', bound=TextWidget)
# Assigns to widget['text'].
_applied_tokens: 'WeakKeyDictionary[TextWidget, TransToken]' = WeakKeyDictionary()
# menu -> index -> token.
_applied_menu_tokens: 'WeakKeyDictionary[tk.Menu, Dict[int, TransToken]]' = WeakKeyDictionary()
# For anything else, this is called which will apply tokens.
_langchange_callback: List[Callable[[], object]] = []
# Track all loaded tokens, so we can export those back out to the packages.
_loaded_tokens: 'WeakSet[TransToken]' = WeakSet()

FOLDER = utils.install_path('i18n')
PARSE_CANCEL = trio.CancelScope()


@attrs.frozen
class Language:
    """Wrapper around the GNU translator, storing the filename and display name."""
    display_name: str
    lang_code: str
    _trans: Dict[str, gettext_mod.NullTranslations]


# The current language.
_CURRENT_LANG = Language(
    '<None>', 'en', {},
)
# Special language which replaces all text with ## to easily identify untranslatable text.
DUMMY: Final = Language('Dummy', 'dummy', {})

PACKAGE_HEADER = """\
# Translations template for BEEmod package "PROJECT".
# Built with BEEmod version VERSION.
#"""


@attrs.frozen(eq=False)
class TransToken:
    """A named section of text that can be translated later on."""
    # The package name, or a NS_* constant.
    namespace: str
    # The token to lookup, or the default if undefined.
    token: str
    # Keyword arguments passed when formatting.
    # If a blank dict is passed, use EmptyMapping to save memory.
    parameters: Mapping[str, object] = attrs.field(converter=lambda m: m or EmptyMapping)

    def __attrs_post_init__(self) -> None:
        _loaded_tokens.add(self)

    @classmethod
    def parse(cls, package: str, text: str) -> 'TransToken':
        """Parse a string to find a translation token, if any."""
        if text.startswith('[['):  # "[[package]] default"
            try:
                package, token = text[2:].split(']]', 1)
                token = token.lstrip()  # Allow whitespace between "]" and text.
                # Don't allow specifying our special namespaces.
                if package.startswith('<') or package.endswith('>'):
                    raise ValueError
            except ValueError:
                LOGGER.warning('Unparsable translation token - expected "[[package]] text", got:\n{}', text)
                return cls(package, text, EmptyMapping)
            else:
                if not package:
                    package = NS_UNTRANSLATED
                return cls(package, token, EmptyMapping)
        elif text.startswith(PETI_KEY_PREFIX):
            return cls(NS_GAME, text, EmptyMapping)
        else:
            return cls(package, text, EmptyMapping)

    @classmethod
    def ui(cls, token: str, /, **kwargs: str) -> 'TransToken':
        """Make a token for a UI string."""
        return cls(NS_UI, token, kwargs)

    @staticmethod
    def ui_plural(singular: str, plural: str,  /, **kwargs: str) -> 'PluralTransToken':
        """Make a plural token for a UI string."""
        return PluralTransToken(NS_UI, singular, kwargs, plural)

    def join(self, children: Iterable['TransToken'], sort: bool=False) -> 'JoinTransToken':
        """Use this as a separator to join other tokens together."""
        return JoinTransToken(self.namespace, self.token, self.parameters, list(children), sort)

    @classmethod
    def from_valve(cls, text: str) -> 'TransToken':
        """Make a token for a string that should be looked up in Valve's translation files."""
        return cls(NS_GAME, text, EmptyMapping)

    @classmethod
    def untranslated(cls, text: str) -> 'TransToken':
        """Make a token that is not actually translated at all.

        In this case, the token is the literal text to use.
        """
        return cls(NS_UNTRANSLATED, text, EmptyMapping)

    @property
    def is_game(self) -> bool:
        """Check if this is a token from basemodui."""
        return self.namespace == NS_GAME

    @property
    def is_untranslated(self) -> bool:
        """Check if this is literal text."""
        return self.namespace == NS_UNTRANSLATED

    @property
    def is_ui(self) -> bool:
        """Check if this is builtin UI text."""
        return self.namespace == NS_UI

    def format(self, /, **kwargs: object) -> 'TransToken':
        """Return a new token with the provided parameters added in."""
        return attrs.evolve(self, parameters={**self.parameters, **kwargs})

    def as_game_token(self) -> str:
        """Return the value which should be written in files read by the game.

        If this is a Valve token, the raw token is returned so the game can do the translation.
        In all other cases, we do the translation immediately.
        """
        if self.namespace == NS_GAME and not self.parameters:
            return self.token
        return str(self)

    def __bool__(self) -> bool:
        """The boolean value of a token is whether the token is entirely blank.

        In that case it's not going to translate to anything.
        """
        return self.token != '' and not self.token.isspace()

    def __eq__(self, other) -> bool:
        if type(other) is TransToken:
            return (
                self.namespace == other.namespace and
                self.token == other.token and
                self.parameters == other.parameters
            )
        return NotImplemented

    def __hash__(self) -> int:
        """Allow hashing the token."""
        return hash((
            self.namespace, self.token,
            frozenset(self.parameters.items()),
        ))

    def __str__(self) -> str:
        """Calling str on a token translates it."""
        # If in the untranslated namespace or blank, don't translate.
        if self.namespace == NS_UNTRANSLATED or not self.token:
            result = self.token
        elif _CURRENT_LANG is DUMMY:
            return '#' * len(self.token)
        elif self.namespace == NS_GAME:
            try:
                result = GAME_TRANSLATIONS[self.token]
            except KeyError:
                result = self.token
        else:
            try:
                # noinspection PyProtectedMember
                result = _CURRENT_LANG._trans[self.namespace].gettext(self.token)
            except KeyError:
                result = self.token
        if self.parameters:
            return result.format_map(self.parameters)
        else:
            return result

    def apply(self, widget: TextWidgetT) -> TextWidgetT:
        """Apply this text to the specified label/button/etc."""
        widget['text'] = str(self)
        _applied_tokens[widget] = self
        return widget

    def apply_title(self, win: Union['tk.Toplevel', 'tk.Tk']) -> None:
        """Set the title of a window to this token."""
        self.add_callback(lambda: win.title(str(self)))

    def apply_menu(self, menu: 'tk.Menu', index: Union[str, int] = 'end') -> None:
        """Apply this text to the item on the specified menu.

        By default, it is applied to the last item.
        """
        try:
            tok_map = _applied_menu_tokens[menu]
        except KeyError:
            tok_map = _applied_menu_tokens[menu] = {}
        ind = menu.index(index)
        menu.entryconfigure(ind, label=str(self))
        tok_map[ind] = self

    @classmethod
    def clear_stored_menu(cls, menu: 'tk.Menu') -> None:
        """Clear the tokens for the specified menu."""
        _applied_menu_tokens.pop(menu, None)

    @classmethod
    def add_callback(cls, func: Callable[[], object], call: bool = True) -> None:
        """Register a function which is called after translations are reloaded.

        This should be used to re-apply tokens in complicated situations after languages change.
        If call is true, the function will immediately be called to apply it now.
        """
        _langchange_callback.append(func)
        if call:
            func()


# Token, package id and "source" string, for updating translation files.
TransTokenSource = Tuple[TransToken, str, str]


@attrs.frozen(eq=False)
class PluralTransToken(TransToken):
    """A pair of tokens, swapped between depending on the number of items.

    It must be formatted with an "n" parameter.
    """
    token_plural: str

    ui = ui_plural = untranslated = from_valve = None  # Cannot construct via these.

    def join(self, children: Iterable['TransToken'], sort: bool = False) -> 'JoinTransToken':
        """Joining is not allowed."""
        raise NotImplementedError('This is not allowed.')

    def __eq__(self, other) -> bool:
        if type(other) is PluralTransToken:
            return (
                self.namespace == other.namespace and
                self.token == other.token and
                self.token_plural == other.token_plural and
                self.parameters == other.parameters
            )
        return NotImplemented

    def __hash__(self) -> int:
        """Allow hashing the token."""
        return hash((
            self.namespace, self.token, self.token_plural,
            frozenset(self.parameters.items()),
        ))

    def __str__(self) -> str:
        """Calling str on a token translates it. Plural tokens require an "n" parameter."""
        try:
            n = int(cast(str, self.parameters['n']))
        except KeyError:
            raise ValueError('Plural token requires "n" parameter!')

        # If in the untranslated namespace or blank, don't translate.
        if self.namespace == NS_UNTRANSLATED or not self.token:
            result = self.token if n == 1 else self.token_plural
        elif _CURRENT_LANG is DUMMY:
            return '#' * len(self.token if n == 1 else self.token_plural)
        elif self.namespace == NS_GAME:
            raise ValueError('Game namespace cannot be pluralised!')
        else:
            try:
                # noinspection PyProtectedMember
                result = _CURRENT_LANG._trans[self.namespace].ngettext(self.token, self.token_plural, n)
            except KeyError:
                result = self.token

        if self.parameters:
            return result.format_map(self.parameters)
        else:
            return result


@attrs.frozen(eq=False)
class JoinTransToken(TransToken):
    """A list of tokens which will be joined together to form a list.

    The token is the joining value.
    """
    children: Sequence[TransToken]
    sort: bool

    def __hash__(self) -> int:
        return hash((self.namespace, self.token, *self.children))

    def __eq__(self, other) -> bool:
        if type(other) is JoinTransToken:
            return (
                self.namespace == other.namespace and
                self.token == other.token and
                self.children == other.children
            )
        return NotImplemented

    def __str__(self) -> str:
        """Translate the token."""
        sep = super().__str__()
        items = [str(child) for child in self.children]
        if self.sort:
            items.sort()
        return sep.join(items)


def expand_langcode(lang_code: str) -> List[str]:
    """If a language is a lang/country specific code like en_AU, return that and the generic version."""
    expanded = [lang_code.casefold()]
    if '_' in lang_code:
        expanded.append(lang_code[:lang_code.index('_')].casefold())
    return expanded

def load_basemodui(basemod_loc: str) -> None:
    """Load basemodui.txt from Portal 2, to provide translations for the default items."""
    if GAME_TRANSLATIONS:
        # Already loaded.
        return

    # Basemod files are encoded in UTF-16.
    try:
        basemod_file = open(basemod_loc, encoding='utf16')
    except FileNotFoundError:
        return

    GAME_TRANSLATIONS.clear()

    with basemod_file:
        # This file is in keyvalues format, supposedly.
        # But it's got a bunch of syntax errors - extra quotes,
        # missing brackets.
        # The structure doesn't matter, so just process line by line.
        for line in basemod_file:
            try:
                __, key, __, value, __ = line.split('"')
            except ValueError:
                continue
            # Ignore non-puzzlemaker keys.
            if key.startswith(PETI_KEY_PREFIX):
                GAME_TRANSLATIONS[key] = value.replace("\\'", "'")


def setup(conf_lang: str) -> None:
    """Setup localisations."""
    # Get the 'en_US' style language code
    lang_code = locale.getdefaultlocale()[0]

    if conf_lang:
        lang_code = conf_lang

    # Allow overriding through command line.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.casefold().startswith('lang='):
                lang_code = arg[5:]
                break

    expanded_langs = expand_langcode(lang_code)

    LOGGER.info('Language: {!r}', lang_code)
    LOGGER.debug('Language codes: {!r}', expanded_langs)

    for lang in expanded_langs:
        try:
            file = open(FOLDER / (lang + '.mo'), 'rb')
        except FileNotFoundError:
            continue
        with file:
            translator = gettext_mod.GNUTranslations(file)
        # i18n: This is displayed in the options menu to switch to this language.
        language = Language(translator.gettext('__LanguageName'), lang_code, {
            NS_UI: translator,
        })
        break
    else:
        # To help identify missing translations, replace everything with
        # something noticeable.
        if lang_code == 'dummy':
            language = DUMMY
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
        else:
            if 'en' not in expanded_langs:
                LOGGER.warning(
                    "Can't find translation for codes: {!r}!",
                    expanded_langs,
                )
            language = Language('English', 'en', {})

    set_language(language)


def get_languages() -> Iterator[Language]:
    """Load all languages we have available."""
    for filename in FOLDER.iterdir():
        if filename.suffix != '.mo':  # Ignore POT and PO sources.
            continue
        try:
            with filename.open('rb') as f:
                translator = gettext_mod.GNUTranslations(f)
        except (IOError, OSError):
            LOGGER.warning('Could not parse "{}"', filename, exc_info=True)
            continue
        yield Language(
            # Special case, hardcode this name since this is the template and will produce the token.
            'English' if filename.stem == 'en' else translator.gettext('__LanguageName'),
            translator.info().get('Language', filename.stem),
            {NS_UI: translator},
        )


def set_language(lang: Language) -> None:
    """Change the app's language."""
    global _CURRENT_LANG
    PARSE_CANCEL.cancel()
    _CURRENT_LANG = lang

    conf = config.APP.get_cur_conf(GenOptions)
    config.APP.store_conf(attrs.evolve(conf, language=lang.lang_code))

    # Reload all our localisations.
    for text_widget, token in _applied_tokens.items():
        text_widget['text'] = str(token)
    for menu, menu_map in _applied_menu_tokens.items():
        for index, token in menu_map.items():
            menu.entryconfigure(index, label=str(token))
    for func in _langchange_callback:
        func()


async def load_package_langs(packset: 'packages.PackagesSet', lang: Language = None) -> None:
    """Load translations from packages, in the background."""
    global PARSE_CANCEL
    PARSE_CANCEL.cancel()  # Stop any in progress loads.

    if lang is None:
        lang = _CURRENT_LANG

    if lang is DUMMY:
        # Dummy does not need to load packages.
        set_language(lang)
        return

    # Preserve only the UI translations.
    lang_map = {NS_UI: lang._trans[NS_UI]}
    expanded = expand_langcode(lang.lang_code)

    async def loader(pak_id: str, fsys: FileSystem) -> None:
        """Load the package language in the background."""
        for code in expanded:
            try:
                file = fsys[f'resources/i18n/{code}.mo']
            except FileNotFoundError:
                continue
            LOGGER.debug('Found localisation file {}:{}', pak_id, file.path)
            try:
                with file.open_bin() as f:
                    lang_map[pak_id] = await trio.to_thread.run_sync(gettext_mod.GNUTranslations, f)
                return
            except OSError:
                LOGGER.warning('Invalid localisation file {}:{}', pak_id, file.path, exc_info=True)

    with trio.CancelScope() as PARSE_CANCEL:
        async with trio.open_nursery() as nursery:
            for pack in packset.packages.values():
                nursery.start_soon(loader, pack.id, pack.fsys)
    # We're not canceled, replace the global language with our new translations.
    set_language(attrs.evolve(lang, trans=lang_map))


async def get_package_tokens(packset: 'packages.PackagesSet') -> AsyncIterator[TransTokenSource]:
    """Get all the tokens from all packages."""
    for pack in packset.packages.values():
        yield pack.disp_name, pack.id, 'package/name'
        yield pack.desc, pack.id, 'package/desc'
    for obj_dict in packset.objects.values():
        for obj in obj_dict.values():
            for tup in obj.iter_trans_tokens():
                yield tup
            await trio.lowlevel.checkpoint()


async def rebuild_package_langs(packset: 'packages.PackagesSet') -> None:
    """Write out POT templates for unzipped packages."""
    from collections import defaultdict
    from babel import messages
    from babel.messages.pofile import read_po, write_po
    from babel.messages.mofile import write_mo

    tok2pack: dict[Union[str, tuple[str, str]], set[str]] = defaultdict(set)
    # Track tokens, so we can check we're not missing iter_trans_tokens() methods.
    found_tokens: set[TransToken] = set()

    pack_paths: dict[str, tuple[trio.Path, messages.Catalog]] = {}
    for pak_id, pack in packset.packages.items():
        if isinstance(pack.fsys, RawFileSystem):
            pack_paths[pak_id.casefold()] = trio.Path(pack.path, 'resources', 'i18n'), messages.Catalog(
                project=pack.disp_name.token,
                version=utils.BEE_VERSION,
            )
    LOGGER.info('Collecting translations...')
    for tok in list(_loaded_tokens):  # Get strong refs, so this doesn't change underneath us.
        try:
            pack_path, catalog = pack_paths[tok.namespace.casefold()]
        except KeyError:
            continue
        if isinstance(tok, PluralTransToken):
            catalog.add((tok.token, tok.token_plural))
            tok2pack[tok.token, tok.token_plural].add(tok.namespace)
        elif tok.token:  # Skip blank tokens.
            catalog.add(tok.token)
            tok2pack[tok.token].add(tok.namespace)

    LOGGER.info('{} translations.', len(_loaded_tokens))
    for pak_id, (pack_path, catalog) in pack_paths.items():
        LOGGER.info('Exporting translations for {}...', pak_id.upper())
        await pack_path.mkdir(parents=True, exist_ok=True)
        catalog.header_comment = PACKAGE_HEADER
        with open(pack_path / 'en.pot', 'wb') as f:
            write_po(f, catalog, include_previous=True, sort_output=True, width=120)
        for lang_file in await pack_path.iterdir():
            if lang_file.suffix != '.po':
                continue
            data = await lang_file.read_text()
            existing: messages.Catalog = read_po(io.StringIO(data))
            existing.update(catalog)
            catalog.header_comment = PACKAGE_HEADER
            existing.version = utils.BEE_VERSION
            LOGGER.info('- Rewriting {}', lang_file)
            with open(lang_file, 'wb') as f:
                write_po(f, existing, sort_output=True, width=120)
            with open(lang_file.with_suffix('.mo'), 'wb') as f:
                write_mo(f, existing)

    LOGGER.info('Repeated tokens:\n{}', '\n'.join([
        f'{", ".join(sorted(tok_pack))} -> {token!r} '
        for (token, tok_pack) in
        sorted(tok2pack.items(), key=lambda t: len(t[1]), reverse=True)
        if len(tok_pack) > 1
    ]))
