"""Manages the list of textures used for brushes, and how they are applied."""
from enum import Enum

import random
import abc

import srctools
from srctools import Property
from srctools import Vec

import comp_consts as consts

from typing import Dict, List, Type, Any

import utils


LOGGER = utils.getLogger(__name__)

GENERATORS = {}
# Algorithms to use.
GEN_CLASSES = utils.FuncLookup('Generators')


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
        v = self.value
        if v == 1:
            return 'floor'
        elif v == 2:
            return 'wall'
        elif v == 3:
            return 'ceiling'


class TileType(str, Enum):
    """Types of textures that can exist, for tile-type generators."""
    TILE_1x1 = '1x1'  # Full block
    TILE_4x4 = '4x4'  # 1/4 of a block
    TILE_2x2 = '2x2'  # 1/2 of a block
    TILE_2x1 = '2x1'  # Two vertical

    TILE_DOUBLE = 'double'  # 256x256 tile textures.

    CLUMP_GAP = 'gap'  # For clumping, spaces without a clump.

    GOO_SIDE = 'goo'  # For on sides of goo - invalid for roof..

    def __str__(self): return self.value

# The defaults for each generator.
# This also defines the texture names allowed, as well
# as the total number of generators.
TEX_DEFAULTS = {
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

# Default values for tile options.
OPTION_DEFAULTS = {
    'MixTiles': False,  # Apply 2x2 to 1x1 space sometimes...
    'ScaleUp256': False,  # In addition to TILE_DOUBLE, use 1x1 at 2x scale.
    'Algorithm': 'RAND',  # The algorithm to use for tiles.

    # For clumping algorithm, the sizes to generate.
    'Clump_length': 4,  # Long direction max
    'Clump_width': 2,  # Other direction max
    'Clump_number': 6,  # Adjust having more or less clumps
}

# Copy left to right if right isn't set.
TILE_INHERIT = [
    (TileType.TILE_4x4, TileType.TILE_2x2),
    (TileType.TILE_2x2, TileType.TILE_2x1),
    (TileType.TILE_2x1, TileType.TILE_1x1),

    (TileType.TILE_4x4, TileType.CLUMP_GAP),
    (TileType.TILE_4x4, TileType.GOO_SIDE),
]


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


def load_config(conf: Property):
    """Setup all the generators from the config data."""
    global_options = {
        prop.name: prop.value
        for prop in
        conf.find_children('Options')
    }

    for gen_key, tex_defaults in TEX_DEFAULTS.items():
        if isinstance(gen_key, GenCat):
            is_tile = False
            gen_cat = gen_key
            gen_conf = conf.find_key(gen_cat.value, [])
        else:
            is_tile = True
            gen_cat, gen_orient, gen_portal = gen_key
            gen_conf = conf.find_key('{}.{}.{}'.format(
                gen_cat.value,
                gen_orient,
                gen_portal.value,
            ), [])

        options = {}
        textures = {}

        # First parse the options.
        parsed_options = {
            prop.name: prop.value
            for prop in
            gen_conf.find_children('Options')
        }

        for opt, default in OPTION_DEFAULTS.items():
            opt = opt.casefold()
            try:
                value = parsed_options[opt]
            except KeyError:
                try:
                    value = global_options[opt]
                except KeyError:
                    options[opt] = default
                    continue

            if isinstance(default, str):
                options[opt] = value
            elif isinstance(default, bool):
                options[opt] = srctools.conv_bool(value, default)
            elif isinstance(default, int):
                options[opt] = srctools.conv_int(value, default)
            elif isinstance(default, float):
                options[opt] = srctools.conv_float(value, default)
            else:
                raise ValueError('Bad default {!r} for "{}"!'.format(default, opt))

        if is_tile:
            # Check the algorithm to use.
            algo = options['algorithm']
            try:
                generator = GEN_CLASSES[algo]  # type: Type[Generator]
            except KeyError:
                raise ValueError('Invalid algorithm "{}" for "{}"!'.format(
                    algo, gen_conf.real_name,
                ))
        else:
            # Signage, Overlays always use the Random generator.
            generator = GenRandom

        # Now do textures.
        # If it's a tile generator we need to do inheritance, otherwise
        # it's direct.
        for tex_name, tex_default in tex_defaults.items():
            textures[tex_name] = tex = [
                prop.value for prop in
                gen_conf.find_all(str(tex_name))
            ]
            if not tex and tex_default:
                tex.append(tex_default)
        if is_tile:
            if TileType.TILE_4x4 not in textures or not textures[TileType.TILE_4x4]:
                raise ValueError('No 4x4 tile set for "{}"!'.format(gen_conf.real_name))

            # We need to do more processing.
            for orig, targ in TILE_INHERIT:
                # The order ensures orig always exists.
                if targ not in textures:
                    textures[targ] = []
                if not textures[targ]:
                    textures[targ] = textures[orig].copy()

        GENERATORS[gen_key] = generator(options, textures)


class Generator(abc.ABC):
    """Base for different texture generators."""
    def __init__(self, options: Dict[str, Any], textures: Dict[str, List[str]]):
        self._options = options
        self._textures = textures

        self._random = random.Random()
        # When set, add the position to that and use to seed the RNG.
        self.map_seed = None

    def get_one(self, loc: Vec, tex_name: str) -> str:
        """Get one texture for a position."""
        loc = loc // 128
        loc *= 128
        loc += (64, 64, 64)

        if self.map_seed:
            self._random.seed(self.map_seed + str(loc))

        try:
            return self._get(loc, tex_name)
        except KeyError as exc:
            raise ValueError('Bad texture name: ' + repr(exc.args[0]))

    def setup(self):
        """Scan tiles in the map and setup the generator."""

    @abc.abstractmethod
    def _get(self, loc: Vec, tex_name: str) -> str:
        """Actually get a texture.

        If KeyError is raised, an appropriate exception is raised from that.
        """


@GEN_CLASSES('RAND')
class GenRandom(Generator):
    """Basic random generator.

    Each texture will be randomly chosen whenever asked.
    """
    def _get(self, loc: Vec, tex_name: str):
        return self._random.choice(self._textures[tex_name])
