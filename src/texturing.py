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


class Generator(abc.ABC):
    """Base for different texture generators."""
    def __init__(self):
        self._random = random.Random()

    def seed(self, seed):
        """Seed the RNG with some value."""
        self._random.seed(seed)

    def get_one(self, loc: Vec, tex_name: str) -> str:
        """Get one texture for a position."""
        loc = loc // 128
        loc *= 128
        loc += (64, 64, 64)

        return self._get(loc, tex_name)

    @abc.abstractmethod
    def _get(self, loc: Vec, tex_name: str) -> str:
        """Actually get a texture."""
