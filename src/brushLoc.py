"""Holds data about the contents of each grid position in the map.

"""
from collections import deque
from srctools import Vec, Vec_tuple, Property, Entity, VMF
from enum import Enum

import utils

from typing import Dict, Union

LOGGER = utils.getLogger(__name__)

def world_to_grid(pos: Vec):
    """Given real coordinates, find the grid position."""
    return pos // 128


def grid_to_world(pos: Vec):
    """Given a grid position, find the center of the real block."""
    pos * 128 + (64, 64, 64)


class Block(Enum):
    """Various contents categories for grid positions."""
    VOID = 0  # Outside the map
    SOLID = 1  # Occupied by a full-block brush
    EMBED = 2  # Occupied by EmbeddedVoxel brushes
    OCCUPIED = 3  # Manually set - air, but filled by some item...
    AIR = 4  # Inside the map

    GOO_SINGLE = 10  # 1-block high goo
    GOO_TOP = 11  # Top of goo
    GOO_MID = 12  # Middle of goo
    GOO_BOTTOM = 13  # Base of goo

    PIT_SINGLE = 20  # 1-block high bottomless pit
    PIT_TOP = 21  # Top of a bottomless pit
    PIT_MID = 22  # Middle of a bottomless pit
    PIT_BOTTOM = 23  # Base of a bottomless pit

    @property
    def inside_map(self):
        """Is this inside the map - will entities leak?"""
        return self.value > 1

    @property
    def traversable(self):
        """Is it possible for physics objects to be in this block?

        Embed is assumed to be solid.
        """
        return self.value > 3

    @property
    def is_goo(self):
        """Does this contain goo?"""
        return 10 <= self.value < 20

    @property
    def is_pit(self):
        """Is this a bottomless pit?"""
        return 20 <= self.value < 30

    @property
    def is_top(self):
        """Is this the top of goo or a bottomless pit?"""
        return self.value in (10, 11, 20, 21)

    @property
    def is_bottom(self):
        """Is this the base of goo or a bottomless pit?"""
        return self.value in (10, 13, 20, 23)

_grid_keys = Union[Vec, Vec_tuple, tuple]


class Grid(Dict[_grid_keys, Block]):
    """Mapping for grid positions."""

    def __getitem__(self, pos: _grid_keys):
        x, y, z = pos
        return super().get((x, y, z), Block.VOID)

    get = __getitem__

    def __setitem__(self, pos: _grid_keys, value: Block):
        if type(value) is not Block:
            raise ValueError('Must be set to a Block item!')

        x, y, z = pos
        super().__setitem__((x, y, z), value)

    def __contains__(self, pos: _grid_keys):
        x, y, z = pos
        return super().__contains__((x, y, z))

    def keys(self):
        yield from map(Vec, super().keys())

    def items(self):
        for pos, block in super.items():
            yield Vec(pos), block
    def dump_to_map(self, vmf: VMF):
        """Debug purposes: Dump the info as entities in the map.

        This makes the map effectively uncompilable...
        """
        # Icons which somewhat match the block type...
        block_icons = {
            Block.VOID: 'env_global',
            Block.SOLID: 'env_cubemap',
            Block.EMBED: 'func_instance_parms',
            Block.OCCUPIED: 'info_target',
            Block.AIR: 'info_null',

            Block.GOO_SINGLE: 'water_lod_control',
            Block.GOO_TOP: 'water_lod_control',
            Block.GOO_MID: 'water_lod_control',
            Block.GOO_BOTTOM: 'water_lod_control',

            Block.PIT_SINGLE: 'logic_autosave',
            Block.PIT_TOP: 'logic_autosave',
            Block.PIT_MID: 'logic_autosave',
            Block.PIT_BOTTOM: 'logic_autosave',
        }
        for pos, block in self.items():  # type: Vec, Block
            vmf.create_ent(
                targetname=block.name.title(),
                classname=block_icons[block],
                origin=grid_to_world(pos),
            )


# Grid position -> block mapping.
# Generally between (-1 -1 -1) and (26 26 26), but can be outside (embedded spaces).
# Unset spaces are assumed to be void.
POS = Grid()
