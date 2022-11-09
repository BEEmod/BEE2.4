"""Translation tokens represent a potentially translatable string.

To actually translate the localisation module is required, for the app only, in the compiler these
exist so that data structures can be shared.
"""
from typing import ClassVar, Dict, Iterable, Mapping, Protocol, Sequence, Tuple, cast
from typing_extensions import Final, LiteralString
import attrs

from srctools import EmptyMapping, logger

LOGGER = logger.get_logger(__name__)
del logger

NS_UI: Final = '<BEE2>'  # Our UI translations.
NS_GAME: Final = '<PORTAL2>'   # Lookup from basemodui.txt
NS_UNTRANSLATED: Final = '<NOTRANSLATE>'  # Legacy values which don't have translation

# The prefix for all Valve's editor keys.
PETI_KEY_PREFIX: Final = 'PORTAL2_PuzzleEditor'


class GetText(Protocol):
    """The methods required for translations. This way we don't need to import gettext."""
    def gettext(self, token: str, /) -> str: ...
    def ngettext(self, single: str, plural: str, n: int, /) -> str: ...


@attrs.frozen
class Language:
    """A language which may be loaded, and the associated translations."""
    display_name: str
    lang_code: str
    _trans: Dict[str, GetText]
    # The loaded translations from basemodui.txt
    game_trans: Mapping[str, str] = EmptyMapping


# The current language.
_CURRENT_LANG = Language(
    '<None>', 'en', {}, {}
)
# Special language which replaces all text with ## to easily identify untranslatable text.
DUMMY: Final = Language('Dummy', 'dummy', {}, {})


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
    def ui(cls, token: LiteralString, /, **kwargs: str) -> 'TransToken':
        """Make a token for a UI string."""
        return cls(NS_UI, NS_UI, token, kwargs)

    @staticmethod
    def ui_plural(singular: LiteralString, plural: LiteralString,  /, **kwargs: str) -> 'PluralTransToken':
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


TransToken.BLANK = TransToken.untranslated('')

# Token and "source" string, for updating translation files.
TransTokenSource = Tuple[TransToken, str]


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