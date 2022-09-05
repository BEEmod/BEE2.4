"""Various constant values (Mainly texture names.)"""
from __future__ import annotations
from typing import Mapping, cast, Any, TypeVar, Type, MutableMapping, Iterator
from uuid import UUID, uuid5

from typing_extensions import Final
from enum import Enum, EnumMeta
from srctools import Side


T = TypeVar('T')
__all__ = [
    'MaterialGroup',

    'MusicChannel',

    'WhitePan', 'BlackPan',
    'Signage', 'Antlines',
    'Goo', 'Fizzler',
    'Special', 'Tools',
    'FixupVars',
    'COUNTER_AND_ON', 'COUNTER_AND_OFF',
    'COUNTER_OR_ON', 'COUNTER_OR_OFF',
    'SEL_ICON_SIZE', 'SEL_ICON_SIZE_LRG', 'SEL_ICON_CROP_SHRINK',
    'PALETTE_FORCE_SHOWN', 'PALETTE_NS',
    'UUID_BLANK', 'UUID_EXPORT', 'UUID_PORTAL2',
]


class _MaterialGroupNS(MutableMapping[str, Any]):
    """Wraps around the enum mapping, to lowercase the values."""
    def __init__(self, orig: MutableMapping[str, Any]) -> None:
        self.mapping = orig

    def __setitem__(self, key: str, value: Any) -> None:
        """Make string objects lowercase when set."""
        if isinstance(value, str):
            value = value.casefold()
        self.mapping[key] = value

    def __delitem__(self, value: str) -> None:
        del self.mapping[value]

    def __getitem__(self, key: str) -> Any:
        return self.mapping[key]

    def __len__(self) -> int:
        return len(self.mapping)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.mapping)


class MaterialGroupMeta(EnumMeta):
    """Metaclass for MaterialGroup, to implement some of its features."""
    _value2member_map_: dict[str, Any]  # Enum defines.

    @classmethod
    def __prepare__(mcs, cls: str, bases: tuple[type, ...], /, **kwd: Any) -> Any:  # type: ignore
        """Override Enum class-dict type.

        This makes string-values lowercase when set.
        """
        namespace = super().__prepare__(cls, bases, **kwd)
        return _MaterialGroupNS(cast(MutableMapping[str, Any], namespace))

    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwds: Any) -> MaterialGroupMeta:
        """Unpack the dict type back to the original for EnumMeta.

        It accesses attributes, so it can't have our wrapper.
        """
        assert isinstance(namespace, _MaterialGroupNS)
        # Is always enum._EnumDict, but that's private.
        return super().__new__(mcs, name, bases, cast(Any, namespace.mapping), **kwds)

    def __contains__(cls, value: object) -> bool:
        """MaterialGroup can check if strings are equal to a member."""
        if isinstance(value, str):
            return value.casefold() in cls._value2member_map_
        elif isinstance(value, Side):
            return value.mat.casefold() in cls._value2member_map_
        return super().__contains__(value)

    # Need to ignore types here, EnumMeta does not match type's signature.
    def __call__(cls: Type[T], value: str, *args, **kwargs) -> T:  # type: ignore
        """Find the existing member with this name."""
        if args or kwargs:
            return super().__call__(value, *args, **kwargs)  # type: ignore
        return cls.__new__(cls, value.casefold())  # type: ignore


class MaterialGroup(str, Enum, metaclass=MaterialGroupMeta):
    """Adds a few useful features to the string enums.

    * They are compared case-insensitively.
    * This can be compared to VMF sides to match the material.
    * 'str' in MaterialGroup can be done to check if a string is equal
      to any members.
    * str(member) == member.value
    """
    def __eq__(self, other: object) -> bool:
        """Compare case-insensitively."""
        if isinstance(other, Side):
            other = other.mat
        if isinstance(other, str):
            return self.value == other.casefold()
        return NotImplemented

    def __ne__(self, other: object) -> bool:
        """Compare case-insensitively."""
        if isinstance(other, Side):
            other = other.mat
        if isinstance(other, str):
            return self.value != other.casefold()
        return NotImplemented

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        """Allow hashing MaterialGroup values."""
        return hash(self.value)


class FixupVars(MaterialGroup):
    """Variable names for fixups."""
    CONN_COUNT = '$connectioncount'
    CONN_COUNT_TBEAM = '$connectioncount_polarity'

    CUBE_TYPE = '$cube_type'

    ST_ENABLED = '$start_enabled'
    ST_REVERSED = '$start_reversed'
    ST_DEPLOYED = '$start_deployed'
    DIS_AUTO_RESPAWN = '$disable_autorespawn'
    DIS_AUTO_DROP = '$disable_autodrop'

    TIM_ENABLED = '$is_timer'
    TIM_DELAY = '$timer_delay'

    # Indicator env_texturetoggle overlay.
    TOGGLE_OVERLAY = '$indicator_name'

    PIST_TOP = '$top_level'
    PIST_BTM = '$bottom_level'
    PIST_IS_UP = '$start_up'

    TRACK_MOVE_DIST = '$travel_distance'
    TRACK_MOVE_ANGLES = '$travel_direction'
    TRACK_START_FRAC = '$starting_position'

    FIZZ_MDL_SKIN = '$skin'  # Fizzler model skin (fizzler, dirty, laserfield)

    # Extra vars we've defined.

    BEE_CONN_COUNT_A = '$conn_count_a'
    BEE_CONN_COUNT_B = '$conn_count_b'

    # Index of entry/exit corridor
    BEE_CORR_INDEX = '$corr_index'
    # Videos set for arrival_departure_transition_ents.
    BEE_ELEV_VERT = '$vert_video'
    BEE_ELEV_HORIZ = '$horiz_video'
    BEE_MONITOR_IS_BREAKABLE = '$is_breakable'
    BEE_MONITOR_TOGGLE_FUNC = '$toggle_func'
    # Is glass or grating?
    BEE_GLS_TYPE = '$barrier_type'
    BEE_PIST_IS_STATIC = '$is_static'
    BEE_PIST_MANAGER_A = '$manager_a'


class WhitePan(MaterialGroup):
    """White tiling."""
    WHITE_FLOOR = "tile/white_floor_tile002a"
    WHITE_1x1 = "tile/white_wall_tile003a"
    WHITE_2x1 = "tile/white_wall_tile003h"
    WHITE_2x2 = "tile/white_wall_tile003c"
    WHITE_4x4 = "tile/white_wall_tile003f"


class BlackPan(MaterialGroup):
    """Black tiling."""
    BLACK_FLOOR = "metal/black_floor_metal_001c"
    BLACK_1x1 = "metal/black_wall_metal_002c"
    BLACK_2x1 = "metal/black_wall_metal_002e"
    BLACK_2x2 = "metal/black_wall_metal_002a"
    BLACK_4x4 = "metal/black_wall_metal_002b"


class Signage(MaterialGroup):
    """The various square white signs used in the PeTI."""
    EXIT = "signage/signage_exit"
    ARROW = "signage/signage_overlay_arrow"
    SHAPE_SQUARE = "signage/shape05"
    SHAPE_CROSS = "signage/shape04"
    SHAPE_DOT = "signage/shape01"
    SHAPE_MOON = "signage/shape02"
    SHAPE_SLASH = "signage/signage_shape_slash"
    SHAPE_TRIANGLE = "signage/shape03"
    SHAPE_SINE = "signage/signage_shape_sine"
    SHAPE_STAR = "signage/signage_shape_star"
    SHAPE_CIRCLE = "signage/signage_shape_circle"
    SHAPE_WAVY = "signage/signage_shape_wavy"


class Special(MaterialGroup):
    BACKPANELS = "anim_wp/framework/backpanels"
    # Note - this is used in PeTI maps.
    BACKPANELS_CHEAP = "anim_wp/framework/backpanels_cheap"
    PED_SIDE = "plastic/plasticwall004a"
    SQUAREBEAMS = "anim_wp/framework/squarebeams"
    GLASS = "glass/glasswindow007a_less_shiny"
    GRATING = "metal/metalgrate018"
    LASERFIELD = "effects/laserplane"
    BULLSEYE = "signage/mgf_overlay_bullseye"


class Goo(MaterialGroup):
    REFLECTIVE = "nature/toxicslime_a2_bridge_intro"
    CHEAP = "nature/toxicslime_puzzlemaker_cheap"
    TIDELINE = "overlays/tideline01b"


class Antlines(MaterialGroup):
    STRAIGHT = "signage/indicator_lights/indicator_lights_floor"
    CORNER = "signage/indicator_lights/indicator_lights_corner_floor"


class Tools(MaterialGroup):
    """Tool textures."""
    NODRAW = 'tools/toolsnodraw'
    INVISIBLE = 'tools/toolsinvisible'
    TRIGGER = 'tools/toolstrigger'

    AREAPORTAL = 'tools/toolsareaportal'
    SKIP = 'tools/toolsskip'
    HINT = 'tools/toolshint'
    OCCLUDER = 'tools/toolsoccluder'

    CLIP = 'tools/toolsclip'
    BLOCK_LOS = 'tools/toolsblock_los'
    BLOCK_LIGHT = 'tools/toolsblocklight'
    BLOCK_BULLETS = 'tools/toolsblockbullets'
    PLAYER_CLIP = 'tools/toolsplayerclip'

    SKYBOX = 'tools/toolsskybox'
    BLACK = 'tools/toolsblack'

    PLAYER_CLIP_GRATE = 'BEE2/grate_player_clip'
    PLAYER_CLIP_GLASS = 'BEE2/glass_player_clip'


class Fizzler(MaterialGroup):
    """Fizzler textures."""
    CENTER = "effects/fizzler_center"
    LEFT = "effects/fizzler_l"
    RIGHT = "effects/fizzler_r"
    SHORT = "effects/fizzler"


class MusicChannel(Enum):
    """Categories of music."""
    BASE = 'base'  # Main track
    TBEAM = 'tbeam'  # Funnel audio
    BOUNCE = 'bouncegel'  # Jumping on repulsion gel.
    SPEED = 'speedgel'  # Moving fast horizontally


# Outputs we need to use to make a math_counter act like
# the specified logic gate.
COUNTER_AND_ON: Final = 'OnHitMax'
COUNTER_AND_OFF: Final = 'OnChangedFromMax'

COUNTER_OR_ON: Final = 'OnChangedFromMin'
COUNTER_OR_OFF: Final = 'OnHitMin'

SEL_ICON_SIZE: Final = 96  # Size of the selector win icons
SEL_ICON_SIZE_LRG: Final = (256, 192)  # Size of the larger icon shown in description.
SEL_ICON_CROP_SHRINK: Final = (32, 0, 256 - 32, 192)  # Bounds required to crop from lrg to small.

# Palette UUIDs
PALETTE_NS = UUID('91001b81-60ee-494d-9d2a-6371397b2240')
UUID_PORTAL2 = uuid5(PALETTE_NS, 'PORTAL2')
UUID_EXPORT = uuid5(PALETTE_NS, 'LAST_EXPORT')
UUID_BLANK = uuid5(PALETTE_NS, 'EMPTY')

# These may not be hidden.
PALETTE_FORCE_SHOWN: frozenset[UUID] = frozenset({UUID_PORTAL2})
