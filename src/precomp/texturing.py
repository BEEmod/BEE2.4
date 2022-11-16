"""Manages the list of textures used for brushes, and how they are applied."""
from typing import TYPE_CHECKING, Union, Type, Any, Dict, List, Tuple, Optional, Iterable, Set
from pathlib import Path
from enum import Enum
import itertools
import abc

import attrs
import trio

from srctools import Property, Vec, conv_bool
from srctools.game import Game
from srctools.tokenizer import TokenSyntaxError
from srctools.vmf import VisGroup, VMF, Side, Solid
from srctools.vmt import Material
import srctools.logger

from precomp import rand
from precomp.brushLoc import POS as BLOCK_TYPE
import consts
import utils

if TYPE_CHECKING:
    from precomp.tiling import TileDef

LOGGER = srctools.logger.get_logger(__name__)

# Algorithms to use.
GEN_CLASSES: utils.FuncLookup[Type['Generator']] = utils.FuncLookup('Generators')

# These can just be looked up directly.
SPECIAL: 'Generator'
OVERLAYS: 'Generator'


class GenCat(Enum):
    """Categories of textures, each with a generator."""
    NORMAL = 'normal'      # Normal tiles
    PANEL = 'panel'        # Different textures for on panels, similar things.
    BULLSEYE = 'bullseye'  # With a Faith Plate target.

    # Non-wall/floor/ceiling
    SPECIAL = 'special'    # Assorted textures for various purposes.
    OVERLAYS = 'overlays'  # info_overlay materials.

    @property
    def is_tile(self) -> bool:
        """Check if this is a tile-type generator.

        These have specific configuration for walls/floors/ceiling and white/black.
        """
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
    FLOOR = +1
    WALL = 0
    CEILING = -1
    CEIL = -1

    def __str__(self) -> str:
        v = self.value
        if v == +1:
            return 'floor'
        elif v == 0:
            return 'wall'
        elif v == -1:
            return 'ceiling'
        else:
            raise AssertionError(f"No string for {self!r}!")

    @property
    def z(self) -> float:
        """Return the Z value of the normal expected for this surface."""
        return self.value


GEN_CATS = {
    'overlays': GenCat.OVERLAYS,
    'overlay': GenCat.OVERLAYS,

    'special': GenCat.SPECIAL,

    'panel': GenCat.PANEL,

    'normal': GenCat.NORMAL,
    'surf': GenCat.NORMAL,
    'tiles': GenCat.NORMAL,

    'bullseye': GenCat.BULLSEYE,
    'faithplate': GenCat.BULLSEYE,
    'faith': GenCat.BULLSEYE,
    'catapult': GenCat.BULLSEYE,
}

ORIENTS = {
    'floor': Orient.FLOOR,
    'floors': Orient.FLOOR,

    'wall': Orient.WALL,
    'walls': Orient.WALL,

    'ceil': Orient.CEIL,
    'ceiling': Orient.CEIL,
    'ceilings': Orient.CEIL,
}

# For each material, the generated nopaint material.
ANTIGEL_MATS: Dict[str, str] = {}
# The folder to add them to
ANTIGEL_PATH = 'BEE2/antigel/gen/'
# The center of each voxel containing an antigel marker.
# Surfaces inside here that aren't a voxel side will be converted.
ANTIGEL_LOCS: Set[Tuple[float, float, float]] = set()

ANTIGEL_TEMPLATE = '''\
Patch
 {{
 include "materials/BEE2/antigel/base.vmt"
 Insert
  {{
  $basetexture "{path}"
  %noportal {noportal}
  }}
 }}
'''


@utils.freeze_enum_props
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

    @property
    def size(self) -> Tuple[int, int]:
        """Return the number of 32-size tiles this takes up."""
        if self.value in ('4x4', 'goo'):
            return 1, 1
        elif self.value in ('1x1', 'gap'):
            return 4, 4
        elif self.value == '2x2':
            return 2, 2
        elif self.value == '2x1':
            return 2, 4
        elif self.value == 'double':
            return 8, 8
        raise AssertionError(self)

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

        # Faith Plate bullseye for non-moving surfaces.
        'bullseye': consts.Special.BULLSEYE,
        # Tideline overlay around the outside of goo pits.
        'tideline': consts.Goo.TIDELINE,
    },
    # Misc textures.
    GenCat.SPECIAL: {
        # Textures for the backside of panels.
        'behind': consts.Special.BACKPANELS_CHEAP,

        # Squarebeams texture for normal walls, and moving panels.
        'edge': consts.Special.SQUAREBEAMS,
        'panel_edge': consts.Special.SQUAREBEAMS,

        # Reflective and cheap Goo
        'goo': consts.Goo.REFLECTIVE,
        'goo_cheap': consts.Goo.CHEAP,

        # Textures for glass and grating.
        'glass': consts.Special.GLASS,
        'grating': consts.Special.GRATING,

        # Fizzler border material (1950s style mainly)
        'fizz_border': '',
    },


    # Tile-type generators:

    (GenCat.NORMAL, Orient.FLOOR, Portalable.WHITE): {
        TileSize.TILE_4x4: consts.WhitePan.WHITE_FLOOR,
    },
    (GenCat.NORMAL, Orient.FLOOR, Portalable.BLACK): {
        TileSize.TILE_4x4: consts.BlackPan.BLACK_FLOOR,
    },

    (GenCat.NORMAL, Orient.CEIL, Portalable.WHITE): {
        TileSize.TILE_4x4: consts.WhitePan.WHITE_4x4,
    },
    (GenCat.NORMAL, Orient.CEIL, Portalable.BLACK): {
        TileSize.TILE_4x4: consts.BlackPan.BLACK_FLOOR,
    },

    (GenCat.NORMAL, Orient.WALL, Portalable.WHITE): {
        TileSize.TILE_1x1: consts.WhitePan.WHITE_1x1,
        TileSize.TILE_2x1: consts.WhitePan.WHITE_2x1,
        TileSize.TILE_2x2: consts.WhitePan.WHITE_2x2,
        TileSize.TILE_4x4: consts.WhitePan.WHITE_4x4,
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

    # Bullseye textures, used when on panels and overlays can't be used.
    (GenCat.BULLSEYE, Orient.FLOOR, Portalable.WHITE): {},
    (GenCat.BULLSEYE, Orient.FLOOR, Portalable.BLACK): {},
    (GenCat.BULLSEYE, Orient.CEIL, Portalable.WHITE): {},
    (GenCat.BULLSEYE, Orient.CEIL, Portalable.BLACK): {},
    (GenCat.BULLSEYE, Orient.WALL, Portalable.WHITE): {},
    (GenCat.BULLSEYE, Orient.WALL, Portalable.BLACK): {},
}

# Default values for tile options.
OPTION_DEFAULTS = {
    'MixTiles': False,  # Apply the smaller tile textures to 1x1 as well.
    'ScaleUp256': False,  # In addition to TILE_DOUBLE, use 1x1 at 2x scale.
    'Antigel_Bullseye': False,  # If true, allow bullseyes on antigel panels.
    'Algorithm': 'RAND',  # The algorithm to use for tiles.

    # For clumping algorithm, the sizes to generate.
    'Clump_length': 4,  # Long direction max
    'Clump_width': 2,  # Other direction max
    'clump_debug': False,  # If true, dump them all as skip brushes.
}

# Copy left to right if right isn't set.
# The order is important, this ensures all tiles will be set
# if only 4x4 is.
TILE_INHERIT = [
    (TileSize.TILE_4x4, TileSize.TILE_2x2),
    (TileSize.TILE_2x2, TileSize.TILE_2x1),
    (TileSize.TILE_2x1, TileSize.TILE_1x1),

    (TileSize.TILE_4x4, TileSize.GOO_SIDE),
]


def format_gen_key(
    gen_key: Union[GenCat, Tuple[GenCat, Orient, Portalable]]
) -> str:
    """Convert the GenCat into a string for nice display."""
    if isinstance(gen_key, GenCat):
        return gen_key.value
    else:
        gen_cat, orient, portal = gen_key
        return f'{gen_cat.value}.{portal}.{orient}'


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
            raise ValueError(f'Bad default {default!r} for "{opt}"!')
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


def parse_name(name: str) -> Tuple['Generator', str]:
    """Parse a dotted string into a generator and a texture name."""
    split_name = name.lower().split('.')
    try:
        gen_cat = GEN_CATS[split_name[0]]
    except KeyError:
        raise ValueError(
            f'Invalid generator category in "{name}"!\n'
            f'Valid categories: \n {",".join([cat.value for cat in GenCat])}'
        ) from None
    if gen_cat.is_tile:
        if len(split_name) != 4:
            raise ValueError(
                f'Tile-type generator categories require '
                f'cat.[floor/wall/ceiling].[white/black].texname, '
                f'not "{name}"!'
            )
        try:
            gen_orient = ORIENTS[split_name[1]]
        except KeyError:
            raise ValueError(f'"{split_name[1]}" is not wall, floor or ceiling!') from None

        try:
            gen_port = Portalable(split_name[2])
        except ValueError:
            raise ValueError(f'"{split_name[2]}" is not white or black!') from None

        return GENERATORS[gen_cat, gen_orient, gen_port], split_name[-1]
    else:
        if len(split_name) != 2:
            raise ValueError(
                f'Non-tile type generator categories'
                f' expect cat.texname, not "{name}"!'
            )
        return GENERATORS[gen_cat], split_name[-1]


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

    face.mat = generator.get(loc + face.normal(), tex_name)


def load_config(conf: Property):
    """Setup all the generators from the config data."""
    global SPECIAL, OVERLAYS
    global_options = {
        prop.name or '': prop.value
        for prop in
        conf.find_children('Options')
    }
    # Give generators access to the global settings.
    Generator.global_settings.update(parse_options(
        # Pass it to both, the second will fail too.
        global_options, global_options,
    ))

    data: Dict[Any, Tuple[Dict[str, Any], Dict[str, List[str]]]] = {}

    gen_cat: GenCat
    gen_orient: Optional[Orient]
    gen_portal: Optional[Portalable]

    # Use this to allow alternate names for generators.
    conf_for_gen: Dict[
        Tuple[GenCat, Optional[Orient], Optional[Portalable]],
        Property,
    ] = {}

    for prop in conf:
        if prop.name in ('options', 'antlines'):
            continue
        if '.' in prop.name:
            try:
                gen_cat_name, gen_portal_raw, gen_orient_raw = prop.name.split('.')
                gen_cat = GEN_CATS[gen_cat_name]
                gen_orient = ORIENTS[gen_orient_raw]
                gen_portal = Portalable(gen_portal_raw)
            except (KeyError, ValueError):
                LOGGER.warning('Could not parse texture generator type "{}"!', prop.name)
                continue
            conf_for_gen[gen_cat, gen_orient, gen_portal] = prop
        else:
            try:
                gen_cat = GEN_CATS[prop.name]
            except KeyError:
                LOGGER.warning('Unknown texture generator type "{}"!', prop.name)
                continue
            conf_for_gen[gen_cat, None, None] = prop

    for gen_key, tex_defaults in TEX_DEFAULTS.items():
        if isinstance(gen_key, GenCat):
            # It's a non-tile generator.
            is_tile = False
            try:
                gen_conf = conf_for_gen[gen_key, None, None]
            except KeyError:
                gen_conf = Property(gen_key.value, [])
        else:
            # Tile-type generator
            is_tile = True
            try:
                gen_conf = conf_for_gen[gen_key]
            except KeyError:
                gen_conf = Property('', [])

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
        textures: Dict[str, List[str]] = {}
        tex_name: str

        # First parse the options.
        options = parse_options({
            prop.name or '': prop.value
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

            # In case someone switches them around, add on 2x1 to 1x2 textures.
            textures[TileSize.TILE_2x1] += [
                prop.value for prop in
                gen_conf.find_all('1x2')
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

        # Next, do a check to see if any texture names were specified that
        # we don't recognise.
        extra_keys = {prop.name for prop in gen_conf}
        extra_keys.discard('options')  # Not a texture name, but valid.

        if isinstance(gen_key, GenCat):
            extra_keys.difference_update(map(str.casefold, tex_defaults.keys()))
        else:
            # The defaults are just the size values.
            extra_keys.difference_update(map(str, TileSize))

        if extra_keys:
            LOGGER.warning(
                '{}: Unknown texture names {}',
                format_gen_key(gen_key),
                ', '.join(sorted(extra_keys))
            )

    # Now complete textures for tile types,
    # copying over data from other generators.
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
            raise ValueError(f'No 4x4 tile set for "{gen_key}"!')

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
                generator = GEN_CLASSES[algo]
            except KeyError:
                raise ValueError(f'Invalid algorithm "{algo}" for {gen_key}!')
        else:
            # Signage, Overlays always use the Random generator.
            generator = GenRandom
            gen_cat = gen_key
            gen_orient = gen_portal = None

        GENERATORS[gen_key] = gentor = generator(gen_cat, gen_orient, gen_portal, options, textures)

        # Allow it to use the default enums as direct lookups.
        if isinstance(gentor, GenRandom):
            if gen_portal is None:
                gentor.set_enum(tex_defaults.items())
            else:
                # Tiles always use TileSize.
                gentor.set_enum((size.value, size) for size in TileSize)

    SPECIAL = GENERATORS[GenCat.SPECIAL]
    OVERLAYS = GENERATORS[GenCat.OVERLAYS]


async def setup(game: Game, vmf: VMF, tiles: List['TileDef']) -> None:
    """Do various setup steps, needed for generating textures.

    - Set randomisation seed on all the generators.
    - Build clumps.
    - Generate antigel materials
    """
    material_folder = game.path / '../bee2/materials/'
    antigel_loc = material_folder / ANTIGEL_PATH
    antigel_loc.mkdir(parents=True, exist_ok=True)

    fsys = game.get_filesystem()

    # Basetexture -> material name
    tex_to_antigel: Dict[str, str] = {}
    # And all the filenames that exist.
    antigel_mats: Set[str] = set()

    async def check_existing(filename: Path) -> None:
        """First, check existing materials to determine which are already created."""
        try:
            with filename.open() as f:
                exist_mat = await trio.to_thread.run_sync(Material.parse, f, str(filename))
        except FileNotFoundError:
            # It should exist, we just checked for it? Doesn't matter though.
            return
        except TokenSyntaxError:
            LOGGER.warning('Unable to parse antigel material {}!', filename, exc_info=True)
            # Delete the bad file.
            await trio.to_thread.run_sync(filename.unlink)
            return
        mat_name = str(filename.relative_to(material_folder).with_suffix('')).replace('\\', '/')
        texture: Optional[str] = None
        for block in exist_mat.blocks:
            if block.name not in ['insert', 'replace']:
                continue
            try:
                texture = block['$basetexture']
                break
            except LookupError:
                pass
        if texture is None:
            LOGGER.warning('No $basetexture in antigel material {}!', mat_name)
            return
        tex_to_antigel[texture.casefold()] = mat_name
        antigel_mats.add(filename.stem)

    async with trio.open_nursery() as nursery:
        for vmt_file in antigel_loc.glob('*.vmt'):
            nursery.start_soon(check_existing, vmt_file)

    materials: set[str] = set()

    for generator in GENERATORS.values():
        generator.setup(vmf, tiles)

        # No need to convert if it's overlay, or it's bullseye and those
        # are incompatible.
        if generator.category is GenCat.BULLSEYE and not generator.options['antigel_bullseye']:
            continue
        if generator.category is GenCat.OVERLAYS:
            continue

        for (mat_cat, mats) in generator.textures.items():
            #  Skip these special mats.
            if mat_cat not in ('glass', 'grating', 'goo', 'goo_cheap'):
                materials.update(mats)

    async def generate_mat(mat_name: str) -> None:
        """Generate an antigel material."""
        try:
            with fsys[f'materials/{mat_name}.vmt'].open_str() as f:
                mat = await trio.to_thread.run_sync(Material.parse, f, mat_name)
            mat = await trio.to_thread.run_sync(mat.apply_patches, fsys)
        except FileNotFoundError:
            LOGGER.warning('Material {} does not exist?', mat_name)
            return
        except TokenSyntaxError:
            LOGGER.warning('Material {} cannot be parsed for antigel:', mat_name, exc_info=True)
            return
        try:
            texture = mat['$basetexture']
        except KeyError:
            LOGGER.warning('No $basetexture in material {}?', mat_name)
            return
        if mat_name.casefold() in ANTIGEL_MATS:
            return
        try:
            ANTIGEL_MATS[mat_name.casefold()] = tex_to_antigel[texture.casefold()]
            return
        except KeyError:
            pass
        noportal = conv_bool(mat.get('%noportal', False))
        # We have to generate.
        antigel_filename = str(antigel_loc / Path(texture).stem)
        if antigel_filename in antigel_mats:
            antigel_filename_base = antigel_filename.rstrip('0123456789')
            for i in itertools.count(1):
                antigel_filename = f'{antigel_filename_base}{i:02}'
                if antigel_filename not in antigel_mats:
                    break
        with open(antigel_filename + '.vmt', 'w') as f:
            f.write(ANTIGEL_TEMPLATE.format(
                path=texture,
                noportal=int(noportal),
            ))
        antigel_mat = str(Path(antigel_filename).relative_to(material_folder)).replace('\\', '/')
        ANTIGEL_MATS[mat_name.casefold()] = tex_to_antigel[texture.casefold()] = antigel_mat
        antigel_mats.add(antigel_mat)

    async with trio.open_nursery() as nursery:
        for mat_name in materials:
            nursery.start_soon(generate_mat, mat_name)


class Generator(abc.ABC):
    """Base for different texture generators."""

    # The settings which apply to all generators.
    # Since they're here all subclasses and instances can access this.
    global_settings: Dict[str, Any] = {}

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

        # Tells us the category each generator matches to.
        self.category = category
        self.orient = orient
        self.portal = portal

    def get(self, loc: Vec, tex_name: str, *, antigel: Optional[bool] = None) -> str:
        """Get one texture for a position.

        If antigel is set, this is directly on a tile and so whether it's antigel
        is known.
        The location should be 1 unit back from the tile, so it'll be in the
        correct block.
        """
        grid_loc = loc // 128

        if antigel is None:
            antigel = grid_loc.as_tuple() in ANTIGEL_LOCS
        if antigel and self.category is GenCat.BULLSEYE and not self.options['antigel_bullseye']:
            assert self.orient is not None or self.portal is not None
            # We can't use antigel on bullseye materials, so revert to normal
            # surfaces.
            return GENERATORS[GenCat.NORMAL, self.orient, self.portal].get(loc, tex_name, antigel=True)

        # Force blocks inside goo to goo side.
        if self.category is GenCat.NORMAL and self.orient is Orient.WALL and BLOCK_TYPE[grid_loc].is_goo:
            tex_name = TileSize.GOO_SIDE

        try:
            texture = self._get(loc, tex_name)
        except KeyError as exc:
            raise self._missing_error(repr(exc.args[0]))
        if antigel:
            try:
                return ANTIGEL_MATS[texture.casefold()]
            except KeyError:
                LOGGER.warning('No antigel mat generated for "{}"!', texture)
                # Set it to itself to silence the warning.
                ANTIGEL_MATS[texture.casefold()] = texture

        return texture

    def setup(self, vmf: VMF, tiles: List['TileDef']) -> None:
        """Scan tiles in the map and set up the generator."""

    def _missing_error(self, tex_name: str):
        return ValueError(f'Bad texture name: {tex_name}\n Allowed: {list(self.textures.keys())!r}')

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
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # For enum constants, use the id() to lookup - this
        # way we're effectively comparing by identity.
        self.enum_data: Dict[int, str] = {}

    def set_enum(self, defaults: Iterable[Tuple[str, str]]) -> None:
        """For OVERLAY and SPECIAL, allow also passing in the enum constants."""
        for key, default in defaults:
            if type(default) != str:
                self.enum_data[id(default)] = key

    def _get(self, loc: Vec, tex_name: str):
        if type(tex_name) != str:
            try:
                tex_name = self.enum_data[id(tex_name)]
            except KeyError:
                raise ValueError(
                    f'Unknown enum value {tex_name!r} '
                    f'for generator type {self.category}!') from None
        return rand.seed(b'tex_rand', loc).choice(self.textures[tex_name])


@attrs.define
class Clump:
    """Represents a region of map, used to create rectangular sections with the same pattern."""
    x1: float
    y1: float
    z1: float
    x2: float
    y2: float
    z2: float
    seed: bytes


@GEN_CLASSES('CLUMP')
class GenClump(Generator):
    """The clumping generator for tiles.

    This creates groups of the same texture in roughly rectangular sections.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # A seed only unique to this generator.
        self.gen_seed = b''
        self._clump_locs: list[Clump] = []

    def setup(self, vmf: VMF, tiles: List['TileDef']) -> None:
        """Build the list of clump locations."""
        assert self.portal is not None
        assert self.orient is not None

        # Convert the generator key to a generator-specific seed.
        # That ensures different surfaces don't end up reusing the same
        # texture indexes.
        self.gen_seed = b''.join([
            self.category.name.encode(),
            self.portal.name.encode(),
            self.orient.name.encode(),
        ])

        LOGGER.info('Generating texture clumps...')

        clump_length: int = self.options['clump_length']
        clump_width: int = self.options['clump_width']

        # The tiles currently present in the map.
        orient_z = self.orient.z
        remaining_tiles: Set[Tuple[float, float, float]] = {
            (tile.pos + 64 * tile.normal // 128 * 128).as_tuple() for tile in tiles
            if tile.normal.z == orient_z
        }

        # A global RNG for picking clump positions.
        clump_rand = rand.seed(b'clump_pos')

        pos_min = Vec()
        pos_max = Vec()

        # For debugging, generate skip brushes with the shape of the clumps.
        debug_visgroup: Optional[VisGroup]
        if self.options['clump_debug']:
            debug_visgroup = vmf.create_visgroup(
                f'{self.category.name}_{self.orient.name}_{self.portal.name}'
            )
        else:
            debug_visgroup = None

        while remaining_tiles:
            # Pick from a random tile.
            tile_pos = next(itertools.islice(
                remaining_tiles,
                clump_rand.randrange(0, len(remaining_tiles)),
                len(remaining_tiles),
            ))
            remaining_tiles.remove(tile_pos)

            pos = Vec(tile_pos)

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

            remaining_tiles.difference_update(map(
                Vec.as_tuple,
                Vec.iter_grid(pos_min, pos_max, 128)
            ))

            self._clump_locs.append(Clump(
                pos_min.x, pos_min.y, pos_min.z,
                pos_max.x, pos_max.y, pos_max.z,
                # We use this to reseed an RNG, giving us the same textures
                # each time for the same clump.
                clump_rand.getrandbits(64).to_bytes(8, 'little'),
            ))
            if debug_visgroup is not None:
                # noinspection PyUnboundLocalVariable
                debug_brush: Solid = vmf.make_prism(
                    pos_min - 64,
                    pos_max + 64,
                    'tools/toolsskip',
                ).solid
                debug_brush.visgroup_ids.add(debug_visgroup.id)
                debug_brush.vis_shown = False
                vmf.add_brush(debug_brush)

        LOGGER.info(
            '{}.{}.{}: {} Clumps for {} tiles',
            self.category.name,
            self.orient.name,
            self.portal.name,
            len(self._clump_locs),
            len(tiles),
        )

    def _get(self, loc: Vec, tex_name: str) -> str:
        clump_seed = self._find_clump(loc)

        if clump_seed is None:
            # No clump found - return the gap texture.
            # But if the texture is GOO_SIDE, do that instead.
            # If we don't have a gap texture, just use any one.
            rng = rand.seed(b'tex_clump_side', loc)
            if tex_name == TileSize.GOO_SIDE or TileSize.CLUMP_GAP not in self:
                return rng.choice(self.textures[tex_name])
            else:
                return rng.choice(self.textures[TileSize.CLUMP_GAP])

        # Mix these three values together to determine the texture.
        # The clump seed makes each clump different, and adding the texture
        # name makes sure different surface types don't copy each other's
        # indexes.
        rng = rand.seed(b'tex_clump_side', self.gen_seed, tex_name, clump_seed)
        return rng.choice(self.textures[tex_name])

    def _find_clump(self, loc: Vec) -> Optional[bytes]:
        """Return the clump seed matching a location."""
        for clump in self._clump_locs:
            if (
                clump.x1 <= loc.x <= clump.x2 and
                clump.y1 <= loc.y <= clump.y2 and
                clump.z1 <= loc.z <= clump.z2
            ):
                return clump.seed
        return None
