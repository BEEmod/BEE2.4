"""Holds data about the contents of each grid position in the map.

"""
from collections import deque

from srctools import Vec, Vec_tuple, VMF
from enum import Enum

import srctools.logger
import bottomlessPit

from typing import Dict, Union, Set, Iterator, Tuple, Iterable


LOGGER = srctools.logger.get_logger(__name__)

# The attribute to set if these are in the map.
VOICE_ATTR_GOO = 'goo'
VOICE_ATTR_PIT = 'bottomless_pit'


def world_to_grid(pos: Vec) -> Vec:
    """Given real coordinates, find the grid position."""
    return pos // 128


def grid_to_world(pos: Vec) -> Vec:
    """Given a grid position, find the center of the real block."""
    return pos * 128 + (64, 64, 64)

w2g = world_to_grid
g2w = grid_to_world


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

    @classmethod
    def from_pitgoo_attr(cls, is_pit: bool, is_top: bool, is_bottom: bool):
        """Return the appropriate enum, based on bool parameters."""
        off = 20 if is_pit else 10
        if is_top:
            if is_bottom:
                return cls(off)  # Single
            else:
                return cls(off + 1)  # top
        elif is_bottom:
            return cls(off + 3)  # Bottom
        else:
            return cls(off + 2)  # Mid

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
    def is_solid(self):
        """Is this a solid brush? """
        return self.value in (1, 2)

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

# Keywords to a set of blocks.
BLOCK_LOOKUP = {
    block.name.casefold(): {block}
    for block in Block
}
BLOCK_LOOKUP['goo'] = {
    Block.GOO_SINGLE,
    Block.GOO_TOP,
    Block.GOO_MID,
    Block.GOO_BOTTOM,
}
BLOCK_LOOKUP['pit'] = {
    Block.PIT_SINGLE,
    Block.PIT_TOP,
    Block.PIT_MID,
    Block.PIT_BOTTOM,
}

_grid_keys = Union[Vec, Vec_tuple, tuple, slice]


class Grid(Dict[_grid_keys, Block]):
    """Mapping for grid positions.

    When doing lookups, the key can be prefixed with 'world': to treat
    as a world position.
    """

    @staticmethod
    def _conv_key(pos: _grid_keys) -> Vec_tuple:
        """Convert the key given in [] to a grid-position, as a x,y,z tuple."""
        if isinstance(pos, slice):
            system, pos = pos.start, pos.stop
            pos = Grid._conv_key(pos)
            if system == 'world':
                return tuple(world_to_grid(Vec(pos)))
            else:
                return pos
        x, y, z = pos
        return x, y, z

    def raycast(
        self,
        pos: _grid_keys,
        direction: Vec,
        collide: Set[Block]=frozenset({Block.SOLID, Block.EMBED, Block.PIT_BOTTOM, Block.PIT_SINGLE}),
    ) -> Vec:
        """Move in a direction until hitting a block of a certain type.

        This returns the position just before hitting a block (which might
        be the start position.)

        The direction vector should be integer numbers (1/0 usually).
        collide is the set of position types to stop at. The default is all
        "solid" walls.

        ValueError is raised if VOID is encountered, or this moves outside the
        map.
        """
        start_pos = pos = Vec(*self._conv_key(pos))
        direction = Vec(direction)
        collide = frozenset(collide)
        # 50x50x50 diagonal = 86, so that's the largest distance
        # you could possibly move.
        for i in range(90):
            next_pos = pos + direction
            block = super().get(next_pos.as_tuple(), Block.VOID)
            if block is Block.VOID:
                raise ValueError(
                    'Reached VOID at ({}) when '
                    'raycasting from {} with direction {}!'.format(
                        next_pos, start_pos, direction
                    )
                )
            if block in collide:
                return pos
            pos = next_pos
        else:
            raise ValueError('Moved too far! (> 90)')

    def raycast_world(
        self,
        pos: Vec,
        direction: Vec,
        collide: Set[Block]=frozenset({Block.SOLID, Block.EMBED, Block.PIT_BOTTOM, Block.PIT_SINGLE}),
    ) -> Vec:
        """Like raycast(), but accepts and returns world positions instead."""
        return g2w(self.raycast(w2g(pos), direction, collide))

    def __getitem__(self, pos: _grid_keys) -> Block:
        return super().get(self._conv_key(pos), Block.VOID)

    get = __getitem__

    def __setitem__(self, pos: _grid_keys, value: Block) -> None:
        if type(value) is not Block:
            raise ValueError('Must be set to a Block item, not "{}"!'.format(
                type(value).__name__,
            ))

        super().__setitem__(self._conv_key(pos), value)

    def __contains__(self, pos: _grid_keys) -> bool:
        return super().__contains__(self._conv_key(pos))

    def keys(self) -> Iterator[Vec]:
        yield from map(Vec, super().keys())

    def items(self) -> Iterator[Tuple[Vec, Block]]:
        for pos, block in super().items():
            yield Vec(pos), block

    def read_from_map(self, vmf: VMF, has_attr: Dict[str, bool]) -> None:
        """Given the map file, set blocks."""
        search_locs = []

        for ent in vmf.entities:
            pos = ent['origin', None]
            if pos is None:
                continue
            pos = world_to_grid(Vec.from_str(pos))

            # Exclude entities outside the main area - elevators mainly.
            # The border should never be set to air!
            if (0, 0, 0) <= pos <= (25, 25, 25):
                search_locs.append(pos)

        can_have_pit = bottomlessPit.pits_allowed()

        for brush in vmf.brushes[:]:
            tex = {face.mat.casefold() for face in brush.sides}

            bbox_min, bbox_max = brush.get_bbox()

            if ('nature/toxicslime_a2_bridge_intro' in tex or
                'nature/toxicslime_puzzlemaker_cheap' in tex):
                # It's goo!

                x = bbox_min.x + 64
                y = bbox_min.y + 64

                g_x = x // 128
                g_y = y // 128

                is_pit = can_have_pit and bottomlessPit.is_pit(bbox_min, bbox_max)

                # If goo is multi-level, we want to record all pos!
                z_pos = range(int(bbox_min.z) + 64, int(bbox_max.z), 128)
                top_ind = len(z_pos) - 1
                for ind, z in enumerate(z_pos):
                    g_z = z // 128
                    self[g_x, g_y, g_z] = Block.from_pitgoo_attr(
                        is_pit,
                        is_top=(ind == top_ind),
                        is_bottom=(ind == 0),
                    )
                    # If goo has totally submerged tunnels, they are not filled.
                    # Add each horizontal neighbour to the search list.
                    # If not found they'll be ignored.
                    if ind != top_ind: # Don't bother on the top level..
                        search_locs.extend([
                            (g_x - 1, g_y, g_z),
                            (g_x + 1, g_y, g_z),
                            (g_x, g_y + 1, g_z),
                            (g_x, g_y - 1, g_z),
                        ])

                # Bottomless pits don't use goo, so remove the water..
                if is_pit:
                    vmf.remove_brush(brush)

                # Indicate that this map contains goo/pits
                if is_pit:
                    has_attr[VOICE_ATTR_PIT] = True
                else:
                    has_attr[VOICE_ATTR_GOO] = True

                continue

            pos = world_to_grid(brush.get_origin(bbox_min, bbox_max))

            if bbox_max - bbox_min == (128, 128, 128):
                # Full block..
                self[pos] = Block.SOLID
            else:
                # Must be an embbedvoxel block
                self[pos] = Block.EMBED

        LOGGER.info(
            'Analysed map, filling air... ({} starting positions..)',
            len(search_locs)
        )
        self.fill_air(search_locs)
        LOGGER.info('Air filled!')

    def fill_air(self, search_locs: Iterable[Vec]):
        """Flood-fill the area, making all inside spaces air.

        This assumes the map is sealed.
        We start by assuming all instance positions are air.
        Since ambient_light ents are placed every 5 blocks, this should
        cover all playable space.
        """
        queue = deque(search_locs)  # type: deque[Union[Vec, Tuple[float, float, float]]]

        def iterdel() -> Iterator[Vec]:
            """Iterate as FIFO queue, deleting as we go."""
            try:
                while True:
                    yield Vec(queue.popleft())
            except IndexError:  # We're empty!
                return

        # This will iterate every item we add to the queue..
        for pos in iterdel():
            if pos in self:
                # Already set...
                continue

            # We got outside the map somehow?
            # There's a buffer region since large embedded areas may
            # be interpreted as small air pockets, that's fine.
            if not ((-15, -15, -15) <= pos <= (40, 40, 40)):
                LOGGER.warning('Attempted leak at {}', pos)
                continue

            self[pos] = Block.AIR
            x, y, z = pos
            # Continue filling in each other direction.
            queue.extend([
                (x, y + 1, z),
                (x, y - 1, z),
                (x + 1, y, z),
                (x - 1, y, z),
                (x, y, z + 1),
                (x, y, z - 1),
            ])

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
                pos=str(pos),
            )


# Grid position -> block mapping.
# Generally between (-1 -1 -1) and (26 26 26), but can be outside (embedded spaces).
# Unset spaces are assumed to be void.
POS = Grid()
