"""Handles user errors found, displaying a friendly interface to the user."""
from __future__ import annotations
from typing import Final, Literal

from pathlib import Path
from collections.abc import Iterable, Mapping
import pickle

from srctools import FrozenVec, Vec, VMF, AtomicWriter, logger
import attrs

from user_errors import DATA_LOC, UserError, TOK_VBSP_LEAK
from precomp.tiling import TileDef
from precomp.brushLoc import Grid as BrushLoc
from precomp import options, barriers, grid_optim
from plane import PlaneKey, PlaneGrid
import consts


__all__ = ['UserError', 'TOK_VBSP_LEAK', 'load_tiledefs']

LOGGER = logger.get_logger(__name__)
NORM_2_ORIENT: Final[Mapping[FrozenVec, Literal['u', 'd', 'n', 's', 'e', 'w']]] = {
    FrozenVec(0.0, 0.0, +1.0): 'u',
    FrozenVec(0.0, 0.0, -1.0): 'd',
    FrozenVec(0.0, +1.0, 0.0): 'n',
    FrozenVec(0.0, -1.0, 0.0): 's',
    FrozenVec(+1.0, 0.0, 0.0): 'e',
    FrozenVec(-1.0, 0.0, 0.0): 'w',
}


def _vec2tup(vec: Vec | FrozenVec) -> tuple[float, float, float]:
    """Convert a vector to a tuple for putting in the error JSON."""
    return (round(vec.x, 12), round(vec.y, 12), round(vec.z, 12))


def load_tiledefs(tiles: Iterable[TileDef], grid: BrushLoc) -> None:
    """Load tiledef info into a simplified tiles list."""

    tiles_white = UserError.simple_tiles["white"]
    tiles_black = UserError.simple_tiles["black"]
    tiles_goo_partial = UserError.simple_tiles["goopartial"]
    tiles_goo_full = UserError.simple_tiles["goofull"]
    for tile in tiles:
        if not tile.base_type.is_tile:
            continue
        block_type = grid.lookup_world(tile.pos + 128 * tile.normal)
        if not block_type.inside_map:
            continue
        # Tint the area underneath goo, by just using two textures with the appropriate tints.
        if tile.base_type.is_goo_side:
            if block_type.is_top and tile.normal.z < 0.9:
                tile_list = tiles_goo_partial
            else:
                tile_list = tiles_goo_full
        elif tile.base_type.is_white:
            tile_list = tiles_white
        else:
            tile_list = tiles_black
        tile_list.append({
            'orient': NORM_2_ORIENT[tile.normal.freeze()],
            'position': _vec2tup((tile.pos + 64 * tile.normal) / 128),
            'width': 1.0,
            'height': 1.0,
        })
    goo_tiles = UserError.simple_tiles["goo"]
    for pos, block in grid.items():
        if block.is_top:  # Both goo and bottomless pits.
            goo_tiles.append({
                'orient': 'd',
                'position': _vec2tup(pos + (0.5, 0.5, 0.75)),
                'width': 1.0,
                'height': 1.0,
            })
    LOGGER.info('Stored map geometry for error display.')


def load_barriers(barrier_map: dict[PlaneKey, PlaneGrid[barriers.Barrier]]) -> None:
    """Load barrier data for display in errors."""
    for plane, grid in barrier_map.items():
        orient = NORM_2_ORIENT[plane.normal]
        for min_u, min_v, max_u, max_v, barrier in grid_optim.optimise(grid):
            if barrier.type.error_disp is None:
                continue
            try:
                tile_list = UserError.simple_tiles[barrier.type.error_disp]
            except KeyError:
                continue
            max_u += 1
            max_v += 1
            pos = plane.plane_to_world(
                32.0 * (min_u + max_u) / 2.0,
                32.0 * (min_v + max_v) / 2.0,
                1.0,
            )
            tile_list.append({
                'orient': orient,
                'position': _vec2tup(pos / 128.0),
                'width': 0.25 * (max_u - min_u),
                'height': 0.25 * (max_v - min_v),
            })


def make_map(error: UserError) -> VMF:
    """Generate a map which triggers the error each time.

    This map is as simple as possible to make compile time quick.
    The content loc is the location of the web resources.
    """
    lang_filename = options.ERROR_TRANSLATIONS()
    if lang_filename and (lang_path := Path(lang_filename)).is_file():
        info = attrs.evolve(error.info, language_file=lang_path)
    else:
        info = error.info
    with AtomicWriter(DATA_LOC, is_bytes=True) as f:
        pickle.dump(info, f, pickle.HIGHEST_PROTOCOL)

    LOGGER.info('Localisation file: {!r}', lang_filename)

    vmf = VMF()
    vmf.map_ver = 1
    vmf.spawn['skyname'] = 'sky_black_nofog'
    vmf.spawn['detailmaterial'] = "detail/detailsprites"
    vmf.spawn['detailvbsp'] = "detail.vbsp"
    vmf.spawn['maxblobcount'] = "250"
    vmf.spawn['paintinmap'] = "0"

    vmf.add_brushes(vmf.make_hollow(
        Vec(),
        Vec(128, 128, 128),
        thick=32,
        mat=consts.Tools.NODRAW,
        inner_mat=consts.Tools.BLACK,
    ))
    # Ensure we have at least one lightmapped surface,
    # so VRAD computes lights.
    roof_detail = vmf.make_prism(
        Vec(48, 48, 120),
        Vec(80, 80, 124)
    )
    roof_detail.top.mat = consts.BlackPan.BLACK_FLOOR
    roof_detail.top.scale = 64
    vmf.create_ent('func_detail').solids.append(roof_detail.solid)

    # VScript displays the webpage, then kicks you back to the editor
    # if the map is swapped back to. VRAD detects the classname and adds the script.
    vmf.create_ent(
        'bee2_user_error',
        origin="64 64 1",
        angles="0 0 0",
    )
    # We need a light, so the map compiles lights and doesn't turn on mat_fullbright.
    vmf.create_ent(
        'light',
        origin="64 64 64",
        angles="0 0 0",
        spawnflags="0",
        _light="255 255 255 1",
        _lightHDR="-1 -1 -1 -1",
        _lightscaleHDR="1",
        _constant_attn="0",
        _quadratic_attn="1",
        _linear_attn="1",
    )
    # Needed to get a default cubemap to be generated.
    vmf.create_ent('env_cubemap', origin='64 64 64')
    # Put two coop spawns in there too.
    vmf.create_ent(
        'info_coop_spawn',
        origin="64 32 1",
        angles="0 0 0",
        forcegunonspawn=0,
        targetname='supress_orange_portalgun_spawn',  # Stop guns
        startingteam=2,
        enabled=1,
    )
    vmf.create_ent(
        'info_coop_spawn',
        origin="64 96 1",
        angles="0 0 0",
        forcegunonspawn=0,
        targetname='supress_blue_portalgun_spawn',
        startingteam=3,
        enabled=1,
    )
    # Suppress portalgun spawn, pinging, taunts
    for state in [
        'portalgun_nospawn',
        'no_pinging_blue', 'no_pinging_orange',
        'no_taunting_blue', 'no_taunting_orange',
    ]:
        vmf.create_ent(
            'env_global',
            origin='64 64 32',
            globalstate=state,
            initialstate=1,
            counter=0,
            spawnflags=1,  # Set initial state
        )
    return vmf
