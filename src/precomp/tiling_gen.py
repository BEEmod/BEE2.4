"""Logic for generating the overall map geometry."""
from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Iterator
import functools
import operator

import attrs
from srctools import Angle, Entity, VMF, Vec, logger

import consts
import utils
from plane import PlaneGrid
from precomp import grid_optim, rand, texturing
from precomp.texturing import MaterialConf, Orient, Portalable, TileSize
from precomp.tiling import TILES, TileDef, TileType, Bevels, make_tile


LOGGER = logger.get_logger(__name__)


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
BEVEL_OFFSETS = [
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
]
ALLOWED_SIZES: dict[TileType, list[TileSize]] = {
    TileType.WHITE: tile_chain,
    TileType.BLACK: tile_chain,

    TileType.WHITE_4x4: [TileSize.TILE_4x4],
    TileType.BLACK_4x4: [TileSize.TILE_4x4],
    TileType.GOO_SIDE: [TileSize.GOO_SIDE],
}


def bevel_split(
    texture_plane: PlaneGrid[TexDef],
    tile_pos: PlaneGrid[TileDef],
    orig_tiles: PlaneGrid[SubTile],
) -> Iterator[tuple[int, int, int, int, Bevels, TexDef]]:
    """Split the optimised segments to produce the correct bevelling."""
    bevels = PlaneGrid(default=Bevels.none)

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

    for min_u, min_v, max_u, max_v, texdef in grid_optim.optimise(texture_plane):
        u_group = list(utils.group_runs(
            (bevels[min_u, v] | bevels[max_u, v]) & Bevels.u_both
            for v in range(min_v, max_v + 1)
        ))
        v_group = list(utils.group_runs(
            (bevels[u, min_v] | bevels[u, max_v]) & Bevels.v_both
            for u in range(min_u, max_u + 1)
        ))
        for bevel_u, v_ind_min, v_ind_max in u_group:
            for bevel_v, u_ind_min, u_ind_max in v_group:
                yield (
                    min_u + u_ind_min,
                    min_v + v_ind_min,
                    min_u + u_ind_max,
                    min_v + v_ind_max,
                    bevel_u | bevel_v,
                    texdef
                )


def generate_brushes(vmf: VMF) -> None:
    """Generate all the brushes in the map."""
    # Clear just in case.
    make_subtile.cache_clear()
    make_texdef.cache_clear()

    LOGGER.info('Generating tiles...')
    # The key is (normal, plane distance)
    full_tiles: dict[
        tuple[float, float, float, float],
        list[TileDef]
    ] = defaultdict(list)

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

        pos = tile.pos + 64 * tile.normal
        plane_dist = pos.dot(tile.normal)

        full_tiles[
            tile.normal.x, tile.normal.y, tile.normal.z,
            plane_dist,
        ].append(tile)

        if tile.has_portal_helper:
            # Add the portal helper in now, so the code below can treat the face normally.
            vmf.create_ent(
                'info_placement_helper',
                angles=Angle.from_basis(x=tile.normal, z=tile.portal_helper_orient),
                origin=pos,
                force_placement=int(tile.has_oriented_portal_helper),
                snap_to_helper_angles=int(tile.has_oriented_portal_helper),
                radius=64,
            )

    LOGGER.info('Generating {} planes:', len(full_tiles))

    for (norm_x, norm_y, norm_z, plane_dist), tiles in full_tiles.items():
        generate_plane(vmf, search_dists, Vec(norm_x, norm_y, norm_z), plane_dist, tiles)
    LOGGER.info(
        'Caches: subtile={}, texdef={}',
        make_subtile.cache_info(), make_texdef.cache_info(),
    )


def generate_plane(
    vmf: VMF,
    search_dists: dict[tuple[Portalable, Orient], int],
    normal: Vec, plane_dist: float,
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
    norm_axis = normal.axis()
    orient = Orient.from_normal(normal)
    u_axis, v_axis = Vec.INV_AXIS[norm_axis]
    grid_pos: PlaneGrid[TileDef] = PlaneGrid()

    VOID = TileType.VOID
    subtile_pos = PlaneGrid(default=SubTile(VOID, False))

    for tile in tiles:
        pos = tile.pos_front
        u_full = int((pos[u_axis] - 64) // 32)
        v_full = int((pos[v_axis] - 64) // 32)
        for u, v, tile_type in tile:
            if tile_type is not VOID:
                subtile_pos[u_full + u, v_full + v] = make_subtile(tile_type, tile.is_antigel())
                grid_pos[u_full + u, v_full + v] = tile

    # Create a copy, but clear the default to ensure an error is raised if indexed incorrectly.
    orig_tiles = PlaneGrid(subtile_pos)
    # Now, reprocess subtiles into textures by repeatedly spreading.
    texture_plane: PlaneGrid[TexDef] = PlaneGrid()
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
        if (1+max_u - min_u1) * (1+max_v-min_v1) > (1+max_u - min_u2) * (1+max_v - min_v2):
            width = max_u - min_u1 + 1
            height = max_v - min_v1 + 1
        else:
            width = max_u - min_u2 + 1
            height = max_v - min_v2 + 1

        if subtile.type.is_tile:
            # Now, pick a tile size.
            rng = rand.seed(
                b'tex_patch',
                normal, plane_dist,
                max_u, max_v,
                subtile.type.value, subtile.antigel,
            )
            gen = texturing.gen(texturing.GenCat.NORMAL, normal, subtile.type.color)
            # Figure out tile sizes we can use. TODO: Cache this generated list.
            sizes: list[TileSize] = []
            counts: list[int] = []
            for size in ALLOWED_SIZES[subtile.type]:
                if size.width <= width and size.height <= height:
                    tex_list = gen.get_all(size)
                    if tex_list:
                        sizes.append(size)
                        counts.append(len(tex_list) * gen.weights[size])
            if not sizes:
                # Fallback, use 4x4.
                sizes = [TileSize.TILE_4x4]
                counts = [len(gen.get_all(TileSize.TILE_4x4))]
            if gen.options['mixtiles']:
                [size] = rng.choices(sizes, counts)
            else:
                # Only use the first.
                size = sizes[0]
            if size is TileSize.TILE_4x4:
                # Force this to only place 1x1, so that other sizes get a chance.
                width = height = 1
            else:
                max_width = width // size.width
                max_height = height // size.height
                width = round(rng.triangular(1, max_width, min(1.5, max_width))) * size.width
                height = round(rng.triangular(1, max_height, min(1.5, max_height))) * size.height
            mat_conf = rng.choice(gen.get_all(size))
            tex_def = make_texdef(
                mat_conf,
                subtile.antigel,
                (1 + max_u - width) % mat_conf.tile_size.width,
                (1 + max_v - height) % mat_conf.tile_size.height,
            )
        else:
            # Not a tile, must be nodraw.
            tex_def = TEXDEF_NODRAW

        for u in range(max_u-width+1, max_u+1):
            for v in range(max_v-height+1, max_v+1):
                del subtile_pos[u, v]
                texture_plane[u, v] = tex_def

    for min_u, min_v, max_u, max_v, bevels, tex_def in bevel_split(texture_plane, grid_pos, orig_tiles):
        center = normal * plane_dist + Vec.with_axes(
            # Compute avg(32*min, 32*max)
            # = (32 * min + 32 * max) / 2
            # = (min + max) * 16
            u_axis, (1 + min_u + max_u) * 16,
            v_axis, (1 + min_v + max_v) * 16,
        )
        brush, front = make_tile(
            vmf,
            center,
            normal,
            tex_def.tex,
            texturing.SPECIAL.get(center, 'behind', antigel=tex_def.antigel),
            bevels=bevels,
            width=(1 + max_u - min_u) * 32,
            height=(1 + max_v - min_v) * 32,
            antigel=tex_def.antigel,
        )
        vmf.add_brush(brush)
        tile_min = Vec.with_axes(
            norm_axis, plane_dist,
            u_axis, -32 * tex_def.u_off,
            v_axis, -32 * tex_def.v_off,
        )
        front.uaxis.offset = (Vec.dot(tile_min, front.uaxis.vec()) / front.uaxis.scale)
        front.vaxis.offset = (Vec.dot(tile_min, front.vaxis.vec()) / front.vaxis.scale)

        for tiledef in {
            grid_pos[u, v]
            for u in range(min_u, max_u + 1)
            for v in range(min_v, max_v + 1)
        }:
            tiledef.brush_faces.append(front)
