"""Manages the list of textures used for brushes, and how they are applied."""
from enum import Enum

import random
import abc

from srctools import Property
from srctools import Vec

import comp_consts as consts

from typing import Dict, List, Tuple, Union, Optional, Iterable

import utils


LOGGER = utils.getLogger(__name__)

GENERATORS = {}


class GenCat(Enum):
    """Categories of textures, each with a generator."""
    NORMAL = 'normal'      # Normal tiles
    PANEL = 'panel'        # Different textures for on panels, similar things.
    BULLSEYE = 'bullseye'  # With a Faith Plate target.

    # Non-wall/floor/ceiling
    SPECIAL = 'special'    # Assorted textures for various purposes.
    OVERLAYS = 'overlays'  # info_overlay materials.


class Portalable(Enum):
    """Is the surface portalable?"""
    WHITE = 'white'
    BLACK = 'black'


class Orient(Enum):
    """Floor, wall or ceiling."""
    FLOOR = 1
    WALL = 2
    CEILING = 3
    CEIL = 3

    def __str__(self):
        if self is Orient.floor:
            return 'floor'
        elif self is Orient.wall:
            return 'wall'
        elif self is Orient.ceiling:
            return 'ceiling'


class TileType(str, Enum):
    """Types of textures that can exist, for tile-type generators."""
    TILE_1x1 = '1x1'  # Full block
    TILE_4x4 = '4x4'  # 1/4 of a block
    TILE_2x2 = '2x2'  # 1/2 of a block
    TILE_2x1 = '2x1'  # Two vertical

    CLUMP_GAP = 'gap'  # For clumping, spaces without a clump.

    GOO_SIDE = 'goo'  # For on sides of goo - invalid for roof..

    def __str__(self): return self.value

# The defaults for each generator.
# This also defines the texture names allowed, as well
# as the total number of generators.
DEFAULTS = {
    # Signage overlays.
    GenCat.OVERLAYS: {
        'exit': consts.Signage.EXIT, 
        'arrow': consts.Signage.ARROW, 
        'dot': consts.Signage.SHAPE_DOT, 
        'moon': consts.Signage.SHAPE_MOON, 
        'triangle': consts.Signage.SHAPE_TRIANGLE, 
        'cross': consts.Signage.SHAPE_CROSS, 
        'square': consts.Signage.SHAPE_SQUARE, 
        'circle': consts.Signage.SHAPE_CIRCLE, 
        'sine': consts.Signage.SHAPE_SINE, 
        'slash': consts.Signage.SHAPE_SLASH, 
        'star': consts.Signage.SHAPE_STAR, 
        'wavy': consts.Signage.SHAPE_WAVY,
        
        # If set, overlays to add on top for successive sets of signage.
        'shape_frame': (), 
    },
    # Misc textures.
    GenCat.SPECIAL: {
        # Textures for the backside of panels.
        'behind': consts.Special.BACKPANELS_CHEAP,

        # Squarebeams texture for normal walls, and moving panels.
        'edge': consts.Special.SQUAREBEAMS,
        'edge_special': consts.Special.SQUAREBEAMS,

        # Reflective and cheap Goo
        'goo': consts.Goo.REFLECTIVE,
        'goo_cheap': consts.Goo.CHEAP,

        # Textures for glass and grating.
        'glass': consts.Special.GLASS,
        'grating': consts.Special.GRATING,
    },


    # Tile-type generators:

    (GenCat.NORMAL, Orient.FLOOR, Portalable.WHITE): {
        TileType.TILE_4x4: consts.WhitePan.WHITE_FLOOR,
        # Swap to black in goo.
        TileType.GOO_SIDE: consts.BlackPan.BLACK_FLOOR,
    },
    (GenCat.NORMAL, Orient.FLOOR, Portalable.BLACK): {
        TileType.TILE_4x4: consts.BlackPan.BLACK_FLOOR,
    },

    (GenCat.NORMAL, Orient.CEIL, Portalable.WHITE): {
        TileType.TILE_4x4: consts.WhitePan.WHITE_FLOOR,
    },
    (GenCat.NORMAL, Orient.CEIL, Portalable.BLACK): {
        TileType.TILE_4x4: consts.BlackPan.BLACK_FLOOR,
    },

    (GenCat.NORMAL, Orient.WALL, Portalable.WHITE): {
        TileType.TILE_1x1: consts.WhitePan.WHITE_1x1,
        TileType.TILE_2x1: consts.WhitePan.WHITE_2x1,
        TileType.TILE_2x2: consts.WhitePan.WHITE_2x2,
        TileType.TILE_4x4: consts.WhitePan.WHITE_4x4,

        TileType.GOO_SIDE: consts.BlackPan.BLACK_4x4,
    },
    (GenCat.NORMAL, Orient.WALL, Portalable.BLACK): {
        TileType.TILE_1x1: consts.BlackPan.BLACK_1x1,
        TileType.TILE_2x2: consts.BlackPan.BLACK_2x2,
        TileType.TILE_4x4: consts.BlackPan.BLACK_4x4,
    },
}


def gen(cat: GenCat, normal: Vec, portalable: Portalable) -> 'Generator':
    """Given a category, normal, and white/black return the correct generator."""

    if cat is GenCat.SPECIAL or cat is GenCat.OVERLAYS:
        return GENERATORS[cat]

    # Even if not axis-aligned, make mostly-flat surfaces
    # floor/ceiling (+-40 degrees)
    # sin(40) = ~0.707
    # floor_tolerance = 0.8

    if normal.z > 0.8:
        orient = Orient.FLOOR
    elif normal.z < -0.8:
        orient = Orient.CEIL
    else:
        orient = Orient.WALL

    return GENERATORS[cat, orient, portalable]


def setup(conf: Property):
    """Setup all the generators from the config data."""


class Generator(abc.ABC):
    """Base for different texture generators."""
    def __init__(self):
        self._random = random.Random()
        # When set, add the position to that and use to seed the RNG.
        self._map_seed = None

    def get_one(self, loc: Vec, tex_name: str) -> str:
        """Get one texture for a position."""
        loc = loc // 128
        loc *= 128
        loc += (64, 64, 64)

        if self._map_seed:
            self._random.seed(self._map_seed + str(loc))

        try:
            return self._get(loc, tex_name)
        except KeyError as exc:
            raise ValueError('Bad texture name: ' + repr(exc.args[0]))

    @abc.abstractmethod
    def _get(self, loc: Vec, tex_name: str) -> str:
        """Actually get a texture.

        If KeyError is raised, an appropriate exception is raised from that.
        """


class GenRandom(Generator):
    """Basic random generator.

    Each texture will be randomly chosen whenever asked.
    """
    def __init__(self, textures: Dict[str, List[str]]):
        super().__init__()
        self._textures = textures

    def _get(self, loc: Vec, tex_name: str):
        return self._random.choice(self._textures[tex_name])
