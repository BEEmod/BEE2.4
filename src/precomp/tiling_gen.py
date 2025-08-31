"""Logic for generating the overall map geometry."""
from __future__ import annotations
from typing import Literal

from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
import functools
import itertools

from srctools import Angle, Entity, VMF, Vec, logger, FrozenVec
import attrs

import utils
from plane import PlaneGrid, PlaneKey
from precomp import rand, texturing, brushLoc
from precomp.texturing import MaterialConf, Orient, Portalable, TileSize
from precomp.tiling import TILES, TileDef, TileType, Bevels, make_tile
import consts


LOGGER = logger.get_logger(__name__)
DEBUG = False
PLANE_NAMES = {
    FrozenVec(-1, 0, 0): 'w',
    FrozenVec(+1, 0, 0): 'e',
    FrozenVec(0, +1, 0): 'n',
    FrozenVec(0, -1, 0): 's',
    FrozenVec(0, 0, +1): 'f',
    FrozenVec(0, 0, -1): 'c',
}


def make_bevel_char(flag: Bevels) -> tuple[str, str]:
    """Generate box drawing characters to represent bevel patterns."""
    if Bevels.north in flag:
        ul = '╔' if Bevels.west in flag else '╒'
    else:
        ul = '╓' if Bevels.west in flag else '┌'
    if Bevels.north in flag:
        ur = '╗' if Bevels.east in flag else '╕'
    else:
        ur = '╖' if Bevels.east in flag else '┐'

    if Bevels.south in flag:
        ll = '╚' if Bevels.west in flag else '╘'
    else:
        ll = '╙' if Bevels.west in flag else '└'

    if Bevels.south in flag:
        lr = '╝' if Bevels.east in flag else '╛'
    else:
        lr = '╜' if Bevels.east in flag else '┘'

    return (ul + ur, ll + lr)


BEVEL_CHAR = {
    bevel: make_bevel_char(bevel)
    for bevel in map(Bevels, range(0, 0b1111 + 1))
}


@attrs.frozen
class SubTile:
    """The state of a single 32x32 tile in a plane."""
    type: TileType
    antigel: bool


@attrs.frozen
class TexDef:
    """The information required to create the surface of a material."""
    tex: MaterialConf
    antigel: bool = False
    u_off: float = 0.0
    v_off: float = 0.0
    scale: float = 0.25  # 0.25 or 0.5 for double.


# We're making huge numbers of these, cache them.
make_subtile = functools.lru_cache(maxsize=None)(SubTile)
make_texdef = functools.lru_cache(maxsize=64)(TexDef)
TEXDEF_NODRAW = TexDef(MaterialConf(consts.Tools.NODRAW))

# Each bevel and the corresponding offset.
BEVEL_OFFSETS: list[tuple[Bevels, Literal[-1, 0, +1], Literal[-1, 0, +1]]] = [
    (Bevels.u_min, -1, 0),
    (Bevels.u_max, +1, 0),
    (Bevels.v_min, 0, -1),
    (Bevels.v_max, 0, +1),
]


@attrs.define
class Tideline:
    """Temporary data used to hold the in-progress tideline overlays."""
    over: Entity
    mid: float
    min: float
    max: float


@attrs.frozen
class TrimColour:
    """Used to allow pattern matching."""
    tile_1x1: TileType
    tile_4x4: TileType


TRIM_COLOURS = [
    TrimColour(TileType.WHITE, TileType.WHITE_4x4),
    TrimColour(TileType.BLACK, TileType.BLACK_4x4),
]

# The TileSize values each type can pick from - first is the match, plus alts.
tile_chain = [
    TileSize.TILE_DOUBLE, TileSize.TILE_1x1,
    TileSize.TILE_1x2, TileSize.TILE_2x1,
    TileSize.TILE_2x2,
    TileSize.TILE_1x4, TileSize.TILE_4x1,
    TileSize.TILE_4x4,
]
ALLOWED_SIZES: dict[TileType, list[TileSize]] = {
    TileType.WHITE: tile_chain,
    TileType.BLACK: tile_chain,

    TileType.WHITE_4x4: [TileSize.TILE_4x4],
    TileType.BLACK_4x4: [TileSize.TILE_4x4],
    TileType.GOO_SIDE_WHITE: [TileSize.GOO_SIDE],
    TileType.GOO_SIDE_BLACK: [TileSize.GOO_SIDE],
}


def bevel_split(
    texture_plane: PlaneGrid[TexDef],
    dump_path: Path | None,
    tile_pos: PlaneGrid[TileDef],
    orig_tiles: PlaneGrid[SubTile],
) -> Iterator[tuple[int, int, int, int, Bevels, TexDef]]:
    """Split the optimised segments to produce the correct bevelling."""
    bevels: PlaneGrid[Bevels] = PlaneGrid(default=Bevels.none)

    total_mins_u, total_mins_v = texture_plane.mins
    total_maxs_u, total_maxs_v = texture_plane.maxes

    # Iterate over every TileDef, apply bevels due to those.
    subtile_range = range(4)
    for u, v in itertools.product(
        range(total_mins_u, total_maxs_u + 1, 4),
        range(total_mins_v, total_maxs_v + 1, 4),
    ):
        try:
            tile = tile_pos[u, v]
        except KeyError:
            # This 4x4 tile is not present.
            continue
        min_u = u // 4 * 4
        min_v = v // 4 * 4
        # These are sort of reversed around, which is a little confusing.
        # Bevel U is facing in the U direction, running across the V.
        if tile.should_bevel(-1, 0):
            for off in subtile_range:
                bevels[min_u, min_v + off] |= Bevels.u_min
        if tile.should_bevel(+1, 0):
            for off in subtile_range:
                bevels[min_u + 3, min_v + off] |= Bevels.u_max
        if tile.should_bevel(0, -1):
            for off in subtile_range:
                bevels[min_u + off, min_v] |= Bevels.v_min
        if tile.should_bevel(0, +1):
            for off in subtile_range:
                bevels[min_u + off, min_v + 3] |= Bevels.v_max

    # Iterate every tile, apply bevels from neighbours.
    for (u, v), texdef in texture_plane.items():
        for bevel, off_u, off_v in BEVEL_OFFSETS:
            try:
                neighbour = orig_tiles[u + off_u, v + off_v]
            except KeyError:
                # Always bevel towards instances.
                bevels[u, v] |= bevel
                continue
            if neighbour.type.is_tile:  # If there's a tile, no need to bevel since it's never visible.
                bevels[u, v] &= ~bevel

    todo_plane = texture_plane.copy()

    if dump_path is not None:
        with open(dump_path, 'w', encoding='utf8') as f:
            f.write(f'Bounds: {total_mins_u},{total_mins_v} - {total_maxs_u}, {total_maxs_v}\n')
            for v in reversed(range(total_mins_v, total_maxs_v + 1)):
                top, bottom = [], []
                for u in range(total_mins_u, total_maxs_u + 1):
                    if (u, v) in texture_plane:
                        a, b = BEVEL_CHAR[bevels[u, v]]
                    else:
                        a = b = '  '
                    top.append(a)
                    bottom.append(b)
                f.write(''.join(top) + '\n')
                f.write(''.join(bottom) + '\n')
            f.write(f'\n\nBevels:\n')
            for (u, v), bevel in bevels.items():
                f.write(f'{u}, {v} = {bevel!r}\n')
            f.write(f'\n\nPlane:\n')
            for (u, v), tex in texture_plane.items():
                f.write(f'{u}, {v} = {tex!r}\n')

    while todo_plane:
        u, v, texdef = todo_plane.largest_index()
        min_u, min_v, max_u, max_v, bevel = _bevel_extend(u, v, texdef, todo_plane, bevels)
        yield min_u, min_v, max_u, max_v, bevel, texdef
        for u, v in itertools.product(range(min_u, max_u + 1), range(min_v, max_v + 1)):
            del todo_plane[u, v]


def _bevel_extend(
    u: int, v: int, texdef: TexDef,
    texture_plane: PlaneGrid[TexDef],
    bevel_plane: PlaneGrid[Bevels],
) -> tuple[int, int, int, int, Bevels]:
    """Extend a tile as far as it can."""
    # Try both orders to see which produces the biggest tile.
    start_bevel = bevel_plane[u, v]
    min_u1, bevels1 = _bevel_extend_u(
        texture_plane, bevel_plane, texdef, u, start_bevel,
        v, v,
    )
    min_v1, bevels1 = _bevel_extend_v(
        texture_plane, bevel_plane, texdef, v, bevels1,
        min_u1, u,
    )
    min_v2, bevels2 = _bevel_extend_v(
        texture_plane, bevel_plane, texdef, v, start_bevel,
        u, u,
    )
    min_u2, bevels2 = _bevel_extend_u(
        texture_plane, bevel_plane, texdef, u, bevels2,
        min_v2, v,
    )
    if (1 + u - min_u1) * (1 + v - min_v1) > (1 + u - min_u2) * (1 + v - min_v2):
        return min_u1, min_v1, u, v, bevels1
    else:
        return min_u2, min_v2, u, v, bevels2


def _bevel_extend_u(
    texture_plane: PlaneGrid[TexDef],
    bevel_plane: PlaneGrid[Bevels],
    tile: TexDef, max_u: int, bevels: Bevels,
    min_v: int, max_v: int,
) -> tuple[int, Bevels]:
    """Extend this region in the -u direction.
    This then returns the required bevelling and the tile size.
    """
    if Bevels.u_min in bevels:
        # Already beveled, stop now.
        return max_u, bevels
    # The starting bevel on these sides.
    bevel_min = bevel_plane[max_u, min_v] & Bevels.v_min
    bevel_max = bevel_plane[max_u, max_v] & Bevels.v_max
    bevels |= bevel_min | bevel_max
    column = range(min_v, max_v + 1)
    min_u = max_u
    while True:
        # Try to advance to this position.
        u = min_u - 1
        # The -u bevel side is special, since we're extending that way.
        # All tiles need to have the same bevel. If we have none, we can continue,
        # but if they're all bevelled, stop immediately including that.
        end_bevel = bevel_plane[u, min_v] & Bevels.u_min
        if (
            # Stop if either end mismatches that side, any texture mismatches, or the leading edge
            # is not all the same as mentioned.
            bevel_plane[u, min_v] & Bevels.v_min != bevel_min or
            bevel_plane[u, max_v] & Bevels.v_max != bevel_max or
            any(
                texture_plane.get((u, v)) is not tile
                or bevel_plane[u, v] & Bevels.u_min != end_bevel
                for v in column
            )
        ):
            return min_u, bevels
        # Else: all good, we can advance to it.
        min_u = u
        if end_bevel:  # This is bevelled, stop now.
            return min_u, bevels | Bevels.u_min


def _bevel_extend_v(
    texture_plane: PlaneGrid[TexDef],
    bevel_plane: PlaneGrid[Bevels],
    tile: TexDef,
    max_v: int,
    bevels: Bevels,
    min_u: int, max_u: int,
) -> tuple[int, Bevels]:
    """Extend this region in the -v direction.
    This then returns the required bevelling and the tile size.
    """
    if Bevels.v_min in bevels:
        return max_v, bevels
    bevel_min = bevel_plane[min_u, max_v] & Bevels.u_min
    bevel_max = bevel_plane[max_u, max_v] & Bevels.u_max
    bevels |= bevel_min | bevel_max
    row = range(min_u, max_u + 1)
    min_v = max_v
    while True:
        v = min_v - 1
        end_bevel = bevel_plane[min_u, v] & Bevels.v_min
        if (
            bevel_plane[min_u, v] & Bevels.u_min != bevel_min or
            bevel_plane[max_u, v] & Bevels.u_max != bevel_max or
            any(
                texture_plane.get((u, v)) is not tile
                or bevel_plane[u, v] & Bevels.v_min != end_bevel
                for u in row
            )
        ):
            return min_v, bevels
        # Else: all good, we can advance to it.
        min_v = v
        if end_bevel:  # This is bevelled, stop now.
            return min_v, bevels | Bevels.v_min


def generate_brushes(vmf: VMF) -> None:
    """Generate all the brushes in the map."""
    # Clear just in case.
    make_subtile.cache_clear()
    make_texdef.cache_clear()

    LOGGER.info('Generating tiles...')
    # The key is (normal, plane distance)
    full_tiles: dict[PlaneKey, list[TileDef]] = defaultdict(list)

    if DEBUG:
        dump_path: Path | None = utils.install_path('reports/tiling_gen')
        LOGGER.error('Dump path: {}', dump_path)
        try:
            for file in dump_path.iterdir():
                if file.is_file():
                    file.unlink(missing_ok=True)
        except FileNotFoundError:
            pass  # Already empty.
        dump_path.mkdir(parents=True, exist_ok=True)
    else:
        dump_path = None

    # First examine each portal/noportal + orient set, to see what the max clump distance can be.
    search_dists: dict[tuple[Portalable, Orient], int] = {}
    for port in Portalable:
        for orient in Orient:
            gen = texturing.GENERATORS[texturing.GenCat.NORMAL, orient, port]
            search_dists[port, orient] = gen.options['clump_length'] * (
                8 if TileSize.TILE_DOUBLE in gen else 4
            )
            LOGGER.debug(
                '{}.{}:\nSearch dist: {}\nWeights: {}',
                port.value, orient.name,
                search_dists[port, orient],
                gen.weights,
            )
    for tile in TILES.values():
        # First, if not a simple tile, we have to deal with it individually.
        if not tile.is_simple():
            tile.export(vmf)
            continue
        # Otherwise, decompose into a big plane dict, for dynamic merging.
        full_tiles[PlaneKey(tile.normal, tile.pos_front)].append(tile)

        if tile.has_portal_helper:
            # Add the portal helper in now, so the code below can treat the face normally.
            vmf.create_ent(
                'info_placement_helper',
                angles=Angle.from_basis(x=tile.normal, z=tile.portal_helper_orient),
                origin=tile.pos_front,
                force_placement=int(tile.has_oriented_portal_helper),
                snap_to_helper_angles=int(tile.has_oriented_portal_helper),
                radius=64,
            )

    LOGGER.info('Generating {} planes:', len(full_tiles))

    for plane_key, tiles in full_tiles.items():
        generate_plane(vmf, dump_path, search_dists, plane_key, tiles)
    LOGGER.info(
        'Caches: subtile={}, texdef={}',
        make_subtile.cache_info(), make_texdef.cache_info(),
    )


def calculate_plane(
    plane_key: PlaneKey,
    texture_plane: PlaneGrid[TexDef],
    search_dists: dict[tuple[Portalable, Orient], int],
    subtile_pos: PlaneGrid[SubTile],
) -> None:
    """Calculate the textures to use for a plane of tiles."""
    orient = Orient.from_normal(plane_key.normal)

    # Reprocess subtiles into textures by repeatedly spreading.
    while subtile_pos:
        max_u, max_v, subtile = subtile_pos.largest_index()
        if subtile.type.is_tile:
            max_dist = search_dists[subtile.type.color, orient]
        else:
            # Not a tile, must be nodraw - we don't care how big.
            assert subtile.type is TileType.NODRAW
            max_dist = 64

        # Search to find the largest region of the same tile type.

        min_u1 = min_u2 = max_u
        min_v1 = min_v2 = max_v

        # First do u, v:
        for u in range(max_u, max_u - max_dist, -1):
            if subtile_pos[u, max_v] == subtile:
                min_u1 = u
            else:
                break
        # Then in v until we hit a boundary.
        for v in range(max_v, max_v - max_dist, -1):
            if all(subtile_pos[u, v] == subtile for u in range(min_u1, max_u + 1)):
                min_v1 = v
            else:
                break

        # Now try v, u:
        for v in range(max_v, max_v - max_dist, -1):
            if subtile_pos[max_u, v] == subtile:
                min_v2 = v
            else:
                break
        # Then in v until we hit a boundary.
        for u in range(max_u, max_u - max_dist, -1):
            if all(subtile_pos[u, v] == subtile for v in range(min_v2, max_v + 1)):
                min_u2 = u
            else:
                break

        # Then pick the biggest axis.
        if (1 + max_u - min_u1) * (1 + max_v - min_v1) > (1 + max_u - min_u2) * (1 + max_v - min_v2):
            width = max_u - min_u1 + 1
            height = max_v - min_v1 + 1
        else:
            width = max_u - min_u2 + 1
            height = max_v - min_v2 + 1

        if subtile.type.is_tile:
            # Now, pick a tile size.
            rng = rand.seed(
                b'tex_patch',
                plane_key.normal, plane_key.distance,
                max_u, max_v,
                subtile.type.value, subtile.antigel,
            )
            gen = texturing.gen(texturing.GenCat.NORMAL, orient, subtile.type.color)
            # Figure out tile sizes we can use. TODO: Cache this generated list.
            sizes: list[TileSize] = []
            counts: list[int] = []
            for size in ALLOWED_SIZES[subtile.type]:
                if size.width <= width and size.height <= height:
                    tex_list = gen.get_all(size, subtile.antigel)
                    if tex_list:
                        weight = gen.weights[size]
                        # If the weight is zero, only include if no larger tile matches.
                        if weight == 0:
                            if sizes:
                                continue
                            else:
                                weight = 1
                        sizes.append(size)
                        counts.append(len(tex_list) * weight)
            if not sizes:
                # Fallback, use 4x4.
                sizes = [TileSize.TILE_4x4]
                counts = [len(gen.get_all(TileSize.TILE_4x4, subtile.antigel))]
            if gen.options['mixtiles']:
                [size] = rng.choices(sizes, counts)
            else:
                # Only use the first.
                size = sizes[0]
            mat_conf = rng.choice(gen.get_all(size, subtile.antigel))
            if size is TileSize.TILE_4x4:
                # Force this to only place 1x1, so that other sizes get a chance.
                width = height = 1
            else:
                max_width = min(width // size.width, mat_conf.repeat_limit)
                max_height = min(height // size.height, mat_conf.repeat_limit)
                rng_width = rng.triangular(1, max_width, min(1.5, max_width))
                rng_height = rng.triangular(1, max_height, min(1.5, max_height))
                width = round(rng_width) * mat_conf.tile_size.width
                height = round(rng_height) * mat_conf.tile_size.height
            tex_def = make_texdef(
                mat_conf,
                subtile.antigel,
                (1 + max_u - width) % mat_conf.tile_size.width,
                (1 + max_v - height) % mat_conf.tile_size.height,
            )
        else:
            # Not a tile, must be nodraw.
            tex_def = TEXDEF_NODRAW

        for u in range(max_u - width + 1, max_u + 1):
            for v in range(max_v - height + 1, max_v + 1):
                del subtile_pos[u, v]
                texture_plane[u, v] = tex_def


def calculate_bottom_trim(
    plane_key: PlaneKey,
    subtile_pos: PlaneGrid[SubTile],
    texture_plane: PlaneGrid[TexDef],
    gen: texturing.Generator,
) -> None:
    """In Portal 1 style, all black walls always have a specific pattern at the base.

    This implements that before the regular tiles are calculated.
    """
    pattern = gen.bottom_trim_pattern
    pattern_count = len(pattern)

    min_u, min_v = subtile_pos.mins
    max_u, max_v = subtile_pos.maxes

    rng = rand.seed(
        b'tex_btm_trim',
        plane_key.normal, plane_key.distance,
        min_u, min_v, max_u, max_v,
    )
    # placed[u][v], we can drop a column once processed.
    placed: dict[int, set[int]] = defaultdict(set)

    for u in range(min_u, max_u + 1):
        # Start one below, so we detect a VOID tile and do that logic below.
        v = min_v - 1
        # This is the current progress through the tile sequence.
        # We set it to len(pattern) (out of range) whenever we want to abandon
        # the pattern - we must then have void to reset.
        count = 0
        placed_col = placed[u]

        while v <= max_v:
            if v in placed_col:
                v += 1  # Column on the left already placed here.
                count = pattern_count
                continue
            subtile = subtile_pos[u, v]

            # For NODRAW and VOID, we need to distinguish between these being set for faces inside
            # and outside the map. For outside, we need to restart the pattern. For inside, VOID
            # immediately cancels the pattern, while nodraw is treated as 4x4.
            if subtile.type is TileType.NODRAW or subtile.type is TileType.VOID:
                norm_axis = plane_key.normal.axis()
                u_ax, v_ax = Vec.INV_AXIS[norm_axis]
                pos = Vec.with_axes(
                    norm_axis,
                    plane_key.normal * (plane_key.distance + 1.0),
                    u_ax, u * 32.0 + 16.0,
                    v_ax, v * 32.0 + 16.0,
                )
                if not brushLoc.POS.lookup_world(pos).traversable:
                    v += 1
                    count = 0
                    continue

            match subtile.type:
                # Restart the pattern above goo tiles.
                case TileType.GOO_SIDE_BLACK:
                    v += 1
                    count = 0
                    continue
                case TileType.NODRAW | TileType.BLACK_4x4:
                    # Allow nodraw to take the place of only 4x4 tiles.
                    # The 4x4 type also matches 4x4 tiles of course.
                    v += 1
                    if count < pattern_count and pattern[count] is TileSize.TILE_4x4:
                        count += 1
                    else:
                        count = pattern_count
                    continue
                case TileType.BLACK:
                    pass
                case _:
                    # Another wall type, abandon entirely.
                    count = pattern_count
                    v += 1
                    continue

            if count < pattern_count:
                # Try to place this tile.
                tile_size = pattern[count]
                tile_u = range(tile_size.width)
                tile_v = range(tile_size.height)
                for u_off, v_off in itertools.product(tile_u, tile_v):
                    if subtile_pos[u + u_off, v + v_off].type is not TileType.BLACK:
                        count = pattern_count
                        break
                else:
                    # All good. Place the tile.
                    mat_conf = rng.choice(gen.get_all(tile_size, subtile.antigel))
                    tex_u = u % mat_conf.tile_size.width
                    tex_v = v % mat_conf.tile_size.height
                    for u_off, v_off in itertools.product(tile_u, tile_v):
                        texture_plane[u + u_off, v + v_off] = make_texdef(
                            mat_conf, subtile.antigel,
                            tex_u, tex_v,
                        )
                        placed[u + u_off].add(v + v_off)
                count += 1
                v += tile_size.height  # Skip multiple for 2x2 or 1x1 tiles.
            else:
                v += 1
        # Do this after, so it doesn't affect logic for previous columns.
        for v in placed_col:
            del subtile_pos[u, v]
        del placed[u]


def generate_plane(
    vmf: VMF,
    dump_path: Path | None,
    search_dists: dict[tuple[Portalable, Orient], int],
    plane_key: PlaneKey,
    tiles: list[TileDef],
) -> None:
    """Generate all the tiles in a single flat plane.

    These are all the ones which could be potentially merged together.
    Order of operations:
    - Order the tiles by their UV positions, in a grid.
    - Decompose those into individual subtile definitions.
    - Repeatedly take sections and compute the texture.
    - A second pass is made to determine the required bevelling.
    - Finally that raw form is converted to brushes.
    """
    # TODO: Use PlaneKey instead of axis strings
    norm_axis = plane_key.normal.axis()
    u_axis, v_axis = Vec.INV_AXIS[norm_axis]
    grid_pos: PlaneGrid[TileDef] = PlaneGrid()
    norm_off = plane_key.normal * plane_key.distance

    subtile_pos = PlaneGrid(default=SubTile(TileType.VOID, False))

    if dump_path is not None:
        dump_path /= f'plane_{PLANE_NAMES.get(plane_key.normal, plane_key.normal.join("_"))}_{round(plane_key.distance):+05}.log'
        LOGGER.info('Dump: {}', dump_path)

    for tile in tiles:
        pos = tile.pos_front
        antigel = tile.is_antigel()
        u_full = int((pos[u_axis] - 64) // 32)
        v_full = int((pos[v_axis] - 64) // 32)
        for u, v, tile_type in tile:
            if tile_type is not TileType.VOID:
                subtile_pos[u_full + u, v_full + v] = make_subtile(tile_type, antigel)
                grid_pos[u_full + u, v_full + v] = tile

    # Create a copy, but clear the default to ensure an error is raised if indexed incorrectly.
    orig_tiles = PlaneGrid(subtile_pos)
    texture_plane: PlaneGrid[TexDef] = PlaneGrid()

    # Check if the P1 style bottom trim option is set, and if so apply it.
    gen = texturing.gen(texturing.GenCat.NORMAL, plane_key.normal, Portalable.BLACK)
    if gen.bottom_trim_pattern:
        calculate_bottom_trim(plane_key, subtile_pos, texture_plane, gen)

    # Calculate the required tiles.
    calculate_plane(plane_key, texture_plane, search_dists, subtile_pos)

    from precomp.conditions import fetch_debug_visgroup
    missing_tiles = fetch_debug_visgroup(vmf, 'Missing plane tiles')

    # Split tiles into each brush that needs to be placed, then create it.
    for min_u, min_v, max_u, max_v, bevels, tex_def in bevel_split(texture_plane, dump_path, grid_pos, orig_tiles):
        center = norm_off + Vec.with_axes(
            # Compute avg(32*min, 32*max)
            # = (32 * min + 32 * max) / 2
            # = (min + max) * 16
            u_axis, (1 + min_u + max_u) * 16,
            v_axis, (1 + min_v + max_v) * 16,
        )
        brush, front = make_tile(
            vmf,
            center,
            plane_key.normal,
            tex_def.tex,
            texturing.SPECIAL.get(center, 'behind', antigel=tex_def.antigel),
            bevels=bevels,
            width=(1 + max_u - min_u) * 32,
            height=(1 + max_v - min_v) * 32,
            antigel=tex_def.antigel,
        )
        vmf.add_brush(brush)
        tile_min = norm_off + Vec.with_axes(
            u_axis, -32 * tex_def.u_off,
            v_axis, -32 * tex_def.v_off,
        )
        front.uaxis.offset = (Vec.dot(tile_min, front.uaxis.vec()) / front.uaxis.scale)
        front.vaxis.offset = (Vec.dot(tile_min, front.vaxis.vec()) / front.vaxis.scale)

        tiledefs = set()
        for u in range(min_u, max_u + 1):
            for v in range(min_v, max_v + 1):
                try:
                    tiledefs.add(grid_pos[u, v])
                except KeyError:
                    pos = norm_off + Vec.with_axes(
                        u_axis, 32. * u + 16.,
                        v_axis, 32. * v + 16.,
                    )
                    LOGGER.warning('Tile badly generated @ {}', pos)
                    missing_tiles('info_null', origin=pos)
        for tiledef in tiledefs:
            tiledef.brush_faces.append(front)
