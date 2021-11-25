"""Logic for generating the overall map geometry."""
from __future__ import annotations
from collections import Counter, defaultdict, abc

import attrs
from srctools import Angle, Entity, Output, VMF, Vec, logger

import consts
import utils
from plane import Plane
from precomp import grid_optim, options, rand, texturing
from precomp.brushLoc import Block, POS as BLOCK_POS
from precomp.texturing import Portalable, TileSize
from precomp.tiling import OVERLAY_BINDS, TILES, TileDef, TileType, make_tile


LOGGER = logger.get_logger(__name__)


@attrs.define(frozen=False)
class Tideline:
    """Temporary data used to hold the in-progress tideline overlays."""
    over: Entity
    mid: float
    min: float
    max: float


def bevel_split(
    rect_points: Plane[bool],
    tile_pos: Plane[TileDef],
) -> abc.Iterator[tuple[int, int, int, int, tuple[bool, bool, bool, bool]]]:
    """Split the optimised segments to produce the correct bevelling."""
    for min_u, min_v, max_u, max_v, _ in grid_optim.optimise(rect_points):
        u_range = range(min_u, max_u + 1)
        v_range = range(min_v, max_v + 1)

        # These are sort of reversed around, which is a little confusing.
        # Bevel U is facing in the U direction, running across the V.
        bevel_umins: list[bool] = [
            tile_pos[min_u, v].should_bevel(-1, 0)
            for v in v_range
        ]
        bevel_umaxes: list[bool] = [
            tile_pos[max_u, v].should_bevel(1, 0)
            for v in v_range
        ]
        bevel_vmins: list[bool] = [
            tile_pos[u, min_v].should_bevel(0, -1)
            for u in u_range
        ]
        bevel_vmaxes: list[bool] = [
            tile_pos[u, max_v].should_bevel(0, 1)
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
                )


def generate_brushes(vmf: VMF) -> None:
    """Generate all the brushes in the map, then set overlay sides."""
    LOGGER.info('Generating tiles...')
    # Each tile is either a full-block tile, or some kind of subtile/special surface.
    # Each subtile is generated individually. If it's a full-block tile we
    # try to merge tiles together with the same texture.

    # The key is (normal, plane distance, tile type)
    full_tiles: dict[
        tuple[float, float, float, float, TileType],
        list[TileDef]
    ] = defaultdict(list)

    for tile in TILES.values():
        if tile.is_simple():
            pos = tile.pos + 64 * tile.normal
            plane_dist = abs(pos.dot(tile.normal))

            full_tiles[
                tile.normal.x, tile.normal.y, tile.normal.z,
                plane_dist,
                tile.base_type,
            ].append(tile)

            if tile.has_portal_helper:
                # Add the portal helper in directly.
                vmf.create_ent(
                    'info_placement_helper',
                    angles=Angle.from_basis(x=tile.normal, z=tile.portal_helper_orient),
                    origin=pos,
                    force_placement=int(tile.has_oriented_portal_helper),
                    snap_to_helper_angles=int(tile.has_oriented_portal_helper),
                    radius=64,
                )
        else:
            tile.export(vmf)

    for (norm_x, norm_y, norm_z, plane_dist, tile_type), tiles in full_tiles.items():
        # Construct each plane of tiles.
        normal = Vec(norm_x, norm_y, norm_z)
        norm_axis = normal.axis()
        u_axis, v_axis = Vec.INV_AXIS[norm_axis]
        # (type, is_antigel, texture) -> (u, v) -> present/absent
        grid_pos: dict[tuple[TileType, bool, str], Plane[bool]] = defaultdict(Plane)

        tile_pos: Plane[TileDef] = Plane()

        for tile in tiles:
            pos = tile.pos + 64 * tile.normal

            if tile_type is TileType.GOO_SIDE:
                # This forces a specific size.
                tex = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    Portalable.BLACK
                ).get(pos, TileSize.GOO_SIDE, antigel=False)
            elif tile_type is TileType.NODRAW:
                tex = consts.Tools.NODRAW
            else:
                tex = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    tile.base_type.color
                ).get(pos, tile.base_type.tile_size, antigel=tile.is_antigel)

            u_pos = int((pos[u_axis]) // 128)
            v_pos = int((pos[v_axis]) // 128)
            grid_pos[tile.base_type, tile.is_antigel, tex][u_pos, v_pos] = True
            tile_pos[u_pos, v_pos] = tile

        for (subtile_type, is_antigel, tex), tex_pos in grid_pos.items():
            for min_u, min_v, max_u, max_v, bevels in bevel_split(tex_pos, tile_pos):
                center = Vec.with_axes(
                    norm_axis, plane_dist,
                    # Compute avg(128*min, 128*max)
                    # = (128 * min + 128 * max) / 2
                    # = (min + max) * 64
                    u_axis, (min_u + max_u) * 64,
                    v_axis, (min_v + max_v) * 64,
                )
                gen = texturing.gen(
                    texturing.GenCat.NORMAL,
                    normal,
                    subtile_type.color
                )
                if TileSize.TILE_DOUBLE in gen and (1 + max_u - min_u) % 2 == 0 and (1 + max_v - min_v) % 2 == 0:
                    is_double = True
                    tex = gen.get(center, TileSize.TILE_DOUBLE, antigel=is_antigel)
                else:
                    is_double = False

                brush, front = make_tile(
                    vmf,
                    center,
                    normal,
                    tex,
                    texturing.SPECIAL.get(center, 'behind', antigel=is_antigel),
                    bevels=bevels,
                    width=(1 + max_u - min_u) * 128,
                    height=(1 + max_v - min_v) * 128,
                    antigel=is_antigel,
                )
                vmf.add_brush(brush)
                if is_double:
                    # Compute the offset so that a 0,0 aligned brush can be
                    # offset so that point is at the minimum point of the tile,
                    # then round to the nearest 256 tile.
                    # That will ensure it gets the correct texturing.
                    # We know the scale is 0.25, so don't bother looking that up.
                    tile_min = Vec.with_axes(
                        norm_axis, plane_dist,
                        u_axis, 128 * min_u - 64,
                        v_axis, 128 * min_v - 64,
                    )
                    front.uaxis.offset = (Vec.dot(tile_min, front.uaxis.vec()) / 0.25) % (256/0.25)
                    front.vaxis.offset = (Vec.dot(tile_min, front.vaxis.vec()) / 0.25) % (256/0.25)
                    if gen.options['scaleup256']:
                        # It's actually a 128x128 tile, that we want to double scale for.
                        front.scale = 0.5
                        front.uaxis.offset /= 2
                        front.vaxis.offset /= 2

                for u in range(min_u, max_u + 1):
                    for v in range(min_v, max_v + 1):
                        tile_pos[u, v].brush_faces.append(front)

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
                            material=texturing.OVERLAYS.get(ent_pos, 'tideline'),
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
            prism.top.mat = texturing.SPECIAL.get(
                bbox_max + (0, 0, 96), (
                    'goo' if
                    max_z == best_goo
                    else 'goo_cheap'
                ),
            )
            vmf.add_brush(prism.solid)

    bbox_min = Vec()

    for (z, grid) in trig_pos.items():
        for min_x, min_y, max_x, max_y, _ in grid_optim.optimise(grid):
            bbox_min = Vec(min_x, min_y, z) * 128
            bbox_max = Vec(max_x, max_y, z) * 128
            trig_hurt.solids.append(vmf.make_prism(
                bbox_min,
                bbox_max + (128, 128, 77),
                mat=consts.Tools.TRIGGER,
            ).solid)
            trig_phys.solids.append(vmf.make_prism(
                bbox_min,
                bbox_max + (128, 128, 26),
                mat=consts.Tools.TRIGGER,
            ).solid)

    # Set to any random position for the entity.
    trig_phys['origin'] = trig_hurt['origin'] = bbox_min + 64
