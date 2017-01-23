"""Implements the cutomisable vactube items.
"""
from collections import namedtuple

import srctools
import template_brush
import utils
import vbsp
from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
    remove_ant_toggle,
    GOO_LOCS, SOLIDS
)
from instanceLocs import resolve as resolve_inst
from srctools import (
    Vec, Vec_tuple,
    Property, Entity,
)

LOGGER = utils.getLogger(__name__, alias='cond.vactubes')

PUSH_SPEED = 700  # The speed of the push triggers.
UP_PUSH_SPEED = 900  # Make it slightly faster when up to counteract gravity
DN_PUSH_SPEED = 400  # Slow down when going down since gravity also applies..

PUSH_TRIGS = {}

CornerAng = namedtuple('CornerAng', 'ang, axis')

xp = Vec_tuple(1, 0, 0)
xn = Vec_tuple(-1, 0, 0)
yp = Vec_tuple(0, 1, 0)
yn = Vec_tuple(0, -1, 0)
zp = Vec_tuple(0, 0, 1)
zn = Vec_tuple(0, 0, -1)

# start, end normals -> angle of corner instance and the unchanged axis
CORNER_ANG = {
    (zp, xp): CornerAng('0 0 0', 'y'),
    (zp, xn): CornerAng('0 180 0', 'y'),
    (zp, yp): CornerAng('0 90 0', 'x'),
    (zp, yn): CornerAng('0 270 0', 'x'),

    (zn, xp): CornerAng('0 0 180', 'y'),
    (zn, xn): CornerAng('0 180 180', 'y'),
    (zn, yp): CornerAng('0 90 180', 'x'),
    (zn, yn): CornerAng('0 270 180', 'x'),

    (xp, yp): CornerAng('0 90 90', 'z'),
    (xp, yn): CornerAng('0 270 270', 'z'),
    (xp, zp): CornerAng('270 180 0', 'y'),
    (xp, zn): CornerAng('90 0 0', 'y'),

    (xn, yp): CornerAng('0 90 270', 'z'),
    (xn, yn): CornerAng('0 270 90', 'z'),
    (xn, zp): CornerAng('270 0 0', 'y'),
    (xn, zn): CornerAng('90 180 0', 'y'),

    (yp, zp): CornerAng('270 270 0', 'x'),
    (yp, zn): CornerAng('90 90 0', 'x'),
    (yp, xp): CornerAng('0 0 270', 'z'),
    (yp, xn): CornerAng('0 180 90', 'z'),

    (yn, zp): CornerAng('270 90 0', 'x'),
    (yn, zn): CornerAng('90 270 0', 'x'),
    (yn, xn): CornerAng('0 180 270', 'z'),
    (yn, xp): CornerAng('0 0 90', 'z'),
}

SUPPORT_POS = {}


def _make_support_table():
    """Make a table of angle/offset values for each direction."""
    for norm in (xp, xn, yp, yn, zp, zn):
        table = SUPPORT_POS[norm] = []
        for x in range(0, 360, 90):
            ang = Vec(norm).to_angle(roll=x)
            table.append((
                ang,
                Vec(0, 0, -64).rotate(*ang)
            ))
_make_support_table()  # Ensure local vars are destroyed

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
def res_vactube_setup(res: Property):
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

            # Supports attach to the 4 sides of the straight part,
            # if there's a brush there.
            'support': block['support_inst', ''],

            'is_tsection': srctools.conv_bool(block['is_tsection', '0']),

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

            inst_configs[resolve_inst(file)[0]] = conf, srctools.conv_int(size, 1)

    return group


@make_result('CustVactube')
def res_make_vactubes(res: Property):
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
    for inst in vbsp.VMF.by_class['func_instance']:  # type: Entity
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

    LOGGER.info('Markers: {}', markers.keys())

    for mark_name, marker in markers.items():
        LOGGER.info('Outputs: {}', marker['next'])
        next_marker = None
        for inst in marker['next']:
            try:
                next_marker = markers[inst]
            except KeyError:
                # Not a marker-instance, remove this (indicator_toggles, etc)
                # We want to remove any them as well as the assoicated
                # antlines!
                for toggle in vbsp.VMF.by_target[inst]:
                    remove_ant_toggle(toggle)
            else:
                marker['next'] = inst
                next_marker['prev'] = mark_name

        if next_marker is None:
            # No next-instances were found..
            # Mark as no-connections
            marker['next'] = None

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

    for inst, end in follow_vac_path(all_markers, start):
        join_markers(inst, end, inst is start)

    end_loc = Vec.from_str(end['ent']['origin'])
    end_norm = Vec(-1, 0, 0).rotate_by_str(end['ent']['angles'])

    # join_markers creates straight parts up-to the marker, but not at it's
    # location - create the last one.
    make_straight(
        end_loc,
        end_norm,
        128,
        end['conf'],
    )

    # If the end is placed in goo, don't add logic - it isn't visible, and
    # the object is on a one-way trip anyway.
    if end_loc.as_tuple() not in GOO_LOCS:
        end_logic = end['ent'].copy()
        vbsp.VMF.add_ent(end_logic)
        end_logic['file'] = end['conf']['exit']


def push_trigger(loc, normal, solids):
    # We only need one trigger per direction, for now.
    try:
        ent = PUSH_TRIGS[normal.as_tuple()]
    except KeyError:
        ent = PUSH_TRIGS[normal.as_tuple()] = vbsp.VMF.create_ent(
            classname='trigger_push',
            origin=loc,
            # The z-direction is reversed..
            pushdir=normal.to_angle(),
            speed=(
                UP_PUSH_SPEED if normal.z > 0 else
                DN_PUSH_SPEED if normal.z < 0 else
                PUSH_SPEED
            ),
            spawnflags='1103',  # Clients, Physics, Everything
        )

    ent.solids.extend(solids)


def motion_trigger(*solids):
    motion_trig = vbsp.VMF.create_ent(
        classname='trigger_vphysics_motion',
        SetGravityScale='0.0',
        origin=solids[0].get_origin(),
        spawnflags='1103',  # Clients, Physics, Everything
    )
    motion_trig.solids.extend(solids)


def make_straight(
        origin: Vec,
        normal: Vec,
        dist: int,
        config: dict,
        is_start=False,
    ):
    """Make a straight line of instances from one point to another."""

    # 32 added to the other directions, plus extended dist in the direction
    # of the normal - 1
    p1 = origin + (normal * ((dist // 128 * 128) - 96))
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

    motion_trigger(solid.copy())

    push_trigger(origin, normal, [solid])

    angles = normal.to_angle()

    support_file = config['support']
    straight_file = config['straight']
    support_positions = (
        SUPPORT_POS[normal.as_tuple()]
        if support_file else
        []
    )

    for off in range(0, int(dist), 128):
        position = origin + off * normal
        vbsp.VMF.create_ent(
            classname='func_instance',
            origin=position,
            angles=angles,
            file=straight_file,
        )

        for supp_ang, supp_off in support_positions:
            if (position + supp_off).as_tuple() in SOLIDS:
                vbsp.VMF.create_ent(
                    classname='func_instance',
                    origin=position,
                    angles=supp_ang,
                    file=support_file,
                )


def make_corner(origin, angle, size, config):
    vbsp.VMF.create_ent(
        classname='func_instance',
        origin=origin,
        angles=angle,
        file=config['corner', size],
    )

    temp = config['corner_temp', size]
    if temp:
        temp_solids = template_brush.import_template(
            temp,
            origin=origin,
            angles=Vec.from_str(angle),
            force_type=template_brush.TEMP_TYPES.world,
        ).world
        for solid in temp_solids:
            vbsp.VMF.remove_brush(solid)
        motion_trigger(*temp_solids)


def make_bend(
        origin_a: Vec,
        origin_b: Vec,
        norm_a: Vec,
        norm_b: Vec,
        corner_ang: str,
        config,
        max_size: int,
        is_start=False,
):
    """Make a corner and the straight sections leading into it."""
    off = origin_b - origin_a
    # The distance to move first, then second.
    first_movement = off.norm_mask(norm_a)
    sec_movement = off.norm_mask(norm_b)

    # The size of the corner ranges from 1-3. It's
    # limited by the user's setting and the distance we have in each direction
    corner_size = min(
        first_movement.mag() // 128, sec_movement.mag() // 128,
        3, max_size,
    )

    straight_a = first_movement.mag() - (corner_size - 1) * 128
    straight_b = sec_movement.mag() - (corner_size * 128)

    if corner_size < 1:
        return []  # No room!

    if straight_a > 0:
        make_straight(
            origin_a,
            norm_a,
            straight_a,
            config,
            is_start,
        )

    corner_origin = origin_a + norm_a * straight_a
    make_corner(
        corner_origin,
        corner_ang,
        corner_size,
        config,
    )

    if straight_b > 0:
        make_straight(
            origin_b - (straight_b * norm_b),
            norm_b,
            straight_b,
            config,
        )


def make_ubend(
        origin_a: Vec,
        origin_b: Vec,
        normal: Vec,
        config,
        max_size: int,
        is_start=False,
):
    """Create u-shaped bends."""
    offset = origin_b - origin_a

    out_axis = normal.axis()
    out_off = offset[out_axis]
    offset[out_axis] = 0

    if len(offset) == 2:
        # Len counts the non-zero values..
        # If 2, the ubend is diagonal so it's ambigous where to put the bends.
        return []

    side_norm = offset.norm()

    for side_axis, side_dist in zip('xyz', offset):
        if side_dist:
            side_dist = abs(side_dist) + 128
            break
    else:
        # The two tube items are on top of another, that's
        # impossible to generate.
        return []

    # Calculate the size of the various parts.
    # first/second _size = size of the corners.
    # first/second _straight = length of straight sections
    # off_straight = length of straight in between corners
    if out_off == 0:
        # Both tubes are parallel to each other - use half the distance
        # for the bends.
        first_size = second_size = min(
            3,
            max_size,
            side_dist // (128 * 2),
        )
        first_straight = second_straight = 0
        side_straight = side_dist - 2 * 128 * first_size
    elif out_off > 0:
        # The second tube is further away than the first - the first bend
        # should be largest.
        # We need 1 spot for the second bend.
        first_size = min(
            3,
            max_size,
            side_dist // 128 - 1,
            out_off,
        )
        second_size = min(3, side_dist // 128 - first_size, max_size)

        first_straight = (out_off + 128) - 128 * second_size
        second_straight = (first_size - second_size) * 128

        side_straight = (side_dist / 128 - first_size - second_size) * 128

    elif out_off < 0:
        # The first tube is further away than the second - the second bend
        # should be largest.
        second_size = min(
            3,
            max_size,
            side_dist // 128 - 1,
            -out_off  # -out = abs()
        )
        first_size = min(3, side_dist // 128 - second_size, max_size)

        first_straight = (second_size - first_size) * 128
        second_straight = (-out_off + 128) - 128 * second_size

        side_straight = (side_dist / 128 - first_size - second_size) * 128
    else:
        return []  # Not possible..

    # We always have a straight segment at the first marker point - move
    # everything up slightly.

    first_straight += 128

    LOGGER.info(
        'Ubend {}: {}, c={}, {}, c={}, {}',
        out_off,
        first_straight,
        first_size,
        side_straight,
        second_size,
        second_straight,
    )

    make_straight(
        origin_a,
        normal,
        first_straight,
        config,
        is_start,
    )

    first_corner_loc = origin_a + (normal * first_straight)

    make_corner(
        first_corner_loc,
        CORNER_ANG[normal.as_tuple(), side_norm.as_tuple()].ang,
        first_size,
        config,
    )

    off_straight_loc = first_corner_loc + normal * (128 * (first_size - 1))
    off_straight_loc += side_norm * (128 * first_size)

    if side_straight > 0:
        make_straight(
            off_straight_loc,
            side_norm,
            side_straight,
            config,
        )

    sec_corner_loc = off_straight_loc + side_norm * side_straight

    make_corner(
        sec_corner_loc,
        CORNER_ANG[side_norm.as_tuple(), (-normal).as_tuple()].ang,
        second_size,
        config,
    )

    if second_straight > 0:
        make_straight(
            sec_corner_loc - normal * (128 * second_size),
            -normal,
            second_straight,
            config,
        )


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
            make_straight(
                origin_a,
                norm_a,
                dist,
                config,
                is_start,
            )
        # else: S-bend, we don't do the geometry for this..
        return

    if norm_a == -norm_b:
        # U-shape bend..
        make_ubend(
            origin_a,
            origin_b,
            norm_a,
            config,
            max_size=inst_a['size'],
        )
        return

    try:
        corner_ang, flat_angle = CORNER_ANG[norm_a.as_tuple(), norm_b.as_tuple()]

        if origin_a[flat_angle] != origin_b[flat_angle]:
            # It needs to be flat in this angle!
            raise ValueError
    except ValueError:
        # The tubes need two corners to join together - abort for that.
        return
    else:
        make_bend(
            origin_a,
            origin_b,
            norm_a,
            norm_b,
            corner_ang,
            config,
            max_size=inst_a['size'],
        )
