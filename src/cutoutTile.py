"""Generate random quarter tiles, like in Destroyed or Retro maps."""
from collections import defaultdict

import random

from utils import Vec
from instanceLocs import resolve as resolve_inst

import utils
import vmfLib as VLib
import conditions
import vbsp

TEX_DEFAULT = [
    ('squarebeams', 'anim_wp/framework/squarebeams'),
    ('ceilingwalls', 'anim_wp/framework/backpanels_cheap'),
    ('floorbase', 'anim_wp/framework/backpanels'),
    ('tile_glue', 'concrete/concrete_modular_floor001e'),
    ('clip', 'tools/toolsplayerclip'),
]


@conditions.make_result('CutOutTile')
def res_cutout_tile(inst, res):
    """Generate random quarter tiles, like in Destroyed or Retro maps.

    - "MarkerItem" is the instance to look for.
    - "TileSize" can be "2x2" or "4x4".

    Materials:
    - "squarebeams" is the squarebeams variant to use.
    - "ceilingwalls" are the sides of the ceiling section.
    - "floorbase" is the texture under floor sections.
    - "tile_glue" is used on top of a thinner tile segment.
    - "clip" is the player_clip texture used over floor segments.
        (This allows customising the surfaceprop.)
    - "Floor4x4Black", "Ceil2x2White" and other combinations can be used to
       override the textures used.
    """
    item = resolve_inst(res['markeritem'])

    INST_LOCS = {}  # Map targetnames -> surface loc
    CEIL_IO = []  # Pairs of ceil inst corners to cut out.
    FLOOR_IO = []  # Pairs of floor inst corners to cut out.

    overlay_ids = {}  # When we replace brushes, we need to fix any overlays
    # on that surface.

    # The solid locations which we're removing from the map. By leaving them
    # in the map until after the condition is evaulated, floor sections will
    # harmlessly modify each other's side textures instead of generating
    # brushes at the junction points of seperate tile 'groups'.
    brushes_to_remove = []

    MATS = defaultdict(list)
    SETTINGS = {
        'floor_chance': utils.conv_int(
            res['floorChance', '100'], 100),
        'ceil_chance': utils.conv_int(
            res['ceilingChance', '100'], 100),
        'floor_glue_chance': utils.conv_int(
            res['floorGlueChance', '0']),
        'ceil_glue_chance': utils.conv_int(
            res['ceilingGlueChance', '0']),

        'beam_skin': res['squarebeamsSkin', '0'],

        'quad_floor': res['FloorSize', '4x4'].casefold() == '2x2',
        'quad_ceil': res['CeilingSize', '4x4'].casefold() == '2x2',
    }

    for mat_prop in res['Materials', []]:
        MATS[mat_prop.name].append(mat_prop.value)

    for key, default in TEX_DEFAULT:
        if key not in MATS:
            MATS[key] = [default]

    # Find our marker ents
    for inst in conditions.VMF.by_class['func_instance']:
        if inst['file'].casefold() not in item:
            continue
        targ = inst['targetname']
        orient = Vec(0, 0, 1).rotate_by_str(inst['angles', '0 0 0'])
        # Check the orientation of the marker to figure out what to generate
        if orient == (0, 0, 1):
            io_list = FLOOR_IO
        else:
            io_list = CEIL_IO

        # Reuse orient to calculate where the solid face will be.
        loc = (orient * -64) + Vec.from_str(inst['origin'])
        INST_LOCS[targ] = loc

        for out in {out.target for out in inst.outputs}:
            io_list.append((targ, out))
        inst.remove()  # Remove the instance itself from the map.
    for start_floor, end_floor in FLOOR_IO:
        if end_floor not in INST_LOCS:
            # Not a marker!
            for inst in conditions.VMF.by_target[end_floor]:
                inst.remove()
            continue

        detail_ent = conditions.VMF.create_ent(
            classname='func_detail'
        )

        box_min = Vec(INST_LOCS[start_floor])
        box_min.min(INST_LOCS[end_floor])

        box_max = Vec(INST_LOCS[start_floor])
        box_max.max(INST_LOCS[end_floor])

        if box_min.z != box_max.z:
            continue  # They're not in the same axis!
        z = box_min.z

        conditions.VMF.add_brush(conditions.VMF.make_prism(
            p1=box_min - Vec(64, 64, 8),
            p2=box_max + Vec(64, 64, 0),
            mat=MATS['clip'][0],
        ).solid)

        # Add a noportal_volume covering the surface, in case there's
        # room for a portal.
        conditions.VMF.create_ent(
            classname='func_noportal_volume',
            origin=box_min.join(' '),
        ).solids.append(
            conditions.VMF.make_prism(
                p1=box_min - Vec(63, 63, 2),
                p2=box_max + Vec(63, 63, 4),
                mat='tools/toolsinvisible',
            ).solid
        )

        for x, y in utils.iter_grid(
                min_x=int(box_min.x),
                max_x=int(box_max.x)+1,
                min_y=int(box_min.y),
                max_y=int(box_max.y)+1,
                stride=128,
                ):
            convert_floor(
                Vec(x, y, z),
                overlay_ids,
                MATS,
                SETTINGS,
                detail_ent,
            )

    reallocate_overlays(overlay_ids)

    return True


def convert_floor(loc, overlay_ids, mats, settings, detail):
    """Cut out tiles at the specified location."""
    try:
        brush = conditions.SOLIDS[loc.as_tuple()]
    except KeyError:
        return False  # No tile here!

    # The new brush IDs overlays need to use
    # NOTE: strings, not ints!
    ant_locs = overlay_ids[str(brush.face.id)] = []

    # Remove the original brush from the map!
    conditions.VMF.remove_brush(brush.solid)

    conditions.VMF.create_ent(
        classname='prop_static',
        angles='0 0 0',
        origin=loc.join(' '),
        model='models/anim_wp/framework/squarebeam_off_2x2.mdl',
        skin=settings['beam_skin'],
        disableshadows='1',
    )

    loc.x -= 64
    loc.y -= 64

    random.seed('cutout_tile' + loc.join(' '))
    tile_map = [
        (random.randint(0, 100) < settings['floor_chance'])
        for _ in range(16)
    ]

    for x, y in utils.iter_grid(max_x=4, max_y=4):
        if tile_map[x*4 + y]:
            # Full tile
            tile_loc = loc + Vec(x*32, y*32, 0)
            tile = make_tile(
                p1=tile_loc,
                p2=tile_loc + Vec(32, 32, -2),
                top_mat=vbsp.get_tex(str(brush.color) + '.floor'),
                bottom_mat='tools/toolsnodraw',
                beam_mat=random.choice(mats['squarebeams']),
            )
            detail.solids.append(tile.solid)
            ant_locs.append(str(tile.top.id))
        else:
            # No tile at this loc!
            pass

    base_brush = conditions.VMF.make_prism(
        p1=loc + Vec(0, 0, -16),
        p2=loc + Vec(128, 128, -8)
    )
    base_brush.top.mat = random.choice(mats['floorbase'])
    conditions.VMF.add_brush(base_brush.solid)


def make_tile(p1, p2, top_mat, bottom_mat, beam_mat):
    """Generate a 2 or 1 unit thick squarebeams tile.

    """
    prism = conditions.VMF.make_prism(p1, p2)
    brush, t, b, n, s, e, w = prism
    t.mat = top_mat
    b.mat = bottom_mat

    n.mat = beam_mat
    s.mat = beam_mat
    e.mat = beam_mat
    w.mat = beam_mat

    # The z-axis texture offset needed
    # The texture is 512 max, so wrap around
    # 56 is the offset for the thin-line part of squarebeams
    z_off = ((max(p1.z, p2.z) * 12) + 56) % 512

    n.uaxis = VLib.UVAxis(
        0, 0, 1, offset=z_off)
    n.vaxis = VLib.UVAxis(
        1, 0, 0, offset=0)
    s.uaxis = n.uaxis.copy()
    s.vaxis = n.vaxis.copy()

    e.uaxis = VLib.UVAxis(
        0, 0, 1, offset=z_off)
    e.vaxis = VLib.UVAxis(
        0, 1, 0, offset=0)
    w.uaxis = e.uaxis.copy()
    w.vaxis = e.vaxis.copy()

    # Ensure the squarebeams textures aren't replaced, as well as floor tex
    vbsp.IGNORED_FACES.update(brush.sides)

    return prism


def _make_squarebeam(x,y,z, skin='0', size=''):
    """Make a squarebeam prop at the given location."""
    conditions.VMF.create_ent(
        classname='prop_static',
        angles='0 0 0',
        origin='{} {} {}'.format(x, y, z),
        model='models/anim_wp/framework/squarebeam_off' + size + '.mdl',
        skin=skin,
        disableshadows='1',
    )


def gen_squarebeams(p1, p2, skin):
    """Generate squarebeams props to fill the space given.

    The space should be in multiples of 64. The squarebeams brush will
    be aligned to the lowest point in the space.
    """
    z = min(p1.z, p2.z) + 8
    min_x = min(p1.x, p2.x)
    min_y = min(p1.y, p2.y)
    max_x = max(p1.x, p2.x)
    max_y = max(p1.y, p2.y)

    dist_x = max_x - min_x
    dist_y = max_y - min_y

    # After this x or y dist, move to the next grid size.
    cutoff_512 = min(dist_x // 512, dist_y // 512) * 512
    cutoff_256 = min(dist_x // 256, dist_y // 256) * 256
    cutoff_128 = min(dist_x // 128, dist_y // 128) * 128

    for x, y in utils.iter_grid(
            min_x=min_x,
            min_y=min_y,
            max_x=max(p1.x, p2.x) + 64,
            max_y=max(p1.y, p2.y) + 64,
            stride=64,
            ):
        dist = max(x-min_x, y-min_y)
        if dist < cutoff_512:
            # Make 1 prop every 512 units, at the center
            if (dist + 256) % 512 == 0:
                _make_squarebeam(x, y, z, skin, '_8x8')
        elif dist < cutoff_256:
            if (dist + 128) % 256 == 0:
                _make_squarebeam(x, y, z, skin, '_4x4')
        elif dist < cutoff_128:
            if (dist + 64) % 128 == 0:
                _make_squarebeam(x, y, z, skin, '_2x2')
        else:
            # Make squarebeams for every point!
            _make_squarebeam(x + 32, y + 32, z, skin)



def reallocate_overlays(mapping):
    """Fix any overlay faces which were removed.
    This makes antlines continue to appear on the small tiles.
    """
    for overlay in conditions.VMF.by_class['info_overlay']:
        sides = overlay['sides', ''].split(' ')
        for side in sides[:]:
            if side not in mapping:
                continue
            sides.remove(side)
            sides.extend(mapping[side])
        overlay['sides'] = ' '.join(sides)