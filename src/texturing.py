"""Manages the list of textures used for brushes, and how they are applied."""
from enum import Enum

import random

from srctools import Property
import comp_consts as consts

from typing import Dict, List, Tuple, Union, Optional, Iterable

import utils


GROUPS = {}

LOGGER = utils.getLogger(__name__)


class TexCat(Enum):
    TILE_1x1 = 0  # Full block
    TILE_4x4 = 1  # 1/4 of a block
    TILE_2x2 = 2  # 1/2 of a block
    TILE_2x1 = 3  # Two vertical

    CLUMP_GAP = 5  # For clumping, spaces without a clump.

    SPECIAL_1x1 = 10  # Checkered or similar, full block
    SPECIAL_4x4 = 11  # Checkered variant, always 4x4
    BULLSEYE = 11  # With integrated bullseye decal - must match 4x4 texture.
    GOO_SIDE = 12  # For on sides of goo - invalid for roof..


class TextureGroup:
    """Generic group of textures - special or overlay."""

    def __init__(
        self, group: str,
        *textures: Iterable[Union[str, Tuple[str, Optional[str]]]]
    ):
        self.group = group

        self.default = {}  # type: Dict[str, List[str]]
        self.tex = {}  # type: Dict[str, List[str]]

        for name in textures:
            default = None
            if isinstance(name, tuple):
                name, default = name
            if default is not None:
                self.default[name] = [str(default)]
            else:
                self.default[name] = []

        GROUPS[group] = self

    def read_from_props(self, props: Property):
        """Given the property block, read in values from items."""
        self.tex.clear()
        self.tex.update(
            (str(name).casefold(), [])
            for name in self.default.keys()
        )

        for prop in props:
            try:
                group = self.tex[prop.name]
            except KeyError:
                LOGGER.warning('Unknown texture type {}.{}!',
                               self.group,
                               prop.name,
                               )
                continue
            if prop.has_children():
                LOGGER.warning("Can't have children on texture defs!")
                continue

            group.append(prop.value)

        for name, value in self.tex.items():
            if not value:
                def_value = self.default[name]
                if def_value:
                    self.tex[name] = def_value.copy()

    def __contains__(self, name):
        """Check if a given texture def has textures set."""
        try:
            return bool(self.tex[name])
        except KeyError:
            raise KeyError('No texture def for "{}.{}"!'.format(
                self.group,
                name,
            ))

    def all(self, name):
        """Returns all the textures for a given name."""
        if name in self:
            return self.tex[name].copy()
        else:
            return []

    def rand(self, name, rand: random.Random=random) -> str:
        """Return one texture from a value. """
        if name in self:
            return rand.choice(self.tex[name])
        else:
            raise ValueError(
                'Tried to get texture from "{}.{}", but none exist!'.format(
                    self.group, name,
                )
            )


class TileGroup(TextureGroup):
    """A group of sized tile textures for a colour and orientation."""
    def __init__(
        self,
        color,
        orient,
        tex_1x1=None,
        tex_2x2=None,
        tex_2x1=None,
        tex_4x4=None,
        tex_goo=None,
    ):
        super().__init__(
            color + '.' + orient,
            (TexCat.TILE_1x1, tex_1x1),
            (TexCat.TILE_2x2, tex_2x2),
            (TexCat.TILE_2x1, tex_2x1),
            (TexCat.TILE_4x4, tex_4x4),
            TexCat.BULLSEYE,
            TexCat.CLUMP_GAP,
            TexCat.SPECIAL_1x1,
            (TexCat.SPECIAL_4x4, tex_4x4),
            TexCat.BULLSEYE,
            (TexCat.GOO_SIDE, tex_goo),
        )


# Default texture definitions.

black_floor = TileGroup(
    'black', 'floor',
    tex_4x4=consts.BlackPan.BLACK_FLOOR,
    tex_goo=consts.BlackPan.BLACK_4x4,
)

black_ceil = TileGroup(
    'black', 'ceiling',
    tex_4x4=consts.BlackPan.BLACK_FLOOR,
)

black_wall = TileGroup(
    'black', 'wall',
    
    tex_1x1=consts.BlackPan.BLACK_1x1,
    tex_2x1=consts.BlackPan.BLACK_2x1,
    tex_2x2=consts.BlackPan.BLACK_2x2,
    tex_4x4=consts.BlackPan.BLACK_4x4,
    tex_goo=consts.BlackPan.BLACK_4x4,
)

white_floor = TileGroup(
    'white', 'floor',
    tex_4x4=consts.WhitePan.WHITE_FLOOR,
    tex_2x2=consts.WhitePan.WHITE_FLOOR,
    tex_1x1=consts.WhitePan.WHITE_FLOOR,
)

white_ceil = TileGroup(
    'white', 'ceiling',
    tex_4x4=consts.WhitePan.WHITE_4x4,
    tex_2x2=consts.WhitePan.WHITE_4x4,
    tex_1x1=consts.WhitePan.WHITE_4x4,
)

white_wall = TileGroup(
    'white', 'wall',
    
    tex_1x1=consts.WhitePan.WHITE_1x1,
    tex_2x1=consts.WhitePan.WHITE_2x1,
    tex_2x2=consts.WhitePan.WHITE_2x2,
    tex_4x4=consts.WhitePan.WHITE_4x4,
)

overlay = TextureGroup(
    'overlay',
    
    ('exit', consts.Signage.EXIT),
    ('arrow', consts.Signage.ARROW),
    ('dot', consts.Signage.SHAPE_DOT),
    ('moon', consts.Signage.SHAPE_MOON),
    ('triangle', consts.Signage.SHAPE_TRIANGLE),
    ('cross', consts.Signage.SHAPE_CROSS),
    ('square', consts.Signage.SHAPE_SQUARE),
    ('circle', consts.Signage.SHAPE_CIRCLE),
    ('sine', consts.Signage.SHAPE_SINE),
    ('slash', consts.Signage.SHAPE_SLASH),
    ('star', consts.Signage.SHAPE_STAR),
    ('wavy', consts.Signage.SHAPE_WAVY),

    # Special additional scale information...
    ('antline', '0.25|' + consts.Antlines.STRAIGHT),
    ('antlinecorner', '1|' + consts.Antlines.CORNER),

    # This is for the P1 style, where antlines use different textures
    # on the floor and wall.
    # We just use the regular version if unset.
    'antlinecornerfloor',
    'antlinefloor',

    # Broken version of antlines
    'antlinebroken',
    'antlinebrokencorner',
    'antlinebrokenfloor',
    'antlinebrokenfloorcorner',
)

special = TextureGroup(
    'special',
    
    ('behind', consts.Special.BACKPANELS_CHEAP),
    ('pedestalside', consts.Special.PED_SIDE),
    ('edge', consts.Special.SQUAREBEAMS),
    'edge_special',
    ('goo', consts.Goo.REFLECTIVE),
    ('goo_cheap', consts.Goo.CHEAP),
    ('glass', consts.Special.GLASS),
    ('grating', consts.Special.GRATING),
    ('laserfield', consts.Special.LASERFIELD),
    ('sky', "sky_black"),

    'fizz_border',
)
