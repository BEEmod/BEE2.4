"""Logic for generating the overall map geometry."""
from __future__ import annotations

import math
from typing import Literal, assert_never

from collections import defaultdict
from collections.abc import Iterator, Callable
from pathlib import Path
import functools
import itertools

from srctools import Angle, Entity, VMF, Vec, logger, FrozenVec
import attrs

import utils
from plane import PlaneGrid, PlaneKey
from precomp import rand, texturing, brushLoc
from precomp.conditions import fetch_debug_visgroup
from precomp.texturing import MaterialConf, Orient, Portalable, TileSize, GenCat
from precomp.tiling import TILES, TileDef, TileType, Bevels, make_tile, Axis
from precomp.template_brush import ScalingTemplate
import consts


__all__ = ['generate_brushes']
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
    # For tiledef overrides only.
    scale_temp: ScalingTemplate | None = None


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
) -> Iterator[tuple[float, float, float, float, Bevels, TexDef]]:
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

    # Don't compact bevels, it's unlikely be continuous.
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
            f.write('\n\nBevels:\n')
            for (u, v), bevel in bevels.items():
                f.write(f'{u}, {v} = {bevel!r}\n')
            f.write('\n\nPlane:\n')
            for (u, v), tex in texture_plane.items():
                f.write(f'{u}, {v} = {tex!r}\n')

    while todo_plane:
        u, v, texdef = todo_plane.largest_index()
        min_u, min_v, max_u, max_v, bevel = _bevel_extend(u, v, texdef, todo_plane, bevels)
        yield min_u, min_v, max_u + 1, max_v + 1, bevel, texdef
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
            # Stop if either end mismatches that side.
            bevel_plane[u, min_v] & Bevels.v_min != bevel_min or
            bevel_plane[u, max_v] & Bevels.v_max != bevel_max
        ):
            return min_u, bevels
        for v in column:
            # Stop if the new leading edge is not all the same, or any texture mismatches exist.
            if (
                bevel_plane[u, v] & Bevels.u_min != end_bevel
                or texture_plane.get((u, v)) is not tile
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
            bevel_plane[max_u, v] & Bevels.u_max != bevel_max
        ):
            return min_v, bevels
        for u in row:
            if (
                bevel_plane[u, v] & Bevels.v_min != end_bevel
                or texture_plane.get((u, v)) is not tile
            ):
                return min_v, bevels
        # Else: all good, we can advance to it.
        min_v = v
        if end_bevel:  # This is bevelled, stop now.
            return min_v, bevels | Bevels.v_min


def fizzler_tile_gen(
    plane_key: PlaneKey,
    def_plane: PlaneGrid[TileDef],
    tile_plane: PlaneGrid[SubTile],
    axis: Literal['u', 'v'],
) -> Iterator[tuple[float, float, float, float, Bevels, TexDef]]:
    """Generate the half-tiles for fizzler brushes."""
    # TODO: Should we handle missing tiles - how should nodraw work?
    if not tile_plane:
        return  # No fizzlers of this type, don't need to calc.

    mins_u, mins_v = tile_plane.mins
    maxs_u, maxs_v = tile_plane.maxes
    if axis == 'u':
        split_min, split_max = mins_u, maxs_u
        along_min, along_max = mins_v, maxs_v
        tile_size = TileSize.TILE_8x4

        def order[T](split: T, along: T) -> tuple[T, T]:
            return (split, along)
    else:
        split_min, split_max = mins_v, maxs_v
        along_min, along_max = mins_u, maxs_u
        tile_size = TileSize.TILE_4x8

        def order[T](split: T, along: T) -> tuple[T, T]:
            return (along, split)

    # In case all of the left are somehow missing, adjust.
    split_min = split_min // 4 * 4 + 1

    orient = Orient.from_normal(plane_key.normal)
    generators = {
        port: texturing.gen(GenCat.NORMAL, orient, port)
        for port in Portalable
    }
    # Include an extra position at the end so we naturally handle tiles running up to the end.
    along_range = range(along_min, along_max + 2)

    def bevel_calc(mins: int, maxs: int) -> Bevels:
        """Calculate bevels for a set of tiles.
        If either end is voxel-aligned, check for whether the tile should bevel.
        """
        u: Axis
        v: Axis
        bevels = Bevels.none
        if mins % 4 == 0:
            tile = def_plane.get(order(voxel_off, mins))
            u, v = order(0, -1)
            if tile is not None and tile.should_bevel(u, v):
                bevels |= Bevels.v_min if axis == 'u' else Bevels.u_min
        if maxs % 4 == 0:
            tile = def_plane.get(order(voxel_off, maxs))
            u, v = order(0, +1)
            if tile is not None and tile.should_bevel(u, v):
                bevels |= Bevels.v_max if axis == 'u' else Bevels.u_max
        return bevels

    for voxel_off in range(split_min, split_max + 1, 4):
        tex: TexDef | None
        # Find the pair of each tiles, or None if missing.
        tiles = [
            (along, tile_plane.get(order(voxel_off, along)), tile_plane.get(order(voxel_off + 1, along)))
            for along in along_range
        ]
        # Then iterate that, create nodraw if either is present, calculating runs to generate one
        # brush.
        nodraw_start: int | None = None
        for along, left, right in tiles:
            if left is not None or right is not None:
                if nodraw_start is None:
                    nodraw_start = along
            elif nodraw_start is not None:
                # Make nodraw. First, calculate bevels - if an end is voxel aligned,
                bevels = bevel_calc(nodraw_start, along - 1)
                if axis == 'u':
                    yield voxel_off + 0.5, nodraw_start, voxel_off + 1.5, along, bevels, TEXDEF_NODRAW
                else:
                    yield nodraw_start, voxel_off + 0.5, along, voxel_off + 1.5, bevels, TEXDEF_NODRAW
                nodraw_start = None
            # Else, nodraw span, ignore.

        # Now do each tile column. First generate the textures for each tile, group runs,
        # then make each brush.
        for tex, start, end in utils.group_runs(
            make_texdef(
                generators[left.type.color].get(
                    plane_key.plane_to_world(
                        *order(32 * voxel_off + 8, 32 * along + 16),
                    ),
                    tile_size,
                    antigel=left.antigel,
                ), left.antigel,
            ) if left is not None and left.type.is_tile else None
            for along, left, right in tiles
        ):
            if tex is not None:
                start += along_min
                end += along_min
                bevels = bevel_calc(start, end)
                if axis == 'u':
                    yield voxel_off, start, voxel_off + 0.5, end + 1, bevels, tex
                else:
                    yield start, voxel_off, end + 1, voxel_off + 0.5, bevels, tex

        for tex, start, end in utils.group_runs(
            make_texdef(
                generators[right.type.color].get(
                    plane_key.plane_to_world(
                        *order(32 * voxel_off + 56, 32 * along + 16),
                    ),
                    tile_size,
                    antigel=right.antigel,
                ), right.antigel,
            ) if right is not None and right.type.is_tile else None
            for along, left, right in tiles
        ):
            if tex is not None:
                start += along_min
                end += along_min
                bevels = bevel_calc(start, end)
                if axis == 'u':
                    yield voxel_off + 1.5, start, voxel_off + 2, end + 1, bevels, tex
                else:
                    yield start, voxel_off + 1.5, end + 1, voxel_off + 2, bevels, tex

        # Additional range increment should have finalised the last tile.
        assert nodraw_start is None, (
            f'Additional position failed? {locals()}'
        )


def generate_brushes(vmf: VMF) -> None:
    """Generate all the brushes in the map."""
    # Clear just in case.
    make_subtile.cache_clear()
    make_texdef.cache_clear()

    LOGGER.info('Generating tiles...')
    # The key is (normal, plane distance)
    full_tiles: dict[PlaneKey, list[TileDef]] = defaultdict(list)

    dump_path: Path | None
    if DEBUG:
        dump_path = utils.install_path('reports/tiling_gen')
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
        if tile.panels or tile.bullseye_count > 0:
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

    if utils.DEV_MODE:
        # For debugging texture definitions, generate a sample for every tile generator.
        gallery_vis = fetch_debug_visgroup(vmf, 'Material Gallery')
        for key, generator in texturing.GENERATORS.items():
            match key:
                case GenCat() as cat, Orient() as orient, Portalable() as port:
                    generate_tile_gallery(vmf, gallery_vis, cat, orient, port, generator)
                case _:
                    pass


def calculate_plane(
    plane_key: PlaneKey,
    texture_plane: PlaneGrid[TexDef],
    search_dists: dict[tuple[Portalable, Orient], int],
    subtile_pos: PlaneGrid[SubTile],
) -> None:
    """Calculate the textures to use for a plane of tiles."""
    orient = Orient.from_normal(plane_key.normal)

    generators = {
        colour: texturing.gen(texturing.GenCat.NORMAL, orient, colour)
        for colour in Portalable
    }

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
            gen = generators[subtile.type.color]
            # Figure out tile sizes we can use. TODO: Cache this generated list.
            sizes: list[TileSize] = []
            counts: list[int] = []
            weights = gen.small_weights if width < 4 or height < 4 else gen.weights
            for size in ALLOWED_SIZES[subtile.type]:
                if size.width <= width and size.height <= height:
                    tex_list = gen.get_all(size, subtile.antigel)
                    if tex_list:
                        weight = weights[size]
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
    texture_plane.compact()


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
    pos: Vec | FrozenVec
    # TODO: Use PlaneKey instead of axis strings
    norm_axis = plane_key.normal.axis()
    u_axis, v_axis = Vec.INV_AXIS[norm_axis]
    norm_off = plane_key.normal * plane_key.distance
    # For each subtile, stores the original tiledef, to associate overlays etc.
    grid_pos: PlaneGrid[TileDef] = PlaneGrid()

    # We fill this plane first, then empty as we place each tile.
    subtile_pos: PlaneGrid[SubTile] = PlaneGrid(default=SubTile(TileType.VOID, False))
    # We also preserve an unmodified copy to consult.
    # We clear the default to ensure an error is raised if indexed incorrectly.
    orig_tiles: PlaneGrid[SubTile] = PlaneGrid()

    if dump_path is not None:
        dump_path /= (
            f'plane_{PLANE_NAMES.get(plane_key.normal, plane_key.normal.join("_"))}'
            f'_{round(plane_key.distance):+05}.log'
        )
        LOGGER.info('Dump: {}', dump_path)

    # Stores tiles constructing the half-border next to fizzlers. These are 16-wide, with nodraw
    # in-between.
    fizzler_split_u: PlaneGrid[SubTile] = PlaneGrid()
    fizzler_split_v: PlaneGrid[SubTile] = PlaneGrid()
    # And then planes storing the tiledefs themselves, for generating the nodraw.

    texture_plane: PlaneGrid[TexDef] = PlaneGrid()

    for tile in tiles:
        pos = tile.pos_front
        antigel = tile.is_antigel()
        tile_u = int((pos[u_axis] - 64) // 32)
        tile_v = int((pos[v_axis] - 64) // 32)
        fizz_split = tile.get_fizz_orient()
        tile_override: TexDef | None
        if tile.override is not None:
            # Tiledef defined an override for materials. We apply this to all regular tiles.
            mat_conf, scale_temp = tile.override
            # TODO: The scale template is offset per-instance, so it won't deduplicate.
            tile_override = TexDef(mat_conf, scale_temp=scale_temp)
        else:
            tile_override = None
        for u, v, tile_type in tile:
            if tile_type is TileType.VOID:
                continue
            key = (tile_u + u, tile_v + v)
            grid_pos[key] = tile
            if tile_type.is_tile and tile_override is not None:
                if fizz_split is not None:
                    raise NotImplementedError(
                        'Cannot use material overrides on a tile with centered fizzlers for now.'
                    )
                texture_plane[key] = tile_override
                continue
            # If the tiledef is fizzler-split, extract the middle row/column pair into the alternate.
            # In all cases, we add to the original tiles plane, for bevelling calculations.
            orig_tiles[key] = subtile = make_subtile(tile_type, antigel)
            match fizz_split:
                case None:
                    subtile_pos[key] = subtile
                case 'u':
                    if u in (1, 2):
                        fizzler_split_u[key] = subtile
                    else:
                        subtile_pos[key] = subtile
                case 'v':
                    if v in (1, 2):
                        fizzler_split_v[key] = subtile
                    else:
                        subtile_pos[key] = subtile
                case never:
                    assert_never(never)

    subtile_pos.compact()
    orig_tiles.compact()
    # Check if the P1 style bottom trim option is set, and if so apply it.
    gen = texturing.gen(texturing.GenCat.NORMAL, plane_key.normal, Portalable.BLACK)
    if gen.bottom_trim_pattern:
        calculate_bottom_trim(plane_key, subtile_pos, texture_plane, gen)

    # Calculate the required tiles.
    calculate_plane(plane_key, texture_plane, search_dists, subtile_pos)

    from precomp.conditions import fetch_debug_visgroup
    missing_tiles = fetch_debug_visgroup(vmf, 'Missing plane tiles')

    # Split tiles into each brush that needs to be placed, then create it.
    for min_u, min_v, max_u, max_v, bevels, tex_def in itertools.chain(
        bevel_split(texture_plane, dump_path, grid_pos, orig_tiles),
        fizzler_tile_gen(plane_key, grid_pos, fizzler_split_u, 'u'),
        fizzler_tile_gen(plane_key, grid_pos, fizzler_split_v, 'v'),
    ):
        center = norm_off + Vec.with_axes(
            # Compute avg(32*min, 32*max)
            # = (32 * min + 32 * max) / 2
            # = (min + max) * 16
            u_axis, (min_u + max_u) * 16,
            v_axis, (min_v + max_v) * 16,
        )
        brush, front = make_tile(
            vmf,
            center,
            plane_key.normal,
            tex_def.tex,
            texturing.SPECIAL.get(center, 'behind', antigel=tex_def.antigel),
            bevels=bevels,
            width=(max_u - min_u) * 32,
            height=(max_v - min_v) * 32,
            antigel=tex_def.antigel,
        )
        vmf.add_brush(brush)
        if tex_def.scale_temp is not None:
            # If the texture isn't supplied, use the one from the template.
            tex_def.scale_temp.apply(front, change_mat=not tex_def.tex)
        else:
            tile_min = norm_off + Vec.with_axes(
                u_axis, -32 * tex_def.u_off,
                v_axis, -32 * tex_def.v_off,
            )
            front.uaxis.offset = (Vec.dot(tile_min, front.uaxis.vec()) / front.uaxis.scale)
            front.vaxis.offset = (Vec.dot(tile_min, front.vaxis.vec()) / front.vaxis.scale)

        tiledefs = set()
        for u in range(math.floor(min_u), math.ceil(max_u)):
            for v in range(math.floor(min_v), math.ceil(max_v)):
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


def generate_tile_gallery(
    vmf: VMF, gallery_vis: Callable[[Entity], object],
    cat: GenCat, orient: Orient, port: Portalable,
    generator: texturing.Generator,
) -> None:
    """For testing purposes, export a gallery of all available tiles."""
    offset = {
        GenCat.NORMAL: 0,
        GenCat.PANEL: 256,
        GenCat.BULLSEYE: 512,
    }[cat]
    if port is Portalable.BLACK:
        offset += 128
    match orient:
        case Orient.WALL:
            plane = PlaneKey((0, 1, 0), 512 + offset)
        case Orient.FLOOR:
            plane = PlaneKey((0, 0, 1), -offset)
        case Orient.CEILING | Orient.CEIL:  # TODO Mypy, redundant.
            plane = PlaneKey((0, 0, -1), 512 + offset)

    LOGGER.info('Generating tile gallery for {}.{}.{} @ {}', cat, orient, port, plane)

    offset_x = offset_y = 0
    for size, confs in generator.textures.items():
        assert isinstance(size, TileSize), f'{size!s}, {size!r}'
        desc = f'{cat.name}_{orient.name}_{port.name}_{size}'
        for tile in sorted(set(confs), key=lambda conf: conf.mat):
            width, height = size.size
            brush, front = make_tile(
                vmf,
                Vec(height * 16, width * 16, 0),
                Vec(0, 0, 1),
                tile,
                width=width * 32,
                height=height * 32,
            )
            tile_min = Vec(0, 0, 0)
            front.uaxis.offset = -(Vec.dot(tile_min, front.uaxis.vec()) / front.uaxis.scale)
            front.vaxis.offset = -(Vec.dot(tile_min, front.vaxis.vec()) / front.vaxis.scale)
            brush.localise(plane.plane_to_world(
                offset_x + height * 16,
                offset_y + width * 16,
            ), plane.orient)
            ent = vmf.create_ent('func_brush', targetname=desc)
            ent.solids = [brush]
            ent.comments = f'{width}x{height}, repeat={tile.repeat_limit}, off={tile.off_x}, {tile.off_y}'
            gallery_vis(ent)

            offset_x += max(width, height) * 32 + 32
            if offset_x >= 3072:
                offset_x = 0
                offset_y += 256 + 32
