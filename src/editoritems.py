"""Parses the Puzzlemaker's item format."""
from enum import Enum, Flag, auto
from typing import List, Dict, Optional, Tuple, Set, Container, Iterable, Union
from pathlib import PurePosixPath as FSPath

from srctools import Vec, logger
from srctools.tokenizer import Tokenizer, Token
from editoritems_props import ItemProp, PROP_TYPES


LOGGER = logger.get_logger(__name__)


class ItemClass(Enum):
    """PeTI item classes."""
    # Value: (ID, instance count, models per subitem)

    # Default
    UNCLASSED = ('ItemBase', 1, 1)

    FLOOR_BUTTON = ('ItemButtonFloor', 6, 1)
    PEDESTAL_BUTTON = ('ItemPedestalButton', 1, 1)

    PANEL_STAIR = 'ItemStairs', 1, 2
    PANEL_FLIP = 'ItemPanelFlip', 1, 1

    # Both glass and panel items
    PANEL_ANGLED = 'ItemAngledPanel', 1, 12
    PISTON_PLATFORM = 'ItemPistonPlatform', 1, 7
    TRACK_PLATFORM = 'ItemRailPlatform', 6, 3

    CUBE = 'ItemCube', 5, 2
    GEL = PAINT = 'ItemPaintSplat', 1, 1
    FAITH_PLATE = 'ItemCatapult', 1, 1

    CUBE_DROPPER = 'ItemCubeDropper', 1, 1
    GEL_DROPPER = PAINT_DROPPER = 'ItemPaintDropper'
    FAITH_TARGET = 'ItemCatapultTarget', 1, 1

    # Input-less items
    GLASS = 'ItemBarrier', 9, 1
    TURRET = 'ItemTurret', 1, 1
    LIGHT_STRIP = 'ItemLightStrip', 1, 1
    GOO = 'ItemGoo', 0, 2

    # Items with inputs
    LASER_EMITTER = 'ItemLaserEmitter', 1, 1
    FUNNEL = 'ItemTBeam', 3, 1
    FIZZLER = 'ItemBarrierHazard', 2, 1
    LIGHT_BRIDGE = 'ItemLightBridge', 1, 1

    # Extent/handle pseudo-items
    HANDLE_FIZZLER = 'ItemBarrierHazardExtent', 0, 1
    HANDLE_GLASS = 'ItemBarrierExtent', 0, 1
    HANDLE_PISTON_PLATFORM = 'ItemPistonPlatformExtent', 0, 1
    HANDLE_TRACK_PLATFORM = 'ItemRailPlatformExtent', 0, 1

    # Entry/Exit corridors
    DOOR_ENTRY_SP = 'ItemEntranceDoor', 12, 1
    DOOR_ENTRY_COOP = 'ItemCoopEntranceDoor', 5, 1
    DOOR_EXIT_SP = 'ItemExitDoor', 6, 2
    DOOR_EXIT_COOP = 'ItemCoopExitDoor', 6, 2

    @property
    def id(self) -> str:
        """The ID used in the configs."""
        return self.value[0]

    @property
    def inst_count(self) -> int:
        """The number of intances items of this type have, at maximum."""
        return self.value[1]

    @property
    def models_per_subtype(self) -> int:
        """The number of models to provide for each subtype."""
        return self.value[2]


CLASS_BY_NAME = {
    itemclass.id.casefold(): itemclass
    for itemclass in ItemClass
}

# The special item IDs for the two "renderables", which show up in their own
# block.
RENDERABLE_ERROR = 'ErrorState'
RENDERABLE_CONN = 'ConnectionHeartSolid'


class Handle(Enum):
    """Types of directional handles."""
    NONE = 'HANDLE_NONE'
    QUAD = 'HANDLE_4_DIRECTIONS'  # 4 directions
    CENT_OFF = 'HANDLE_5_DIRECTIONS'  # Center, 4 offsets
    DUAL_OFF = 'HANDLE_6_DIRECTIONS'  # 4 offsets, center in 2 directions
    QUAD_OFF = 'HANDLE_8_DIRECTIONS'  # 4 directions, center and offset each
    FREE_ROT = 'HANDLE_36_DIRECTIONS'  # 10 degree increments on floor
    FAITH = 'HANDLE_CATAPULT'  # Faith Plate


class Surface(Enum):
    """Used for InvalidSurface."""
    WALL = WALLS = 'WALLS'
    FLOOR = 'FLOOR'
    CEIL = CEILING = 'CEILING'


class DesiredFacing(Enum):
    """Items automatically reorient when moved around."""
    NONE = 'ANYTHING'  # Doesn't care.
    POSX = UP = 'UP'  # Point +x upward.
    NEGX = DN = DOWN = 'DOWN'  # Point -x upward.
    HORIZ = HORIZONTAL = 'HORIZONTAL'  # Point y axis up, either way.


class FaceType(Enum):
    """Types of surfaces produced by EmbedFace."""
    NORMAL = 'Grid_Default'  # Whatever normally appears.
    HALF_VERT = '2x1'  # Half-vertical white.
    LRG = FULL = '1x1'
    MED = HALF = '2x2'
    SML = QUAD = '4x4'
    CHECK = CHECKERED = '4x4_checkered'


class CollType(Enum):
    """Types of collisions between items."""
    GRATE = GRATING = auto()
    GLASS = auto()
    BRIDGE = auto()
    FIZZLER = auto()
    PHYSICS = auto()
    ANTLINES = auto()
    NOTHING = auto()
    EVERYTHING = auto()


class Sound(Enum):
    """Events which trigger a sound."""
    SELECT = 'SOUND_SELECTED'
    DESELECT = 'SOUND_DESELECTED'
    DELETE = 'SOUND_DELETED'
    CREATE = 'SOUND_CREATED'
    PROPS_OPEN = 'SOUND_EDITING_ACTIVATE'
    PROPS_CLOSE = 'SOUND_EDITING_DEACTIVATE'


class Anim(Enum):
    """Maps events to sequence indexes for the editor models.

    Most of these are used for the special cube behaviour.
    Flat there is on the floor without a dropper, fall is for the midair pose
    with a dropper.
    """
    IDLE = 'ANIM_IDLE'

    EDIT_START = 'ANIM_EDITING_ACTIVATE'
    EDIT_STOP = 'ANIM_EDITING_DEACTIVATE'

    CUBE_FLAT = IDLE
    CUBE_FLAT_EDIT_START = EDIT_START
    CUBE_FLAT_EDIT_STOP = EDIT_STOP

    CUBE_FALL = 'ANIM_FALLING_IDLE'
    CUBE_FALL_EDIT_START = 'ANIM_FALLING_EDITING_ACTIVATE'
    CUBE_FALL_EDIT_STOP = 'ANIM_FALLING_EDITING_DEACTIVATE'
    CUBE_FLAT2FALL = 'ANIM_GROUND_TO_FALLING'
    CUBE_FALL2FLAT = 'ANIM_FALLING_TO_GROUND'
    CUBE_FLAT2FALL_EDIT = 'ANIM_GROUND_TO_FALLING_EDITING'
    CUBE_FALL2FLAT_EDIT = 'ANIM_FALLING_TO_GROUND_EDITING'

    CDROP_ENABLE = 'ANIM_REAPPEAR'
    CDROP_DISABLE = 'ANIM_DISAPPEAR'

    # Connection heart icon:
    HEART_IDLE = 'ANIM_ICON_HEART_HAPPY_IDLE'
    HEART_CONN_MADE = 'ANIM_ICON_HEART_SUCCESS'
    HEART_CONN_BROKE = 'ANIM_ICON_HEART_BREAK'

    # Invalid-placement icon:
    BAD_PLACE_IDLE = 'ANIM_ICON_IDLE'
    BAD_PLACE_SHOW = 'ANIM_ICON_SHOW'
    BAD_PLACE_HIDE = 'ANIM_ICON_HIDE'


class ConnTypes(Enum):
    """Input/output types. Many of these are used to link item pairs."""
    NORMAL = IO = 'CONNECTION_STANDARD'  # Normal input/output
    POLARITY = 'CONNECTION_TBEAM_POLARITY'

    CUBE_DROPPER = BOX_DROPPER = 'CONNECTION_BOX_DROPPER'
    GEL_DROPPER = PAINT_DROPPER = 'CONNECTION_PAINT_DROPPER'
    BARRIER = 'CONNECTION_BARRIER_ANCHOR_TO_EXTENT'

    FIZZ_BRUSH = 'CONNECTION_HAZARD_BRUSH'
    FIZZ_MODEL = 'CONNECTION_HAZARD_MODEL'  # Broken open/close input.
    FIZZ = 'CONNECTION_HAZARD'  # Output from base.


ITEM_CLASSES: Dict[str, ItemClass] = {
    cls.id.casefold(): cls
    for cls in ItemClass
}

# The defaults, if this is unset.
DEFAULT_ANIMS = {
    Anim.IDLE: 0,
    Anim.EDIT_START: 1,
    Anim.EDIT_STOP: 2,
}
DEFAULT_SOUNDS = {
    Sound.SELECT: '',
    Sound.DESELECT: '',

    Sound.PROPS_OPEN: 'P2Editor.ExpandOther',
    Sound.PROPS_CLOSE: 'P2Editor.CollapseOther',

    Sound.CREATE: 'P2Editor.PlaceOther',
    Sound.DELETE: 'P2Editor.RemoveOther',
}


class SubType:
    """Represents a single sub-item component of an overall item.

    Should not be constructed directly.
    """
    # The name, shown on remove connection windows.
    name: str
    # The models this uses, in order. The editoritems format includes
    # a texture name for each of these, but it's never used.
    models: List[FSPath]
    # For each sound type, the soundscript to use.
    sounds: Dict[Sound, str]
    # For each animation category, the sequence index.
    anims: Dict[Anim, int]

    # The capitalised name to display in the bottom of the palette window.
    # If not on the palette, set to ''.
    pal_name: str
    # X/Y position on the palette, or None if not on the palette
    pal_pos: Optional[Tuple[int, int]]
    # The path to the icon VTF, in 'models/props_map_editor'.
    pal_icon: Optional[FSPath]


class Item:
    """A specific item."""
    id: str  # The item's unique ID.
    # The C++ class used to instantiate the item in the editor.
    cls: ItemClass
    subtype_prop: ItemProp
    # Movement handle
    handle: Handle
    facing: DesiredFacing
    invalid_surf: Set[Surface]

    anchor_barriers: bool
    anchor_goo: bool

    _subtypes: List[SubType]  # Each subtype in order.

    def __init__(
        self,
        item_id: str,
        cls: ItemClass,
        subtype_prop: Optional[ItemProp] = None,
        movement_handle: Handle = Handle.NONE,
        desired_facing: DesiredFacing = DesiredFacing.NONE,
        invalid_surf: Iterable[Surface] = (),
        anchor_on_barriers: bool = False,
        anchor_on_goo: bool = False,
    ) -> None:
        self.id = item_id
        self.cls = cls
        self.subtype_prop = subtype_prop
        self._subtypes = []
        self.properties: Dict[str, ItemProp] = {}
        self.handle = movement_handle
        self.facing = desired_facing
        self.invalid_surf = set(invalid_surf)
        self.anchor_barriers = anchor_on_barriers
        self.anchor_goo = anchor_on_goo
        self.offset = Vec()

    @classmethod
    def parse(cls, file: Iterable[str]) -> Dict[str, 'Item']:
        """Parse an entire editoritems file."""
        items: Dict[str, Item] = {}
        tok = Tokenizer(file)

        if tok.expect(Token.STRING).casefold() != 'itemdata':
            raise tok.error('No "ItemData" block present!')
        tok.expect(Token.BRACE_OPEN)

        for token, tok_value in tok:
            if token is Token.STRING:
                if tok_value.casefold() == 'item':
                    it = cls.parse_one(tok, False)
                    if it.id == RENDERABLE_ERROR:
                        raise ValueError('Error icon must be in the renderables section!')
                    if it.id == RENDERABLE_CONN:
                        raise ValueError('Connections icon must be in the renderables section!')
                    if it.id in items:
                        LOGGER.warning('Item {} redeclared!', it.id)
                    items[it.id] = it
                elif tok_value.casefold() == 'renderables':
                    tok.expect(Token.BRACE_OPEN)
                    for token, tok_value in tok:
                        if token is Token.STRING and tok_value.casefold() == 'item':
                            it = cls.parse_one(tok, True)
                            if it.id != RENDERABLE_ERROR and it.id != RENDERABLE_CONN:
                                raise ValueError(f'Item ID {it.id} is not a known renderable!')
                            items[it.id] = it
                        elif token is Token.BRACE_CLOSE:
                            break
                        elif token is not Token.NEWLINE:
                            raise tok.error(token)
                    else:
                        raise tok.error('Unclosed Renderables block!')
                else:
                    raise tok.error('Unknown block "{}"!', tok_value)
            elif token is Token.BRACE_CLOSE:
                break
            elif token is not Token.NEWLINE:
                raise tok.error(token)
        else:
            raise tok.error('Unclosed ItemData block!')
        return items

    @classmethod
    def parse_one(cls, tok: Tokenizer, renderable: bool) -> 'Item':
        """Parse an item.

        This expects the "Item" token to have been read already.
        """
        tok.expect(Token.BRACE_OPEN)
        item = cls('', ItemClass.UNCLASSED)

        for token, tok_value in tok:
            if token is Token.BRACE_CLOSE:
                # Done, check we're not missing critical stuff.
                if not item.id:
                    raise tok.error('No item ID (Type) set!')
                return item
            elif token is Token.NEWLINE:
                continue
            elif token is not Token.STRING:
                raise tok.error(token)
            tok_value = tok_value.casefold()
            if tok_value == 'type':
                if item.id:
                    raise tok.error('Item ID (Type) set multiple times!')
                item.id = tok.expect(Token.STRING).upper()
                if not item.id:
                    raise tok.error('Invalid item ID (Type) "{}"', item.id)
            elif tok_value == 'itemclass':
                item_class = tok.expect(Token.STRING)
                try:
                    item.cls = ITEM_CLASSES[item_class.casefold()]
                except KeyError:
                    raise tok.error('Unknown item class {}!', item_class)
            elif tok_value == 'editor':
                tok.expect(Token.BRACE_OPEN)
                item._parse_editor_block(tok)
            elif tok_value == 'properties':
                tok.expect(Token.BRACE_OPEN)
                item._parse_properties_block(tok)
            elif tok_value == 'exporting':
                tok.expect(Token.BRACE_OPEN)
                item._parse_export_block(tok)
            else:
                raise tok.error('Unexpected item option "{}"!', tok_value)

        raise tok.error('File ended without closing item block!')

    def _parse_editor_block(self, tok: Tokenizer) -> None:
        """Parse the editor block of the item definitions."""

    def _parse_properties_block(self, tok: Tokenizer) -> None:
        """Parse the properties block of the item definitions."""

    def _parse_export_block(self, tok: Tokenizer) -> None:
        """Parse the export block of the item definitions."""
