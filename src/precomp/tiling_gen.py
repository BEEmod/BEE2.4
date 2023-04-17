"""Logic for generating the overall map geometry."""
from __future__ import annotations
from collections import Counter, defaultdict
from typing import Iterator
import functools

import attrs
from srctools import Angle, Entity, Output, VMF, Vec, logger

import consts
import utils
from plane import Plane
from precomp import grid_optim, options, rand, texturing
from precomp.brushLoc import Block, POS as BLOCK_POS
from precomp.texturing import MaterialConf, Orient, Portalable, TileSize
from precomp.tiling import OVERLAY_BINDS, TILES, TileDef, TileType, make_tile


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
make_texdef = functools.lru_cache(maxsize=32)(TexDef)
TEXDEF_NODRAW = TexDef(MaterialConf(consts.Tools.NODRAW))
# We know we don't modify the tiledefs while generating.
_cached_bevel = functools.lru_cache(maxsize=32)(TileDef.should_bevel)


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


def _compute_bevel(tile: TileDef, u: int, v: int, neighbour: SubTile | None) -> bool:
    if neighbour is None:
        # We know we don't modify the tiledefs while generating.
        return tile.should_bevel(u, v)
    if neighbour.type is TileType.VOID:  # Always bevel towards instances.
        return True
    if neighbour.type.is_tile:  # If there's a tile, no need to bevel since it's never visible.
        return False
    # We know we don't modify the tiledefs while generating.
    return tile.should_bevel(u, v)


def bevel_split(
    texture_plane: Plane[TexDef],
    tile_pos: Plane[TileDef],
    orig_tiles: Plane[SubTile],
) -> Iterator[tuple[int, int, int, int, tuple[bool, bool, bool, bool], TexDef]]:
    """Split the optimised segments to produce the correct bevelling."""
    for min_u, min_v, max_u, max_v, texdef in grid_optim.optimise(texture_plane):
        u_range = range(min_u, max_u + 1)
        v_range = range(min_v, max_v + 1)

        # These are sort of reversed around, which is a little confusing.
        # Bevel U is facing in the U direction, running across the V.
        bevel_umins: list[bool] = [
            _compute_bevel(tile_pos[min_u, v], -1, 0, orig_tiles[min_u-1, v])
            for v in v_range
        ]
        bevel_umaxes: list[bool] = [
            _compute_bevel(tile_pos[max_u, v], 1, 0, orig_tiles[max_u+1, v])
            for v in v_range
        ]
        bevel_vmins: list[bool] = [
            _compute_bevel(tile_pos[u, min_v], 0, -1, orig_tiles[u, min_v-1])
            for u in u_range
        ]
        bevel_vmaxes: list[bool] = [
            _compute_bevel(tile_pos[u, max_v], 0, 1, orig_tiles[u, min_v+1])
            for u in u_range
        ]

        u_group = list(utils.group_runs(zip(bevel_umins, bevel_umaxes)))
        v_group = list(utils.group_runs(zip(bevel_vmins, bevel_vmaxes)))

        for bevel_u, v_ind_min, v_ind_max in u_group:
            for bevel_v, u_ind_min, u_ind_max in v_group:
                yield (
                    min_u + u_ind_min,
                    min_v + v_ind_min,
                    min_u + u_ind_max,
                    min_v + v_ind_max,
                    bevel_u + bevel_v,
                    texdef
                )


def generate_brushes(vmf: VMF) -> None:
    """Generate all the brushes in the map, then set overlay sides."""
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
    LOGGER.info('Caches: subtile={}, texdef={}', make_subtile.cache_info(), make_texdef.cache_info())

    LOGGER.info('Generating goop...')
    generate_goo(vmf)

    nodraw = consts.Tools.NODRAW
    for over, over_tiles in OVERLAY_BINDS.items():
        # Keep already set sides.
        faces = set(over['sides', ''].split())
        # We don't want to include nodraw, since that doesn't accept
        # overlays anyway.
        for tile in over_tiles:
            faces.update(
                str(f.id)
                for f in tile.brush_faces
                if f.mat != nodraw
            )

        # If it turns out there's no faces for this, discard the overlay.
        if faces:
            over['sides'] = ' '.join(sorted(faces))
        else:
            over.remove()


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
    grid_pos: Plane[TileDef] = Plane()

    VOID = TileType.VOID
    subtile_pos = Plane(default=SubTile(VOID, False))

    for tile in tiles:
        pos = tile.pos_front
        u_full = int((pos[u_axis] - 64) // 32)
        v_full = int((pos[v_axis] - 64) // 32)
        for u, v, tile_type in tile:
            if tile_type is not VOID:
                subtile_pos[u_full + u, v_full + v] = make_subtile(tile_type, tile.is_antigel)
                grid_pos[u_full + u, v_full + v] = tile

    orig_tiles = subtile_pos.copy()
    orig_tiles.default = None
    # Now, reprocess subtiles into textures by repeatedly spreading.
    texture_plane: Plane[TexDef] = Plane()
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
            # Figure out tile sizes we can use.
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


def generate_goo(vmf: VMF) -> None:
    """Generate goo pit brushes and triggers."""
    # We want to use as few brushes as possible.
    # So group them by their min/max Z, and then produce bounding boxes.
    goo_pos: dict[tuple[float, float], dict[tuple[float, float], bool]] = defaultdict(dict)

    # For triggers, we want to only group by the top surface, we don't care
    # how deep.
    trig_pos: dict[float, dict[tuple[float, float], bool]] = defaultdict(dict)

    # Calculate the z-level with the largest number of goo brushes,
    # so we can ensure the 'fancy' pit is the largest one.
    # Valve just does it semi-randomly.
    goo_heights: dict[float, int] = Counter()

    # If enabled, generate tideline overlays.
    use_tidelines = options.get(bool, 'generate_tidelines')
    # Z, x-cell, y-cell, x-norm, y-norm = overlay ent.
    tideline_over: dict[tuple[float, float, float, int, int], Tideline] = {}

    pos: Vec | None = None
    for pos, block_type in BLOCK_POS.items():
        if block_type is Block.GOO_SINGLE:
            goo_pos[pos.z, pos.z][pos.x, pos.y] = True
        elif block_type is Block.GOO_TOP:
            # Multi-layer..
            lower_pos = BLOCK_POS.raycast(pos, Vec(0, 0, -1))

            goo_pos[lower_pos.z, pos.z][pos.x, pos.y] = True
        else:  # Not goo.
            continue
        goo_heights[pos.z] += 1
        trig_pos[pos.z][pos.x, pos.y] = True
        if use_tidelines:
            voxel_center = 128 * pos + 64
            for x, y in [(-1, 0), (0, -1), (1, 0), (0, 1)]:
                norm = Vec(x, y)
                try:
                    tile = TILES[(voxel_center - 128*norm).as_tuple(), (x, y, 0)]
                except KeyError:
                    continue
                side = Vec.cross(norm, (0.0, 0.0, -1.0))
                off = Vec.dot(voxel_center, side)

                # Divide the x/y into sections, so we don't extend the overlay
                # too much over too many faces.
                key = pos.z, pos.x//8, pos.y//8, x, y
                try:
                    tideline = tideline_over[key]
                except KeyError:
                    ent_pos = voxel_center + 32 * Vec(x, y, 1)
                    tideline = tideline_over[key] = Tideline(
                        vmf.create_ent(
                            'info_overlay',
                            material='material',  # Will be filled in the next loop.
                            angles='0 0 0',
                            origin=ent_pos,
                            basisOrigin=ent_pos,
                            basisNormal=f'{x} {y} 0',
                            basisU=side,
                            basisV='0 0 1',
                            startU='0',
                            startV='1',
                            endU='1',
                            endV='0',
                        ),
                        off, off, off,
                    )
                    OVERLAY_BINDS[tideline.over] = [tile]
                else:
                    tideline.min = min(tideline.min, off)
                    tideline.max = max(tideline.max, off)
                    OVERLAY_BINDS[tideline.over].append(tile)

    for tideline in tideline_over.values():
        tide_min = tideline.min - tideline.mid - 64
        tide_max = tideline.max - tideline.mid + 64
        rng = rand.seed(b'tideline', tide_min, tide_max)

        width = (tide_max - tide_min) / 128.0
        # Randomly flip around
        if rng.choice((False, True)):
            tideline.over['startu'] = 0
            tideline.over['endu'] = width
        else:
            tideline.over['endu'] = 0
            tideline.over['startu'] = width

        # Vary the ends up/down from 32, to distort a little.
        tideline.over['uv0'] = f'{tide_min} {rng.randint(-36, -28)} 0'
        tideline.over['uv1'] = f'{tide_min} {rng.randint(28, 32)} 0'
        tideline.over['uv2'] = f'{tide_max} {rng.randint(28, 32)} 0'
        tideline.over['uv3'] = f'{tide_max} {rng.randint(-36, -28)} 0'
        texturing.OVERLAYS.get(Vec.from_str(tideline.over['origin']), 'tideline').apply_over(tideline.over)

    # No goo.
    if not goo_pos or pos is None:
        return

    trig_phys = vmf.create_ent(
        'trigger_multiple',
        spawnflags='8',  # Physics Objects
        wait='0.1',
        origin=pos * 128,
    )
    trig_phys.add_out(
        Output('OnStartTouch', '!activator', 'SilentDissolve'),
        Output('OnStartTouch', '!activator', 'CallScriptFunction', 'FellInGoo', delay=0.01),
        Output('OnStartTouch', '!activator', 'Kill', delay=0.1),
    )

    trig_hurt = vmf.create_ent(
        'trigger_hurt',
        spawnflags='1',  # Clients
        damage='1000',
        damagecap='1000',
        damagetype=(1 << 18),  # Radiation
    )

    goo_scale = options.get(float, 'goo_scale')

    # Find key with the highest value - that gives the largest z-level.
    [best_goo, _] = max(goo_heights.items(), key=lambda x: x[1])

    for ((min_z, max_z), grid) in goo_pos.items():
        for min_x, min_y, max_x, max_y, _ in grid_optim.optimise(grid):
            bbox_min = Vec(min_x, min_y, min_z) * 128
            bbox_max = Vec(max_x, max_y, max_z) * 128
            prism = vmf.make_prism(
                bbox_min,
                bbox_max + (128, 128, 96),
            )
            # Apply goo scaling
            prism.top.scale = goo_scale
            # Use fancy goo on the level with the
            # highest number of blocks.
            # All plane z are the same.
            texturing.SPECIAL.get(
                bbox_max + (0, 0, 96), (
                    'goo' if
                    max_z == best_goo
                    else 'goo_cheap'
                ),
            ).apply(prism.top)
            vmf.add_brush(prism.solid)

    bbox_min = Vec()

    for (z, grid) in trig_pos.items():
        for min_x, min_y, max_x, max_y, _ in grid_optim.optimise(grid):
            bbox_min = Vec(min_x, min_y, z) * 128
            bbox_max = Vec(max_x, max_y, z) * 128
            trig_hurt.solids.append(vmf.make_prism(
                bbox_min,
                # 19 units below the surface.
                bbox_max + (128, 128, 96 - 19),
                mat=consts.Tools.TRIGGER,
            ).solid)
            trig_phys.solids.append(vmf.make_prism(
                bbox_min,
                # 70 units below the surface - 1 unit more than the height of a turret with its
                # antenna extended. Most likely this is why PeTI uses this particular height.
                bbox_max + (128, 128, 96 - 70),
                mat=consts.Tools.TRIGGER,
            ).solid)

    # Set to any random position for the entity.
    trig_phys['origin'] = trig_hurt['origin'] = bbox_min + 64
