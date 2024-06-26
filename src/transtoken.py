"""Translation tokens represent a potentially translatable string.

Translation only occurs in the app, using the localisation module. In the compiler this exists still
so that data structures can be shared.
We take care not to directly import gettext and babel, so the compiler can omit those.
"""
from __future__ import annotations
from typing import (
    Any, Callable, ClassVar, Dict, Final, Iterable, List, Mapping, NoReturn,
    Optional, Protocol, Sequence, Tuple, cast, final,
)

from typing_extensions import LiteralString, TypeAliasType, override
from enum import Enum
from html import escape as html_escape
from pathlib import Path
import string

from trio_util import AsyncValue
from srctools import EmptyMapping, logger
import attrs

import utils


LOGGER = logger.get_logger(__name__)
del logger

NS_UI: Final = utils.special_id('<BEE2>')  # Our UI translations.
NS_GAME: Final = utils.special_id('<PORTAL2>')   # Lookup from basemodui.txt
NS_UNTRANSLATED: Final = utils.special_id('<NOTRANSLATE>')  # Legacy values which don't have translation

# The prefix for all Valve's editor keys.
PETI_KEY_PREFIX: Final = 'PORTAL2_PuzzleEditor'


class ListStyle(Enum):
    """Kind of comma-separated list to produce."""
    AND = 'standard'
    OR = 'or'
    AND_SHORT = 'standard-short'
    OR_SHORT = 'or-short'
    UNIT = 'unit'
    UNIT_SHORT = 'unit-short'
    UNIT_NARROW = 'unit-narrow'


class GetText(Protocol):
    """The methods required for translations. This way we don't need to import gettext."""
    def gettext(self, token: str, /) -> str: ...
    def ngettext(self, single: str, plural: str, n: int, /) -> str: ...


@attrs.frozen(kw_only=True, eq=False)
class Language:
    """A language which may be loaded, and the associated translations."""
    lang_code: str
    ui_filename: Optional[Path] = None  # Filename of the UI translation, if it exists.
    _trans: Dict[str, GetText] = attrs.field(alias='trans')
    # The loaded translations from basemodui.txt
    game_trans: Mapping[str, str] = EmptyMapping


# The current language. Can be set to change language, but don't do that in the UI.
CURRENT_LANG: Final = AsyncValue(Language(lang_code='en', trans={}))
# Special language which replaces all text with ## to easily identify untranslatable text.
DUMMY: Final = Language(lang_code='dummy', trans={})

# Set by the localisation module to a function which gets a formatter for UI text, given the lang code.
# It's initialised to a basic version, in case we're running in the compiler.
ui_format_getter: Callable[[str], Optional[string.Formatter]] = lambda lang, /: None
# Similarly, joins a list given the language, kind of list and children.
ui_list_getter: Callable[[str, ListStyle, List[str]], str] = lambda lang, kind, children, /: ', '.join(children)


class HTMLFormatter(string.Formatter):
    """Custom format variant which escapes fields for HTML."""
    @override
    def format_field(self, value: Any, format_spec: str) -> str:
        """Called to convert a field in the format string."""
        if isinstance(value, TransToken):
            return format(value.translate_html(), format_spec)
        else:
            return html_escape(format(value, format_spec))


HTML_FORMAT = HTMLFormatter()


def _param_convert(params: Mapping[str, object]) -> Mapping[str, object]:
    """If a blank dict is passed, use EmptyMapping to save memory."""
    return EmptyMapping if len(params) == 0 else params


@attrs.frozen(eq=False)
class TransToken:
    """A named section of text that can be translated later on."""
    # The package name, or a NS_* constant.
    namespace: utils.SpecialID
    # Original package where this was parsed from.
    orig_pack: utils.SpecialID
    # The token to lookup, or the default if undefined.
    token: str
    # Keyword arguments passed when formatting.
    parameters: Mapping[str, object] = attrs.field(converter=_param_convert)

    BLANK: ClassVar[TransToken]   # Quick access to blank token.

    @classmethod
    def parse(cls, package: utils.SpecialID, text: str) -> TransToken:
        """Parse a string to find a translation token, if any."""
        orig_pack = package
        if text.startswith('[['):  # "[[package]] default"
            try:
                package_str, token = text[2:].split(']]', 1)
                token = token.lstrip()  # Allow whitespace between "]" and text.
                # Don't allow specifying our special namespaces, except allow empty string for UNTRANSLATED
                package = utils.obj_id(package_str) if package_str else NS_UNTRANSLATED
            except ValueError:
                LOGGER.warning(
                    'Unparsable translation token - expected "[[package]] text", got:\n{!r}',
                    text
                )
                return cls(package, orig_pack, text, EmptyMapping)
            else:
                return cls(package, orig_pack, token, EmptyMapping)
        elif text.startswith(PETI_KEY_PREFIX):
            return cls(NS_GAME, orig_pack, text, EmptyMapping)
        else:
            return cls(package, orig_pack, text, EmptyMapping)

    @classmethod
    def ui(cls, token: LiteralString, /, **kwargs: str) -> TransToken:
        """Make a token for a UI string."""
        return cls(NS_UI, NS_UI, token, kwargs)

    @staticmethod
    def ui_plural(singular: LiteralString, plural: LiteralString, /, **kwargs: str) -> PluralTransToken:
        """Make a plural token for a UI string."""
        return PluralTransToken(NS_UI, NS_UI, singular, kwargs, plural)

    def join(self, children: Iterable[TransToken], sort: bool = False) -> JoinTransToken:
        """Use this as a separator to join other tokens together."""
        return JoinTransToken(
            self.namespace, self.orig_pack, self.token, self.parameters,
            list(children), sort,
        )

    @classmethod
    def from_valve(cls, text: str) -> TransToken:
        """Make a token for a string that should be looked up in Valve's translation files."""
        return cls(NS_GAME, NS_GAME, text, EmptyMapping)

    @classmethod
    def untranslated(cls, text: str) -> TransToken:
        """Make a token that is not actually translated at all.

        In this case, the token is the literal text to use.
        """
        return cls(NS_UNTRANSLATED, NS_UNTRANSLATED, text, EmptyMapping)

    @classmethod
    def list_and(cls, children: Iterable[TransToken], sort: bool = False) -> ListTransToken:
        """Join multiple tokens together in an and-list."""
        return ListTransToken(
            NS_UNTRANSLATED, NS_UNTRANSLATED, ', ', EmptyMapping,
            list(children), sort, ListStyle.AND,
        )

    @classmethod
    def list_or(cls, children: Iterable[TransToken], sort: bool = False) -> ListTransToken:
        """Join multiple tokens together in an or-list."""
        return ListTransToken(
            NS_UNTRANSLATED, NS_UNTRANSLATED, ', ', EmptyMapping,
            list(children), sort, ListStyle.OR,
        )

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

    def format(self, /, **kwargs: object) -> TransToken:
        """Return a new token with the provided parameters added in."""
        # Only merge together if we had parameters, otherwise just store the dict.
        if self.parameters and kwargs:
            return attrs.evolve(self, parameters={**self.parameters, **kwargs})
        elif kwargs:
            # This can be shared, we don't allow editing it.
            return attrs.evolve(self, parameters=kwargs)
        else:
            return self

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

    def __eq__(self, other: object) -> bool:
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

    def _convert_token(self) -> str:
        """Return the translated version of our token."""
        cur_lang = CURRENT_LANG.value

        # If in the untranslated namespace or blank, don't translate.
        if self.namespace == NS_UNTRANSLATED or not self.token:
            return self.token
        elif cur_lang is DUMMY:
            return '#' * len(self.token)
        elif self.namespace == NS_GAME:
            try:
                return cur_lang.game_trans[self.token]
            except KeyError:
                return self.token
        else:
            try:
                # noinspection PyProtectedMember
                return cur_lang._trans[self.namespace].gettext(self.token)
            except KeyError:
                return self.token

    def __str__(self) -> str:
        """Calling str on a token translates it."""
        text = self._convert_token()
        if self.parameters:
            formatter = ui_format_getter(CURRENT_LANG.value.lang_code)
            try:
                if formatter is not None:
                    return formatter.vformat(text, (), self.parameters)
                else:
                    return text.format_map(self.parameters)
            except KeyError:
                LOGGER.warning('Could not format {!r} with {}', text, self.parameters)
                return text
        else:
            return text

    def translate_html(self) -> str:
        """Translate to text, escaping parameters for HTML.

        Any non-token parameters will have HTML syntax escaped.
        """
        text = self._convert_token()
        if self.parameters:
            return HTML_FORMAT.vformat(text, (), self.parameters)
        else:
            return text


TransToken.BLANK = TransToken.untranslated('')

# Token and "source" string, for updating translation files.
TransTokenSource = TypeAliasType("TransTokenSource", Tuple[TransToken, str])


@attrs.frozen(eq=False)
class PluralTransToken(TransToken):
    """A pair of tokens, swapped between depending on the number of items.

    It must be formatted with an "n" parameter.
    """
    token_plural: str

    @classmethod
    def _not_allowed(cls, *args: NoReturn, **kwargs: NoReturn) -> NoReturn:
        raise NotImplementedError('This is not allowed.')

    # Also not allowed.
    ui = ui_plural = untranslated = from_valve = _not_allowed  # type: ignore[assignment]

    @override
    def join(self, children: Iterable[TransToken], sort: bool = False) -> JoinTransToken:
        """Joining is not allowed."""
        raise NotImplementedError('This is not allowed.')

    @override
    def __eq__(self, other: object) -> bool:
        if type(other) is PluralTransToken:
            return (
                self.namespace == other.namespace and
                self.token == other.token and
                self.token_plural == other.token_plural and
                self.parameters == other.parameters
            )
        return NotImplemented

    @override
    def __hash__(self) -> int:
        """Allow hashing the token."""
        return hash((
            self.namespace, self.token, self.token_plural,
            frozenset(self.parameters.items()),
        ))

    @override
    def _convert_token(self) -> str:
        """Return the translated version of our token, handling plurals."""
        try:
            n = int(cast(str, self.parameters['n']))
        except KeyError:
            raise ValueError('Plural token requires "n" parameter!') from None
        cur_lang = CURRENT_LANG.value

        # If in the untranslated namespace or blank, don't translate.
        if self.namespace == NS_UNTRANSLATED or not self.token:
            return self.token if n == 1 else self.token_plural
        elif cur_lang is DUMMY:
            return '#' * len(self.token if n == 1 else self.token_plural)
        elif self.namespace == NS_GAME:
            raise ValueError('Game namespace cannot be pluralised!')
        else:
            try:
                # noinspection PyProtectedMember
                return cur_lang._trans[self.namespace].ngettext(self.token, self.token_plural, n)
            except KeyError:
                return self.token


@attrs.frozen(eq=False)
class JoinTransToken(TransToken):
    """A list of tokens which will be joined together to form a list.

    The token is the joining value.
    """
    children: Sequence[TransToken]
    sort: bool

    @override
    def format(self, /, **kwargs: object) -> NoReturn:
        """Joined tokens cannot be formatted."""
        raise NotImplementedError('Cannot format joined tokens!')

    @override
    def __hash__(self) -> int:
        return hash((self.namespace, self.token, *self.children))

    @override
    def __eq__(self, other: object) -> bool:
        if type(other) is JoinTransToken:
            return (
                self.namespace == other.namespace and
                self.token == other.token and
                self.children == other.children
            )
        return NotImplemented

    @override
    def __str__(self) -> str:
        """Translate the token."""
        if self.parameters:
            raise ValueError(f'Cannot format joined token: {vars(self)}')
        sep = self._convert_token()
        items = [str(child) for child in self.children]
        if self.sort:
            items.sort()
        return sep.join(items)

    @override
    def translate_html(self) -> str:
        """Translate to text, escaping parameters for HTML.

        Any non-token parameters in children will have HTML syntax escaped.
        """
        if self.parameters:
            raise ValueError(f'Cannot format joined token: {vars(self)}')
        sep = self._convert_token()
        items = [child.translate_html() for child in self.children]
        if self.sort:
            items.sort()
        return sep.join(items)


@attrs.frozen(eq=False)
class ListTransToken(JoinTransToken):
    """A special variant of JoinTransToken which uses language-specific joiners."""
    kind: ListStyle

    @override
    def format(self, /, **kwargs: object) -> NoReturn:
        """List tokens cannot be formatted."""
        raise NotImplementedError('Cannot format list tokens!')

    @override
    def __eq__(self, other: object) -> bool:
        if type(other) is ListTransToken:
            return (
                self.namespace == other.namespace and
                self.token == other.token and
                self.children == other.children
            )
        return NotImplemented

    @override
    def __str__(self) -> str:
        """Translate the token."""
        if self.parameters:
            raise ValueError(f'Cannot format list token: {vars(self)}')

        items = [str(child) for child in self.children]
        if self.sort:
            items.sort()
        return ui_list_getter(CURRENT_LANG.value.lang_code, self.kind, items)


# TODO: Move this back to app.errors when that can be imported in compiler safely.

@final
@attrs.define(init=False)
class AppError(Exception):
    """An error that occurs when using the app, that should be displayed to the user."""
    message: TransToken
    fatal: bool

    def __init__(self, message: TransToken) -> None:
        super().__init__(message)
        self.message = message
        self.fatal = False

    def __str__(self) -> str:
        return f"AppError: {self.message}"
