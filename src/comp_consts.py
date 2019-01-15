"""Various constant values for use by VBSP. (Mainly texture names.)"""
from enum import Enum, EnumMeta

from srctools import Side as _Side, Entity


__all__ = [
    'MaterialGroup',

    'WhitePan', 'BlackPan',
    'Signage', 'Antlines',
    'Goo', 'Fizzler',
    'Special', 'Tools',
    'FixupVars'
]


class MaterialGroupMeta(EnumMeta):
    @classmethod
    def __prepare__(mcs, cls, bases):
        """Override Enum class-dict type.
        
        This makes string-values lowercase when set.
        """
        # The original class is private - grab it via prepare, and make
        # a subclass right here.
        orig_dict = type(super().__prepare__(cls, bases))
        class RepDict(orig_dict):
            def __setitem__(self, key, value):
                if isinstance(value, str):
                    value = value.casefold()
                super().__setitem__(key, value)
        
        return RepDict()
        
    def __contains__(cls, value):
        """MaterialGroup can check if strings are equal to a member."""
        if isinstance(value, str):
            return value.casefold() in cls._value2member_map_
        elif isinstance(value, _Side):
            return value.mat.casefold() in cls._value2member_map_
        return super().__contains__(value)
        
    def __call__(cls, value, *args, **kwargs):
        if args or kwargs:
            return super().__call__(value, *args, **kwargs)
        return cls.__new__(cls, value.casefold())

    __call__.__doc__ = EnumMeta.__call__.__doc__


class MaterialGroup(str, Enum, metaclass=MaterialGroupMeta):
    """Adds a few useful features to the string enums.

    * They are compared case-insensitively.
    * This can be compared to VMF sides to match the material.
    * 'str' in MaterialGroup can be done to check if a string is equal
      to any members.
    * str(member) == member.value
    """
    def __eq__(self, other):
        if isinstance(other, _Side):
            other = other.mat
        return self.value == other.casefold()

    def __str__(self):
        return self.value

    def __hash__(self):
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


class ItemClass(MaterialGroup):
    """PeTI item classes."""
    # Default
    UNCLASSED = 'ItemBase'

    FLOOR_BUTTON = 'ItemButtonFloor'
    PEDESTAL_BUTTON = 'ItemPedestalButton'

    PANEL_STAIR = 'ItemStairs'
    PANEL_FLIP = 'ItemPanelFlip'
    PANEL_ANGLED = 'ItemAngledPanel'  # Both items
    PISTON_PLATFORM = 'ItemPistonPlatform'
    TRACK_PLATFORM = 'ItemRailPlatform'

    CUBE = 'ItemCube'
    GEL = PAINT = 'ItemPaintSplat'
    FAITH_PLATE = 'ItemCatapult'

    CUBE_DROPPER = 'ItemCubeDropper'
    GEL_DROPPER = PAINT_DROPPER = 'ItemPaintDropper'
    FAITH_TARGET = 'ItemCatapultTarget'

    # Input-less items
    GLASS = 'ItemBarrier'
    TURRET = 'ItemTurret'
    LIGHT_STRIP = 'ItemLightStrip'
    GOO = 'ItemGoo'

    # Items with inputs
    LASER_EMITTER = 'ItemLaserEmitter'
    FUNNEL = 'ItemTBeam'
    FIZZLER = 'ItemBarrierHazard'
    LIGHT_BRIDGE = 'ItemLightBridge'

    # Extent/handle pseudo-items
    HANDLE_FIZZLER = 'ItemBarrierHazardExtent'
    HANDLE_GLASS = 'ItemBarrierExtent'
    HANDLE_PISTON_PLATFORM = 'ItemPistonPlatformExtent'
    HANDLE_TRACK_PLATFORM = 'ItemRailPlatformExtent'

    # Entry/Exit corridors
    DOOR_ENTRY_SP = 'ItemEntranceDoor'
    DOOR_ENTRY_COOP = 'ItemCoopEntranceDoor'
    DOOR_EXIT_SP = 'ItemExitDoor'
    DOOR_EXIT_COOP = 'ItemCoopExitDoor'


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
    SHAPE_DOT = "signage/shape01"
    SHAPE_MOON = "signage/shape02"
    SHAPE_TRIANGLE = "signage/shape03"
    SHAPE_CROSS = "signage/shape04"
    SHAPE_SQUARE = "signage/shape05"
    SHAPE_CIRCLE = "signage/signage_shape_circle"
    SHAPE_SINE = "signage/signage_shape_sine"
    SHAPE_SLASH = "signage/signage_shape_slash"
    SHAPE_STAR = "signage/signage_shape_star"
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


class Goo(MaterialGroup):
    REFLECTIVE = "nature/toxicslime_a2_bridge_intro"
    CHEAP = "nature/toxicslime_puzzlemaker_cheap"


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
