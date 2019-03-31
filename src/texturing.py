"""Manages the list of textures used for brushes, and how they are applied."""
from collections import namedtuple
from enum import Enum

import random
import abc

import srctools.logger
from srctools import Property, Side, Vec

import comp_consts as consts

from typing import (
    TYPE_CHECKING,
    Union, Type, Any,
    Dict, List, Tuple,
    Optional,
)

import utils

if TYPE_CHECKING:
    from tiling import TileDef

LOGGER = srctools.logger.get_logger(__name__)

# Algorithms to use.
GEN_CLASSES = utils.FuncLookup('Generators')

# These can just be looked up directly.
SPECIAL: 'Generator'
OVERLAYS: 'Generator'

Clump = namedtuple('Clump', 'x1 y1 z1 x2 y2 z2 seed')


class GenCat(Enum):
    """Categories of textures, each with a generator."""
    NORMAL = 'normal'      # Normal tiles
    PANEL = 'panel'        # Different textures for on panels, similar things.
    BULLSEYE = 'bullseye'  # With a Faith Plate target.

    # Non-wall/floor/ceiling
    SPECIAL = 'special'    # Assorted textures for various purposes.
    OVERLAYS = 'overlays'  # info_overlay materials.

    @property
    def is_tile(self):
        return self.value in ('normal', 'panel', 'bullseye')


class Portalable(Enum):
    """Is the surface portalable?"""
    WHITE = 'white'
    BLACK = 'black'
    white = WHITE
    black = BLACK

    def __str__(self) -> str:
        return self.value

    def __invert__(self) -> 'Portalable':
        if self.value == 'white':
            return Portalable.BLACK
        else:
            return Portalable.WHITE


class Orient(Enum):
    """Floor, wall or ceiling."""
    FLOOR = 1
    WALL = 2
    CEILING = 3
    CEIL = 3

    def __str__(self) -> str:
        v = self.value
        if v == 1:
            return 'floor'
        elif v == 2:
            return 'wall'
        elif v == 3:
            return 'ceiling'
        else:
            raise AssertionError(f"No string for {self!r}!")


class TileSize(str, Enum):
    """Types of textures that can exist, for tile-type generators."""
    TILE_1x1 = '1x1'  # Full block
    TILE_4x4 = '4x4'  # 1/4 of a block
    TILE_2x2 = '2x2'  # 1/2 of a block
    TILE_2x1 = '2x1'  # Two vertical

    TILE_DOUBLE = 'double'  # 256x256 tile textures.

    CLUMP_GAP = 'gap'  # For clumping, spaces without a clump.

    GOO_SIDE = 'goo'  # For on sides of goo.

    def __str__(self) -> str: return self.value

GENERATORS: Dict[
    Union[GenCat, Tuple[GenCat, Orient, Portalable]],
    'Generator'
] = {}

# The defaults for each generator.
# This also defines the texture names allowed, as well
# as the total number of generators.
TEX_DEFAULTS: Dict[
    Union[GenCat, Tuple[GenCat, Orient, Portalable]],
    Dict[str, str],
] = {
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

        # If set and enabled, adds frames for >10 sign pairs
        # to distinguish repeats.
        'shapeframe': '',
    },
    # Misc textures.
    GenCat.SPECIAL: {
        # Textures for the backside of panels.
        'behind': consts.Special.BACKPANELS_CHEAP,

        # Squarebeams texture for normal walls, and moving panels.
        'edge': consts.Special.SQUAREBEAMS,
        'panel_edge': consts.Special.SQUAREBEAMS,

        # Texture on the side of the special pedestal platform.
        'pedestalside': consts.Special.PED_SIDE,

        # Reflective and cheap Goo
        'goo': consts.Goo.REFLECTIVE,
        'goo_cheap': consts.Goo.CHEAP,

        # Textures for glass and grating.
        'glass': consts.Special.GLASS,
        'grating': consts.Special.GRATING,
    },


    # Tile-type generators:

    (GenCat.NORMAL, Orient.FLOOR, Portalable.WHITE): {
        TileSize.TILE_4x4: consts.WhitePan.WHITE_FLOOR,
        # Swap to black in goo.
        TileSize.GOO_SIDE: consts.BlackPan.BLACK_FLOOR,
    },
    (GenCat.NORMAL, Orient.FLOOR, Portalable.BLACK): {
        TileSize.TILE_4x4: consts.BlackPan.BLACK_FLOOR,
    },

    (GenCat.NORMAL, Orient.CEIL, Portalable.WHITE): {
        TileSize.TILE_4x4: consts.WhitePan.WHITE_FLOOR,
    },
    (GenCat.NORMAL, Orient.CEIL, Portalable.BLACK): {
        TileSize.TILE_4x4: consts.BlackPan.BLACK_FLOOR,
    },

    (GenCat.NORMAL, Orient.WALL, Portalable.WHITE): {
        TileSize.TILE_1x1: consts.WhitePan.WHITE_1x1,
        TileSize.TILE_2x1: consts.WhitePan.WHITE_2x1,
        TileSize.TILE_2x2: consts.WhitePan.WHITE_2x2,
        TileSize.TILE_4x4: consts.WhitePan.WHITE_4x4,

        TileSize.GOO_SIDE: consts.BlackPan.BLACK_4x4,
    },
    (GenCat.NORMAL, Orient.WALL, Portalable.BLACK): {
        TileSize.TILE_1x1: consts.BlackPan.BLACK_1x1,
        TileSize.TILE_2x2: consts.BlackPan.BLACK_2x2,
        TileSize.TILE_4x4: consts.BlackPan.BLACK_4x4,
    },

    # Panel:
    (GenCat.PANEL, Orient.FLOOR, Portalable.WHITE): {},
    (GenCat.PANEL, Orient.FLOOR, Portalable.BLACK): {},
    (GenCat.PANEL, Orient.CEIL, Portalable.WHITE): {},
    (GenCat.PANEL, Orient.CEIL, Portalable.BLACK): {},
    (GenCat.PANEL, Orient.WALL, Portalable.WHITE): {},
    (GenCat.PANEL, Orient.WALL, Portalable.BLACK): {},

    # Bullseye:
    (GenCat.PANEL, Orient.FLOOR, Portalable.WHITE): {},
    (GenCat.PANEL, Orient.FLOOR, Portalable.BLACK): {},
    (GenCat.PANEL, Orient.CEIL, Portalable.WHITE): {},
    (GenCat.PANEL, Orient.CEIL, Portalable.BLACK): {},
    (GenCat.PANEL, Orient.WALL, Portalable.WHITE): {},
    (GenCat.PANEL, Orient.WALL, Portalable.BLACK): {},
}

# Default values for tile options.
OPTION_DEFAULTS = {
    'MixTiles': False,  # Apply the smaller tile textures to 1x1 as well.
    'ScaleUp256': False,  # In addition to TILE_DOUBLE, use 1x1 at 2x scale.
    'Algorithm': 'RAND',  # The algorithm to use for tiles.

    # For clumping algorithm, the sizes to generate.
    'Clump_length': 4,  # Long direction max
    'Clump_width': 2,  # Other direction max
    'Clump_number': 6,  # Adjust having more or less clumps
}

# Copy left to right if right isn't set.
# The order is important, this ensures all tiles will be set
# if only 4x4 is.
TILE_INHERIT = [
    (TileSize.TILE_4x4, TileSize.TILE_2x2),
    (TileSize.TILE_2x2, TileSize.TILE_2x1),
    (TileSize.TILE_2x1, TileSize.TILE_1x1),

    (TileSize.TILE_4x4, TileSize.CLUMP_GAP),
    (TileSize.TILE_4x4, TileSize.GOO_SIDE),
]


def parse_options(settings: Dict[str, Any], global_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the options for a generator block."""
    options = {}
    for opt, default in OPTION_DEFAULTS.items():
        opt = opt.casefold()
        try:
            value = settings[opt]
        except KeyError:
            try:
                value = global_settings[opt]
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
    return options


def gen(cat: GenCat, normal: Vec=None, portalable: Portalable=None) -> 'Generator':
    """Given a category, normal, and white/black return the correct generator."""

    if cat is GenCat.SPECIAL or cat is GenCat.OVERLAYS:
        return GENERATORS[cat]

    if normal is None:
        raise TypeError('Normal not provided!')

    if portalable is None:
        raise TypeError('Portalability not provided!')

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


def apply(
    cat: GenCat,
    face: Side,
    tex_name: str,
    portalable: Portalable=None,
    normal: Vec=None,
    loc: Vec=None
):
    """Apply directly to a face, optionally using that to retrieve the location."""
    if cat is GenCat.SPECIAL or cat is GenCat.OVERLAYS:
        generator = GENERATORS[cat]
    else:
        if normal is None:
            normal = face.normal()
            normal.z = -normal.z
        generator = gen(cat, normal, portalable)

    if loc is None:
        loc = face.get_origin()

    face.mat = generator.get(loc, tex_name)


def load_config(conf: Property):
    """Setup all the generators from the config data."""
    global SPECIAL, OVERLAYS
    global_options = {
        prop.name: prop.value
        for prop in
        conf.find_children('Options')
    }
    # Give generators access to the global settings.
    Generator.global_settings.update(parse_options(
        # Pass it to both, the second will fail too.
        global_options, global_options,
    ))

    data = {}  # type: Dict[Any, Tuple[Dict[str, Any], Dict[str, List[str]]]]

    gen_cat: GenCat
    gen_orient: Optional[Orient]
    gen_portal: Optional[Portalable]

    for gen_key, tex_defaults in TEX_DEFAULTS.items():
        if isinstance(gen_key, GenCat):
            # It's a non-tile generator.
            is_tile = False
            gen_cat = gen_key
            gen_conf = conf.find_key(gen_cat.value, [])
        else:
            # Tile-type generator
            is_tile = True
            gen_cat, gen_orient, gen_portal = gen_key
            gen_conf = conf.find_key('{}.{}.{}'.format(
                gen_cat.value,
                gen_portal.value,
                gen_orient,
            ), [])

            if not gen_conf.has_children():
                # Special case - using a single value to indicate that all
                # textures are the same.
                gen_conf = Property(gen_conf.real_name, [
                    Property('4x4', gen_conf.value),
                    Property('Options', [
                        # Clumping isn't useful since it's all the same.
                        Property('Algorithm', 'RAND'),
                    ])
                ])
        textures = {}

        # First parse the options.
        options = parse_options({
            prop.name: prop.value
            for prop in
            gen_conf.find_children('Options')
        }, global_options)

        # Now do textures.
        if is_tile:
            # Tile generator, always have all tile sizes, and
            # only use the defaults if no textures were specified.
            for tex_name in TileSize:
                textures[tex_name] = [
                    prop.value for prop in
                    gen_conf.find_all(str(tex_name))
                ]
            if not any(textures.values()):
                for tex_name, tex_default in tex_defaults.items():
                    textures[tex_name] = [tex_default]
        else:
            # Non-tile generator, use defaults for each value
            for tex_name, tex_default in tex_defaults.items():
                textures[tex_name] = tex = [
                    prop.value for prop in
                    gen_conf.find_all(str(tex_name))
                ]
                if not tex and tex_default:
                    tex.append(tex_default)

        data[gen_key] = options, textures

    # Now do textures.
    for gen_key, tex_defaults in TEX_DEFAULTS.items():
        if isinstance(gen_key, GenCat):
            continue
        gen_cat, gen_orient, gen_portal = gen_key

        options, textures = data[gen_key]

        if not any(textures.values()) and gen_cat is not GenCat.NORMAL:
            # For the additional categories of tiles, we copy the entire
            # NORMAL one over if it's not set.
            textures.update(data[GenCat.NORMAL, gen_orient, gen_portal][1])

        if not textures[TileSize.TILE_4x4]:
            raise ValueError(
                'No 4x4 tile set for "{}"!'.format(gen_key))

        # Copy 4x4, 2x2, 2x1 textures to the 1x1 size if the option was set.
        # Do it before inheriting tiles, so there won't be duplicates.
        if options['mixtiles']:
            block_tex = textures[TileSize.TILE_1x1]
            block_tex += textures[TileSize.TILE_4x4]
            block_tex += textures[TileSize.TILE_2x2]
            block_tex += textures[TileSize.TILE_2x1]

        # We need to do more processing.
        for orig, targ in TILE_INHERIT:
            if not textures[targ]:
                textures[targ] = textures[orig].copy()

    # Now finally create the generators.
    for gen_key, tex_defaults in TEX_DEFAULTS.items():
        options, textures = data[gen_key]

        if isinstance(gen_key, tuple):
            # Check the algorithm to use.
            algo = options['algorithm']
            gen_cat, gen_orient, gen_portal = gen_key
            try:
                generator: Type[Generator] = GEN_CLASSES[algo]  # type: ignore
            except KeyError:
                raise ValueError('Invalid algorithm "{}" for {}!'.format(
                    algo, gen_key
                ))
        else:
            # Signage, Overlays always use the Random generator.
            generator = GenRandom
            gen_cat = gen_key
            gen_orient = gen_portal = None

        GENERATORS[gen_key] = generator(gen_cat, gen_orient, gen_portal, options, textures)

    SPECIAL = GENERATORS[GenCat.SPECIAL]
    OVERLAYS = GENERATORS[GenCat.OVERLAYS]


def setup(global_seed, tiles: List['TileDef']):
    """Set randomisation seed on all the generators, and build clumps."""
    gen_key_str: Union[GenCat, str]
    for gen_key, generator in GENERATORS.items():
        if isinstance(gen_key, tuple):
            gen_cat, gen_orient, gen_portal = gen_key
            gen_key_str = '{}.{}.{}'.format(
                gen_cat.value,
                gen_portal.value,
                gen_orient,
            )
        else:
            gen_key_str = gen_key

        generator.map_seed = '{}_tex_{}_'.format(global_seed, gen_key_str)
        generator.setup(global_seed, tiles)


class Generator(abc.ABC):
    """Base for different texture generators."""

    # The settings which apply to all generators.
    # Since they're here all subclasses and instances can access this.
    global_settings = {}  # type: Dict[str, Any]

    def __init__(
        self,
        category: GenCat,
        orient: Optional[Orient],
        portal: Optional[Portalable],
        options: Dict[str, Any],
        textures: Dict[str, List[str]],
    ):
        self.options = options
        self.textures = textures

        self._random = random.Random()
        # When set, add the position to that and use to seed the RNG.
        self.map_seed = ''

        # Tells us the category each generator matches to.
        self.category = category
        self.orient = orient
        self.portal = portal

    def get(self, loc: Vec, tex_name: str) -> str:
        """Get one texture for a position."""
        loc = loc // 128
        loc *= 128
        loc += (64, 64, 64)

        if self.map_seed:
            self._random.seed(self.map_seed + str(loc))
        else:
            LOGGER.warning('Choosing texture ("{}") without seed!', tex_name)

        try:
            return self._get(loc, tex_name)
        except KeyError as exc:
            raise self._missing_error(repr(exc.args[0]))

    def setup(self, global_seed: str, tiles: List['TileDef']):
        """Scan tiles in the map and setup the generator."""

    def _missing_error(self, tex_name: str):
        return ValueError('Bad texture name: {}\n Allowed: {!r}'.format(
            tex_name,
            list(self.textures.keys()),
        ))

    @abc.abstractmethod
    def _get(self, loc: Vec, tex_name: str) -> str:
        """Actually get a texture.

        If KeyError is raised, an appropriate exception is raised from that.
        """

    def get_all(self, tex_name: str) -> List[str]:
        """Return all the textures possible for a given name."""
        try:
            return list(self.textures[tex_name])
        except KeyError:
            raise self._missing_error(tex_name) from None

    def __contains__(self, tex_name: str) -> bool:
        """Return True if the texture is defined."""
        try:
            return bool(self.textures[tex_name])
        except KeyError:
            return False


@GEN_CLASSES('RAND')
class GenRandom(Generator):
    """Basic random generator.

    Each texture will be randomly chosen whenever asked.
    This is used for Overlay and Signage as well.
    """

    def _get(self, loc: Vec, tex_name: str):
        return self._random.choice(self.textures[tex_name])


@GEN_CLASSES('CLUMP')
class GenClump(Generator):
    """The clumping generator for tiles.

    This creates groups of the same texture in roughly rectangular sections.
    """

    # The clump locations are shared among all generators.
    clump_locs = []  # type: List[Clump]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # A seed only unique to this generator, in int form.
        self.gen_seed = 0

    def setup(self, global_seed: str, tiles: List['TileDef']):
        """Build the list of clump locations."""
        assert self.portal is not None
        assert self.orient is not None

        # Convert the generator key to a generator-specific seed.
        # That ensures different surfaces don't end up reusing the same
        # texture indexes.
        self.gen_seed = int.from_bytes(
            self.category.name.encode() +
            self.portal.name.encode() +
            self.orient.name.encode(),
            'big',
        )

        # We only do this once, as it applies to all generators.
        if GenClump.clump_locs:
            return

        LOGGER.info('Generating texture clumps...')

        clump_length = self.global_settings['clump_length']  # type: int
        clump_width = self.global_settings['clump_width']  # type: int
        clump_number = self.global_settings['clump_number']  # type: int

        # Clump_number adjusts the amount of clumps in the map, to control
        # how much they overlap each other.
        clump_numb = len(tiles) // (clump_length * clump_width * clump_width)
        clump_numb *= clump_number

        # A global RNG for picking clump positions.
        clump_rand = random.Random(global_seed + '_clumping')

        LOGGER.info('{} Clumps for {} tiles', clump_numb, len(tiles))

        pos_min = Vec()
        pos_max = Vec()

        for _ in range(clump_numb):
            # Picking out of the map origins helps ensure at least 1 texture is
            # modded by a clump
            tile = clump_rand.choice(tiles)  # type: TileDef
            pos = tile.pos // 128 * 128  # type: Vec

            # Clumps are long strips mainly extended in one direction
            # In the other directions extend by 'width'. It can point any axis.
            direction = clump_rand.choice('xyz')
            for axis in 'xyz':
                if axis == direction:
                    dist = clump_length
                else:
                    dist = clump_width
                pos_min[axis] = pos[axis] - clump_rand.randint(0, dist) * 128
                pos_max[axis] = pos[axis] + clump_rand.randint(0, dist) * 128

                self.clump_locs.append(Clump(
                    pos_min.x, pos_min.y, pos_min.z,
                    pos_max.x, pos_max.y, pos_max.z,
                    # We use this to reseed an RNG, giving us the same textures
                    # each time for the same clump.
                    clump_rand.getrandbits(32),
                ))

    def _get(self, loc: Vec, tex_name: str) -> str:
        clump_seed = self._find_clump(loc)

        if clump_seed is None:
            # No clump found - return the gap texture.
            return self._random.choice(self.textures[TileSize.CLUMP_GAP])

        # Mix these three values together to determine the texture.
        # The clump seed makes each clump different, and adding the texture
        # name makes sure different surface types don't copy each other's
        # indexes.
        self._random.seed(
            self.gen_seed ^
            int.from_bytes(tex_name.encode(), 'big') ^
            clump_seed
        )
        return self._random.choice(self.textures[tex_name])

    def _find_clump(self, loc: Vec) -> Optional[int]:
        """Return the clump seed matching a location."""
        for clump in self.clump_locs:
            if (
                clump.x1 <= loc.x <= clump.x2 and
                clump.y1 <= loc.y <= clump.y2 and
                clump.z1 <= loc.z <= clump.z2
            ):
                return clump.seed
        return None

