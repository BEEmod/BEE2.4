"""Various constant values for use by VBSP. (Mainly texture names.)"""
from enum import Enum, EnumMeta


class ConstGroupMeta(EnumMeta):
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
        """ConstGroup can check if strings are equal to a member."""
        if isinstance(value, str):
            return value.casefold() in cls._value2member_map_
        return super().__contains__(value)
        
    def __call__(cls, value, *args, **kwargs):
        if args or kwargs:
            return super().__call__(value, *args, **kwargs)
        return cls.__new__(cls, value.casefold())

    __call__.__doc__ = EnumMeta.__call__.__doc__


class ConstGroup(str, Enum, metaclass=ConstGroupMeta):
    """Adds a few useful features to the string enums.

    * They are compared case-insensitively.
    * 'str' in ConstGroup can be done to check if a string is equal
      to any members.
    * str(member) == member.value
    """
    def __eq__(self, other):
        return self.value == other.casefold()

    def __str__(self):
        return self.value

    def __hash__(self):
        """Allow hashing ConstGroup values."""
        return hash(self.value)


class WhitePan(ConstGroup):
    """White tiling."""
    WHITE_FLOOR = "tile/white_floor_tile002a"
    WHITE_1x1 = "tile/white_wall_tile003a"
    WHITE_2x1 = "tile/white_wall_tile003h"
    WHITE_2x2 = "tile/white_wall_tile003c"
    WHITE_4x4 = "tile/white_wall_tile003f"


class BlackPan(ConstGroup):
    """Black tiling."""
    BLACK_FLOOR = "metal/black_floor_metal_001c"
    BLACK_1 = "metal/black_wall_metal_002c"
    BLACK_2 = "metal/black_wall_metal_002e"
    BLACK_2x2 = "metal/black_wall_metal_002a"  # 2x2
    BLACK_4x4 = "metal/black_wall_metal_002b"  # 4x4


class Signage(ConstGroup):
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


class Special(ConstGroup):
    BACKPANELS = "anim_wp/framework/backpanels"
    # Note - this is used in PeTI maps.
    BACKPANELS_CHEAP = "anim_wp/framework/backpanels_cheap"
    PED_SIDE = "plastic/plasticwall004a"
    SQUAREBEAMS = "anim_wp/framework/squarebeams"
    GLASS = "glass/glasswindow007a_less_shiny"
    GRATING = "metal/metalgrate018"
    LASERFIELD = "effects/laserplane"


class Goo(ConstGroup):
    REFLECTIVE = "nature/toxicslime_a2_bridge_intro"
    CHEAP = "nature/toxicslime_puzzlemaker_cheap"


class Antlines(ConstGroup):
    STRAIGHT = "signage/indicator_lights/indicator_lights_floor"
    CORNER = "signage/indicator_lights/indicator_lights_corner_floor"


class Tools(ConstGroup):
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


class Fizzler(ConstGroup):
    """Fizzler textures."""
    CENTER = "effects/fizzler_center"
    LEFT = "effects/fizzler_l"
    RIGHT = "effects/fizzler_r"
    SHORT = "effects/fizzler"
