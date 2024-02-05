"""Common data for the compile user error support.

UserError is imported all over, so this needs to have minimal imports to avoid cycles.
"""
from typing import (
    ClassVar, Collection, Dict, Iterable, List, Literal, Optional, Set, Tuple,
    TypedDict, Union,
)
from typing_extensions import TypeAlias
from pathlib import Path

from srctools import FrozenVec, Vec, logger
import attrs

from transtoken import TransToken
import utils


Kind: TypeAlias = Literal["white", "black", "goo", "goopartial", "goofull", "back", "glass", "grating"]
TuplePos: TypeAlias = Tuple[float, float, float]
# Textures for displaying barrier items.
BARRIER_TEX_SET: Set[Kind] = {"glass", "grating", "white", "black"}
TEX_SET: Set[Kind] = {
    "white", "black",
    "glass", "grating",
    "goo", "goopartial", "goofull",
    "back",
}


class SimpleTile(TypedDict):
    """A super simplified version of tiledef data for the error window. This can be converted right to JSON."""
    position: TuplePos
    orient: Literal["n", "s", "e", "w", "u", "d"]


class BarrierHole(TypedDict):
    """Information for improperly placed glass/grating hole items."""
    pos: TuplePos
    axis: Literal["x", "y", "z"]
    large: bool
    small: bool
    footprint: bool


@attrs.frozen(kw_only=True)
class ErrorInfo:
    """Data to display to the user."""
    message: TransToken
    language_file: Optional[Path] = None
    # Logging context
    context: str = ''
    faces: Dict[Kind, List[SimpleTile]] = attrs.Factory(dict)
    # Voxels of interest in the map.
    voxels: List[TuplePos] = attrs.Factory(list)
    # Points of interest in the map.
    points: List[TuplePos] = attrs.Factory(list)
    # Special list of locations forming a pointfile line.
    leakpoints: List[TuplePos] = attrs.Factory(list)
    # A list of point pairs which get lines drawn.
    lines: List[Tuple[TuplePos, TuplePos]] = attrs.Factory(list)
    # If a glass/grating hole is misplaced, show its location.
    barrier_hole: Optional[BarrierHole] = None


class ServerInfo(TypedDict):
    """When the error server is active it writes this JSON to disk to communicate with us."""
    port: int  # The server should respond to 'https//localhost:{port}'.
    coop_text: str  # Localised copy of TOK_COOP_SHOWURL, so VRAD can set it in a game_text.


DATA_LOC = utils.conf_location('compile_error.pickle')
# The location of the ServerInfo data.
SERVER_INFO_FILE = utils.conf_location('error_server_info.json')


def to_threespace(vec: Union[Vec, FrozenVec]) -> TuplePos:
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
    simple_tiles: ClassVar[Dict[Kind, List[SimpleTile]]] = {kind: [] for kind in TEX_SET}

    def __init__(
        self,
        message: TransToken,
        *,
        docsurl: str='',
        voxels: Iterable[Union[Vec, FrozenVec]]=(),
        points: Iterable[Union[Vec, FrozenVec]]=(),
        textlist: Collection[str]=(),
        leakpoints: Collection[Union[Vec, FrozenVec]]=(),
        lines: Iterable[Tuple[Union[Vec, FrozenVec], Union[Vec, FrozenVec]]]=(),
        barrier_hole: Optional[BarrierHole]=None,
    ) -> None:
        """Specify the info to show to the user.

        :param message: This is a translation token potentially containing HTML. Strings
            formatted into it will be escaped.
        :param voxels: A list of offending voxel locations, which will be displayed in
            the render of the map as 64x64 boxes.
        :param points: A list of smaller points, which are displayed as 12 unit spheres.
        :param docsurl: If specified, adds a link to relevant documentation.
        :param textlist: If specified, adds the specified strings as a bulleted list.
        :param leakpoints: Specifies pointfile locations to display a leak.
        :param lines: A list of point pairs which get lines drawn.
        :param barrier_hole: If set, an errored glass/grating hole to place.
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
            message=message,
            language_file=None,
            context=ctx,
            faces=self.simple_tiles,
            voxels=list(map(to_threespace, voxels)),
            points=list(map(to_threespace, points)),
            leakpoints=list(map(to_threespace, leakpoints)),
            lines=[(to_threespace(a), to_threespace(b)) for a, b in lines],
            barrier_hole=barrier_hole,
        )

    def __str__(self) -> str:
        return f'Error message: {self.info.message}'


# Define a translation token for every error message that can be produced. The app will translate
# them all during export, then store that for the compiler's use.

# i18n: Special token, must be exactly two lines, shown via game_text if an error occurs in Coop.
TOK_COOP_SHOWURL = TransToken.ui(
    'Compile Error. Open the following URL\n'
    'in a browser on this computer to see:'
)

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

TOK_WRONG_ITEM_TYPE = TransToken.ui(
    'The item "<var>{item}</var>" is not a {kind}!<br>Instance: <code>{inst}</code>'
)

TOK_SEEDOCS = TransToken.untranslated('{msg}\n<p><a href="{url}">{docs}</a>.</p>').format(
    docs=TransToken.ui('See the documentation')
)

# Specific errors:

TOK_BRUSHLOC_LEAK = TransToken.ui(
    'One or more items were placed ouside the map! Move these back inside the map, or delete them. '
    'Items with no collision (like Half Walls or Logic Gates) can be left when rooms are moved, '
    'look for those.',
)

TOK_VBSP_LEAK = TransToken.ui(
    'This map has <a href="https://developer.valvesoftware.com/wiki/Leak">"leaked"</a>. This is a '
    'bug in an item or style, which should be fixed. The displayed line indicates the location of '
    'the leak, you may be able to resolve it by removing/modifying items in that area. Please '
    'submit a bug report to the author of the item so this can be resolved. Leak coordinates:'
)

TOK_VBSP_MISSING_INSTANCE = TransToken.ui(
    'The instance <code>{inst}</code> does not exist, meaning the map cannot be compiled! '
    'Try other configurations for this item, it may be the case that only some are missing.',
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
    'Check for reuse of the instance in multiple items, or restart Portal 2 if you just exported.'
)

TOK_CORRIDOR_EMPTY_GROUP = TransToken.ui(
    'No corridors were defined for the <var>{orient}_{mode}_{dir}</var> group. Try moving '
    'this door back onto a wall.'
)

# Format in so it automatically matches the stylevar name.
# i18n: Reference to the stylevar
UNLOCK_DEFAULT = TransToken.ui('Unlock Default Items')

TOK_CORRIDOR_NO_CORR_ITEM = TransToken.ui(
    'The map appears to be missing the {kind} door. This could be caused by an export from BEE2 while '
    'the game was open - close and reopen the game if that is the case. If it has been deleted, '
    'enable "{stylevar}" in Style Properties, then add it your palette so it can be put back in the '
    'map. If the door is present, this is likely an issue with the style definitions. '
).format(stylevar=UNLOCK_DEFAULT)

TOK_CORRIDOR_BOTH_MODES = TransToken.ui(
    'The map contains both singleplayer and coop entry/exit corridors. This can happen if they are '
    'manually added using the "{stylevar}" stylevar. In that case delete one of them.'
).format(stylevar=UNLOCK_DEFAULT)

TOK_CORRIDOR_ENTRY = TransToken.ui('Entry')  # i18n: Entry door
TOK_CORRIDOR_EXIT = TransToken.ui('Exit')  # i18n: Exit door

TOK_CUBE_NO_CUBETYPE_TEST = TransToken.ui('"CubeType" test used but with no type specified!')
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
TOK_CUBE_SUPERPOS_BAD_REAL = TransToken.ui(
    'Superposition Entanglers must be placed on top of a single dropper.'
)
TOK_CUBE_SUPERPOS_BAD_GHOST = TransToken.ui(
    'Superposition Entanglers must be connected to a single dropper, not any other items.'
)
TOK_CUBE_SUPERPOS_MULTILINK = TransToken.ui(
    'Two Superposition Entanglers cannot be connected to a single dropper!'
)

TOK_BARRIER_HOLE_FOOTPRINT = TransToken.ui(
    'A glass/grating Hole does not have sufficent space. The entire highlighted yellow area should '
    'be occupied by continous glass or grating. For large holes, the diagonally adjacient voxels '
    'are not required. In addition, two Hole items cannot overlap each other.'
)

TOK_BARRIER_HOLE_MISPLACED = TransToken.ui(
    'A glass/grating Hole was misplaced. The item must be placed against a glass or grating sheet, '
    'which it will then cut a hole into. To rotate the item properly, you may need to place it on '
    'a wall with the same orientation first, then drag it onto the glass without dragging it over '
    'surfaces with different orientations. Alternatively put a block temporarily in the glass or '
    "grating's location to position the hole item, then carve into the block from a side to remove "
    'it while keeping the hole in the same position.'
)

TOK_CHAINING_MULTI_INPUT = TransToken.ui(
    'A chain of items has multiple inputs to a single item. The chain should form a single '
    'path, not have branches.'
)

TOK_CHAINING_MULTI_OUTPUT = TransToken.ui(
    'A chain of items has multiple outputs from a single item. The chain should form a '
    'single path, not have branches.'
)

TOK_CHAINING_LOOP = TransToken.ui(
    'A chain of items has been constructed with a loop, but this type of item does not '
    'support a loop. Break the connection at some point.'
)

TOK_CHAINING_INVALID_KIND = TransToken.ui(
    'The highlighted items in this chain do not support being linked together in this '
    'fashion. Check the order of connections.'
)

TOK_TEMPLATE_MULTI_VISGROUPS = TransToken.ui(
    'The template "{id}" has a {type} with two visgroups: <var>{groups}</var>. Brushes and'
    'overlays in templates may currently only use one visgroup each.'
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
