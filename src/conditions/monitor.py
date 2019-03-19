from collections import namedtuple, defaultdict
import os
import math

import connections
from conditions import (
    make_result, make_result_setup, meta_cond, RES_EXHAUSTED,
    local_name
)
import instanceLocs
from srctools import Property, Vec, Entity, VMF, Output
import srctools.logger
import vbsp_options
import voiceLine

from typing import Optional, List, Dict, Tuple


COND_MOD_NAME = 'Monitors'

LOGGER = srctools.logger.get_logger(__name__, 'cond.monitor')

ALL_MONITORS = []  # type: List[Monitor]
ALL_CAMERAS = []  # type: List[Camera]

# Keep a counter of the number of monitor bullseyes at a pos.
# This allows us to ensure we don't remove catapults also aiming here,
# and that we remove when more than one camera is pointed here.
BULLSYE_LOCS = defaultdict(int)  # type: Dict[Tuple[float, float, float], int]

MON_ARGS_SCRIPT = os.path.join('bee2', 'inject', 'monitor_args.nut')

Camera = namedtuple('Camera', 'inst config cam_pos cam_angles')
Monitor = namedtuple('Monitor', 'inst')

# Are there monitors that should be shot?
NEEDS_TURRET = False

# ai_relationships used for monitors.
# If non-emtpy we have monitors to shoot by turrets.
MONITOR_RELATIONSHIP_ENTS = []  # type: List[Entity]


def get_studio_pose() -> Vec:
    """Return the position of the studio camera."""
    return voiceLine.get_studio_loc() + vbsp_options.get(Vec, 'voice_studio_cam_loc')


@make_result_setup('Monitor')
def res_monitor_setup(res: Property):
    return (
        res['breakInst', None],
        res['bullseye_name', ''],
        res.vec('bullseye_loc'),
        res['bullseye_parent', ''],
    )


@make_result('Monitor')
def res_monitor(inst: Entity, res: Property) -> None:
    """Result for the monitor component.

    """
    import vbsp

    (
        break_inst,
        bullseye_name,
        bullseye_loc,
        bullseye_parent,
    ) = res.value

    ALL_MONITORS.append(Monitor(inst))

    has_laser = vbsp.settings['has_attr']['laser']
    # Allow turrets if the monitor is setup to allow it, and the actor should
    # be shot.
    needs_turret = bullseye_name and vbsp_options.get(bool, 'voice_studio_should_shoot')

    inst.fixup['$is_breakable'] = has_laser or needs_turret

    # We need to generate an ai_relationship, which makes turrets hate
    # a bullseye.
    if needs_turret:
        loc = Vec(bullseye_loc)
        loc.localise(
            Vec.from_str(inst['origin']),
            Vec.from_str(inst['angles']),
        )
        bullseye_name = local_name(inst, bullseye_name)
        inst.map.create_ent(
            classname='npc_bullseye',
            targetname=bullseye_name,
            parentname=local_name(inst, bullseye_parent),
            spawnflags=221186,  # Non-solid, invisible, etc..
            origin=loc,
        )
        relation = inst.map.create_ent(
            classname='ai_relationship',
            targetname='@monitor_turr_hate',
            spawnflags=2,  # Notify turrets about monitor locations
            disposition=1,  # Hate
            origin=loc,
            subject='npc_portal_turret_floor',
            target=bullseye_name,
        )
        MONITOR_RELATIONSHIP_ENTS.append(relation)


@make_result_setup('Camera')
def res_camera_setup(res: Property):
    return {
        'cam_off': Vec.from_str(res['CamOff', '']),
        'yaw_off': Vec.from_str(res['YawOff', '']),
        'pitch_off': Vec.from_str(res['PitchOff', '']),

        'yaw_inst': instanceLocs.resolve_one(res['yawInst', '']),
        'pitch_inst': instanceLocs.resolve_one(res['pitchInst', '']),

        'yaw_range': srctools.conv_int(res['YawRange', ''], 90),
        'pitch_range': srctools.conv_int(res['YawRange', ''], 90),
    }


@make_result('Camera')
def res_camera(inst: Entity, res: Property):
    """Result for the camera component.

    """
    conf = res.value
    normal = Vec(0, 0, 1).rotate_by_str(inst['angles'])
    if normal.z != 0:
        # Can't be on floor/ceiling!
        inst.remove()
        return
    base_yaw = math.degrees(math.atan2(normal.y, normal.x)) % 360
    inst['angles'] = '0 {:g} 0'.format(base_yaw)

    inst_name = inst['targetname']

    try:
        [target] = inst.map.by_target[inst_name + '-target']  # type: Entity
    except ValueError:
        # No targets with that name
        inst.remove()
        return

    for trig in inst.map.by_class['trigger_catapult']:  # type: Entity
        if trig['targetname'].startswith(inst_name):
            trig.remove()

    target_loc = Vec.from_str(target['origin'])
    target.remove()  # Not needed...

    BULLSYE_LOCS[target_loc.as_tuple()] += 1

    base_loc = Vec.from_str(inst['origin'])

    # Move three times to position the camera arms and lens.
    yaw_pos = Vec(conf['yaw_off']).rotate_by_str(inst['angles'])
    yaw_pos += base_loc

    pitch, yaw, _ = (target_loc - yaw_pos).to_angle()

    inst.map.create_ent(
        classname='func_instance',
        targetname=inst['targetname'],
        file=conf['yaw_inst'],
        angles='0 {:g} 0'.format(yaw),
        origin=yaw_pos,
    )

    pitch_pos = Vec(conf['pitch_off'])
    pitch_pos.rotate(yaw=yaw)
    pitch_pos.rotate_by_str(inst['angles'])
    pitch_pos += yaw_pos

    inst.map.create_ent(
        classname='func_instance',
        targetname=inst['targetname'],
        file=conf['pitch_inst'],
        angles='{:g} {:g} 0'.format(pitch, yaw),
        origin=pitch_pos,
    )

    cam_pos = Vec(conf['cam_off'])
    cam_pos.rotate(pitch=pitch, yaw=yaw)
    cam_pos += pitch_pos

    # Recompute, since this can be slightly different if the camera is large.
    cam_angles = (target_loc - cam_pos).to_angle()

    ALL_CAMERAS.append(Camera(inst, res.value, cam_pos, cam_angles))


@meta_cond(priority=-5, only_once=False)
def mon_remove_bullseyes(inst: Entity) -> Optional[object]:
    """Remove bullsyes used for cameras."""
    if not BULLSYE_LOCS:
        return RES_EXHAUSTED

    if inst['file'].casefold() not in instanceLocs.resolve('<ITEM_CATAPULT_TARGET>'):
        return

    origin = Vec(0, 0, -64)
    origin.localise(Vec.from_str(inst['origin']), Vec.from_str(inst['angles']))
    origin = origin.as_tuple()

    LOGGER.info('Pos: {} -> ', origin, BULLSYE_LOCS[origin])

    if BULLSYE_LOCS[origin]:
        BULLSYE_LOCS[origin] -= 1
        inst.remove()


@meta_cond(priority=-275, only_once=True)
def mon_camera_link() -> None:
    """Link cameras to monitors."""
    import vbsp
    LOGGER.info('Bullseye {}', BULLSYE_LOCS)

    if not ALL_MONITORS:
        return

    ALL_CAMERAS.sort(key=Camera.cam_pos.fget)

    fog_opt = vbsp.settings['fog']

    active_counts = [
        srctools.conv_int(cam.inst.fixup['$start_enabled', '0'])
        for cam in
        ALL_CAMERAS
    ]

    for index, cam in enumerate(ALL_CAMERAS):  # type: int, Camera
        if srctools.conv_int(cam.inst.fixup['$connectioncount']) == 0:
            continue

        conn_item = connections.ITEMS[cam.inst['targetname']]
        # Generate an input to the VScript which turns on/off this camera.
        # Everything's by index.
        conn_item.enable_cmd = (Output(
            '',
            '@camera',
            'RunScriptCode',
            'CamEnable({})'.format(index),
        ), )
        conn_item.disable_cmd = (Output(
            '',
            '@camera',
            'RunScriptCode',
            'CamDisable({})'.format(index),
        ), )

    for is_act, cam in zip(active_counts, ALL_CAMERAS):
        if is_act:
            start_pos = cam.cam_pos
            start_angles = cam.cam_angles
            break
    else:
        if vbsp_options.get(str, 'voice_studio_inst'):
            # Start at the studio, if it exists.
            start_pos = get_studio_pose()
            start_angles = '{:g} {:g} 0'.format(
                vbsp_options.get(float, 'voice_studio_cam_pitch'),
                vbsp_options.get(float, 'voice_studio_cam_yaw'),
            )
            # If we start at the studio, make the ai_relationships
            # for turret fire start active.
            for relation in MONITOR_RELATIONSHIP_ENTS:
                relation['StartActive'] = '1'
        else:
            # Start in arrival_departure_transition_ents...
            start_pos = '-2500 -2500 0'
            start_angles = '0 90 0'

    cam = vbsp.VMF.create_ent(
        classname='point_camera',
        targetname='@camera',
        spawnflags='0',  # Start on
        origin=start_pos,
        angles=start_angles,
        fov='60',

        # Copy fog settings from the skybox.
        fogEnable='1',
        fogMaxDensity='1',
        fogColor=fog_opt['primary'],
        fogStart=fog_opt['start'],
        fogEnd=fog_opt['end'],
    )  # type: Entity

    if not ALL_CAMERAS:
        # No cameras in the map - we don't move at all.
        # So we don't need the script.
        return

    # Set the vscripts
    cam['vscripts'] = 'BEE2/mon_camera_args.nut BEE2/mon_camera.nut'
    cam['thinkfunction'] = 'Think'


# Note that we must happen after voiceline adding!

@meta_cond(priority=150, only_once=True)
def mon_camera_script() -> None:
    """Write out a script containing the arguments to the camera."""
    active_counts = [
        srctools.conv_int(cam.inst.fixup['$start_enabled', '0'])
        for cam in
        ALL_CAMERAS
    ]

    with open(MON_ARGS_SCRIPT, 'w') as scr:
        scr.write('CAM_NUM <- {};\n'.format(len(ALL_CAMERAS)))
        scr.write('CAM_ACTIVE_NUM <- {};\n'.format(sum(active_counts)))
        scr.write('CAM_ACTIVE <- {!r};\n'.format(active_counts))
        scr.write('CAM_LOC <- [\n')
        scr.write(',\n'.join([
            ' Vector({0.x:.3f}, {0.y:.3f}, {0.z:.3f})'.format(cam.cam_pos)
            for cam in ALL_CAMERAS
        ]))
        scr.write('\n];\n')
        scr.write('CAM_ANGLES <- [\n')
        scr.write(',\n'.join([
            ' Vector({0.x:.3f}, {0.y:.3f})'.format(cam.cam_angles)
            for cam in ALL_CAMERAS
        ]))
        scr.write('\n];\n')

        if vbsp_options.get(str, 'voice_studio_inst'):
            # We have a voice studio, send values to the script.
            scr.write(
                'CAM_STUDIO_LOC <- Vector({0.x:.3f}, '
                '{0.y:.3f}, {0.z:.3f});\n'.format(get_studio_pose()),
            )
            scr.write(
                'CAM_STUDIO_CHANCE <- {chance};\n'
                'CAM_STUDIO_PITCH <- {pitch};\n'
                'CAM_STUDIO_YAW <- {yaw};\n'
                'CAM_STUDIO_TURRET <- {turret!r};\n'.format(
                    chance=vbsp_options.get(float, 'voice_studio_inter_chance'),
                    pitch=vbsp_options.get(float, 'voice_studio_cam_pitch'),
                    yaw=vbsp_options.get(float, 'voice_studio_cam_yaw'),
                    turret='1' if MONITOR_RELATIONSHIP_ENTS else '0',
                )
            )
        else:
            scr.write(
                'CAM_STUDIO_CHANCE <- -1;\n'
                'CAM_STUDIO_TURRET <- 0;\n'
            )


def make_voice_studio(vmf: VMF) -> bool:
    """Create the voice-line studio.

    This is either an instance (if monitors are present), or a nodraw room.
    """

    studio_file = vbsp_options.get(str, 'voice_studio_inst')
    loc = voiceLine.get_studio_loc()

    if ALL_MONITORS and studio_file:
        vmf.create_ent(
            classname='func_instance',
            file=studio_file,
            origin=loc,
            angles='0 0 0',
        )
        return True
    else:
        # If there aren't monitors, the studio instance isn't used.
        # We need to seal anyway.
        vmf.add_brushes(vmf.make_hollow(
            loc - 256,
            loc + 256,
            thick=32,
        ))
        return False
