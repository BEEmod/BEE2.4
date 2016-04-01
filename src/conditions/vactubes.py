"""Implements the cutomisable vactube items.
"""
from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
)
from instanceLocs import resolve as resolve_inst
from utils import Vec
import vmfLib as VLib
import utils
import vbsp

LOGGER = utils.getLogger(__name__, alias='cond.vactubes')

PUSH_SPEED = 400  # The speed of the push triggers.


xp = utils.Vec_tuple(1, 0, 0)
xn = utils.Vec_tuple(-1, 0, 0)
yp = utils.Vec_tuple(0, 1, 0)
yn = utils.Vec_tuple(0, -1, 0)
zp = utils.Vec_tuple(0, 0, 1)
zn = utils.Vec_tuple(0, 0, -1)

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
    LOGGER.info(VAC_CONFIGS)
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
        'ceiling' if start_normal.z > 1 else
        'floor' if start_normal.z < 1 else
        'wall'
    )]

    end = start

    motion_trig = vbsp.VMF.create_ent(
        classname='trigger_vphysics_motion',
        SetGravityScale='0.0',
        spawnflags='1103',  # Clients, Physics, Everything
    )

    for start, end in follow_vac_path(all_markers, start):
        motion_trig.solids.extend(
            join_markers(start, end)
        )

    end_logic = end['ent'].copy()
    vbsp.VMF.add_ent(end_logic)
    end_logic['file'] = end['conf']['exit']


def push_trigger(loc, normal, solids):
    ent = vbsp.VMF.create_ent(
        classname='trigger_push',
        origin=loc,
        # The z-direction is reversed..
        pushdir=normal.to_angle(),
        speed=PUSH_SPEED,
        spawnflags='1103',  # Clients, Physics, Everything
    )
    ent.solids.extend(solids)
    return ent


def make_straight(origin: Vec, normal: Vec, dist: int, file, name):
    """Make a straight line of instances from one point to another."""
    solid = vbsp.VMF.make_prism(
        # 32 added to the other directions, plus extended dist in the other
        # directions
        origin + 32 + (normal * (dist + 32)),
        origin - 32 - (normal * 32),
        mat='tools/toolstrigger',
    ).solid

    push_trigger(origin, normal, (solid,))

    angles = normal.to_angle()

    for pos in range(0, dist + 1, 128):
        vbsp.VMF.create_ent(
            classname='func_instance',
            targetname=name,
            origin=origin + pos * normal,
            angles=angles,
            file=file,
        )

    return solid.copy()


def join_markers(inst_a, inst_b):
    """Join two marker ents together with corners.

    This returns a list of solids used for the vphysics_motion trigger.
    """
    origin_a = Vec.from_str(inst_a['ent']['origin'])
    origin_b = Vec.from_str(inst_b['ent']['origin'])

    norm_a = Vec(-1, 0, 0).rotate_by_str(inst_a['ent']['angles'])
    norm_b = Vec(-1, 0, 0).rotate_by_str(inst_b['ent']['angles'])

    config = inst_a['conf']
    name = inst_a['ent']['targetname']

    LOGGER.info('{0}:{2} -> {1}:{3}', origin_a, origin_b, norm_a, norm_b)

    if norm_a == norm_b:
        # Either straight-line, or s-bend.
        dist = int((origin_a - origin_b).mag())

        if origin_a + (norm_a * dist) == origin_b:
            return [make_straight(
                origin_a,
                norm_a,
                dist,
                config['straight'],
                name
            )]
        else:
            # S-bend, we don't do the geometry for this..
            return []


