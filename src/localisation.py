"""An object-oriented approach to localising text.

All translations are stored as token objects, which translate when str() is called. They also store
the widgets they are applied to, so those can be refreshed when swapping languages.

This is also imported in the compiler, so UI imports must be inside functions.
"""
import io
import os.path
import warnings
from pathlib import Path
from typing import (
    AsyncIterator, Callable, ClassVar, Dict, Iterable, Iterator, List, Mapping, Sequence,
    TYPE_CHECKING, Tuple, TypeVar, Union, cast,
)

from srctools.filesys import RawFileSystem
from typing_extensions import ParamSpec, Final, TypeAlias
from weakref import WeakKeyDictionary
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
    from app import gameMan

__all__ = [
    'TransToken',
    'set_text', 'set_menu_text', 'set_win_title', 'add_callback',
    'DUMMY', 'Language', 'set_language', 'load_aux_langs',
    'setup', 'expand_langcode',
    'TransTokenSource', 'rebuild_app_langs', 'rebuild_package_langs',
]

LOGGER = logger.get_logger(__name__)
P = ParamSpec('P')

NS_UI: Final = '<BEE2>'  # Our UI translations.
NS_GAME: Final = '<PORTAL2>'   # Lookup from basemodui.txt
NS_UNTRANSLATED: Final = '<NOTRANSLATE>'  # Legacy values which don't have translation
# The prefix for all Valve's editor keys.
PETI_KEY_PREFIX: Final = 'PORTAL2_PuzzleEditor'
# Location of basemodui, relative to Portal 2
BASEMODUI_PATH = 'portal2_dlc2/resource/basemodui_{}.txt'

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

FOLDER = utils.install_path('i18n')
PARSE_CANCEL = trio.CancelScope()


@attrs.frozen
class Language:
    """Wrapper around the GNU translator, storing the filename and display name."""
    display_name: str
    lang_code: str
    _trans: Dict[str, gettext_mod.NullTranslations]
    # The loaded translations from basemodui.txt
    game_trans: Mapping[str, str] = EmptyMapping


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


# Country code -> Source name suffix.
STEAM_LANGS = {
    'ar': 'arabic',  # Not in P2.
    'pt_br': 'brazilian',
    'bg': 'bulgarian',
    'cs': 'czech',
    'da': 'danish',
    'nl': 'dutch',
    'en': 'english',
    'fi': 'finnish',
    'fr': 'french',
    'de': 'german',
    'el': 'greek',
    'hu': 'hungarian',
    'it': 'italian',
    'ja': 'japanese',
    'ko': 'korean',
    # 'ko': 'koreana',  # North? identical.
    'es_419': 'latam',
    'no': 'norwegian',
    # '': 'pirate',  # Not real.
    'pl': 'polish',
    'pt': 'portuguese',
    'ro': 'romanian',
    'ru': 'russian',
    'zh_cn': 'schinese',
    'es': 'spanish',
    'sv': 'swedish',
    'zh_tw': 'tchinese',
    'th': 'thai',
    'tr': 'turkish',
    'uk': 'ukrainian',
    'vn': 'vietnamese',
}


@attrs.frozen(eq=False)
class TransToken:
    """A named section of text that can be translated later on."""
    # The package name, or a NS_* constant.
    namespace: str
    # Original package where this was parsed from.
    orig_pack: str
    # The token to lookup, or the default if undefined.
    token: str
    # Keyword arguments passed when formatting.
    # If a blank dict is passed, use EmptyMapping to save memory.
    parameters: Mapping[str, object] = attrs.field(converter=lambda m: m or EmptyMapping)

    BLANK: ClassVar['TransToken']   # Quick access to blank token.

    @classmethod
    def parse(cls, package: str, text: str) -> 'TransToken':
        """Parse a string to find a translation token, if any."""
        orig_pack = package
        if text.startswith('[['):  # "[[package]] default"
            try:
                package, token = text[2:].split(']]', 1)
                token = token.lstrip()  # Allow whitespace between "]" and text.
                # Don't allow specifying our special namespaces.
                if package.startswith('<') or package.endswith('>'):
                    raise ValueError
            except ValueError:
                LOGGER.warning('Unparsable translation token - expected "[[package]] text", got:\n{}', text)
                return cls(package, orig_pack, text, EmptyMapping)
            else:
                if not package:
                    package = NS_UNTRANSLATED
                return cls(package, orig_pack, token, EmptyMapping)
        elif text.startswith(PETI_KEY_PREFIX):
            return cls(NS_GAME, orig_pack, text, EmptyMapping)
        else:
            return cls(package, orig_pack, text, EmptyMapping)

    @classmethod
    def ui(cls, token: str, /, **kwargs: str) -> 'TransToken':
        """Make a token for a UI string."""
        return cls(NS_UI, NS_UI, token, kwargs)

    @staticmethod
    def ui_plural(singular: str, plural: str,  /, **kwargs: str) -> 'PluralTransToken':
        """Make a plural token for a UI string."""
        return PluralTransToken(NS_UI, NS_UI, singular, kwargs, plural)

    def join(self, children: Iterable['TransToken'], sort: bool=False) -> 'JoinTransToken':
        """Use this as a separator to join other tokens together."""
        return JoinTransToken(self.namespace, self.orig_pack, self.token, self.parameters, list(children), sort)

    @classmethod
    def from_valve(cls, text: str) -> 'TransToken':
        """Make a token for a string that should be looked up in Valve's translation files."""
        return cls(NS_GAME, NS_GAME, text, EmptyMapping)

    @classmethod
    def untranslated(cls, text: str) -> 'TransToken':
        """Make a token that is not actually translated at all.

        In this case, the token is the literal text to use.
        """
        return cls(NS_UNTRANSLATED, NS_UNTRANSLATED, text, EmptyMapping)

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
                result = _CURRENT_LANG.game_trans[self.token]
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
        warnings.warn('Use the function', DeprecationWarning, stacklevel=2)
        return set_text(widget, self)

    def apply_title(self, win: Union['tk.Toplevel', 'tk.Tk']) -> None:
        warnings.warn('Use the function', DeprecationWarning, stacklevel=2)
        set_win_title(win, self)

    def apply_menu(self, menu: 'tk.Menu', index: Union[str, int] = 'end') -> None:
        warnings.warn('Use the function', DeprecationWarning, stacklevel=2)
        set_menu_text(menu, self, index)

    @classmethod
    def clear_stored_menu(cls, menu: 'tk.Menu') -> None:
        """Clear the tokens for the specified menu."""
        clear_stored_menu(menu)

    @classmethod
    def add_callback(cls, func: Callable[[], object], call: bool = True) -> None:
        add_callback(func, call)

TransToken.BLANK = TransToken.untranslated('')


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


# Token and "source" string, for updating translation files.
TransTokenSource = Tuple[TransToken, str]


def set_text(widget: TextWidgetT, token: TransToken) -> TextWidgetT:
    """Apply a token to the specified label/button/etc."""
    widget['text'] = str(token)
    _applied_tokens[widget] = token
    return widget


def set_win_title(win: Union['tk.Toplevel', 'tk.Tk'], token: TransToken) -> None:
    """Set the title of a window to this token."""
    add_callback(lambda: win.title(str(token)))


def set_menu_text(menu: 'tk.Menu', token: TransToken, index: Union[str, int] = 'end') -> None:
    """Apply this text to the item on the specified menu.

    By default, it is applied to the last item.
    """
    try:
        tok_map = _applied_menu_tokens[menu]
    except KeyError:
        tok_map = _applied_menu_tokens[menu] = {}
    ind = menu.index(index)
    menu.entryconfigure(ind, label=str(token))
    tok_map[ind] = token


def clear_stored_menu(menu: 'tk.Menu') -> None:
    """Clear the tokens for the specified menu."""
    _applied_menu_tokens.pop(menu, None)


def add_callback(func: Callable[[], object], call: bool = True) -> None:
    """Register a function which is called after translations are reloaded.

    This should be used to re-apply tokens in complicated situations after languages change.
    If call is true, the function will immediately be called to apply it now.
    """
    _langchange_callback.append(func)
    if call:
        func()


def expand_langcode(lang_code: str) -> List[str]:
    """If a language is a lang/country specific code like en_AU, return that and the generic version."""
    expanded = [lang_code.casefold()]
    if '_' in lang_code:
        expanded.append(lang_code[:lang_code.index('_')].casefold())
    return expanded


def find_basemodui(games: List['gameMan.Game'], langs: List[str]) -> str:
    """Load basemodui.txt from Portal 2, to provide translations for the default items."""
    # Check Portal 2 first, others might not be fully correct?
    games.sort(key=lambda gm: gm.steamID != '620')

    for lang in langs:
        try:
            game_lang = STEAM_LANGS[lang.casefold()]
            break
        except KeyError:
            pass
    else:
        game_lang = ''

    for game in games:
        if game_lang:
            loc = game.abs_path(BASEMODUI_PATH.format(game_lang))
            LOGGER.debug('Checking lang "{}"', loc)
            if os.path.exists(loc):
                return loc
        # Fall back to configured language.
        game_lang = game.get_game_lang()
        if game_lang:
            loc = game.abs_path(BASEMODUI_PATH.format(game_lang))
            LOGGER.debug('Checking lang "{}"', loc)
            if os.path.exists(loc):
                return loc

    # Nothing found, pick first english copy.
    for game in games:
        loc = game.abs_path(BASEMODUI_PATH.format('english'))
        LOGGER.debug('Checking lang "{}"', loc)
        if os.path.exists(loc):
            return loc


def parse_basemodui(result: dict[str, str], data: str) -> None:
    """Parse the basemodui keyvalues file."""
    # This file is in keyvalues format, supposedly.
    # But it's got a bunch of syntax errors - extra quotes,
    # missing brackets.
    # The structure doesn't matter, so just process line by line.
    for line in io.StringIO(data):
        try:
            __, key, __, value, __ = line.split('"')
        except ValueError:
            continue
        # Ignore non-puzzlemaker keys.
        if key.startswith(PETI_KEY_PREFIX):
            result[key] = value.replace("\\'", "'")


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


async def rebuild_app_langs() -> None:
    """Compile .po files for the app into .mo files. This does not extract tokens, that needs source."""
    from babel.messages.pofile import read_po
    from babel.messages.mofile import write_mo
    from app import tk_tools

    def build_file(filename: Path) -> None:
        """Synchronous I/O code run as a backround thread."""
        with filename.open('rb') as src:
            catalog = read_po(src, locale=filename.stem)
        with filename.with_suffix('.mo').open('wb') as dest:
            write_mo(dest, catalog)

    async def build_lang(filename: Path) -> None:
        try:
            await trio.to_thread.run_sync(build_file, fname)
        except (IOError, OSError):
            LOGGER.warning('Could not convert "{}"', filename, exc_info=True)
        else:
            LOGGER.info('Converted "{}"', filename)

    async with trio.open_nursery() as nursery:
        for fname in FOLDER.iterdir():
            if fname.suffix == '.po':
                nursery.start_soon(build_lang, fname)
    tk_tools.showinfo(TransToken.ui('BEEMod'), TransToken.ui('UI Translations rebuilt.'))


async def load_aux_langs(
    games: Iterable['gameMan.Game'],
    packset: 'packages.PackagesSet',
    lang: Language = None,
) -> None:
    """Load all our non-UI translation files in the background.

    We already loaded the UI langs to create Language.
    """
    global PARSE_CANCEL
    PARSE_CANCEL.cancel()  # Stop any other in progress loads.

    if lang is None:
        lang = _CURRENT_LANG

    if lang is DUMMY:
        # Dummy does not need to load these files.
        set_language(lang)
        return

    # Preserve only the UI translations.
    # noinspection PyProtectedMember
    lang_map = {NS_UI: lang._trans[NS_UI]}
    # The parsed game translations.
    game_dict: dict[str, str] = {}

    # Expand to a generic country code.
    expanded = expand_langcode(lang.lang_code)

    async def package_lang(pak_id: str, fsys: FileSystem) -> None:
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

    async def game_lang(game_it: Iterable['gameMan.Game'], expanded_langs: List[str]) -> None:
        """Load the game language in the background."""
        basemod_loc = find_basemodui(list(game_it), expanded_langs)
        if not basemod_loc:
            LOGGER.warning('Could not find BaseModUI file for Portal 2!')
            return
        try:
            # BaseModUI files are encoded in UTF-16.
            data = await trio.Path(basemod_loc).read_text('utf16')
        except FileNotFoundError:
            LOGGER.warning('BaseModUI file "{}" does not exist!', basemod_loc)
        else:
            await trio.to_thread.run_sync(parse_basemodui, game_dict, data)

    with trio.CancelScope() as PARSE_CANCEL:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(game_lang, games, expanded)
            for pack in packset.packages.values():
                nursery.start_soon(package_lang, pack.id, pack.fsys)
    # We're not canceled, replace the global language with our new translations.
    set_language(attrs.evolve(lang, trans=lang_map, game_trans=game_dict))


async def get_package_tokens(packset: 'packages.PackagesSet') -> AsyncIterator[TransTokenSource]:
    """Get all the tokens from all packages."""
    for pack in packset.packages.values():
        yield pack.disp_name, 'package/name'
        yield pack.desc, 'package/desc'
    for obj_type in packset.objects:
        LOGGER.debug('Checking object type {}', obj_type.__name__)
        for obj in packset.all_obj(obj_type):
            for tup in obj.iter_trans_tokens():
                yield tup
            await trio.lowlevel.checkpoint()


def _get_children(tok: TransToken) -> Iterator[TransToken]:
    """If this token has children, yield those."""
    yield tok
    for val in tok.parameters.values():
        if isinstance(val, TransToken):
            yield from _get_children(val)


async def rebuild_package_langs(packset: 'packages.PackagesSet') -> None:
    """Write out POT templates for unzipped packages."""
    from collections import defaultdict
    from babel import messages
    from babel.messages.pofile import read_po, write_po
    from babel.messages.mofile import write_mo

    tok2pack: dict[Union[str, tuple[str, str]], set[str]] = defaultdict(set)
    pack_paths: dict[str, tuple[trio.Path, messages.Catalog]] = {}

    for pak_id, pack in packset.packages.items():
        if isinstance(pack.fsys, RawFileSystem):
            pack_paths[pak_id.casefold()] = trio.Path(pack.path, 'resources', 'i18n'), messages.Catalog(
                project=pack.disp_name.token,
                version=utils.BEE_VERSION,
            )

    LOGGER.info('Collecting translations...')
    async for orig_tok, source in get_package_tokens(packset):
        for tok in _get_children(orig_tok):
            if not tok:
                continue  # Ignore blank tokens, not important to translate.
            try:
                pack_path, catalog = pack_paths[tok.namespace.casefold()]
            except KeyError:
                continue
            # Line number is just zero - we don't know which lines these originated from.
            if tok.namespace.casefold() != tok.orig_pack.casefold():
                # Originated from a different package, include that.
                loc = [(f'{tok.orig_pack}:{source}', 0)]
            else:  # Omit, most of the time.
                loc = [(source, 0)]

            if isinstance(tok, PluralTransToken):
                catalog.add((tok.token, tok.token_plural), locations=loc)
                tok2pack[tok.token, tok.token_plural].add(tok.namespace)
            else:
                catalog.add(tok.token, locations=loc)
                tok2pack[tok.token].add(tok.namespace)

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
