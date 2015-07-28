# coding=utf-8
from collections import defaultdict, namedtuple
from decimal import Decimal
from enum import Enum
import random

from utils import CONN_TYPES

import vmfLib as VLib
import vbsp
import utils

settings = {}

EDGE_DIRS = [
    # The direction for each value in the edges array
    # x, y, offsets
    (0, 128),   # North
    (0, -128),  # South
    (128, 0),   # East
    (-128, 0)   # West
]


def load_settings(config):
    global settings
    pit = config.find_key("bottomless_pit", [])
    if pit:
        settings = {
            'tex_goo': pit['goo_tex', 'nature/toxicslime_a2_bridge_intro'],
            'tex_sky': pit['sky_tex', 'tools/toolsskybox'],
            'should_tele': utils.conv_bool(pit['teleport', '0']),
            'tele_dest': pit['tele_target', '@goo_targ'],
            'tele_ref': pit['tele_ref', '@goo_ref'],
            'off_x': utils.conv_int(pit['off_x', '0']) + 64,
            'off_y': utils.conv_int(pit['off_y', '0']) + 64,
            'height': utils.conv_int(pit['max_height', '386'], 386),
            'skybox': pit['sky_inst', ''],
            'skybox_ceil': pit['sky_inst_ceil', ''],
            'targ': pit['targ_inst', ''],
        }
        pit_inst = settings['pit']['inst'] = {}
        for inst_type in (
                'support',
                'side',
                'corner',
                'double',
                'triple',
                'pillar',
                ):
            vals = [prop.value for prop in pit.find_all(inst_type + '_inst')]
            if len(vals) == 0:
                vals = [""]
            pit_inst[inst_type] = vals
    else:
        settings.clear()


def find_goo_sides():
    teleport = settings['should_tele']
    tele_ref = settings['tele_ref']
    tele_dest = settings['tele_dest']

    # To figure out what positions need edge pieces, we use a dict
    # indexed by XY tuples. The four Nones match the NSEW directions.
    # For each trigger, we loop through the grid points it's in. We
    # set all the center parts to None, but set the 4 neighbouring
    # blocks if they aren't None.
    # If a value = None, it is occupied by goo.
    edges = defaultdict(lambda: [None, None, None, None])

    if teleport:
        # transform the skybox physics triggers into teleports to move cubes
            # into the skybox zone
        for trig in vbsp.VMF.by_class['trigger_multiple']:
            if trig['wait'] == '0.1':
                bbox_min, bbox_max = trig.get_bbox()
                origin = (bbox_min + bbox_max)/2
                """:type :Vec"""
                # We only modify triggers which are below the given z-index
                if origin.z < settings['height']:
                    trig['classname'] = 'trigger_teleport'
                    trig['spawnflags'] = '4106'  # Physics and npcs
                    trig['landmark'] = tele_ref
                    trig['target'] = tele_dest
                    trig.outputs.clear()
                    for x in range(int(bbox_min.x), int(bbox_max.x), 128):
                        for y in range(int(bbox_min.y), int(bbox_max.y), 128):
                            # Remove the pillar from the center of the item
                            edges[x, y] = None
                            for i, (xoff, yoff) in enumerate(EDGE_DIRS):
                                side = edges[x+xoff, y+yoff]
                                if side is not None:
                                    side[i] = origin.z - 13

                    # The triggers are 26 high, make them 10 units thick to
                    # make it harder to see the teleport
                    for side in trig.sides():
                        for plane in side.planes:
                            if plane.z > origin.z:
                                plane.z -= 16

    return edges


def add_supports(support_loc):
    tele_off_x = settings['tele_off_x']
    tele_off_y = settings['tele_off_y']

    supp_inst = settings['inst']['support']

    make_ent = vbsp.VMF.create_ent

    for (x, y, z) in support_loc:
        random.seed(str(x) + str(y) + '-support')
        file = random.choice(supp_inst)
        if file != '':
            make_ent(
                classname='func_instance',
                file=file,
                targetname='goo_support',
                angles='0 ' + str(random.randrange(0, 360, 90)) + ' 0',
                origin='{!s} {!s} {!s}'.format(
                    x+tele_off_x,
                    y+tele_off_y,
                    z,
                ),
            ).make_unique()


def add_edge_inst(edges):
    instances = settings['inst']
    tele_off_x = settings['tele_off_x']
    tele_off_y = settings['tele_off_y']

    side_types = {
        CONN_TYPES.side: instances['side'],
        CONN_TYPES.corner: instances['corner'],
        CONN_TYPES.straight: instances['double'],
        CONN_TYPES.triple: instances['triple'],
        CONN_TYPES.all: instances['pillar'],
        CONN_TYPES.none: [''],  # Never add instance if no walls
    }

    support_locs = set()

    utils.con_log('Pillar:', instances)
    for (x, y), mask in edges.items():
        if mask is None:
            continue  # This is goo

        random.seed(str(x) + str(y) + 'sides')

        inst_type, angle = utils.CONN_LOOKUP[
            tuple((val is not None) for val in mask)
        ]

        file = random.choice(side_types[inst_type])

        highest_point = max(
            x
            for x in mask
            if x is not None
        )

        if file != '':
            vbsp.VMF.create_ent(
                classname='func_instance',
                file=file,
                targetname='goo_side',
                origin='{!s} {!s} {!s}'.format(
                    x+tele_off_x,
                    y+tele_off_y,
                    highest_point,
                ),
                angles=angle,
            ).make_unique()

        if mask is CONN_TYPES.corner or mask is CONN_TYPES.all:
            # These always have supports
            support_locs.add(
                (x, y, highest_point)
            )
        elif mask is CONN_TYPES.triple:
            # Triple sections have the support in the adjacent block
            for (jump_x,jump_y), mask_part in zip(EDGE_DIRS, mask):
                # Look in each direction, then add a support there.
                if mask_part is not None:
                    support_locs.add(
                        (x+jump_x, y+jump_y, max(
                            x
                            for x in edges[x+jump_x, y+jump_y]
                            if x is not None
                        ))
                    )

    return support_locs


def make_bottomless_pit(solids, max_height):
    """Transform all the goo pits into bottomless pits."""
    tex_sky = settings['tex_sky']
    tele_off_x = settings['tele_off_x'] - 128
    tele_off_y = settings['tele_off_y'] - 128

    for solid, wat_face in solids:
        wat_face.mat = tex_sky
        for vec in wat_face.planes:
            vec.z = float(Decimal(vec.z) - Decimal('95.5'))
            # subtract 95.5 from z axis to make it 0.5 units thick
            # we do the calc with Decimal to ensure precision

    if settings['skybox'] != '':
        # Add in the actual skybox edges and triggers
        vbsp.VMF.create_ent(
            classname='func_instance',
            file=settings['skybox'],
            targetname='skybox',
            angles='0 0 0',
            origin='{!s} {!s} 0'.format(
                tele_off_x,
                tele_off_y,
            ),
        )

    if settings['skybox_ceil'] != '':
        # We dynamically add the ceiling so it resizes to match the map,
        # and lighting won't be too far away.
        vbsp.VMF.create_ent(
            classname='func_instance',
            file=settings['skybox_ceil'],
            targetname='skybox',
            angles='0 0 0',
            origin='{!s} {!s} {!s}'.format(
                tele_off_x,
                tele_off_y,
                max_height,
            ),
        )

    if settings['targ'] != '':
        # Add in the relative target for the triggers.
        vbsp.VMF.create_ent(
            classname='func_instance',
            file=settings['targ'],
            targetname='skybox',
            angles='0 0 0',
            origin='0 0 0',
        )

    edges = find_goo_sides()

    supp_loc = add_edge_inst(edges)

    add_supports(supp_loc)




def iter_grid(dist_x, dist_y, stride=1):
    """Loop over a rectangular grid area."""
    for x in range(0, dist_x, stride):
        for y in range(0, dist_y, stride):
            yield x, y


def add_goo_mist(sides):
    """Add water_mist* particle systems to goo.

    This uses larger particles when needed to save ents.
    """
    needs_mist = sides  # Locations that still need mist
    sides = sorted(sides)
    fit_goo_mist(
        sides, needs_mist,
        grid_x=1024,
        grid_y=512,
        particle='water_mist_1024_512',
        angles='0 0 0',
    )

    fit_goo_mist(
        sides, needs_mist,
        grid_x=512,
        grid_y=1024,
        particle='water_mist_1024_512',
        angles='0 90 0',
    )

    fit_goo_mist(
        sides, needs_mist,
        grid_x=512,
        grid_y=512,
        particle='water_mist_512',
    )

    fit_goo_mist(
        sides, needs_mist,
        grid_x=256,
        grid_y=256,
        particle='water_mist_256',
    )

    # There isn't a 128 particle so use 256 centered
    fit_goo_mist(
        sides, needs_mist,
        grid_x=128,
        grid_y=128,
        particle='water_mist_256',
    )


def fit_goo_mist(
        sides,
        needs_mist,
        grid_x,
        grid_y,
        particle,
        angles='0 0 0',
        ):
    """Try to add particles of the given size.

    needs_mist is a set of all added sides, so we don't double-up on a space.
    """
    if grid_y is None:
        grid_y = grid_x
    for pos in sides:
        if pos not in needs_mist:
            continue  # We filled this space already
        for x, y in iter_grid(grid_x, grid_y, 128):
            if (pos.x+x, pos.y+y, pos.z) not in needs_mist:
                break  # Doesn't match
        else:
            vbsp.VMF.create_ent(
                classname='info_particle_system',
                targetname='@goo_mist',
                start_active='1',
                effect_name=particle,
                origin='{x!s} {y!s} {z!s}'.format(
                    x=pos.x + (grid_x/2 - 64),
                    y=pos.y + (grid_y/2 - 64),
                    z=pos.z + 48,
                ),
                angles=angles,
            )
            for (x, y) in iter_grid(grid_x, grid_y, 128):
                needs_mist.remove((pos.x+x, pos.y+y, pos.z))


def change_goo_sides():
    """Replace the textures on the sides of goo with specific ones.

    """
    if vbsp.settings['textures']['special.goo_wall'] == ['']:
        return
    utils.con_log("Changing goo sides...")
    face_dict = {}
    for solid in vbsp.VMF.iter_wbrushes(world=True, detail=False):
        for face in solid:
            if face.mat.casefold() != 'tools/toolsnodraw':
                # Don't record the goo textured brushes
                x, y, z = face.get_origin()
                face_dict[x, y, z] = face

    dirs = [
        # x, y, z
        (0, 64, 0),  # North
        (0, -64, 0),  # South
        (64, 0, 0),  # East
        (-64, 0, 0),  # West
        (0, 0, -64),  # Down
    ]
    for trig in vbsp.VMF.by_class['trigger_multiple']:
        if trig['wait'] != '0.1':
            continue
        bbox_min, bbox_max = trig.get_bbox()
        z = int(bbox_min.z + 64)
        for x in range(int(bbox_min.x)+64, int(bbox_max.x), 128):
            for y in range(int(bbox_min.y)+64, int(bbox_max.y), 128):
                for xoff, yoff, zoff in dirs:
                    try:
                        face = face_dict[x+xoff, y+yoff, z+zoff]
                    except KeyError:
                        continue

                    utils.con_log('Success: ', face.mat.casefold())
                    if (
                            face.mat.casefold() in vbsp.BLACK_PAN or
                            face.mat.casefold() == 'tools/toolsnodraw'
                            ):
                        face.mat = vbsp.get_tex('special.goo_wall')
    utils.con_log("Done!")


def collapse_goo_trig():
    """Collapse the goo triggers to only use 2 entities for all pits."""
    utils.con_log('Collapsing goo triggers...')

    hurt_trig = None
    cube_trig = None
    for trig in vbsp.VMF.by_class['trigger_multiple']:
        if trig['wait'] == '0.1' and trig['targetname', ''] == '':
            if cube_trig is None:
                cube_trig = trig
            else:
                cube_trig.solids.extend(trig.solids)
                trig.remove()

    for trig in vbsp.VMF.by_class['trigger_hurt']:
        if trig['targetname', ''] == '':
            if hurt_trig is None:
                hurt_trig = trig
            else:
                hurt_trig.solids.extend(trig.solids)
                trig.remove()

    if hurt_trig is not None:
        hurt_trig['damage'] = '99999'
        hurt_trig.outputs.append(
            VLib.Output(
                'OnHurtPlayer',
                '@goo_fade',
                'Fade',
            ),
        )

    utils.con_log('Done!')