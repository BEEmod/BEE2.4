"""Wraps gettext, to localise all UI text."""
from typing import Callable, Dict, List, Mapping, TYPE_CHECKING, TypeVar, Union, cast
from typing_extensions import ParamSpec, Final, TypeAlias
from weakref import WeakKeyDictionary
import gettext as gettext_mod
import locale
import logging
import sys
import builtins
import warnings

import attrs
from srctools.property_parser import PROP_FLAGS_DEFAULT
from srctools import EmptyMapping, logger

import utils

if TYPE_CHECKING:  # Don't import at runtime, we don't want TK in the compiler.
    import tkinter as tk
    from tkinter import ttk

LOGGER = logger.get_logger(__name__)
_TRANSLATOR = gettext_mod.NullTranslations()
P = ParamSpec('P')

NS_UI: Final = '<BEE2>'  # Our UI translations.
NS_GAME: Final = '<PORTAL2>'   # Lookup from basemodui.txt
NS_UNTRANSLATED: Final = '<NOTRANSLATE>'  # Legacy values which don't have translation
# The prefix for all Valve's editor keys.
PETI_KEY_PREFIX: Final = 'PORTAL2_PuzzleEditor'

# The currently loaded translations. First is the namespace, then the token -> string.
TRANSLATIONS: Dict[str, Dict[str, str]] = {}

TextWidget: TypeAlias = Union[
    'tk.Label', 'tk.LabelFrame', 'tk.Button', 'tk.Radiobutton', 'tk.Checkbutton',
    'ttk.Label', 'ttk.LabelFrame', 'ttk.Button', 'ttk.Radiobutton', 'ttk.Checkbutton'
]
TextWidgetT = TypeVar('TextWidgetT', bound=TextWidget)
# Assigns to widget['text'].
_applied_tokens: 'WeakKeyDictionary[TextWidget, TransToken]' = WeakKeyDictionary()
# For anything else, this is called which will apply tokens.
_langchange_callback: List[Callable[[], object]] = []


@attrs.frozen(eq=False)
class TransToken:
    """A named section of text that can be translated later on."""
    # The package name, or a NS_* constant.
    namespace: str
    # The token to lookup, or the default if undefined.
    token: str
    # Keyword arguments passed when formatting.
    # If a blank dict is passed, use EmptyMapping to save memory.
    parameters: Mapping[str, object] = attrs.field(
        default=EmptyMapping,
        converter=lambda m: m or EmptyMapping,
    )

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
                return cls(package, text)
            else:
                if not package:
                    package = NS_UNTRANSLATED
                return cls(package, token)
        elif text.startswith(PETI_KEY_PREFIX):
            return cls(NS_GAME, text)
        else:
            return cls(package, text)

    @classmethod
    def ui(cls, token: str, /, **kwargs: str) -> 'TransToken':
        """Make a token for a UI string."""
        return cls(NS_UI, token, kwargs)

    @classmethod
    def from_valve(cls, text: str) -> 'TransToken':
        """Make a token for a string that should be looked up in Valve's translation files."""
        return cls(NS_GAME, text)

    @classmethod
    def untranslated(cls, text: str) -> 'TransToken':
        """Make a token that is not actually translated at all.

        In this case, the token is the literal text to use.
        """
        return cls(NS_UNTRANSLATED, text)

    def format(self, /, **kwargs: object) -> 'TransToken':
        """Return a new token with the provided parameters added in."""
        return attrs.evolve(self, parameters={**self.parameters, **kwargs})

    def __bool__(self) -> bool:
        """The boolean value of a token is whether the token is entirely blank.

        In that case it's not going to translate to anything.
        """
        return self.token != '' and not self.token.isspace()

    def __eq__(self, other) -> bool:
        if isinstance(other, TransToken):
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
        elif self.namespace == NS_UI:
            result = _TRANSLATOR.gettext(self.token)
        else:
            try:
                result = TRANSLATIONS[self.namespace][self.token]
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

    def apply_win_title(self, win: 'tk.Toplevel') -> None:
        """Set the title of a window to this token."""
        self.apply_global(lambda: win.title(str(self)))

    @classmethod
    def apply_global(cls, func: Callable[[], object], call: bool = True) -> None:
        """Register a function which is called after translations are reloaded.

        This should be used to re-apply tokens in complicated situations after languages change.
        If call is true, the function will immediately be called to apply it now.
        """
        _langchange_callback.append(func)
        if call:
            func()


@attrs.frozen(eq=False)
class PluralTransToken(TransToken):
    """A pair of tokens, swapped between depending on the number of items.

    It must be formatted with an "n" parameter.
    """
    token_plural: str = attrs.Factory(lambda s: s.token, takes_self=True)

    @classmethod
    def ui(cls, singular: str, plural: str = '',  /, **kwargs: str) -> 'TransToken':
        """Make a token for a UI string."""
        if not plural:
            plural = singular
        return cls(NS_UI, singular, kwargs, token_plural=plural)

    @classmethod
    def untranslated(cls, text: str, plural: str = '') -> 'TransToken':
        """Make a token that is not actually translated at all."""
        if not plural:
            plural = text
        return cls(NS_UNTRANSLATED, text, token_plural=plural)

    @classmethod
    def parse(cls, package: str, text: str) -> 'TransToken':
        """Parse a string to find a translation token, if any."""
        raise NotImplementedError('Cannot be parsed from files.')

    @classmethod
    def from_valve(cls, text: str) -> 'TransToken':
        """Make a token for a string that should be looked up in Valve's translation files."""
        raise NotImplementedError("Valve's files have no plural translations.")

    def __eq__(self, other) -> bool:
        if isinstance(other, PluralTransToken):
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
        elif self.namespace == NS_UI:
            result = _TRANSLATOR.ngettext(self.token, self.token_plural, n)
        else:
            raise ValueError(f'Namespace "{self.namespace}" is not allowed.')

        if self.parameters:
            return result.format_map(self.parameters)
        else:
            return result


def load_basemodui(basemod_loc: str) -> None:
    """Load basemodui.txt from Portal 2, to provide translations for the default items."""
    if NS_GAME in TRANSLATIONS:
        # Already loaded.
        return

    # Basemod files are encoded in UTF-16.
    try:
        basemod_file = open(basemod_loc, encoding='utf16')
    except FileNotFoundError:
        return

    trans_data = TRANSLATIONS[NS_GAME] = {}

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
                trans_data[key] = value.replace("\\'", "'")

    if gettext('Quit') == '####':
        # Dummy translations installed, apply here too.
        for key in trans_data:
            trans_data[key] = gettext(key)


class DummyTranslations(gettext_mod.NullTranslations):
    """Dummy form for identifying missing translation entries."""

    def gettext(self, message: str) -> str:
        """Generate placeholder of the right size."""
        # We don't want to leave {arr} intact.
        return ''.join([
            '#' if s.isalnum() or s in '{}' else s
            for s in message
        ])

    def ngettext(self, msgid1: str, msgid2: str, n: int) -> str:
        """Generate placeholder of the right size for plurals."""
        return self.gettext(msgid1 if n == 1 else msgid2)

    lgettext = gettext
    lngettext = ngettext


def gettext(message: str) -> str:
    """Translate the given string."""
    return _TRANSLATOR.gettext(message)


def setup(logger: logging.Logger) -> None:
    """Setup gettext localisations."""
    global _TRANSLATOR
    # Get the 'en_US' style language code
    lang_code = locale.getdefaultlocale()[0]

    # Allow overriding through command line.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.casefold().startswith('lang='):
                lang_code = arg[5:]
                break

    # Expands single code to parent categories.
    expanded_langs = gettext_mod._expand_lang(lang_code)

    logger.info('Language: {!r}', lang_code)
    logger.debug('Language codes: {!r}', expanded_langs)

    # Add these to Property's default flags, so config files can also
    # be localised.
    for lang in expanded_langs:
        PROP_FLAGS_DEFAULT['lang_' + lang] = True

    lang_folder = utils.install_path('i18n')

    for lang in expanded_langs:
        try:
            file = open(lang_folder / (lang + '.mo').format(lang), 'rb')
        except FileNotFoundError:
            continue
        with file:
            _TRANSLATOR = gettext_mod.GNUTranslations(file)
            break
    else:
        # To help identify missing translations, replace everything with
        # something noticeable.
        if lang_code == 'dummy':
            _TRANSLATOR = DummyTranslations()
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
        else:
            if 'en' not in expanded_langs:
                logger.warning(
                    "Can't find translation for codes: {!r}!",
                    expanded_langs,
                )
            _TRANSLATOR = gettext_mod.NullTranslations()

    def warn_translate(name: str, func: Callable[P, str]):
        """Raise a deprecation warning when this is used from builtins."""
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
            """Raise and call the origina."""
            warnings.warn(
                f"Translation function {name}() called from builtins!",
                DeprecationWarning, stacklevel=2,
            )
            return func(*args, **kwargs)
        setattr(builtins, '_', wrapper)

    # Add functions to builtins, but deprecated.
    warn_translate('_', _TRANSLATOR.gettext)
    warn_translate('gettext', _TRANSLATOR.gettext)

    # Some lang-specific overrides..

    if gettext('__LANG_USE_SANS_SERIF__') == 'YES':
        # For Japanese/Chinese, we want a 'sans-serif' / gothic font
        # style.
        try:
            from tkinter import font
        except ImportError:
            return
        font_names = [
            'TkDefaultFont',
            'TkHeadingFont',
            'TkTooltipFont',
            'TkMenuFont',
            'TkTextFont',
            'TkCaptionFont',
            'TkSmallCaptionFont',
            'TkIconFont',
            # Note - not fixed-width...
        ]
        for font_name in font_names:
            font.nametofont(font_name).configure(family='sans-serif')
