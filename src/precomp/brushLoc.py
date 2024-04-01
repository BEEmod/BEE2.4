"""Holds data about the contents of each grid position in the map.

"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from collections import deque
from typing import TypeVar, Union, Any, Tuple, ItemsView, MutableMapping
from enum import Enum

from srctools import FrozenVec, Vec, Matrix, VMF

import srctools.logger
from typing_extensions import Self

import user_errors
import utils
import editoritems


LOGGER = srctools.logger.get_logger(__name__)

# The attribute to set if these are in the map.
VOICE_ATTR_GOO = 'goo'
VOICE_ATTR_PIT = 'bottomless_pit'
VecT = TypeVar("VecT", Vec, FrozenVec)


def world_to_grid(pos: VecT) -> VecT:
    """Given real coordinates, find the grid position."""
    return pos // 128


def grid_to_world(pos: VecT) -> VecT:
    """Given a grid position, find the center of the real block."""
    return pos * 128 + (64, 64, 64)

w2g = world_to_grid
g2w = grid_to_world


@utils.freeze_enum_props
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
    def from_pitgoo_attr(cls, is_pit: bool, is_top: bool, is_bottom: bool) -> Self:
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
    def inside_map(self) -> bool:
        """Is this inside the map main map?"""
        return self.value > 2

    @property
    def traversable(self) -> bool:
        """Is it possible for physics objects to be in this block?

        Embed is assumed to be solid.
        """
        return self.value > 3

    @property
    def is_solid(self) -> bool:
        """Is this a solid brush? """
        return self.value in (1, 2)

    @property
    def is_goo(self) -> bool:
        """Does this contain goo?"""
        return 10 <= self.value < 20

    @property
    def is_pit(self) -> bool:
        """Is this a bottomless pit?"""
        return 20 <= self.value < 30

    @property
    def is_top(self) -> bool:
        """Is this the top of goo or a bottomless pit?"""
        return self.value in (10, 11, 20, 21)

    @property
    def is_bottom(self) -> bool:
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


_grid_keys = Union[Vec, FrozenVec, Tuple[float, float, float], slice]


def _conv_key(pos: _grid_keys) -> FrozenVec:
    """Convert the key given in [] to a grid-position, as an x,y,z tuple."""
    # TODO: Slices are assumed to be int by typeshed.
    system: str
    slice_pos: Vec | FrozenVec
    if isinstance(pos, slice):
        system, slice_pos = pos.start, pos.stop
        if system == 'world':
            return world_to_grid(FrozenVec(slice_pos))
        else:
            return FrozenVec(slice_pos)
    return FrozenVec(pos)


class _GridItemsView(ItemsView[FrozenVec, Block]):
    """Implements the Grid.items() view, providing a view over the pos, block pairs."""
    # Initialised by superclass.
    _mapping: dict[FrozenVec, Block]
    def __init__(self, grid: dict[FrozenVec, Block]) -> None:
        super().__init__(grid)

    def __contains__(self, item: Any) -> bool:
        pos, block = item
        try:
            return block is self._mapping[_conv_key(pos)]
        except KeyError:
            return False

    def __iter__(self) -> Iterator[tuple[FrozenVec, Block]]:
        yield from self._mapping.items()


class Grid(MutableMapping[_grid_keys, Block]):
    """Mapping for grid positions.

    When doing lookups, the key can be prefixed with 'world': to treat
    as a world position.
    """
    def __init__(self) -> None:
        self._grid: dict[FrozenVec, Block] = {}

    def raycast(
        self,
        pos: _grid_keys,
        direction: Vec | FrozenVec | Tuple[int, int, int],
        collide: Iterable[Block]=frozenset({
            Block.SOLID, Block.EMBED,
            Block.PIT_BOTTOM, Block.PIT_SINGLE,
        }),
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
        start_pos = pos = Vec(*_conv_key(pos))
        direction_v = Vec(direction)
        collide_set = frozenset(collide)
        # 50x50x50 diagonal = 86, so that's the largest distance
        # you could possibly move.
        for _ in range(90):
            next_pos = pos + direction_v
            block = super().get(next_pos.freeze(), Block.VOID)
            if block is Block.VOID:
                raise ValueError(
                    f'Reached VOID at ({next_pos}) when raycasting from {start_pos} with '
                    f'direction {direction_v}!'
                )
            if block in collide_set:
                return pos
            pos = next_pos
        # We should always hit VOID at some point before this.
        raise ValueError('Moved too far! (> 90)')

    def raycast_world(
        self,
        pos: Vec,
        direction: Vec | Tuple[int, int, int],
        collide: Iterable[Block]=frozenset({
            Block.SOLID, Block.EMBED,
            Block.PIT_BOTTOM, Block.PIT_SINGLE,
        }),
    ) -> Vec:
        """Like raycast(), but accepts and returns world positions instead."""
        return g2w(self.raycast(w2g(pos), direction, collide))

    def lookup_world(self, pos: Iterable[float]) -> Block:
        """Lookup a world position."""
        return self._grid.get(world_to_grid(FrozenVec(pos)), Block.VOID)

    def __getitem__(self, pos: _grid_keys) -> Block:
        return self._grid.get(_conv_key(pos), Block.VOID)

    def __setitem__(self, pos: _grid_keys, value: Block) -> None:
        if type(value) is not Block:
            raise ValueError(f'Must be set to a Block item, not "{type(value).__name__}"!')

        self._grid[_conv_key(pos)] = value

    def set_world(self, pos: Iterable[float], value: Block) -> None:
        """Set a world position."""
        if type(value) is not Block:
            raise ValueError(f'Must be set to a Block item, not "{type(value).__name__}"!')

        self._grid[world_to_grid(FrozenVec(pos))] = value

    def __delitem__(self, pos: _grid_keys) -> None:
        del self._grid[_conv_key(pos)]

    def __contains__(self, pos: object) -> bool:
        try:
            coords = _conv_key(pos)  # type: ignore
        except (TypeError, ValueError):
            return False
        return coords in self._grid

    def __iter__(self) -> Iterator[FrozenVec]:
        yield from self._grid

    def __len__(self) -> int:
        return len(self._grid)

    def items(self) -> _GridItemsView:
        """Return a view over the grid items."""
        return _GridItemsView(self._grid)

    def read_from_map(self, vmf: VMF, items: dict[utils.ObjectID, editoritems.Item]) -> set[str]:
        """Given the map file, set blocks. This returns some voice attributes that may be set."""
        from precomp.instance_traits import get_item_id
        from precomp import bottomlessPit

        # Starting points to fill air and goo.
        # We want to fill goo first...
        air_search_locs: list[tuple[Vec, bool]] = []
        goo_search_locs: list[tuple[Vec, bool]] = []

        has_attr: set[str] = set()

        for ent in vmf.entities:
            str_pos = ent['origin', None]
            if str_pos is None:
                continue

            pos = world_to_grid(Vec.from_str(str_pos))

            # Exclude entities outside the main area - elevators mainly.
            # The border should never be set to air!
            if not ((0, 0, 0) <= pos <= (25, 25, 25)):
                continue

            # We need to manually set EmbeddedVoxel locations.
            # These might not be detected for items where there's a block
            # which is entirely empty - corridors and obs rooms for example.
            # We also need to check occupy locations, so that it can seed search
            # locs.
            item_id = get_item_id(ent)
            seeded = False
            if item_id:
                try:
                    item = items[utils.obj_id(item_id)]
                except KeyError:
                    pass
                else:
                    orient = Matrix.from_angstr(ent['angles'])
                    for local_pos in item.embed_voxels:
                        # Offset down because 0 0 0 is the floor voxel.
                        world_pos = (Vec(local_pos) - (0, 0, 1)) @ orient + pos
                        self[round(world_pos, 0)] = Block.EMBED
                    for occu in item.occupy_voxels:
                        world_pos = Vec(occu.pos) @ orient + pos
                        air_search_locs.append((round(world_pos, 0), False))
                        seeded = True
            if not seeded:
                # Assume origin is its location.
                air_search_locs.append((pos.copy(), False))

        can_have_pit = bottomlessPit.pits_allowed()

        for brush in vmf.brushes[:]:
            tex = {face.mat.casefold() for face in brush.sides}

            bbox_min, bbox_max = brush.get_bbox()

            if (
                'nature/toxicslime_a2_bridge_intro' in tex or
                'nature/toxicslime_puzzlemaker_cheap' in tex
            ):
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
                    goo_search_locs += [
                        (Vec(g_x - 1, g_y, g_z), True),
                        (Vec(g_x + 1, g_y, g_z), True),
                        (Vec(g_x, g_y + 1, g_z), True),
                        (Vec(g_x, g_y - 1, g_z), True),
                    ]

                # Remove the brush, since we're not going to use it.
                vmf.remove_brush(brush)

                # Indicate that this map contains goo/pits
                if is_pit:
                    has_attr.add(VOICE_ATTR_PIT)
                else:
                    has_attr.add(VOICE_ATTR_GOO)

                continue

            pos = world_to_grid(brush.get_origin(bbox_min, bbox_max))

            if bbox_max - bbox_min == (128, 128, 128):
                # Full block...
                self[pos] = Block.SOLID
            else:
                # Must be an embbedvoxel block
                self[pos] = Block.EMBED

        LOGGER.info(
            'Analysed map, filling air... ({} starting positions..)',
            len(air_search_locs)
        )
        self.fill_air(goo_search_locs + air_search_locs)
        LOGGER.info('Air filled!')
        return has_attr

    def fill_air(self, search_locs: Iterable[tuple[Vec, bool]]) -> None:
        """Flood-fill the area, making all inside spaces air or goo.

        This assumes the map is sealed.
        We start by assuming all instance positions are air.
        Since ambient_light ents are placed every 5 blocks, this should
        cover all playable space.

        This will also fill the submerged tunnels with goo.
        """
        queue: deque[tuple[Vec, bool]] = deque(search_locs)

        def iterdel() -> Iterator[tuple[Vec, bool]]:
            """Iterate as FIFO queue, deleting as we go."""
            try:
                while True:
                    yield queue.popleft()
            except IndexError:  # We're empty!
                return

        # Air pockets need to be filled, and bottomless pits.
        # Otherwise we could have those appearing next to real goo pits,
        # with complicated room heights.
        goo_fillable = [
            Block.AIR,
            Block.OCCUPIED,
            Block.PIT_BOTTOM,
            Block.PIT_MID,
            Block.PIT_TOP,
            Block.PIT_SINGLE,
        ]

        # This will iterate every item we add to the queue..
        for pos, is_goo in iterdel():
            # Already set. But allow the goo to fill certain types.
            if pos in self and not (is_goo and self[pos] in goo_fillable):
                continue

            # We got outside the map somehow?
            # There's a buffer region since large embedded areas may
            # be interpreted as small air pockets, that's fine.
            if not ((-15, -15, -15) <= pos <= (40, 40, 40)):
                # We're too early to actually visualise anything.
                raise user_errors.UserError(user_errors.TOK_BRUSHLOC_LEAK)

            # For go we need to determine which kind to use.
            # We only fill from underneath the surface, so
            # use "mid" even for toplevel pits.
            if is_goo:
                if self[pos].is_pit:
                    self[pos] = Block.from_pitgoo_attr(
                        False,
                        self[pos].is_top,
                        self[pos].is_bottom,
                    )
                elif self[pos.x, pos.y - 1, pos.z].is_solid:
                    self[pos] = Block.GOO_BOTTOM
                else:
                    self[pos] = Block.GOO_MID
            else:
                self[pos] = Block.AIR

            x, y, z = pos
            # Continue filling in each other direction.
            # But not up for goo.
            if not is_goo:
                queue.append((Vec(x, y, z + 1), is_goo))
            queue.append((Vec(x, y + 1, z), is_goo))
            queue.append((Vec(x, y - 1, z), is_goo))
            queue.append((Vec(x + 1, y, z), is_goo))
            queue.append((Vec(x - 1, y, z), is_goo))
            queue.append((Vec(x, y, z - 1), is_goo))

    def dump_to_map(self, vmf: VMF) -> None:
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
        for pos, block in self.items():
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
