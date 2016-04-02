"""Implements the cutomisable vactube items.
"""
from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
    import_template, remove_ant_toggle,
    TEMP_TYPES, GOO_LOCS,
)
from instanceLocs import resolve as resolve_inst
from utils import Vec
import vmfLib as VLib
import conditions
import utils
import vbsp

LOGGER = utils.getLogger(__name__, alias='cond.vactubes')

PUSH_SPEED = 400  # The speed of the push triggers.
UP_PUSH_SPEED = 600  # Make it slightly faster when up to counteract gravity


xp = utils.Vec_tuple(1, 0, 0)
xn = utils.Vec_tuple(-1, 0, 0)
yp = utils.Vec_tuple(0, 1, 0)
yn = utils.Vec_tuple(0, -1, 0)
zp = utils.Vec_tuple(0, 0, 1)
zn = utils.Vec_tuple(0, 0, -1)

# start, end normals -> angle of corner instance and the unchanged axis
CORNER_ANG = {
    (zp, xp): ('0 0 0', 'y'),
    (zp, xn): ('0 180 0', 'y'),
    (zp, yp): ('0 90 0', 'x'),
    (zp, yn): ('0 270 0', 'x'),

    (zn, xp): ('0 0 180', 'y'),
    (zn, xn): ('0 180 180', 'y'),
    (zn, yp): ('0 90 180', 'x'),
    (zn, yn): ('0 270 180', 'x'),

    (xp, yp): ('0 90 90', 'z'),
    (xp, yn): ('0 270 270', 'z'),
    (xp, zp): ('270 180 0', 'y'),
    (xp, zn): ('90 0 0', 'y'),

    (xn, yp): ('0 90 270', 'z'),
    (xn, yn): ('0 270 90', 'z'),
    (xn, zp): ('270 0 0', 'y'),
    (xn, zn): ('90 180 0', 'y'),

    (yp, zp): ('270 270 0', 'x'),
    (yp, zn): ('90 90 0', 'x'),
    (yp, xp): ('0 0 270', 'z'),
    (yp, xn): ('0 180 90', 'z'),

    (yn, zp): ('270 90 0', 'x'),
    (yn, zn): ('90 270 0', 'x'),
    (yn, xn): ('0 180 270', 'z'),
    (yn, xp): ('0 0 90', 'z'),
}

del xp, xn, yp, yn, zp, zn


def follow_vac_path(inst_list, start_ent):
    """Given the start item and instance list, follow the programmed path."""
    cur_ent = start_ent
    while True:
        next_ent = inst_list.get(cur_ent['next'], None)
        if next_ent is None:
            return
        yield cur_ent, next_ent
        cur_ent = next_ent

# Store the configs for vactube items so we can
# join them together - multiple item types can participate in the same
# vatube track.
VAC_CONFIGS = {}


@make_result_setup('CustVactube')
def res_vactube_setup(res):
    group = res['group', 'DEFAULT_GROUP']

    if group not in VAC_CONFIGS:
        # Store our values in the CONFIGS dictionary
        config, inst_configs = VAC_CONFIGS[group] = {}, {}
    else:
        # Grab the already-filled values, and add to them
        config, inst_configs = VAC_CONFIGS[group]

    for block in res.find_all("Instance"):
        # Configuration info for each instance set..
        conf = {
            # The three sizes of corner instance
            ('corner', 1): block['corner_small_inst', ''],
            ('corner', 2): block['corner_medium_inst', ''],
            ('corner', 3): block['corner_large_inst', ''],

            ('corner_temp', 1): block['temp_corner_small', ''],
            ('corner_temp', 2): block['temp_corner_medium', ''],
            ('corner_temp', 3): block['temp_corner_large', ''],

            # Straight instances connected to the next part
            'straight': block['straight_inst', ''],

            'is_tsection': utils.conv_bool(block['is_tsection', '0']),

            ('entry', 'wall'): block['entry_inst'],
            ('entry', 'floor'): block['entry_floor_inst'],
            ('entry', 'ceiling'): block['entry_ceil_inst'],

            'exit': block['exit_inst'],
        }

        for prop in block.find_all("File"):
            try:
                size, file = prop.value.split(":", 1)
            except ValueError:
                size = 1
                file = prop.value

            inst_configs[resolve_inst(file)[0]] = conf, utils.conv_int(size, 1)

    return group


@make_result('CustVactube')
def res_make_vactubes(_, res):
    """Speciallised result to generate vactubes from markers.

    Only runs once, and then quits the condition list.
    Instances:
    """
    if res.value not in VAC_CONFIGS:
        # We've already executed this config group
        return RES_EXHAUSTED

    LOGGER.info(
        'Running Generator ({})...',
        res.value
    )
    CONFIG, INST_CONFIGS = VAC_CONFIGS[res.value]
    del VAC_CONFIGS[res.value]  # Don't let this run twice

    markers = {}

    # Find all our markers, so we can look them up by targetname.
    for inst in vbsp.VMF.by_class['func_instance']:  # type: VLib.Entity
        try:
            config, inst_size = INST_CONFIGS[inst['file'].casefold()]
        except KeyError:
            continue  # Not a marker

        next_instances = {
            out.target
            for out in
            inst.outputs
        }

        # Destroy these outputs, they're useless now!
        inst.outputs.clear()

        # Remove the original instance from the level - we spawn entirely new
        # ones.
        inst.remove()

        markers[inst['targetname']] = {
            'ent': inst,
            'conf': config,
            'next': next_instances,
            'prev': None,
            'size': inst_size,
        }

    if not markers:
        # No actual vactubes..
        return RES_EXHAUSTED

    for mark_name, marker in markers.items():
        for next_inst in marker['next']:
            try:
                next_marker = markers[next_inst]
                break
            except KeyError:
                # Not a marker-instance, remove this (indicator_toggles, etc)
                # We want to remove any them as well as the assoicated
                # antlines!
                for toggle in vbsp.VMF.by_target[next_inst]:
                    remove_ant_toggle(toggle)
                continue
        else:
            marker['next'] = None
            continue  # No next-instances

        marker['next'] = next_inst
        next_marker['prev'] = mark_name

    LOGGER.info('Markers: {}', markers.keys())

    for marker in markers.values():
        if marker['prev'] is not None:
            continue

        make_vac_track(marker, markers)


def make_vac_track(start, all_markers):
    """Create a vactube path section.

    """

    start_normal = Vec(-1, 0, 0).rotate_by_str(start['ent']['angles'])

    # First create the start section..
    start_logic = start['ent'].copy()
    vbsp.VMF.add_ent(start_logic)

    start_logic['file'] = start['conf']['entry', (
        'ceiling' if (start_normal.z > 0) else
        'floor' if (start_normal.z < 0) else
        'wall'
    )]

    end = start

    motion_trig = vbsp.VMF.create_ent(
        classname='trigger_vphysics_motion',
        SetGravityScale='0.0',
        spawnflags='1103',  # Clients, Physics, Everything
    )

    for inst, end in follow_vac_path(all_markers, start):
        motion_trig.solids.extend(
            join_markers(inst, end, inst is start)
        )

    end_loc = Vec.from_str(end['ent']['origin'])
    end_norm = Vec(-1, 0, 0).rotate_by_str(end['ent']['angles'])

    # join_markers creates straight parts up-to the marker, but not at it's
    # location - create the last one.
    motion_trig.solids.append(make_straight(
        end_loc,
        end_norm,
        128,
        end['conf']['straight'],
    ))

    # If the end is placed in goo, don't add logic - it isn't visible, and
    # the object is on a one-way trip anyway.
    if end_loc.as_tuple() not in GOO_LOCS:
        end_logic = end['ent'].copy()
        vbsp.VMF.add_ent(end_logic)
        end_logic['file'] = end['conf']['exit']


def push_trigger(loc, normal, solids):
    ent = vbsp.VMF.create_ent(
        classname='trigger_push',
        origin=loc,
        # The z-direction is reversed..
        pushdir=normal.to_angle(),
        speed=(UP_PUSH_SPEED if normal.z > 0 else PUSH_SPEED),
        spawnflags='1103',  # Clients, Physics, Everything
    )
    ent.solids.extend(solids)
    return ent


def make_straight(
        origin: Vec,
        normal: Vec,
        dist: int,
        file,
        is_start=False,
    ):
    """Make a straight line of instances from one point to another."""

    # 32 added to the other directions, plus extended dist in the direction
    # of the normal - 1
    p1 = origin + (normal * (dist - 96))
    # The starting brush needs to
    # stick out a bit further, to cover the
    # point_push entity.
    p2 = origin - (normal * (96 if is_start else 32))

    # bbox before +- 32 to ensure the above doesn't wipe it out
    p1, p2 = Vec.bbox(p1, p2)

    solid = vbsp.VMF.make_prism(
        # Expand to 64x64 in the other two directions
        p1 - 32, p2 + 32,
        mat='tools/toolstrigger',
    ).solid

    push_trigger(origin, normal, [solid])

    angles = normal.to_angle()

    for pos in range(0, int(dist), 128):
        vbsp.VMF.create_ent(
            classname='func_instance',
            origin=origin + pos * normal,
            angles=angles,
            file=file,
        )

    return solid.copy()


def make_bend(
        origin_a: Vec,
        origin_b: Vec,
        norm_a: Vec,
        norm_b: Vec,
        corner_ang: str,
        config,
        max_size: int,
):
    """Make a corner and the straight sections leading into it."""
    off = origin_b - origin_a
    # The distance to move first, then second.
    first_movement = Vec(norm_a.x * off.x, norm_a.y * off.y, norm_a.z * off.z)
    sec_movement = Vec(norm_b.x * off.x, norm_b.y * off.y, norm_b.z * off.z)

    # The size of the corner ranges from 1-3. It's
    # limited by the user's setting and the distance we have in each direction
    corner_size = min(
        first_movement.mag() // 128, sec_movement.mag() // 128,
        3, max_size,
    )

    solids = []

    straight_a = first_movement.mag() - (corner_size - 1) * 128
    straight_b = sec_movement.mag() - (corner_size * 128)

    if corner_size < 1:
        return []  # No room!

    if straight_a > 0:
        solids.append(make_straight(
            origin_a,
            norm_a,
            straight_a,
            config['straight'],
        ))

    corner_origin = origin_a + norm_a * straight_a
    vbsp.VMF.create_ent(
        classname='func_instance',
        origin=corner_origin,
        angles=corner_ang,
        file=config['corner', corner_size],
    )

    temp = config['corner_temp', corner_size]
    if temp:
        temp_solids = import_template(
            temp,
            origin=corner_origin,
            angles=Vec.from_str(corner_ang),
            force_type=TEMP_TYPES.world,
        ).world
        for solid in temp_solids:
            vbsp.VMF.remove_brush(solid)
        solids += temp_solids

    if straight_b > 0:
        solids.append(make_straight(
            origin_b - (straight_b * norm_b),
            norm_b,
            straight_b,
            config['straight'],
        ))

    return solids


def join_markers(inst_a, inst_b, is_start=False):
    """Join two marker ents together with corners.

    This returns a list of solids used for the vphysics_motion trigger.
    """
    origin_a = Vec.from_str(inst_a['ent']['origin'])
    origin_b = Vec.from_str(inst_b['ent']['origin'])

    norm_a = Vec(-1, 0, 0).rotate_by_str(inst_a['ent']['angles'])
    norm_b = Vec(-1, 0, 0).rotate_by_str(inst_b['ent']['angles'])

    config = inst_a['conf']

    if norm_a == norm_b:
        # Either straight-line, or s-bend.
        dist = (origin_a - origin_b).mag()

        if origin_a + (norm_a * dist) == origin_b:
            return [make_straight(
                origin_a,
                norm_a,
                dist,
                config['straight'],
                is_start,
            )]
        else:
            # S-bend, we don't do the geometry for this..
            return []

    try:
        corner_ang, flat_angle = CORNER_ANG[norm_a.as_tuple(), norm_b.as_tuple()]

        if origin_a[flat_angle] != origin_b[flat_angle]:
            # It needs to be flat in this angle!
            raise ValueError
    except ValueError:
        # The two tubes point in a u-shape, or need two corners - abort.
        return []
    else:
        return make_bend(
            origin_a,
            origin_b,
            norm_a,
            norm_b,
            corner_ang,
            config,
            max_size=inst_a['size'],
        )
