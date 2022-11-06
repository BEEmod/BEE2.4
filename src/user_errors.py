"""Common data for the compile user error support.

UserError is imported all over, so this needs to have minimal imports to avoid cycles.
"""
from typing import ClassVar, Collection, Dict, Iterable, List, Literal, Tuple, TypedDict
import attrs
from srctools import Matrix, Vec, logger

import utils
from transtoken import TransToken


Kind = Literal["white", "black", "goo", "goopartial", "goofull", "back"]


class SimpleTile(TypedDict):
    """A super simplified version of tiledef data for the error window. This can be converted right to JSON."""
    pos: Tuple[float, float, float]
    orient: Literal["n", "s", "e", "w", "u", "d"]


@attrs.frozen
class ErrorInfo:
    """Data to display to the user."""
    message: TransToken
    # Logging context
    context: str = ''
    faces: Dict[Kind, List[SimpleTile]] = attrs.Factory(dict)
    # Points of interest in the map.
    points: List[Tuple[float, float, float]] = attrs.Factory(list)
    # Special list of locations forming a pointfile line.
    leakpoints: List[Tuple[float, float, float]] = attrs.Factory(list)


DATA_LOC = utils.conf_location('compile_error.pickle')
SERVER_PORT = utils.conf_location('error_server_url.txt')


def to_threespace(vec: Vec) -> Tuple[float, float, float]:
    """Convert a vector to the conventions THREE.js uses."""
    return (
        vec.x / 128.0,
        vec.z / 128.0,
        vec.y / -128.0,
    )


class UserError(BaseException):
    """Special exception used to indicate a error in item placement, etc.

    This will result in the compile switching to compile a map which displays
    a HTML page to the user via the Steam Overlay.
    """
    _simple_tiles: ClassVar[Dict[Kind, List[SimpleTile]]] = {}

    def __init__(
        self,
        message: TransToken,
        points: Iterable[Vec]=(),
        *,
        docsurl: str='',
        textlist: Collection[str]=(),
        leakpoints: Collection[Vec]=(),
    ) -> None:
        """Specify the info to show to the user.

        :param message: This is a translation token potentially containing HTML. Strings formatted into it
            will be escaped. TODO implement.
        :param points: This is a list of offending map locations, which will be displayed in a
            render of the map.
        :param docsurl: If specified, adds a link to relevant documentation.
        :param textlist: If specified, adds the specified strings as a bulleted list.
        :param leakpoints: Specifies pointfile locations to display a leak.
        """
        if utils.DEV_MODE:
            try:
                ctx = f'Error occured in: <code>{", ".join(logger.CTX_STACK.get())}</code>'
            except LookupError:
                ctx = ''
        else:
            ctx = ''

        if isinstance(message, str):  # Temporary, prevent this breaking.
            message = TransToken.untranslated(message)

        if leakpoints:
            textlist = [f'({point})' for point in leakpoints]

        if textlist:
            # Build up a bullet list.
            tok_list_elem = TransToken.untranslated('<li><code>{text}</code></li>')
            message = TransToken.untranslated('{msg}\n<ul>{list}</ul>').format(
                msg=message,
                list=TransToken.untranslated('\n').join([
                    tok_list_elem.format(text=value)
                    for value in textlist
                ]),
            )

        if docsurl:
            message = TOK_SEEDOCS.format(msg=message, url=docsurl)

        self.info = ErrorInfo(
            message,
            ctx,
            self._simple_tiles,
            points=list(map(to_threespace, points)),
            leakpoints=list(map(to_threespace, leakpoints)),
        )

    def __str__(self) -> str:
        return f'Error message: {self.info.message}'


# Define a translation token for every error message that can be produced. The app will translate
# them all during export, then store that for the compiler's use.

# Generic tokens:
TOK_INVALID_PARAM = TransToken.ui(
    'Invalid <code>{option}=</code>"<code>{value}</code>" for {kind} "<var>{id}</var>"!'
)
TOK_REQUIRED_PARAM = TransToken.ui(
    'Option <code>{option}</code> is required for {kind} "<var>{id}</var>"!'
)
TOK_DUPLICATE_ID = TransToken.ui(
    'Duplicate {kind} ID "<var>{id}</var>". Change the ID of one of them.'
)
TOK_UNKNOWN_ID = TransToken.ui('Unknown {kind} ID "<var>{id}</var>".')

TOK_SEEDOCS = TransToken.untranslated('{msg}\n<p><a href="{url}">See the documentation</a>.</p>')

# Specific errors:

TOK_LEAK = TransToken.ui(
    'This map has <a href="https://developer.valvesoftware.com/wiki/Leak">"leaked"</a>. This is a '
    'bug in an item or style, which should be fixed. The displayed line indicates the location of '
    'the leak, you may be able to resolve it by removing/modifying items in that area. Please '
    'submit a bug report to the author of the item so this can be resolved. Leak coordinates:'
)

TOK_GLASS_FLOORBEAM_TEMPLATE = TransToken.ui(
    'Bad Glass Floorbeam template! The template must have a single brush, with one face '
    'pointing in the <var>+X</var> direction.'
)

TOK_CONNECTION_REQUIRED_ITEM = TransToken.ui(
    'No I/O configuration specified for special indicator item "<var>{item}</var>"! This is '
    'required for antlines to work.'
)

TOK_CONNECTIONS_UNKNOWN_INSTANCE = TransToken.ui(
    'The instance named "<var>{item}</var>" is not recognised! If you just swapped styles and '
    'exported, you will need to restart Portal 2. Otherwise check the relevant package.'
)

TOK_CONNECTIONS_INSTANCE_NO_IO = TransToken.ui(
    'The instance "<var>{inst}</var>" is reciving inputs, but none were configured in the item. '
    'Check for reuse of the instance in multiple items, or restart Portal 2 '
    'if you just exported.'
)

TOK_NO_CORRIDOR = TransToken.ui('No corridors available for {orient} {mode} {dir} group!')

TOK_CUBE_NO_CUBETYPE_FLAG = TransToken.ui('"CubeType" result used but with no type specified!')
TOK_CUBE_BAD_SPECIAL_CUBETYPE = TransToken.ui('Unrecognised special cube type "<var>{type}</var>"!')

TOK_CUBE_TIMERS_DUPLICATE = TransToken.ui(
    'Two or more cubes/droppers have the same timer value (<var>{timer}</var>). These are used to '
    'link a cube and dropper item together, so the cube is preplaced in the map but respawns '
    'from the specified dropper.'
)
TOK_CUBE_TIMERS_INVALID_CUBEVAL = TransToken.ui(
    'The specified cube has a timer value <var>{timer}</var>, which does not match any droppers. '
    'A dropper should be placed with a matching timer value, to specify the respawn point for this '
    'preplaced cube.'
)
TOK_CUBE_DROPPER_LINKED = TransToken.ui(
    'Dropper above custom cube of type <var>{type}</var> is already linked! Custom cubes convert'
    'droppers above them into their type, to allow having droppers.',
)

TOK_FIZZLER_NO_ITEM = TransToken.ui('No item ID for fizzler instance <var>"{inst}"</var>!')
TOK_FIZZLER_UNKNOWN_TYPE = TransToken.ui('No fizzler type for {item} (<var>"{inst}"</var>)!')
TOK_FIZZLER_NO_MODEL_SIDE = TransToken.ui('No model specified for one side of "{id}" fizzlers.')

TOK_INSTLOC_EMPTY = TransToken.ui(
    'Instance lookup path <code>"{path}"</code> returned no instances.'
)
TOK_INSTLOC_MULTIPLE = TransToken.ui(
    'Instance lookup path <code>"{path}"</code> was expected to provide one instance, '
    'but it returned multiple instances:'
)

# Tokens used when the system fails.
TOK_ERR_MISSING = TransToken.ui('<strong>No error?</strong>')
TOK_ERR_FAIL_LOAD = TransToken.ui('Failed to load error!')

ALL_TOKENS = [
    tok for name, tok in globals().items()
    if name.startswith('TOK_') and isinstance(tok, TransToken)
]
