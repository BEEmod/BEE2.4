"""Parses the Puzzlemaker's item format."""
from __future__ import annotations
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from enum import Enum, Flag
from typing import Callable, ClassVar, Final, List, Optional, Protocol, Any, Tuple
from pathlib import PurePosixPath as FSPath

import attrs

from srctools import Vec, logger, conv_int, conv_bool, Keyvalues, Output
from srctools.tokenizer import Tokenizer, Token
from typing_extensions import TypeAlias

from connections import Config as ConnConfig, InputType, OutNames
from editoritems_props import ItemProp, ItemPropKind, PROP_TYPES
from collisions import CollideType, BBox, NonBBoxError
from transtoken import TransToken, TransTokenSource


__all__ = [
    "ItemProp", "ItemPropKind", "PROP_TYPES",  "ConnConfig", "InputType", "OutNames", "FSPath",  # Re-export
    "ItemClass", "RenderableType", "Handle", "Surface", "DesiredFacing", "FaceType", "OccuType",
    "Sound", "Anim", "ConnTypes", "Connection", "InstCount", "Coord", "EmbedFace", "Overlay",
    "ConnSide", "AntlinePoint", "OccupiedVoxel", "Renderable", "SubType", "Item",
    "bounding_boxes",
]
LOGGER = logger.get_logger(__name__)
# __getstate__ / __setstate__ types.
_SubTypeState: TypeAlias = Tuple[TransToken, List[str], List[str], List[int], TransToken, int, int, Optional[FSPath]]


class ItemClass(Enum):
    """PeTI item classes."""
    # Value:
    # -  The ID used in the configs.
    # - The number of instances items of this type have, at maximum.
    # - The number of models to provide for each subtype.

    def __init__(self, name: str, inst_count: int, models: int) -> None:
        """Initialise attributes."""
        self.id = name
        self.inst_count = inst_count
        self.mdl_per_subtype = models

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
    GEL_DROPPER = PAINT_DROPPER = 'ItemPaintDropper', 1, 4
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
    HANDLE_PISTON_PLATFORM = 'ItemPistonPlatformExtent', 0, 2
    HANDLE_TRACK_PLATFORM = 'ItemRailPlatformExtent', 0, 1

    # Entry/Exit corridors
    DOOR_ENTRY_SP = 'ItemEntranceDoor', 12, 1
    DOOR_ENTRY_COOP = 'ItemCoopEntranceDoor', 5, 1
    DOOR_EXIT_SP = 'ItemExitDoor', 6, 2
    DOOR_EXIT_COOP = 'ItemCoopExitDoor', 6, 2


CLASS_BY_NAME = {
    itemclass.id.casefold(): itemclass
    for itemclass in ItemClass
}


class RenderableType(Enum):
    """The two "renderables", which show up in their own block."""
    ERROR = 'ErrorState'
    CONN = 'ConnectionHeartSolid'


class Handle(Enum):
    """Types of directional handles."""
    NONE = 'HANDLE_NONE'
    QUAD = 'HANDLE_4_DIRECTIONS'  # 4 directions
    CENT_OFF = 'HANDLE_5_POSITIONS'  # Center, 4 offsets
    DUAL_OFF = 'HANDLE_6_POSITIONS'  # 4 offsets, center in 2 directions
    QUAD_OFF = 'HANDLE_8_POSITIONS'  # 4 directions, center and offset each
    FREE_ROT = 'HANDLE_36_DIRECTIONS'  # 10 degree increments on floor
    FAITH = 'HANDLE_CATAPULT'  # Faith Plate


class Surface(Enum):
    """Used for InvalidSurface."""
    WALL = WALLS = 'WALL'
    FLOOR = 'FLOOR'
    CEIL = CEILING = 'CEILING'


class DesiredFacing(Enum):
    """Items automatically reorient when moved around."""
    NONE = 'DESIRES_ANYTHING'  # Doesn't care.
    POSX = UP = 'DESIRES_UP'  # Point +x upward.
    NEGX = DN = DOWN = 'DESIRES_DOWN'  # Point -x upward.
    HORIZ = HORIZONTAL = 'DESIRES_HORIZONTAL'  # Point y axis up, either way.


class FaceType(Enum):
    """Types of surfaces produced by EmbedFace."""
    NORMAL = 'Grid_Default'  # Whatever normally appears.
    HALF_VERT = '2x1'  # Half-vertical white.
    LRG = FULL = '1x1'
    MED = HALF = '2x2'
    SML = QUAD = '4x4'
    CHECK = CHECKERED = '4x4_checkered'


class OccuType(Flag):
    """Types of occupation between items.

    This is named OccuType to distinguish it from the expanded collision types
    used in the compiler.
    Physics is excluded from the generated piston collisions, if it
    can move out of those locations.
    """
    NOTHING =          0b0
    SOLID =            0b1
    GRATING =         0b10
    GLASS =          0b100
    BRIDGE =        0b1000
    FIZZLER =      0b10000
    PHYSICS =     0b100000
    ANTLINES =   0b1000000
    EVERYTHING = 0b1111111

    GRATE = GRATING
    NONE = NOTHING
    # If unset, everything but physics collides.
    DEFAULT = SOLID | GRATE | GLASS | BRIDGE | FIZZLER | PHYSICS | ANTLINES

    @classmethod
    def parse(cls, tok: Tokenizer) -> OccuType:
        """Parse the collision type value."""
        coll = cls.NOTHING
        for part in tok.expect(Token.STRING).split():
            try:
                coll |= OCCU_TYPES[part.upper()]
            except KeyError:
                raise tok.error('Unknown Occupied Voxels collision type "{}"!', part) from None
        return coll

    def __str__(self) -> str:
        """The string form is each of the names seperated by spaces."""
        value = self.value
        try:
            return _occu_type_str[value]
        except KeyError:
            pass
        names = []
        for name, occu_type in OCCU_TYPES.items():
            if name != 'COLLIDE_EVERYTHING' and occu_type.value & value:
                names.append(name)
        names.sort()
        res = _occu_type_str[value] = ' '.join(names)
        return res

    @property
    def collision(self) -> CollideType:
        """Convert to the equivalent collision type."""
        try:
            return _occu_to_collide[self]
        except KeyError:
            pass
        result = CollideType.NOTHING
        occu_type: OccuType
        for occu_type in OccuType:
            if occu_type is OccuType.EVERYTHING:
                continue
            assert occu_type.name is not None, occu_type
            if occu_type.value & self.value:
                result |= CollideType[occu_type.name]
        _occu_to_collide[self] = result
        return result


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

    @classmethod
    def parse_block(cls, anims: dict[Anim, int], tok: Tokenizer) -> None:
        """Parse a block of animation definitions."""
        for anim_name in tok.block('Animations'):
            try:
                anim = Anim(anim_name)
            except ValueError:
                raise tok.error('Unknown animation {}', anim_name) from None
            anims[anim] = conv_int(tok.expect(Token.STRING))


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


class _TextFile(Protocol):
    """The functions we require in order to write text to a file."""
    def write(self, __text: str) -> Any:
        """We simply need a write() method, and ignore the return value."""


@attrs.define
class Connection:
    """Activate/deactivate pair defined for connections."""
    act_name: str | None
    activate: str | None  # Input/output used to activate.
    deact_name: str | None
    deactivate: str | None  # Input/output used to deactivate.

    def write(self, f: _TextFile, conn_type: str) -> None:
        """Produce the activate/deactivate keys."""
        if self.activate is None and self.deactivate is None:
            return
        f.write(f'\t\t\t"{conn_type}"\n')
        f.write('\t\t\t\t{\n')
        if self.activate is not None:
            if self.act_name:
                f.write(f'\t\t\t\t"Activate" "instance:{self.act_name};{self.activate}"\n')
            else:
                f.write(f'\t\t\t\t"Activate" "{self.activate}"\n')
        if self.deactivate is not None:
            if self.deact_name:
                f.write(f'\t\t\t\t"Deactivate" "instance:{self.deact_name};{self.deactivate}"\n')
            else:
                f.write(f'\t\t\t\t"Deactivate" "{self.deactivate}"\n')
        f.write('\t\t\t\t}\n')


@attrs.define
class InstCount:
    """Instances have several associated counts."""
    # The actual filename.
    inst: FSPath = attrs.field(converter=FSPath)
    ent_count: int = 0
    brush_count: int = 0
    face_count: int = 0


@attrs.frozen
class Coord:
    """Integer coordinates."""
    x: int
    y: int
    z: int

    def __str__(self) -> str:
        """The string form has no delimiters."""
        return f'{self.x} {self.y} {self.z}'

    def __iter__(self) -> Iterator[int]:
        """Return each coordinate in order."""
        yield self.x
        yield self.y
        yield self.z

    @classmethod
    def from_vec(cls, vec: Vec) -> Coord:
        """Round a vector to grid coordinates."""
        x = round(vec.x)
        y = round(vec.y)
        z = round(vec.z)
        try:
            return _coord_cache[x, y, z]
        except KeyError:
            result = cls(x, y, z)
            _coord_cache[x, y, z] = result
            return result

    @classmethod
    def parse(cls, value: str, error_func: Callable[..., BaseException]) -> Coord:
        """Parse from a string, using the function to raise errors."""
        parts = value.split()
        if len(parts) != 3:
            raise error_func('Incorrect number of points for a coordinate!')
        try:
            x = int(parts[0])
        except ValueError:
            raise error_func('Invalid coordinate value "{}"!', parts[0]) from None
        try:
            y = int(parts[1])
        except ValueError:
            raise error_func('Invalid coordinate value "{}"!', parts[1]) from None
        try:
            z = int(parts[2])
        except ValueError:
            raise error_func('Invalid coordinate value "{}"!', parts[2]) from None
        try:
            return _coord_cache[x, y, z]
        except KeyError:
            result = cls(x, y, z)
            _coord_cache[x, y, z] = result
            return result

    def bbox(self, other: Coord) -> Iterator[Coord]:
        """Iterate through the points inside this bounding box."""
        range_x = range(min(self.x, other.x), max(self.x, other.x) + 1)
        range_y = range(min(self.y, other.y), max(self.y, other.y) + 1)
        range_z = range(min(self.z, other.z), max(self.z, other.z) + 1)
        for x in range_x:
            for y in range_y:
                for z in range_z:
                    try:
                        result = _coord_cache[x, y, z]
                    except KeyError:
                        result = Coord(x, y, z)
                        _coord_cache[x, y, z] = result
                    yield result


@attrs.define
class EmbedFace:
    """A face generated by the editor."""
    center: Vec  # Center point, Z always is 128.
    size: Vec  # Size of the tile.
    type: FaceType  # Surface material.


@attrs.define
class Overlay:
    """An overlay placed by the editor on the ground."""
    material: str  # Material to show.
    center: Vec  # Center point.
    size: Vec  # Size of the overlay.
    rotation: int  # Orientation of the overlay.


# Cache these coordinates, since most items are going to be near the origin.
_coord_cache: dict[tuple[int, int, int], Coord] = {}

NORMALS = {
    Coord(0, 0, -1),
    Coord(0, 0, +1),
    Coord(0, -1, 0),
    Coord(0, +1, 0),
    Coord(-1, 0, 0),
    Coord(+1, 0, 0),
}
_coord_cache.update({
    (c.x, c.y, c.z): c
    for c in NORMALS
})
# Cache the computed value shapes.
_occu_type_str: dict[int, str] = {
    OccuType.NOTHING.value: 'COLLIDE_NOTHING',
    OccuType.EVERYTHING.value: 'COLLIDE_EVERYTHING',
}
# Cached OccuType -> CollideType conversions.
_occu_to_collide: dict[OccuType, CollideType] = {}

ITEM_CLASSES: dict[str, ItemClass] = {
    cls.id.casefold(): cls
    for cls in ItemClass
}
FACE_TYPES: dict[str, FaceType] = {
    face.value.casefold(): face
    for face in FaceType
}
OCCU_TYPES: dict[str, OccuType] = {
    'COLLIDE_' + name: OccuType[name]
    for name in [
        "NOTHING", "SOLID", "GRATING", "GLASS", "BRIDGE", "FIZZLER", "PHYSICS",
        "ANTLINES", "EVERYTHING",
    ]
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
_BLANK_INST = [InstCount(FSPath(), 0, 0, 0)]


class ConnSide(Enum):
    """Sides of an item, where antlines connect to.

    The name is the side of the item it attaches, the vector is the direction the end points - so
    they're reversed compared to each other.
    """
    LEFT = Coord(1, 0, 0)
    RIGHT = Coord(-1, 0, 0)
    UP = Coord(0, 1, 0)
    DOWN = Coord(0, -1, 0)

    @classmethod
    def from_yaw(cls, value: int) -> ConnSide:
        """Return the the side pointing in this yaw direction."""
        value %= 360
        if value == 0:
            return ConnSide.LEFT
        elif value == 90:
            return ConnSide.DOWN
        elif value == 180:
            return ConnSide.RIGHT
        elif value == 270:
            return ConnSide.UP
        raise ValueError(f'Invalid yaw {value}!')

    @classmethod
    def parse(cls, value: str, error_func: Callable[..., BaseException]) -> ConnSide:
        """Parse a connection side."""
        try:
            return cls[value.upper()]
        except KeyError:
            pass
        parts = value.split()
        if len(parts) != 3:
            raise error_func('Incorrect number of points for a direction!')
        try:
            x, y, z = map(int, parts)
        except ValueError:
            raise error_func('Invalid connection side "{}"!', value) from None
        if z != 0:
            raise error_func('Connection side must be flat!')
        if x == 0:
            if y == 1:
                return ConnSide.UP
            elif y == -1:
                return ConnSide.DOWN
        elif y == 0:
            if x == -1:
                return ConnSide.RIGHT
            elif x == 1:
                return ConnSide.LEFT
        raise error_func('Unknown connection side ({}, {}, 0)', x, y)

    @property
    def x(self) -> int:
        """Return the X coordinate."""
        return self.value.x

    @property
    def y(self) -> int:
        """Return the X coordinate."""
        return self.value.y

    @property
    def yaw(self) -> int:
        """Return the yaw direction."""
        if self is ConnSide.LEFT:
            return 0
        if self is ConnSide.DOWN:
            return 90
        if self is ConnSide.RIGHT:
            return 180
        if self is ConnSide.UP:
            return 270
        raise AssertionError(f'Unknown value {self!r}')


@attrs.frozen
class AntlinePoint:
    """Locations antlines can connect to."""
    pos: Coord
    sign_off: Coord
    priority: int
    group: int | None


@attrs.frozen
class OccupiedVoxel:
    """Represents the collision information for an item.

    If normal is not None, this is a side and not a cube.
    If subpos is not None, this is a 32x32 cube and not a full voxel.
    """
    type: OccuType
    against: OccuType | None  # TODO: Don't know what the default is.
    pos: Coord
    subpos: Coord | None = None
    normal: Coord | None = None


def bounding_boxes(voxels: Iterable[Coord]) -> Iterator[tuple[Coord, Coord]]:
    """Decompose a bunch of points into a small list of bounding boxes enclosing them.

    This is used to determine a good set of Volume definitions to write out.
    """
    # To compute the volume, pick a random point still to be done, then
    # expand as far as possible in each direction.
    EXTENT = 50
    todo = set(voxels)
    while todo:
        x1, y1, z1 = x2, y2, z2 = todo.pop()
        # X+:
        for x in range(x1 + 1, x1 + EXTENT):
            if Coord(x, y1, z1) in todo:
                x2 = x
            else:
                break
        # X-:
        for x in range(x1 - 1, x1 - EXTENT, -1):
            if Coord(x, y1, z1) in todo:
                x1 = x
            else:
                break

        # Y+:
        for y in range(y1 + 1, y1 + EXTENT):
            if all(Coord(x, y, z1) in todo for x in range(x1, x2+1)):
                y2 = y
            else:
                break

        # Y-:
        for y in range(y1 - 1, y1 - EXTENT, -1):
            if all(Coord(x, y, z1) in todo for x in range(x1, x2+1)):
                y1 = y
            else:
                break

        # Y+:
        for z in range(z1 + 1, z1 + EXTENT):
            if all(Coord(x, y, z) in todo for x in range(x1, x2+1) for y in range(y1, y2+1)):
                z2 = z
            else:
                break

        # Y-:
        for z in range(z1 - 1, z1 - EXTENT, -1):
            if all(Coord(x, y, z) in todo for x in range(x1, x2+1) for y in range(y1, y2+1)):
                z1 = z
            else:
                break

        for x in range(x1, x2+1):
            for y in range(y1, y2+1):
                for z in range(z1, z2+1):
                    todo.discard(Coord(x, y, z))
        yield Coord(x1, y1, z1), Coord(x2, y2, z2)


@attrs.define
class Renderable:
    """Simpler definition used for the heart and error icons."""
    _types: ClassVar = {r.value.casefold(): r for r in RenderableType}

    type: RenderableType
    model: str
    animations: dict[Anim, int]

    @classmethod
    def parse(cls, tok: Tokenizer) -> Renderable:
        """Parse a renderable."""
        kind: RenderableType | None = None
        model = ''
        anims: dict[Anim, int] = {}

        for key in tok.block("Renderable Item"):
            if key.casefold() == "type":
                render_id = tok.expect(Token.STRING)
                try:
                    kind = cls._types[render_id.casefold()]
                except KeyError:
                    raise tok.error('Unknown Renderable "{}"!', render_id) from None
            elif key.casefold() == "animations":
                Anim.parse_block(anims, tok)
            elif key.casefold() == "model":
                model = tok.expect(Token.STRING)
            else:
                raise tok.error('Unknown renderable option "{}"!', key)
        if kind is None:
            raise tok.error('No type specified for Renderable!')
        return Renderable(kind, model, anims)


@attrs.define
class SubType:
    """Represents a single sub-item component of an overall item.

    Should not be constructed directly.
    """
    # The name, shown on remove connection windows.
    name: TransToken = TransToken.BLANK
    # The models this uses, in order. The editoritems format includes
    # a texture name for each of these, but it's never used.
    models: list[FSPath] = attrs.Factory(list)
    # For each sound type, the soundscript to use.
    sounds: dict[Sound, str] = attrs.Factory(DEFAULT_SOUNDS.copy)
    # For each animation category, the sequence index.
    anims: dict[Anim, int] = attrs.Factory(dict)

    # The capitalised name to display in the bottom of the palette window.
    # If not on the palette, set to blank
    pal_name: TransToken = TransToken.BLANK
    # X/Y position on the palette, or None if not on the palette
    pal_pos: tuple[int, int] | None = None
    # The path to the icon VTF, in 'models/props_map_editor'.
    pal_icon: FSPath | None = None

    def copy(self) -> SubType:
        """Duplicate this subtype."""
        return SubType(
            self.name,
            self.models.copy(),
            self.sounds.copy(),
            self.anims.copy(),
            self.pal_name,
            self.pal_pos,
            self.pal_icon,
        )

    __copy__ = copy

    def __deepcopy__(self, memodict: dict[int, Any] | None = None) -> SubType:
        """Duplicate this subtype.

        We don't need to deep-copy the contents of the containers,
        since they're all immutable.
        """
        return SubType(
            self.name,
            self.models.copy(),
            self.sounds.copy(),
            self.anims.copy(),
            self.pal_name,
            self.pal_pos,
            self.pal_icon,
        )

    def __getstate__(self) -> object:
        if self.pal_pos is None:
            x, y = -1, -1
        else:
            x, y = self.pal_pos

        anim = [self.anims.get(anim, -1) for anim in Anim]
        while anim and anim[-1] == -1:  # Remove any -1 from the end.
            anim.pop()

        return (
            self.name,
            list(map(str, self.models)),
            # These are mostly the same, intern so it deduplicates.
            [sys.intern(self.sounds.get(snd, '')) for snd in Sound],
            anim,
            self.pal_name,
            x, y,
            self.pal_icon,
        )

    def __setstate__(self, state: _SubTypeState) -> None:
        self.name, mdls, snds, anims, self.pal_name, x, y, self.pal_icon = state
        self.models = list(map(FSPath, mdls))
        self.sounds = {
            snd: sndscript
            for snd, sndscript in zip(Sound, snds)
            if sndscript
        }
        self.anims = {
            anim: ind
            for anim, ind in zip(Anim, anims)
            if ind != -1
        }
        if x >= 0 and y >= 0:
            self.pal_pos = x, y
        else:
            self.pal_pos = None

    @classmethod
    def parse(cls, tok: Tokenizer, pak_id: str) -> SubType:
        """Parse a subtype from editoritems."""
        subtype = SubType()
        for key in tok.block('Subtype'):
            folded_key = key.casefold()
            if folded_key == 'name':
                subtype.name = TransToken.parse(pak_id, tok.expect(Token.STRING))
            elif folded_key == 'model':
                # In the original file this is a block, but allow a name
                # since the texture is unused.
                token, tok_value = next(tok.skipping_newlines())
                model_name: FSPath | None = None
                if token is Token.STRING:
                    model_name = FSPath(tok_value)
                elif token is Token.BRACE_OPEN:
                    # Parse the block.
                    for subkey in tok.block('Model', consume_brace=False):
                        subkey = subkey.casefold()
                        if subkey == 'modelname':
                            model_name = FSPath(tok.expect(Token.STRING))
                        elif subkey == 'texturename':
                            tok.expect(Token.STRING)  # Skip this.
                        else:
                            raise tok.error('Unknown model option "{}"!', subkey)
                else:
                    raise tok.error(token)
                if model_name is None:
                    raise tok.error('No model name specified!')
                if model_name.suffix.casefold() != '.mdl':
                    # Swap to '.mdl', since that's what the real model is.
                    model_name = model_name.with_suffix('.mdl')
                subtype.models.append(model_name)
            elif folded_key == 'palette':
                for subkey in tok.block('Palette'):
                    subkey = subkey.casefold()
                    if subkey == 'tooltip':
                        subtype.pal_name = TransToken.parse(pak_id, tok.expect(Token.STRING))
                    elif subkey == 'image':
                        # Usually defined in file as PNG, but actually VTF.
                        subtype.pal_icon = FSPath(tok.expect(Token.STRING)).with_suffix('.vtf')
                    elif subkey == 'position':
                        points = tok.expect(Token.STRING).split()
                        if len(points) in (2, 3):
                            try:
                                x = int(points[0])
                                y = int(points[1])
                            except ValueError:
                                raise tok.error('Invalid position value!') from None
                        else:
                            raise tok.error('Incorrect number of points in position') from None
                        subtype.pal_pos = x, y
                    else:
                        raise tok.error('Unknown palette option "{}"!', subkey)
            elif folded_key == 'sounds':
                for sound_kind in tok.block('Sounds'):
                    try:
                        sound = Sound(sound_kind.upper())
                    except ValueError:
                        raise tok.error('Unknown sound type "{}"!', sound_kind) from None
                    subtype.sounds[sound] = tok.expect(Token.STRING)
            elif folded_key == 'animations':
                Anim.parse_block(subtype.anims, tok)
            else:
                raise tok.error('Unknown subtype option "{}"!', key)
        return subtype

    def export(self, f: _TextFile) -> None:
        """Write the subtype to a file."""
        f.write('\t\t"SubType"\n\t\t\t{\n')
        if self.name:
            f.write(f'\t\t\t"Name" "{self.name.as_game_token()}"\n')
        for model in self.models:
            # It has to be a .3ds file, even though it's really MDL.
            model = model.with_suffix('.3ds')
            f.write(f'\t\t\t"Model" {{ "ModelName" "{model}" }}\n')
        if self.pal_pos is not None:
            f.write('\t\t\t"Palette"\n\t\t\t\t{\n')
            f.write(f'\t\t\t\t"Tooltip"  "{self.pal_name.as_game_token()}"\n')
            if self.pal_icon is not None:
                # Similarly needs to be PNG even though it's really VTF.
                pal_icon = self.pal_icon.with_suffix('.png')
                f.write(f'\t\t\t\t"Image"    "{pal_icon}"\n')
            x, y = self.pal_pos
            f.write(f'\t\t\t\t"Position" "{x} {y} 0"\n')
            f.write('\t\t\t\t}\n')
        if self.sounds and self.sounds != DEFAULT_SOUNDS:
            f.write('\t\t\t"Sounds"\n\t\t\t\t{\n')
            for snd_type in Sound:
                try:
                    sndscript = self.sounds[snd_type]
                except KeyError:
                    continue
                f.write(f'\t\t\t\t"{snd_type.value}" "{sndscript}"\n')
            f.write('\t\t\t\t}\n')
        if self.anims:
            f.write('\t\t\t"Animations"\n\t\t\t\t{\n')
            for anim_name, anim_ind in sorted(self.anims.items(), key=lambda t: t[1]):
                f.write(f'\t\t\t\t"{anim_name.value}" "{anim_ind}"\n')
            f.write('\t\t\t\t}\n')
        f.write('\t\t\t}\n')


@attrs.define
class Item:
    """A specific item."""
    id: str  # The item's unique ID.
    # The C++ class used to instantiate the item in the editor.
    cls: ItemClass = ItemClass.UNCLASSED
    # Type if present.
    subtype_prop: ItemPropKind[Any] | None = None
    subtypes: list[SubType] = attrs.Factory(list)  # Each subtype in order.
    # Movement handle
    handle: Handle = Handle.NONE
    facing: DesiredFacing = DesiredFacing.NONE
    invalid_surf: set[Surface] = attrs.field(factory=set)
    # Anim name to sequence index.
    animations: dict[Anim, int] = attrs.field(factory=dict)

    anchor_barriers: bool = False
    anchor_goo: bool = False
    occupies_voxel: bool = False
    pseudo_handle: bool = False
    copiable: bool = True
    deletable: bool = True

    targetname: str = ''
    # The default is 0 0 0, but this isn't useful since the rotation point
    # is wrong. So just make it the useful default, users can override.
    offset: Vec = attrs.Factory(lambda: Vec(64, 64, 64))

    properties: dict[str, ItemProp[Any]] = attrs.Factory(dict)

    # The instances used by the editor, then custom slots used by
    # conditions. For the latter we don't care about the counts.
    instances: list[InstCount] = attrs.Factory(list)
    cust_instances: dict[str, FSPath] = attrs.Factory(dict)

    antline_points: dict[ConnSide, list[AntlinePoint]] = attrs.Factory(lambda: {
        side: [] for side in ConnSide
    })
    # The points this collides with.
    occupy_voxels: set[OccupiedVoxel] = attrs.Factory(set)
    # The voxels this hollows out inside the floor.
    embed_voxels: set[Coord] = attrs.Factory(set)
    # Brushes automatically created
    embed_faces: list[EmbedFace] = attrs.Factory(list)
    # Overlays automatically placed
    overlays: list[Overlay] = attrs.Factory(list)
    # More precise BEE collisions.
    collisions: list[BBox] = attrs.Factory(list)
    # Record if collisions were set in editoritems, so an empty block can be used
    # to opt out of inheriting from occupied voxels.
    _has_collisions_block: bool = attrs.field(init=False, default=False, repr=False)

    # Connection types that don't represent item I/O, like for droppers
    # or fizzlers.
    conn_inputs: dict[ConnTypes, Connection] = attrs.Factory(dict)
    conn_outputs: dict[ConnTypes, Connection] = attrs.Factory(dict)

    # The configuration for actual item I/O.
    conn_config: ConnConfig | None = None
    # If we want to force this item to have inputs/outputs,
    # like for linking together items.
    force_input: bool = False
    force_output: bool = False

    def has_prim_input(self) -> bool:
        """Check whether this item has a primary input."""
        if self.force_input:
            return True
        if self.conn_config is None:
            return False
        return bool(self.conn_config.enable_cmd or self.conn_config.disable_cmd)

    def has_sec_input(self) -> bool:
        """Check whether this item has a secondary input."""
        if self.conn_config is None:
            return False
        return bool(self.conn_config.sec_enable_cmd or self.conn_config.sec_disable_cmd)

    def has_output(self) -> bool:
        """Check whether this item has an output."""
        if self.force_output:
            return True
        if self.conn_config is None:
            return False
        return self.conn_config.output_act is not None or self.conn_config.output_deact is not None

    def set_inst(self, ind: int, inst: InstCount) -> None:
        """Set the specified instance index, filling empty spaces in the list."""
        inst_count = len(self.instances)
        if ind < 0:
            raise ValueError(f'Index must be positive, not {ind}!')
        elif ind < inst_count:
            self.instances[ind] = inst
        elif ind == inst_count:
            self.instances.append(inst)
        else:
            # Add blank spots.
            self.instances += _BLANK_INST * (ind - inst_count)
            self.instances.append(inst)
        assert self.instances[ind] is inst

    @classmethod
    def parse(
        cls,
        file: Iterable[str],
        filename: str | None = None,
    ) -> tuple[list[Item], dict[RenderableType, Renderable]]:
        """Parse an entire editoritems file.

        The "ItemData" {} wrapper may optionally be included.
        """
        known_ids: set[str] = set()
        items: list[Item] = []
        icons: dict[RenderableType, Renderable] = {}
        tok = Tokenizer(file, filename)

        # Check for the itemdata header.
        itemdata_header = False
        for tok_type, tok_value in tok:
            if tok_type is Token.STRING and tok_value == 'ItemData':
                tok.expect(Token.BRACE_OPEN)
                itemdata_header = True
                break
            elif tok_type is not Token.NEWLINE:
                # Something else, no header is present.
                tok.push_back(tok_type, tok_value)
                break

        for tok_type, tok_value in tok:
            if tok_type is Token.NEWLINE:
                continue
            elif tok_type is Token.BRACE_CLOSE and itemdata_header:
                break
            elif tok_type is not Token.STRING:
                raise tok.error(tok_type)

            if tok_value.casefold() == 'item':
                it = cls.parse_one(tok)
                if it.id.casefold() in known_ids:
                    LOGGER.warning('Item {} redeclared!', it.id)
                known_ids.add(it.id.casefold())
                items.append(it)
            elif tok_value.casefold() == 'renderables':
                for render_block in tok.block('Renderables'):
                    if render_block.casefold() != 'item':
                        raise tok.error('Unknown block "{}"!', render_block)
                    ico = Renderable.parse(tok)
                    icons[ico.type] = ico
            else:
                raise tok.error('Unknown block "{}"!', tok_value)
        else:
            if itemdata_header:
                raise tok.error("ItemData block wasn't closed!")

        return items, icons

    @classmethod
    def parse_one(cls, tok: Tokenizer, pak_id: str='') -> Item:
        """Parse an item.

        This expects the "Item" token to have been read already.
        """
        connections = Keyvalues('Connections', [])
        tok.expect(Token.BRACE_OPEN)
        item = Item('')

        for token, tok_value in tok:
            if token is Token.BRACE_CLOSE:
                # We're finished.
                break
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
                # The items here are used internally and must have inputs.
                if item.id in {
                    'ITEM_INDICATOR_TOGGLE',
                    'ITEM_INDICATOR_PANEL',
                    'ITEM_INDICATOR_PANEL_TIMER',
                }:
                    item.force_input = True
            elif tok_value == 'itemclass':
                item_class = tok.expect(Token.STRING)
                try:
                    item.cls = ITEM_CLASSES[item_class.casefold()]
                except KeyError:
                    raise tok.error('Unknown item class {}!', item_class) from None
            elif tok_value == 'editor':
                item._parse_editor_block(tok, pak_id)
            elif tok_value == 'properties':
                item._parse_properties_block(tok, pak_id)
            elif tok_value == 'exporting':
                item._parse_export_block(tok, connections)
            elif tok_value in ('author', 'description', 'filter'):
                # These are BEE2.2 values, which are not used.
                tok.expect(Token.STRING)
            else:
                raise tok.error('Unexpected item option "{}"!', tok_value)
        else:
            raise tok.error('File ended without closing item block!')

        # Done, check we're not missing critical stuff.
        if not item.id:
            raise tok.error('No item ID (Type) set!')

        # If the user defined a subtype property, that prop's default value should not be changed.
        if item.subtype_prop is not None:
            prop_name = item.subtype_prop.id
            try:
                item.properties[prop_name.casefold()].allow_user_default = False
            except KeyError:
                LOGGER.warning('Subtype property of "{}" set, but property not present!', prop_name)

        # Parse the connection info, if it exists.
        if connections or item.conn_inputs or item.conn_outputs:
            item.conn_config = ConnConfig.parse(item.id, connections)
            item._finalise_connections()
            if 'activate' in connections or 'deactivate' in connections:
                LOGGER.warning('', exc_info=tok.error('Output activate/deactivate commands need out_ prefix!'))
        return item

    # Boolean option in editor -> Item attribute.
    _BOOL_ATTRS: ClassVar[Mapping[str, str]] = {
        'cananchoronbarriers': 'anchor_barriers',
        'cananchorongoo': 'anchor_barriers',
        'occupiesvoxel': 'occupies_voxel',
        'copyable': 'copiable',
        'deletable': 'deletable',
        'pseudohandle': 'pseudo_handle',
    }

    def _parse_editor_block(self, tok: Tokenizer, pak_id: str) -> None:
        """Parse the editor block of the item definitions."""
        for key in tok.block('Editor'):
            folded_key = key.casefold()
            if folded_key == 'subtype':
                self.subtypes.append(SubType.parse(tok, pak_id))
            elif folded_key == 'animations':
                Anim.parse_block(self.animations, tok)
            elif folded_key == 'movementhandle':
                handle_str = tok.expect(Token.STRING)
                try:
                    self.handle = Handle(handle_str.upper())
                except ValueError:
                    LOGGER.warning(
                        'Unknown movement handle "{}"  in ({}:{})',
                        handle_str, tok.filename, tok.line_num,
                    )
            elif folded_key == 'invalidsurface':
                for word in tok.expect(Token.STRING).split():
                    try:
                        self.invalid_surf.add(Surface[word.upper()])
                    except KeyError:
                        LOGGER.warning(
                            'Unknown invalid surface "{}"  in ({}:{})',
                            word, tok.filename, tok.line_num,
                        )
            elif folded_key == 'subtypeproperty':
                subtype_prop = tok.expect(Token.STRING)
                try:
                    self.subtype_prop = PROP_TYPES[subtype_prop.casefold()]
                except ValueError:
                    LOGGER.warning('Unknown subtype property "{}"!', subtype_prop)
                    # Construct a generic kind.
                    self.subtype_prop = ItemPropKind.unknown(subtype_prop)
            elif folded_key == 'desiredfacing':
                desired_facing = tok.expect(Token.STRING)
                try:
                    self.facing = DesiredFacing(desired_facing.upper())
                except ValueError:
                    LOGGER.warning(
                        'Unknown desired facing {}, assuming ANYTHING in ({}:{})',
                        desired_facing, tok.filename, tok.line_num,
                    )
                    self.facing = DesiredFacing.NONE
            elif folded_key == 'rendercolor':
                # Rendercolor is on catapult targets, and is useless.
                tok.expect(Token.STRING)
            else:
                # These flag keyvalues can be handled the same way.
                try:
                    conf_attr = self._BOOL_ATTRS[folded_key]
                except KeyError:
                    raise tok.error('Unknown editor option {}', key) from None
                else:
                    setattr(self, conf_attr, conv_bool(tok.expect(Token.STRING)))

    def _parse_properties_block(self, tok: Tokenizer, pak_id: str) -> None:
        """Parse the properties block of the item definitions."""
        for prop_str in tok.block('Properties'):
            prop_type: ItemPropKind[Any] | None
            try:
                prop_type = PROP_TYPES[prop_str.casefold()]
            except KeyError:
                LOGGER.warning('Unknown property "{}"!', prop_str)
                prop_type = ItemPropKind.unknown(prop_str)

            default = ''
            index = 0
            disable_prop = False
            desc = TransToken.BLANK
            for prop_value in tok.block(prop_str + ' options'):
                prop_value = prop_value.casefold()
                if prop_value == 'defaultvalue':
                    default = tok.expect(Token.STRING)
                elif prop_value == 'index':
                    index = conv_int(tok.expect(Token.STRING))
                elif prop_value == 'bee2_ignore':
                    disable_prop = conv_bool(tok.expect(Token.STRING), disable_prop)
                    if prop_type.is_unknown:
                        LOGGER.warning(
                            'Disabling setting defaults for property "{}" is not useful, '
                            'the property is unknown and so will not have UI!',
                            prop_str,
                        )
                elif prop_value in ('desc', 'description'):
                    desc = TransToken.parse(pak_id, tok.expect(Token.STRING))
                else:
                    raise tok.error('Unknown property option "{}"!', prop_value)
            try:
                self.properties[prop_type.id.casefold()] = ItemProp(
                    prop_type,default, index, not disable_prop, desc,
                )
            except ValueError as exc:
                raise tok.error(
                    'Default value {} is not valid for {} properties!',
                    default, prop_type.id,
                ) from exc

    def _parse_export_block(self, tok: Tokenizer, connections: Keyvalues) -> None:
        """Parse the export block of the item definitions. This returns the parsed connection's info.

        Since the standard input/output blocks must be parsed in one group, we collect those in the
        passed-in keyvalues block for later parsing.
        """
        for key in tok.block('Exporting'):
            folded_key = key.casefold()
            if folded_key == 'targetname':
                self.targetname = tok.expect(Token.STRING)
            elif folded_key == 'offset':
                self.offset = Vec.from_str(tok.expect(Token.STRING))
            elif folded_key == 'instances':
                # We allow several syntaxes for instances, since the counts are
                # pretty useless. Instances can be defined by position (for originals),
                # or by name for use in conditions.
                for inst_name in tok.block('Instance'):
                    self._parse_instance_block(tok, inst_name)
            elif folded_key == 'connectionpoints':
                self._parse_connection_points(tok)
            elif folded_key == 'occupiedvoxels':
                self._parse_occupied_voxels(tok)
            elif folded_key == 'embeddedvoxels':
                self._parse_embedded_voxels(tok)
            elif folded_key == 'collisions':
                self._parse_collisions(tok)
            elif folded_key == 'embedface':
                self._parse_embed_faces(tok)
            elif folded_key == 'overlay':
                self._parse_overlay(tok)
            elif folded_key == 'inputs':
                self._parse_connections(tok, connections, self.conn_inputs)
            elif folded_key == 'outputs':
                self._parse_connections(tok, connections, self.conn_outputs)
            else:
                raise tok.error('Unknown export option {}!', key)

    def _parse_instance_block(self, tok: Tokenizer, inst_name: str) -> None:
        """Parse a section in the instances block."""
        inst_ind: int | None
        inst_file: str | None
        try:
            inst_ind = int(inst_name)
        except ValueError:
            inst_ind = None
            if inst_name.casefold().startswith('bee2_'):
                inst_name = inst_name[5:]
            # else:
            #     LOGGER.warning(
            #         'Custom instance name "{}" should have bee2_ prefix (line '
            #         '{}, file {})',
            #         inst_name, tok.line_num, tok.filename)

        block_tok, inst_file = next(tok.skipping_newlines())
        if block_tok is Token.BRACE_OPEN:
            ent_count = brush_count = side_count = 0
            inst_file = None
            for block_key in tok.block('Instances', consume_brace=False):
                folded_key = block_key.casefold()
                if folded_key == 'name':
                    inst_file = tok.expect(Token.STRING)
                elif folded_key == 'entitycount':
                    ent_count = conv_int(tok.expect(Token.STRING))
                elif folded_key == 'brushcount':
                    brush_count = conv_int(tok.expect(Token.STRING))
                elif folded_key == 'brushsidecount':
                    side_count = conv_int(tok.expect(Token.STRING))
                else:
                    raise tok.error('Unknown instance option {}', block_key)
            if inst_file is None:
                raise tok.error('No instance filename provided!')
            inst = InstCount(FSPath(inst_file), ent_count, brush_count, side_count)
        elif block_tok is Token.STRING:
            inst = InstCount(FSPath(inst_file))
        else:
            raise tok.error(block_tok)
        if inst_ind is not None:
            self.set_inst(inst_ind, inst)
        else:
            self.cust_instances[inst_name.casefold()] = inst.inst

    def _parse_connections(
        self,
        tok: Tokenizer,
        kv_block: Keyvalues,
        target: dict[ConnTypes, Connection],
    ) -> None:
        """Parse either an inputs or outputs block.

        This is either a regular PeTI block with Activate/Deactivate options,
        or the BEE2 block with custom options. In the latter case it's stored
        in a keyvalues block for later parsing (since inputs/outputs need to
        be combined).
        """
        for conn_name in tok.block('Connection'):
            try:
                conn_type = ConnTypes(conn_name.upper())
            except ValueError:
                # Our custom BEEMOD options.
                if conn_name.casefold() in ('bee', 'bee2'):
                    for key in tok.block(conn_name):
                        value = tok.expect(Token.STRING, skip_newline=False)
                        if key.casefold() == 'force':
                            value = value.casefold()
                            if 'in' in value:
                                self.force_input = True
                            if 'out' in value:
                                self.force_output = True
                        else:
                            kv_block.append(Keyvalues(key, value))
                    continue  # We deal with this after the export block is done.
                else:
                    raise tok.error('Unknown connection type "{}"!', conn_name) from None

            act_name: str | None = None
            activate: str | None = None
            deact_name: str | None = None
            deactivate: str | None = None
            for conn_key in tok.block(conn_name):
                if conn_key.casefold() == 'activate':
                    value = tok.expect(Token.STRING, skip_newline=False)
                    tok.expect(Token.NEWLINE)
                    act_name, activate = Output.parse_name(value)
                elif conn_key.casefold() == 'deactivate':
                    value = tok.expect(Token.STRING, skip_newline=False)
                    tok.expect(Token.NEWLINE)
                    deact_name, deactivate = Output.parse_name(value)
                else:
                    raise tok.error('Unknown option "{}"!', conn_key)
            if activate is not None or deactivate is not None:
                target[conn_type] = Connection(act_name, activate, deact_name, deactivate)

    def _finalise_connections(self) -> None:
        """Apply legacy outputs to the config, and do some verification."""
        conf = self.conn_config
        assert conf is not None
        # If regular inputs or outputs are defined, convert to the new style.
        if ConnTypes.NORMAL in self.conn_inputs:
            conn = self.conn_inputs.pop(ConnTypes.NORMAL)
            if conn.activate is not None:
                conf.enable_cmd += (Output('', '', conn.activate, inst_in=conn.act_name), )
            if conn.deactivate is not None:
                conf.disable_cmd += (Output('', '', conn.deactivate, inst_in=conn.deact_name), )

        if ConnTypes.POLARITY in self.conn_inputs:
            if self.id.upper() != 'ITEM_TBEAM':
                LOGGER.warning(
                    'Item {} has polarity inputs, '
                    'this only works for the actual funnel!',
                    self.id
                )
            conn = self.conn_inputs.pop(ConnTypes.POLARITY)
            if conn.activate is not None:
                conf.sec_enable_cmd += (Output('', '', conn.activate, inst_in=conn.act_name), )
            if conn.deactivate is not None:
                conf.sec_disable_cmd += (Output('', '', conn.deactivate, inst_out=conn.deact_name), )

        if ConnTypes.NORMAL in self.conn_outputs:
            conn = self.conn_outputs.pop(ConnTypes.NORMAL)
            if conn.activate is not None:
                conf.output_act = (conn.act_name, conn.activate)
            if conn.deactivate is not None:
                conf.output_deact = (conn.deact_name, conn.deactivate)

        has_prim_input = bool(conf.enable_cmd or conf.disable_cmd)
        has_sec_input = bool(conf.sec_enable_cmd or conf.sec_disable_cmd)
        has_output = conf.output_act is not None or conf.output_deact is not None

        # Verify the configuration matches the input type.
        if has_sec_input and conf.input_type is not InputType.DUAL and self.id.upper() != 'ITEM_TBEAM':
            LOGGER.warning('Item "{}" has a secondary input but is not DUAL type!', self.id)
            conf.input_type = InputType.DUAL

        if conf.input_type is InputType.DAISYCHAIN:
            # We specify this.
            if has_prim_input:
                LOGGER.warning(
                    'Item "{}" is set to daisychain input, '
                    'but has inputs specified! These will be ignored.',
                    self.id,
                )
                conf.enable_cmd = conf.disable_cmd = ()
            # The item has an input, but the instance never gets it.
            self.force_input = True
            if not has_output:
                LOGGER.warning(
                    'Item "{}" is set to daisychain input, '
                    'but has no output. This is useless.',
                    self.id,
                )
        elif conf.input_type.is_logic:
            if has_output:
                LOGGER.warning(
                    'Item "{}" is set to a logic I/O type, but has outputs specified. '
                    'These will never be used.',
                    self.id,
                )
                conf.output_act = conf.output_deact = None
            if has_prim_input or has_sec_input:
                LOGGER.warning(
                    'Item "{}" is set to a logic I/O type, but has inputs specified. '
                    'These will never be used.',
                    self.id,
                )
                conf.enable_cmd = conf.sec_enable_cmd = conf.disable_cmd = conf.sec_disable_cmd = ()
            # These logically always have both.
            self.force_input = self.force_output = True

    def _parse_connection_points(self, tok: Tokenizer) -> None:
        for point_key in tok.block('ConnectionPoints'):
            if point_key.casefold() != 'point':
                raise tok.error('Unknown connection point "{}"!', point_key)
            direction: ConnSide | None = None
            pos: Coord | None = None
            sign_pos: Coord | None = None
            group_id: int | None = None
            priority = 0
            for conn_key in tok.block('Point'):
                folded_key = conn_key.casefold()
                if folded_key == 'dir':
                    direction = ConnSide.parse(tok.expect(Token.STRING), tok.error)
                elif folded_key == 'pos':
                    pos = Coord.parse(tok.expect(Token.STRING), tok.error)
                elif folded_key == 'signageoffset':
                    sign_pos = Coord.parse(tok.expect(Token.STRING), tok.error)
                elif folded_key == 'priority':
                    priority = conv_int(tok.expect(Token.STRING))
                elif folded_key == 'groupid':
                    group_id = conv_int(tok.expect(Token.STRING))
                else:
                    raise tok.error('Unknown point option "{}"!', folded_key)
            if direction is None:
                raise tok.error('No direction for connection point!')
            if pos is None:
                raise tok.error('No position for connection point!')
            if sign_pos is None:
                raise tok.error('No signage position for connection point!')
            self.antline_points[direction].append(AntlinePoint(pos, sign_pos, priority, group_id))

    def _parse_occupied_voxels(self, tok: Tokenizer) -> None:
        """Parse occupied voxel definitions. We add on the volume variant for convienience."""
        for occu_key in tok.block('OccupiedVoxels'):
            collide_type = OccuType.DEFAULT
            collide_against: OccuType | None = None
            pos1 = Coord(0, 0, 0)
            pos2: Coord | None = None
            normal: Coord | None = None

            # If no directions are specified, this is a full voxel.
            added_parts: set[tuple[Coord | None, Coord | None]] = set()
            # Extension, specify pairs of subpos points to bounding box include
            # all of them.
            subpos_pairs: list[Coord] = []

            occu_type = occu_key.casefold()
            if occu_type not in ('voxel', 'surfacevolume', 'volume'):
                raise tok.error('Unknown occupied voxel type {}!', occu_type)

            for opt_key in tok.block(occu_key):
                folded_key = opt_key.casefold()
                if folded_key in ('pos', 'pos1'):
                    pos1 = Coord.parse(tok.expect(Token.STRING), tok.error)
                elif folded_key == 'pos2':
                    pos2 = Coord.parse(tok.expect(Token.STRING), tok.error)
                elif folded_key == 'collidetype':
                    collide_type = OccuType.parse(tok)
                elif folded_key == 'collideagainst':
                    collide_against = OccuType.parse(tok)
                elif folded_key == 'normal':
                    normal = Coord.parse(tok.expect(Token.STRING), tok.error)
                    if normal not in NORMALS:
                        raise tok.error('{} is not a valid normal!', normal)
                elif folded_key in ('subpos', 'subpos1', 'subpos2'):
                    subpos_pairs.append(Coord.parse(tok.expect(Token.STRING), tok.error))
                elif folded_key == 'surface':
                    sub_normal: Coord | None = None
                    sub_pos: Coord | None = None
                    for surf_key in tok.block('Surface'):
                        folded_key = surf_key.casefold()
                        if folded_key == 'pos':
                            sub_pos = Coord.parse(tok.expect(Token.STRING), tok.error)
                        elif folded_key == 'normal':
                            sub_normal = Coord.parse(tok.expect(Token.STRING), tok.error)
                            if sub_normal not in NORMALS:
                                raise tok.error('{} is not a valid normal!', sub_normal)
                        else:
                            raise tok.error('Unknown voxel surface option "{}"!', surf_key)
                    added_parts.add((sub_pos, sub_normal))
            if len(subpos_pairs) % 2 != 0:
                raise tok.error('Subpos positions must be provided in pairs.')
            for subpos1, subpos2 in zip(subpos_pairs[::2], subpos_pairs[1::2]):
                for sub_pos in Coord.bbox(subpos1, subpos2):
                    added_parts.add((sub_pos, normal))

            if not added_parts:
                # Default to a single voxel.
                added_parts.add((None, None))
            volume: Iterable[Coord]
            if pos2 is None:
                volume = [pos1]
            else:
                volume = Coord.bbox(pos1, pos2)
            for pos in volume:
                for sub_pos, sub_normal in added_parts:
                    self.occupy_voxels.add(OccupiedVoxel(
                        collide_type,
                        collide_against,
                        pos,
                        sub_pos, sub_normal,
                    ))

    def _parse_embedded_voxels(self, tok: Tokenizer) -> None:
        # There are two definition types here - a single voxel, or a whole bbox.
        for embed_key in tok.block('EmbeddedVoxels'):
            folded_key = embed_key.casefold()
            if folded_key == 'volume':
                pos_1: Coord | None = None
                pos_2: Coord | None = None
                for pos_key in tok.block('EmbeddedVolume'):
                    if pos_key.casefold() == 'pos1':
                        pos_1 = Coord.parse(tok.expect(Token.STRING), tok.error)
                    elif pos_key.casefold() == 'pos2':
                        pos_2 = Coord.parse(tok.expect(Token.STRING), tok.error)
                    else:
                        raise tok.error('Unknown volume key "{}"!', pos_key)
                if pos_1 is None or pos_2 is None:
                    raise tok.error('Missing coordinate for volume!')
                for pos in Coord.bbox(pos_1, pos_2):
                    self.embed_voxels.add(pos)
            elif folded_key == 'voxel':
                # A single position.
                for pos_key in tok.block('EmbeddedVoxel'):
                    if pos_key.casefold() == 'pos':
                        self.embed_voxels.add(Coord.parse(
                            tok.expect(Token.STRING),
                            tok.error,
                        ))
                    else:
                        raise tok.error('Unknown voxel key "{}"!', pos_key)

    def _parse_embed_faces(self, tok: Tokenizer) -> None:
        """Parse embedFace definitions, which add additional brushes to the item."""
        for solid_key in tok.block('EmbedFace'):
            if solid_key.casefold() != 'solid':
                raise tok.error('Unknown Embed Face type "{}"!', solid_key)
            center: Vec | None = None
            size: Vec | None = None
            grid = FaceType.NORMAL
            for opt_key in tok.block('Solid'):
                folded_key = opt_key.casefold()
                if folded_key == 'center':
                    center = Vec.from_str(tok.expect(Token.STRING))
                elif folded_key == 'dimensions':
                    size = Vec.from_str(tok.expect(Token.STRING))
                elif folded_key == 'grid':
                    grid_str = tok.expect(Token.STRING)
                    try:
                        grid = FACE_TYPES[grid_str.casefold()]
                    except KeyError:
                        raise tok.error('Unknown face type "{}"!', grid_str) from None
                else:
                    raise tok.error('Unknown Embed Face option "{}"!', opt_key)
            if center is None:
                raise tok.error('No position specified for embedded face!')
            if size is None:
                raise tok.error('No size specified for embedded face!')
            self.embed_faces.append(EmbedFace(center, size, grid))

    def _parse_collisions(self, tok: Tokenizer) -> None:
        """Parse the enhanced blocks BEE uses for collision."""
        self._has_collisions_block = True
        for box_name in tok.block('Collisions'):
            if box_name.casefold() != 'bbox':
                raise tok.error('Unknown collision type "{}"!', box_name)
            points: list[Vec] = []
            coll_type = CollideType.NOTHING
            tags = set()
            for bbox_key in tok.block(box_name):
                folded_key = bbox_key.casefold()
                if folded_key.rstrip('0123456789') == 'pos':
                    points.append(Vec.from_str(tok.expect(Token.STRING)))
                elif folded_key in ('tag', 'tags'):
                    tags.update(tok.expect(Token.STRING).casefold().split())
                elif folded_key == 'type':
                    for name in tok.expect(Token.STRING).split():
                        try:
                            coll_type |= CollideType[name.upper()]
                        except KeyError:
                            raise tok.error('Unknown collision type "{}"', name) from None
            if len(points) < 2:
                raise tok.error('Two points must be provided for a bounding box!')
            bb_min, bb_max = Vec.bbox(points)
            try:
                self.collisions.append(BBox(bb_min, bb_max, contents=coll_type, tags=tags))
            except NonBBoxError as exc:
                raise tok.error(str(exc)) from None

    def generate_collisions(self) -> None:
        """If no specific collisions were defined, generate them by looking at OccupiedVoxels."""
        # Explicitly specified, don't generate.
        if self.collisions or self._has_collisions_block:
            return
        for occu in self.occupy_voxels:
            pos = Vec(occu.pos) * 128
            if occu.subpos is None:
                half_dist = 64.0
            else:
                pos += Vec(occu.subpos) * 32 - (48, 48, 48)
                half_dist = 16.0
            if occu.normal is None:
                # Full cube.
                try:
                    self.collisions.append(BBox(
                        pos - half_dist, pos + half_dist,
                        contents=occu.type.collision, tags='generated',
                    ))
                except NonBBoxError as exc:
                    LOGGER.warning('"{}": Invalid occupied voxel: {}', self.id, exc)
            else:
                # Plane.
                pos -= half_dist * Vec(occu.normal)
                pos1, pos2 = pos, pos.copy()
                # Expand in all but the normal axis.
                for axis, val in enumerate(occu.normal):
                    if val == 0.0:
                        pos1[axis] -= half_dist
                        pos2[axis] += half_dist
                try:
                    self.collisions.append(BBox(pos1, pos2, contents=occu.type.collision, tags='generated'))
                except NonBBoxError as exc:
                    LOGGER.warning('"{}": Invalid occupied voxel: {}', self.id, exc)

    def _parse_overlay(self, tok: Tokenizer) -> None:
        """Parse overlay definitions, which place overlays."""
        center: Vec | None = None
        size: Vec | None = None
        material = ''
        rotation = 0
        for opt_key in tok.block('Overlay'):
            folded_key = opt_key.casefold()
            if folded_key == 'center':
                center = Vec.from_str(tok.expect(Token.STRING))
            elif folded_key == 'dimensions':
                size = Vec.from_str(tok.expect(Token.STRING))
            elif folded_key == 'material':
                material = tok.expect(Token.STRING)
            elif folded_key == 'rotation':
                rotation = conv_int(tok.expect(Token.STRING))
            else:
                raise tok.error('Unknown Overlay option "{}"!', opt_key)
        if center is None:
            raise tok.error('No position specified for overlay!')
        if size is None:
            raise tok.error('No size specified for overlay!')
        self.overlays.append(Overlay(material, center, size, rotation))

    @classmethod
    def export(
        cls, f: _TextFile,
        items: Iterable[Item],
        renderables: Mapping[RenderableType, Renderable],
        id_filenames: bool = False,
    ) -> None:
        """Write a full editoritems file out.

        If id_filenames are enabled, items all use "instances/id/<item_id>/sub_<subtype>.vmf".
        """
        f.write('"ItemData"\n{\n')
        for item in items:
            item.export_one(f)
        if renderables:
            f.write('\n\n"Renderables"\n\t{\n')
            for rend_type, rend in renderables.items():
                f.write('\t"Item"\n\t\t{\n')
                f.write(f'\t\t"Type"  "{rend_type.value}"\n')
                f.write(f'\t\t"Model" "{rend.model}"\n')
                f.write('\t\t"Animations"\n\t\t\t{\n')
                for anim, ind in rend.animations.items():
                    f.write(f'\t\t\t"{anim.value}" "{ind}"\n')
                f.write('\t\t\t}\n\t\t}\n')
            f.write('\t}\n')
        f.write('}\n')

    def export_one(self, f: _TextFile, id_filenames: bool = False) -> None:
        """Write a single item out to a file.

        If id_filenames are enabled, items all use "instances/id/<item_id>/sub_<subtype>.vmf".
        """
        f.write('"Item"\n\t{\n')
        if self.cls is not ItemClass.UNCLASSED:
            f.write(f'\t"Type"      "{self.id}"\n')
            f.write(f'\t"ItemClass" "{self.cls.id}"\n')
        else:
            f.write(f'\t"Type" "{self.id}"\n')
        f.write('\t"Editor"\n\t\t{\n')
        if self.subtype_prop is not None:
            if isinstance(self.subtype_prop, str):
                f.write(f'\t\t"SubtypeProperty" "{self.subtype_prop}"\n')
            else:
                f.write(f'\t\t"SubtypeProperty" "{self.subtype_prop.id}"\n')
        for subtype in self.subtypes:
            subtype.export(f)
        f.write(f'\t\t"MovementHandle" "{self.handle.value}"\n')
        f.write(f'\t\t"OccupiesVoxel"  "{"1" if self.occupies_voxel else "0"}"\n')

        if self.facing is not DesiredFacing.NONE:
            f.write(f'\t\t"DesiredFacing"  "{self.facing.value}"\n')

        if self.invalid_surf:
            invalid = ' '.join(sorted(surf.value for surf in self.invalid_surf))
            f.write(f'\t\t"InvalidSurface" "{invalid}"\n')

        if self.anchor_goo:
            f.write('\t\t"CanAnchorOnGoo"      "1"\n')
        if self.anchor_barriers:
            f.write('\t\t"CanAnchorOnBarriers" "1"\n')
        if not self.copiable:
            f.write('\t\t"Copyable"  "0"\n')
        if not self.deletable:
            f.write('\t\t"Deletable" "0"\n')
        if self.pseudo_handle:
            f.write('\t\t"PseudoHandle" "1"\n')
        f.write('\t\t}\n')

        if self.properties:
            f.write('\t"Properties"\n\t\t{\n')
            for prop in self.properties.values():
                f.write(f'\t\t"{prop.kind.id}"\n\t\t\t{{\n')
                f.write(f'\t\t\t"DefaultValue" "{prop.export()}"\n')
                f.write(f'\t\t\t"Index"        "{prop.index}"\n')
                f.write('\t\t\t}\n')
            f.write('\t\t}\n')
        f.write('\t"Exporting"\n\t\t{\n')
        if self.instances:
            f.write('\t\t"Instances"\n\t\t\t{\n')
            for i, inst in enumerate(self.instances):
                f.write(f'\t\t\t"{i}"\n\t\t\t\t{{\n')
                if id_filenames:
                    file = FSPath("instances", "BEE2_by_id", self.id, f"sub_{i}.vmf")
                else:
                    file = inst.inst
                if file == FSPath():  # Don't write just a ".".
                    f.write('\t\t\t\t"Name" ""\n')
                elif inst.ent_count or inst.brush_count or inst.face_count:
                    f.write(f'\t\t\t\t"Name"           "{file}"\n')
                    f.write(f'\t\t\t\t"EntityCount"    "{inst.ent_count}"\n')
                    f.write(f'\t\t\t\t"BrushCount"     "{inst.brush_count}"\n')
                    f.write(f'\t\t\t\t"BrushSideCount" "{inst.face_count}"\n')
                else:
                    f.write(f'\t\t\t\t"Name" "{file}"\n')
                f.write('\t\t\t\t}\n')
            f.write('\t\t\t}\n')

        if self.targetname:
            f.write(f'\t\t"Targetname" "{self.targetname}"\n')
        f.write(f'\t\t"Offset"     "{self.offset}"\n')

        has_prim_input = self.has_prim_input()
        has_sec_input = self.has_sec_input()
        # Fizzlers don't output correctly, so don't allow them to output
        # in editoritems.
        has_output = self.has_output() and self.cls is not ItemClass.FIZZLER
        if has_prim_input or has_sec_input or self.conn_inputs:
            f.write('\t\t"Inputs"\n\t\t\t{\n')
            if has_prim_input:
                f.write(f'\t\t\t"{ConnTypes.NORMAL.value}"\n')
                f.write('\t\t\t\t{\n')
                f.write(f'\t\t\t\t"Activate" "{OutNames.IN_ACT.value}"\n')
                f.write(f'\t\t\t\t"Deactivate" "{OutNames.IN_DEACT.value}"\n')
                f.write('\t\t\t\t}\n')
            # Only add the tbeam input for actual funnels.
            # It doesn't work there.
            if has_sec_input and self.id.casefold() == 'item_tbeam':
                f.write(f'\t\t\t"{ConnTypes.POLARITY.value}"\n')
                f.write('\t\t\t\t{\n')
                f.write(f'\t\t\t\t"Activate" "{OutNames.IN_SEC_ACT.value}"\n')
                f.write(f'\t\t\t\t"Deactivate" "{OutNames.IN_SEC_DEACT.value}"\n')
                f.write('\t\t\t\t}\n')
            for conn_type, conn in self.conn_inputs.items():
                conn.write(f, conn_type.value)
            f.write('\t\t\t}\n')
        if has_output or self.conn_outputs:
            f.write('\t\t"Outputs"\n\t\t\t{\n')
            if has_output:
                f.write(f'\t\t\t"{ConnTypes.NORMAL.value}"\n')
                f.write('\t\t\t\t{\n')
                f.write(f'\t\t\t\t"Activate" "{OutNames.OUT_ACT.value}"\n')
                f.write(f'\t\t\t\t"Deactivate" "{OutNames.OUT_DEACT.value}"\n')
                f.write('\t\t\t\t}\n')
            for conn_type, conn in self.conn_outputs.items():
                conn.write(f, conn_type.value)
            f.write('\t\t\t}\n')

        if self.embed_voxels:
            f.write('\t\t"EmbeddedVoxels"\n\t\t\t{\n')
            for pos1, pos2 in bounding_boxes(self.embed_voxels):
                if pos1 == pos2:
                    f.write('\t\t\t"Voxel"\n\t\t\t\t{\n')
                    f.write(f'\t\t\t\t"Pos" "{pos1}"\n')
                else:
                    f.write('\t\t\t"Volume"\n\t\t\t\t{\n')
                    f.write(f'\t\t\t\t"Pos1" "{pos1}"\n')
                    f.write(f'\t\t\t\t"Pos2" "{pos2}"\n')
                f.write('\t\t\t\t}\n')
            f.write('\t\t\t}\n')

        if self.embed_faces:
            f.write('\t\t"EmbedFace"\n\t\t\t{\n')
            for face in self.embed_faces:
                f.write('\t\t\t"Solid"\n\t\t\t\t{\n')
                f.write(f'\t\t\t\t"Center"     "{face.center}"\n')
                f.write(f'\t\t\t\t"Dimensions" "{face.size}"\n')
                f.write(f'\t\t\t\t"Grid"       "{face.type.value}"\n')
                f.write('\t\t\t\t}\n')
            f.write('\t\t\t}\n')

        if self.occupy_voxels:
            self._export_occupied_voxels(f)

        for over in self.overlays:
            f.write('\t\t"Overlay"\n\t\t\t{\n')
            f.write(f'\t\t\t"Material"   "{over.material}"\n')
            f.write(f'\t\t\t"Center"     "{over.center}"\n')
            f.write(f'\t\t\t"Dimensions" "{over.size}"\n')
            f.write(f'\t\t\t"Rotation"   "{over.rotation}"\n')
            f.write('\t\t\t}\n')

        if any(self.antline_points.values()):
            f.write('\t\t"ConnectionPoints"\n\t\t\t{\n')
            is_first = True
            for side in ConnSide:
                points = self.antline_points[side]
                if not points:
                    continue
                # Newline between sections.
                if not is_first:
                    f.write('\n')
                is_first = False
                # Recreate Valve's comments around the points, because we can.
                f.write(f'\t\t\t// {side.name.title()}\n')

                for point in points:
                    f.write('\t\t\t"Point"\n\t\t\t\t{\n')
                    f.write(f'\t\t\t\t"Dir"           "{side.value}"\n')
                    f.write(f'\t\t\t\t"Pos"           "{point.pos}"\n')
                    f.write(f'\t\t\t\t"SignageOffset" "{point.sign_off}"\n')
                    f.write(f'\t\t\t\t"Priority"      "{point.priority}"\n')
                    if point.group is not None:
                        f.write(f'\t\t\t\t"GroupID"       "{point.group}"\n')
                    f.write('\t\t\t\t}\n')
            f.write('\t\t\t}\n')
        f.write('\t\t}\n')
        f.write('\t}\n')

    def _export_occupied_voxels(self, f: _TextFile) -> None:
        """Write occupied voxels to a file."""
        voxel_groups: dict[tuple[Coord, OccuType, OccuType | None], list[OccupiedVoxel]] = defaultdict(list)
        voxel: OccupiedVoxel
        voxels: list[OccupiedVoxel]
        for voxel in self.occupy_voxels:
            voxel_groups[voxel.pos, voxel.type, voxel.against].append(voxel)

        f.write('\t\t"OccupiedVoxels"\n\t\t\t{\n')
        for (pos, typ, against), voxels in voxel_groups.items():
            f.write('\t\t\t"Voxel"\n\t\t\t\t{\n')
            f.write(f'\t\t\t\t"Pos" "{pos}"\n')
            if typ is not OccuType.DEFAULT and against is not None:
                f.write(f'\t\t\t\t"CollideType"    "{typ}"\n')
                f.write(f'\t\t\t\t"CollideAgainst" "{against}"\n')
            elif typ is not OccuType.DEFAULT:
                f.write(f'\t\t\t\t"CollideType" "{typ}"\n')
            elif against is not None:
                f.write(f'\t\t\t\t"CollideAgainst" "{against}"\n')
            # Special case - single full voxel has no surface sections.
            if len(voxels) != 1 or voxels[0].subpos is not None or voxels[0].normal is not None:
                for voxel in voxels:
                    f.write('\t\t\t\t"Surface"\n')
                    f.write('\t\t\t\t\t{\n')
                    if voxel.subpos is not None and voxel.normal is not None:
                        f.write(f'\t\t\t\t\t"Pos"    "{voxel.subpos}"\n')
                        f.write(f'\t\t\t\t\t"Normal" "{voxel.normal}"\n')
                    elif voxel.subpos is not None:
                        f.write(f'\t\t\t\t\t"Pos" "{voxel.subpos}"\n')
                    elif voxel.normal is not None:
                        f.write(f'\t\t\t\t\t"Normal" "{voxel.normal}"\n')
                    f.write('\t\t\t\t\t}\n')
            f.write('\t\t\t\t}\n')
        f.write('\t\t\t}\n')

    def __getstate__(self) -> tuple:
        """Simplify pickles.

        We produce a tuple to avoid needing to specify the attributes in the file.
        We can also eliminate some dict keys since they're constant.
        """
        return (
            self.id,
            self.cls,
            self.subtype_prop,
            self.subtypes,
            list(self.properties.values()),
            self.animations,
            self.handle,
            self.facing,
            self.invalid_surf,
            self.anchor_barriers,
            self.anchor_goo,
            self.occupies_voxel,
            self.copiable,
            self.deletable,
            self.pseudo_handle,
            self.offset,
            self.targetname,
            self.instances,
            self.cust_instances,
            [self.antline_points[side] for side in ConnSide],
            self.occupy_voxels,
            self.embed_voxels,
            self.embed_faces,
            self.collisions,
            self.overlays,
            self.conn_inputs,
            self.conn_outputs,
            self.conn_config,
            self.force_input,
            self.force_output,
        )

    def __setstate__(self, state: tuple) -> None:
        props: list[ItemProp[Any]]
        antline_points: list[list[AntlinePoint]]
        (
            self.id,
            self.cls,
            self.subtype_prop,
            self.subtypes,
            props,
            self.animations,
            self.handle,
            self.facing,
            self.invalid_surf,
            self.anchor_barriers,
            self.anchor_goo,
            self.occupies_voxel,
            self.copiable,
            self.deletable,
            self.pseudo_handle,
            self.offset,
            self.targetname,
            self.instances,
            self.cust_instances,
            antline_points,
            self.occupy_voxels,
            self.embed_voxels,
            self.embed_faces,
            self.collisions,
            self.overlays,
            self.conn_inputs,
            self.conn_outputs,
            self.conn_config,
            self.force_input,
            self.force_output,
        ) = state

        self.properties = {prop.kind.id.casefold(): prop for prop in props}
        self.antline_points = dict(zip(ConnSide, antline_points))

    def validate(self) -> None:
        """Look through the item and check for potential mistakes in configuration."""
        for i, subtype in enumerate(self.subtypes, 1):
            if len(subtype.models) != self.cls.mdl_per_subtype:
                # Suppress, this is a Reflection Gel hack.
                if len(subtype.models) == 5 and self.cls is ItemClass.PAINT_DROPPER:
                    continue

                LOGGER.warning(
                    '{} items expect {} models, but subtype {} has {} models!',
                    self.cls.id, self.cls.mdl_per_subtype,
                    i, len(subtype.models),
                )
        if 'buttontype' in self.properties and self.cls is not ItemClass.FLOOR_BUTTON:
            LOGGER.warning(
                'The ButtonType property does nothing if the '
                'item class is not ItemButtonFloor, only instance 0 is shown.'
            )
        # The indicator items are special, they always have just one input...
        if self.has_prim_input() and 'connectioncount' not in self.properties and self.id not in [
            'ITEM_INDICATOR_TOGGLE', 'ITEM_INDICATOR_PANEL', 'ITEM_INDICATOR_PANEL_TIMER',
        ]:
            LOGGER.warning(
                'Items with inputs must have ConnectionCount to work!'
            )
        # Track platform is a special case, it has hardcoded connections for
        # each track segment.
        if (
            (self.has_prim_input() or self.has_sec_input() or self.has_output())
            and not self.antline_points
            and self.cls is not ItemClass.TRACK_PLATFORM
        ):
            LOGGER.warning('Items with inputs or outputs need ConnectionPoints definition!')

    def iter_trans_tokens(self, source: str) -> Iterator[TransTokenSource]:
        """Iterate over translation tokens in this item."""
        for subtype in self.subtypes:
            yield subtype.name, source + '.name'
            yield subtype.pal_name, source + '.pal_name'
        for prop in self.properties.values():
            yield prop.desc, f'{source}.property.{prop.kind.id}'
