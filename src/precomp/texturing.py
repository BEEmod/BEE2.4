"""Manages the list of textures used for brushes, and how they are applied."""
from __future__ import annotations

from typing import ClassVar, TYPE_CHECKING, Any, Iterable

from collections.abc import Sequence
from pathlib import Path
from enum import Enum
import itertools
import abc

import attrs
import trio

from srctools import FrozenMatrix, FrozenVec, Keyvalues, Matrix, Vec, conv_bool
from srctools.game import Game
from srctools.tokenizer import TokenSyntaxError
from srctools.vmf import Entity, UVAxis, VisGroup, VMF, Side, Solid
from srctools.vmt import Material
import srctools.logger

from precomp import rand
from precomp.brushLoc import POS as BLOCK_TYPE
import consts
import utils

if TYPE_CHECKING:
    from precomp.tiling import TileDef

LOGGER = srctools.logger.get_logger(__name__)

# These can just be looked up directly.
SPECIAL: Generator
OVERLAYS: Generator


# Whether to use the new generator or not
NEW_TILE_GEN = False


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

    def __invert__(self) -> Portalable:
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

    @classmethod
    def from_normal(cls, norm: Vec | FrozenVec) -> Orient:
        """Find the orient matching this normal."""
        # Even if not axis-aligned, make mostly-flat surfaces
        # floor/ceiling (+-40 degrees)
        # sin(40) = ~0.707
        # So use 0.8.

        if norm.z > 0.8:
            return Orient.FLOOR
        elif norm.z < -0.8:
            return Orient.CEIL
        else:
            return Orient.WALL


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
ANTIGEL_MATS: dict[str, str] = {}
# The folder to add them to
ANTIGEL_PATH = 'BEE2/antigel/gen/'
# The center of each voxel containing an antigel marker.
# Surfaces inside here that aren't a voxel side will be converted.
ANTIGEL_LOCS: set[FrozenVec] = set()
# And then for each normal direction, if an antigel marker was defined there.
ANTIGEL_BY_NORMAL: dict[FrozenVec, set[FrozenVec]] = {
    FrozenVec.N: set(),
    FrozenVec.S: set(),
    FrozenVec.E: set(),
    FrozenVec.W: set(),
    FrozenVec.T: set(),
    FrozenVec.B: set(),
}

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
class QuarterRot(Enum):
    """Valid 90-degree rotation values."""
    NONE = 0
    CCW = 90
    HALF = 180
    CW = 270

    ROT_0 = 0
    ROT_90 = 90
    ROT_180 = 180
    ROT_270 = 270

    @classmethod
    def parse(cls, value: str) -> QuarterRot:
        """Parse a string into a rotation value."""
        try:
            angle = round(int(value))
        except (TypeError, ValueError, OverflowError):
            LOGGER.warning('Non-numeric rotation value "{}"!', value)
            return QuarterRot.NONE
        angle %= 360
        try:
            return cls(angle)
        except ValueError:
            LOGGER.warning('Rotation values must be multiples of 90 degrees, not {}!', angle)
            return QuarterRot.NONE

    def __add__(self, other: QuarterRot) -> QuarterRot:
        """Adding two rotations concatenates them."""
        return QuarterRot((self.value + other.value) % 360)

    @property
    def flips_uv(self) -> bool:
        """Returns if the horizontal/vertical directions have swapped."""
        return self.value in [90, 270]

    @property
    def mat_x(self) -> FrozenMatrix:
        """Return the matrix performing this rotation, around the X axis."""
        return FrozenMatrix.from_roll(self.value)

    @property
    def mat_y(self) -> FrozenMatrix:
        """Return the matrix performing this rotation, around the Y axis."""
        return FrozenMatrix.from_pitch(self.value)

    @property
    def mat_z(self) -> FrozenMatrix:
        """Return the matrix performing this rotation, around the Z axis."""
        return FrozenMatrix.from_yaw(self.value)


@utils.freeze_enum_props
class TileSize(str, Enum):
    """Types of textures that can exist, for tile-type generators."""
    TILE_1x1 = '1x1'  # Full block
    TILE_4x4 = '4x4'  # 1/4 of a block
    TILE_2x2 = '2x2'  # 1/2 of a block

    TILE_2x1 = '2x1'  # Two vertical
    TILE_1x2 = '1x2'  # Two horizontal

    TILE_1x4 = '1x4'  # Horizontal strip
    TILE_4x1 = '4x1'  # Vertical strip

    TILE_DOUBLE = 'double'  # 256x256 tile textures.

    CLUMP_GAP = 'gap'  # For clumping, spaces without a clump.

    GOO_SIDE = 'goo'  # For on sides of goo.

    def __str__(self) -> str: return self.value

    @property
    def size(self) -> tuple[int, int]:
        """Return the number of 32-size tiles this takes up."""
        if self.value in ('4x4', 'goo'):
            return 1, 1
        elif self.value in ('1x1', 'gap'):
            return 4, 4
        elif self.value == '2x2':
            return 2, 2
        elif self.value == '2x1':
            return 2, 4
        elif self.value == '1x2':
            return 4, 2
        elif self.value == '4x1':
            return 1, 4
        elif self.value == '1x4':
            return 4, 1
        elif self.value == 'double':
            return 8, 8
        raise AssertionError(self)

    @property
    def width(self) -> int:
        """Return the number of 32-size tiles this takes up, horizontally."""
        return self.size[0]

    @property
    def height(self) -> int:
        """Return the number of 32-size tiles this takes up, vertically."""
        return self.size[1]

    @property
    def is_rect(self) -> bool:
        """Return if this is a non-square shape."""
        width, height = self.size
        return width != height

    @property
    def rotated(self) -> TileSize:
        """Return the size when this is rotated 90 degrees."""
        if self is TileSize.TILE_1x2:
            return TileSize.TILE_2x1
        if self is TileSize.TILE_2x1:
            return TileSize.TILE_1x2

        if self is TileSize.TILE_1x4:
            return TileSize.TILE_4x1
        if self is TileSize.TILE_4x1:
            return TileSize.TILE_1x4
        return self


BOTTOM_TRIM_CHAR = {
    '1': TileSize.TILE_1x1,
    '2': TileSize.TILE_2x2,
    '4': TileSize.TILE_4x4,
}


@attrs.frozen
class MaterialConf:
    """Texture, rotation, scale to apply."""
    mat: str
    scale: float = 1.0
    rotation: QuarterRot = QuarterRot.NONE
    # If set, determines the maximum number of times this tile can be repeated before a new
    # one must be calculated.
    repeat_limit: int = 8
    # For tile materials, the original size of the surface.
    # This is used for aligning UVs correctly.
    tile_size: TileSize = TileSize.TILE_4x4

    @classmethod
    def parse(cls, kv: Keyvalues, tile_size: TileSize = TileSize.TILE_4x4) -> MaterialConf:
        """Parse a property block."""
        if not kv.has_children():
            return cls(kv.value,  tile_size=tile_size)
        try:
            material = kv['material']
        except LookupError:
            raise ValueError('Material definition must have "material" key!') from None
        scale = kv.float('scale', 1.0)
        if scale <= 0.0:
            LOGGER.warning('Material scale should be positive, not {}!', scale)
            scale = 1.0
        repeat_limit = kv.int('repeat', 8)
        if repeat_limit <= 0:
            LOGGER.warning('Material repeat limit should be positive, not {}!', repeat_limit)
            repeat_limit = 1
        try:
            rotation = QuarterRot.parse(kv['rotation'])
        except LookupError:
            rotation = QuarterRot.NONE
        return cls(material, scale, rotation, repeat_limit, tile_size)

    def __bool__(self) -> bool:
        """Blank materials are falsey."""
        return self.mat != ''

    def __str__(self) -> str:
        """Stringifying the MatConf produces the material."""
        return self.mat

    def apply(self, face: Side) -> None:
        """Apply the config to a brush face.
        This will overwrite the material, scale, and potentially rotate the face.
        For this reason the scale and offsets should be set first.
        """
        face.mat = self.mat
        uaxis, vaxis = face.uaxis, face.vaxis

        uaxis.scale *= self.scale
        vaxis.scale *= self.scale
        if self.rotation is not QuarterRot.NONE:
            u_axis, v_axis = uaxis.vec(), vaxis.vec()
            # Convert the offset values into an offset from the origin, then rotate.
            # We can then extract the new offset via u/v axis dotting.
            offset = u_axis * uaxis.offset + v_axis * vaxis.offset
            orient = Matrix.axis_angle(face.normal(), self.rotation.value)
            offset @= orient
            u_axis @= orient
            v_axis @= orient

            face.uaxis = UVAxis(u_axis.x, u_axis.y, u_axis.z, Vec.dot(offset, u_axis), uaxis.scale)
            face.vaxis = UVAxis(v_axis.x, v_axis.y, v_axis.z, Vec.dot(offset, v_axis), vaxis.scale)
            # Doesn't actually do anything, but makes Hammer look nicer.
            face.ham_rot = (face.ham_rot + self.rotation.value) % 360

    def apply_over(self, over: Entity) -> None:
        """Apply the config to an overlay."""
        over['material'] = self.mat
        # TODO: Rotation, scale

    def as_antigel(self) -> MaterialConf:
        """Return the antigel version of this material conf."""
        try:
            antigel_tex = ANTIGEL_MATS[self.mat.casefold()]
        except KeyError:
            LOGGER.warning('No antigel mat generated for {!r}!', self)
            # Set it to itself to silence the warning.
            ANTIGEL_MATS[self.mat.casefold()] = self.mat
            return self
        else:
            return attrs.evolve(self, mat=antigel_tex)

# Identifier for each generator.
type GenKey = GenCat | tuple[GenCat, Orient, Portalable]

GENERATORS: dict[GenKey, Generator] = {}

# The defaults for each generator.
# This also defines the texture names allowed, as well
# as the total number of generators.
TEX_DEFAULTS: dict[GenKey, dict[str, str | MaterialConf]] = {
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
    # If true, randomly rotate all tiles by adding 3 copies of each. True on floors/ceilings by default.
    'MixRotation': False,
    'Antigel_Bullseye': False,  # If true, allow bullseyes on antigel panels.
    'Algorithm': 'RAND',  # The algorithm to use for tiles.
    'BottomTrim': '',  # If set, 1/2/4 numbers to indicate tile sizes to force at the bottom of walls.

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
    (TileSize.TILE_4x4, TileSize.TILE_4x1),
    (TileSize.TILE_4x4, TileSize.TILE_1x4),
    (TileSize.TILE_2x2, TileSize.TILE_2x1),
    (TileSize.TILE_2x2, TileSize.TILE_1x2),
    (TileSize.TILE_2x1, TileSize.TILE_1x1),

    (TileSize.TILE_4x4, TileSize.GOO_SIDE),
]

DEFAULT_WEIGHTS = {
    TileSize.TILE_DOUBLE: 60,
    TileSize.TILE_1x1: 40,
    TileSize.TILE_2x1: 25,
    TileSize.TILE_1x2: 25,
    TileSize.TILE_2x2: 4,
    TileSize.TILE_4x1: 3,
    TileSize.TILE_1x4: 3,
    TileSize.TILE_4x4: 1,
    TileSize.GOO_SIDE: 1,
    TileSize.CLUMP_GAP: 1,
}


def format_gen_key(gen_key: GenCat | tuple[GenCat, Orient, Portalable]) -> str:
    """Convert the GenCat into a string for nice display."""
    if isinstance(gen_key, GenCat):
        return gen_key.value
    else:
        gen_cat, orient, portal = gen_key
        return f'{gen_cat.value}.{portal}.{orient}'


def parse_options(
    settings: dict[str, Any],
    global_settings: dict[str, Any],
    mix_rotation_default: bool = False,
) -> dict[str, Any]:
    """Parse the options for a generator block."""
    options = {}
    for opt, default in OPTION_DEFAULTS.items():
        opt = opt.casefold()
        # We want to change the default for this on ceilings/floors.
        if opt == 'mixrotation':
            default = mix_rotation_default
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


def gen(
    cat: GenCat,
    normal_or_orient: Orient | Vec | FrozenVec | None = None,
    portalable: Portalable | None = None,
    /,
) -> Generator:
    """Given a category, normal/orient, and white/black return the correct generator."""

    if cat is GenCat.SPECIAL or cat is GenCat.OVERLAYS:
        return GENERATORS[cat]

    if normal_or_orient is None:
        raise TypeError('Normal/Orient not provided!')

    if isinstance(normal_or_orient, Orient):
        orient = normal_or_orient
    else:
        orient = Orient.from_normal(normal_or_orient)

    if portalable is None:
        raise TypeError('Portalability not provided!')

    return GENERATORS[cat, orient, portalable]


def parse_name(name: str) -> tuple[Generator, str]:
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
    portalable: Portalable | None = None,
    normal: Orient | Vec | None = None,
    loc: Vec | None = None,
) -> None:
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

    generator.get(loc + face.normal(), tex_name).apply(face)


def load_config(conf: Keyvalues) -> None:
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

    # We put the configurations for each generator in here, before constructing them.
    all_options: dict[GenKey, dict[str, Any]] = {}
    all_weights: dict[GenKey, dict[TileSize, int]] = {}
    all_textures: dict[GenKey, dict[str, list[MaterialConf]]] = {}

    gen_cat: GenCat
    gen_orient: Orient | None
    gen_portal: Portalable | None

    # Use this to allow alternate names for generators.
    conf_for_gen: dict[
        tuple[GenCat, Orient | None, Portalable | None],
        Keyvalues,
    ] = {}

    # In the version adding the configuration for texturing, we made 1x2 a tile type
    # instead of an alias for 2x1. So check for the former, to see if we need to warn about
    # the latter change.
    has_block_mats = False

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
            if not has_block_mats and prop.has_children():
                for child in prop:
                    if child.name != 'options' and child.has_children():
                        has_block_mats = True
                        break
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
            is_ceil = False
            try:
                gen_conf = conf_for_gen[gen_key, None, None]
            except KeyError:
                gen_conf = Keyvalues(gen_key.value, [])
        else:
            # Tile-type generator
            is_tile = True
            try:
                gen_conf = conf_for_gen[gen_key]
            except KeyError:
                gen_conf = Keyvalues('', [])

            if not gen_conf.has_children():
                # Special case - using a single value to indicate that all
                # textures are the same.
                gen_conf = Keyvalues(gen_conf.real_name, [
                    Keyvalues('4x4', gen_conf.value),
                    Keyvalues('Options', [
                        # Clumping isn't useful since it's all the same.
                        Keyvalues('Algorithm', 'RAND'),
                    ])
                ])
            is_ceil = gen_key[1] is Orient.CEIL

        # First parse the options.
        all_options[gen_key] = parse_options({
            prop.name or '': prop.value
            for prop in
            gen_conf.find_children('Options')
        }, global_options, is_ceil)

        all_weights[gen_key] = weights = DEFAULT_WEIGHTS.copy()
        textures: dict[str, list[MaterialConf]] = {}
        tex_name: str
        all_textures[gen_key] = textures

        # Now do textures.
        if is_tile:
            # Tile generator, always have all tile sizes, and
            # only use the defaults if no textures were specified.
            tile_size: TileSize
            for tile_size in TileSize:
                textures[tile_size] = [
                    MaterialConf.parse(prop, tile_size) for prop in
                    gen_conf.find_all(str(tile_size))
                ]

            if '1x2' in gen_conf and not has_block_mats:
                LOGGER.warning('1x2 textures have changed to actually be two vertical tiles!')

            if NEW_TILE_GEN and TileSize.TILE_DOUBLE in textures and all_options[gen_key]['scaleup256']:
                # Reimplement this logic.
                textures[TileSize.TILE_DOUBLE] = [
                    attrs.evolve(conf, scale=conf.scale * 2) for conf in
                    textures[TileSize.TILE_DOUBLE]
                ]

            if all_options[gen_key]['mixrotation']:
                # Automatically rotate tiles.
                orig_defs: dict[TileSize, list[MaterialConf]] = {
                    tex_name: tex_list.copy()
                    for tex_name, tex_list in textures.items()
                    if isinstance(tex_name, TileSize)  # Always true.
                }
                for start_size, mat_list in orig_defs.items():
                    for rot in QuarterRot:
                        size = start_size.rotated if rot.flips_uv else start_size
                        for mat in mat_list:
                            textures[size].append(attrs.evolve(mat, rotation=mat.rotation + rot))

            # If not provided, use defaults. Otherwise, ignore them entirely.
            if not any(textures.values()):
                for tex_name, tex_default in tex_defaults.items():
                    assert isinstance(tex_name, TileSize), f'{tex_name}: {tex_default}'
                    # Use default scale/rotation.
                    textures[tex_name] = [
                        MaterialConf(tex_default, tile_size=tex_name)
                        if isinstance(tex_default, str) else tex_default
                    ]
            for subprop in gen_conf.find_children('weights'):
                try:
                    size = TileSize(subprop.name)
                except ValueError:
                    LOGGER.warning('Unknown tile size "{}"!', subprop.real_name)
                    continue
                try:
                    weights[size] = int(subprop.value)
                except (TypeError, ValueError, OverflowError):
                    LOGGER.warning(
                        'Invalid weight "{}" for size {}',
                        subprop.value, subprop.real_name,
                    )
        else:
            # Non-tile generator, use defaults for each value
            for tex_name, tex_default in tex_defaults.items():
                textures[tex_name] = tex = [
                    MaterialConf.parse(child) for child in
                    gen_conf.find_all(str(tex_name))
                ]
                if not tex and tex_default:
                    if isinstance(tex_default, str):
                        # Use default scale/rotation.
                        tex.append(MaterialConf(tex_default))
                    else:
                        tex.append(tex_default)

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
    for gen_key in TEX_DEFAULTS:
        if isinstance(gen_key, GenCat):
            continue
        gen_cat, gen_orient, gen_portal = gen_key

        textures = all_textures[gen_key]

        if not any(textures.values()) and gen_cat is not GenCat.NORMAL:
            # For the additional categories of tiles, we copy the entire
            # NORMAL one over if it's not set.
            for text_name, mat_list in all_textures[GenCat.NORMAL, gen_orient, gen_portal].items():
                textures[text_name] = mat_list.copy()

        if not textures[TileSize.TILE_4x4]:
            raise ValueError(f'No 4x4 tile set for "{gen_key}"!')

        # Copy all other textures to the 1x1 size if the option was set.
        # Do it before inheriting tiles, so there won't be duplicates.
        if all_options[gen_key]['mixtiles'] and not NEW_TILE_GEN:
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
        options = all_options[gen_key]
        weights = all_weights[gen_key]
        textures = all_textures[gen_key]
        generator: type[Generator]
        if isinstance(gen_key, tuple):
            # Check the algorithm to use.
            algo = options['algorithm']
            gen_cat, gen_orient, gen_portal = gen_key
            match algo.casefold():
                case 'rand':
                    generator = GenRandom
                case 'clump':
                    generator = GenClump
                case _:
                    raise ValueError(f'Invalid algorithm "{algo}" for {gen_key}!') from None
        else:
            # Signage, Overlays always use the Random generator.
            generator = GenRandom
            gen_cat = gen_key
            gen_orient = gen_portal = None

        GENERATORS[gen_key] = gentor = generator(gen_cat, gen_orient, gen_portal, options, weights, textures)

        # Allow it to use the default enums as direct lookups.
        if isinstance(gentor, GenRandom):
            if gen_portal is None:
                gentor.set_enum(tex_defaults.items())
            else:
                # Tiles always use TileSize.
                gentor.set_enum((size.value, size) for size in TileSize)

    SPECIAL = GENERATORS[GenCat.SPECIAL]
    OVERLAYS = GENERATORS[GenCat.OVERLAYS]


async def setup(game: Game, vmf: VMF, tiles: list[TileDef]) -> None:
    """Do various setup steps, needed for generating textures.

    - Set randomisation seed on all the generators.
    - Build clumps.
    - Generate antigel materials.
    """
    material_folder = (game.path / '..' / 'bee2' / 'materials').resolve()
    antigel_loc = material_folder / ANTIGEL_PATH
    antigel_loc.mkdir(parents=True, exist_ok=True)

    # Basetexture -> material name
    tex_to_antigel: dict[str, str] = {}
    # And all the filenames that exist already.
    antigel_mats: set[str] = set()

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
        mat_name = filename.relative_to(material_folder).with_suffix('').as_posix()
        texture: str | None = None
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
        antigel_mats.add(mat_name.casefold())

    async with trio.open_nursery() as nursery:
        # Parse the filesystems (importantly the VPKs) in the background while we check the existing
        # VMTs.
        fsys_res = utils.sync_result(nursery, game.get_filesystem)
        for vmt_file in antigel_loc.glob('*.vmt'):
            nursery.start_soon(check_existing, vmt_file)

    fsys = fsys_res.result()
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
                # We don't care about the configured scale/rotation, just the mat.
                for mat_conf in mats:
                    materials.add(mat_conf.mat)

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
        antigel_filename = antigel_loc / Path(texture)
        antigel_mat = Path(antigel_filename).relative_to(material_folder).with_suffix('').as_posix()
        if antigel_mat in antigel_mats:
            antigel_filename_base = antigel_filename.name.rstrip('0123456789')
            for i in itertools.count(1):
                antigel_filename = antigel_filename.with_name(f'{antigel_filename_base}{i:02}')
                antigel_mat = Path(antigel_filename).relative_to(material_folder).with_suffix('').as_posix()
                if antigel_mat not in antigel_mats:
                    break
        dest = trio.Path(antigel_filename.with_suffix('.vmt'))
        antigel_mats.add(antigel_mat)  # Do first, make sure nobody else claims!
        await dest.parent.mkdir(parents=True, exist_ok=True)
        await dest.write_text(ANTIGEL_TEMPLATE.format(
            path=texture,
            noportal=int(noportal),
        ))
        ANTIGEL_MATS[mat_name.casefold()] = tex_to_antigel[texture.casefold()] = antigel_mat
        ANTIGEL_MATS[antigel_mat.casefold()] = antigel_mat  # Make antigel conversion idempotent.

    async with trio.open_nursery() as nursery:
        for mat_name in materials:
            nursery.start_soon(generate_mat, mat_name)


class Generator(abc.ABC):
    """Base for different texture generators."""

    # The settings which apply to all generators.
    # Since they're here all subclasses and instances can access this.
    global_settings: ClassVar[dict[str, Any]] = {}
    bottom_trim_pattern: Sequence[TileSize]

    def __init__(
        self,
        category: GenCat,
        orient: Orient | None,
        portal: Portalable | None,
        options: dict[str, Any],
        weights: dict[TileSize, int],
        textures: dict[str, list[MaterialConf]],
    ) -> None:
        self.options = options
        self.textures = textures
        self.weights = weights

        # Tells us the category each generator matches to.
        self.category = category
        self.orient = orient
        self.portal = portal

        try:
            self.bottom_trim_pattern = [
                BOTTOM_TRIM_CHAR[char]
                for char in options['bottomtrim']
            ] or ()
        except KeyError:
            raise ValueError(f'Invalid bottom trim pattern "{options['bottomtrim']}"') from None

    def get(self, loc: FrozenVec | Vec, tex_name: str, *, antigel: bool | None = None) -> MaterialConf:
        """Get one texture for a position.

        If antigel is set, this is directly on a tile and so whether it's antigel
        is known.
        The location should be 1 unit back from the tile, so it'll be in the
        correct block.
        """
        grid_loc = FrozenVec(loc // 128)

        if antigel is None:
            antigel = grid_loc in ANTIGEL_LOCS
        if antigel and self.category is GenCat.BULLSEYE and not self.options['antigel_bullseye']:
            assert self.orient is not None and self.portal is not None
            # We can't use antigel on bullseye materials, so revert to normal
            # surfaces.
            return GENERATORS[GenCat.NORMAL, self.orient, self.portal].get(loc, tex_name, antigel=True)

        # Force blocks inside goo to goo side.
        if self.category is GenCat.NORMAL and self.orient is Orient.WALL and BLOCK_TYPE[grid_loc].is_goo:
            tex_name = TileSize.GOO_SIDE

        try:
            mat_conf = self._get(loc, tex_name)
        except KeyError as exc:
            raise self._missing_error(repr(exc.args[0])) from None
        return mat_conf.as_antigel() if antigel else mat_conf

    def setup(self, vmf: VMF, tiles: list[TileDef]) -> None:
        """Scan tiles in the map and set up the generator."""
        return None  # Deliberately non-abstract.

    def _missing_error(self, tex_name: str) -> Exception:
        return ValueError(f'Bad texture name: {tex_name}\n Allowed: {list(self.textures.keys())!r}')

    @abc.abstractmethod
    def _get(self, loc: Vec | FrozenVec, tex_name: str, /) -> MaterialConf:
        """Actually get a texture.

        If KeyError is raised, an appropriate exception is raised from that.
        """

    def get_all(self, tex_name: str, antigel: bool) -> Sequence[MaterialConf]:
        """Return all the textures possible for a given name."""
        if antigel and self.category is GenCat.BULLSEYE and not self.options['antigel_bullseye']:
            assert self.orient is not None and self.portal is not None
            # We can't use antigel on bullseye materials, so revert to normal surfaces.
            return GENERATORS[GenCat.NORMAL, self.orient, self.portal].get_all(tex_name, True)

        try:
            mat_confs = self.textures[tex_name]
        except KeyError:
            raise self._missing_error(tex_name) from None
        if antigel:
            return [
                conf.as_antigel()
                for conf in mat_confs
            ]
        return mat_confs

    def __contains__(self, tex_name: str) -> bool:
        """Return True if the texture is defined."""
        try:
            return bool(self.textures[tex_name])
        except KeyError:
            return False


class GenRandom(Generator):
    """Basic random generator.

    Each texture will be randomly chosen whenever asked.
    This is used for Overlay and Signage as well.
    """
    def __init__(
        self,
        category: GenCat,
        orient: Orient | None,
        portal: Portalable | None,
        options: dict[str, Any],
        weights: dict[TileSize, int],
        textures: dict[str, list[MaterialConf]],
    ) -> None:
        super().__init__(category, orient, portal, options, weights, textures)
        # For enum constants, use the id() to lookup - this
        # way we're effectively comparing by identity.
        self.enum_data: dict[int, str] = {}

    def set_enum(self, defaults: Iterable[tuple[str, MaterialConf | str]]) -> None:
        """For OVERLAY and SPECIAL, allow also passing in the enum constants."""
        for key, default in defaults:
            if isinstance(default, MaterialConf):
                default = default.mat
            if type(default) is not str:
                self.enum_data[id(default)] = key

    def _get(self, loc: Vec | FrozenVec, tex_name: str) -> MaterialConf:
        if type(tex_name) is not str:
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


class GenClump(Generator):
    """The clumping generator for tiles.

    This creates groups of the same texture in roughly rectangular sections.
    """
    def __init__(
        self,
        category: GenCat,
        orient: Orient | None,
        portal: Portalable | None,
        options: dict[str, Any],
        weights: dict[TileSize, int],
        textures: dict[str, list[MaterialConf]],
    ) -> None:
        super().__init__(category, orient, portal, options, weights, textures)

        # A seed only unique to this generator.
        self.gen_seed = b''
        self._clump_locs: list[Clump] = []

    def setup(self, vmf: VMF, tiles: list[TileDef]) -> None:
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
        remaining_tiles: set[FrozenVec] = {
            (tile.pos + 64 * tile.normal // 128 * 128).freeze() for tile in tiles
            if tile.normal.z == orient_z
        }

        # A global RNG for picking clump positions.
        clump_rand = rand.seed(b'clump_pos')

        pos_min = Vec()
        pos_max = Vec()

        # For debugging, generate skip brushes with the shape of the clumps.
        debug_visgroup: VisGroup | None
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
                None,
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

            remaining_tiles.difference_update(FrozenVec.iter_grid(pos_min, pos_max, 128))

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

    def _get(self, loc: Vec | FrozenVec, tex_name: str) -> MaterialConf:
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

    def _find_clump(self, loc: Vec | FrozenVec) -> bytes | None:
        """Return the clump seed matching a location."""
        for clump in self._clump_locs:
            if (
                clump.x1 <= loc.x <= clump.x2 and
                clump.y1 <= loc.y <= clump.y2 and
                clump.z1 <= loc.z <= clump.z2
            ):
                return clump.seed
        return None
