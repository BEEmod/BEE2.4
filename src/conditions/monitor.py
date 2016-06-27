from collections import namedtuple
import os
import math

from conditions import (
    make_result, make_result_setup, meta_cond,
)
from instanceLocs import resolve as resolve_inst
from srctools import Property, Vec, Entity
import srctools
import voiceLine
import utils

LOGGER = utils.getLogger(__name__, 'cond.monitor')

ALL_MONITORS = []
ALL_CAMERAS = []

MON_ARGS_SCRIPT = os.path.join('BEE2', 'inject', 'monitor_args.nut')

Camera = namedtuple('Camera', 'inst config cam_pos cam_angles')
Monitor = namedtuple('Monitor', 'inst config')

@make_result_setup('Monitor')
def res_monitor_setup(res: Property):
    return {}


@make_result('Monitor')
def res_monitor(inst: Entity, res: Property):
    """Result for the monitor component.

    """
    ALL_MONITORS.append(Monitor(inst, res.value))


@make_result_setup('Camera')
def res_camera_setup(res: Property):
    return {
        'cam_off': Vec.from_str(res['CamOff', '']),
        'yaw_off': Vec.from_str(res['YawOff', '']),
        'pitch_off': Vec.from_str(res['PitchOff', '']),

        'yaw_inst': resolve_inst(res['yawInst', ''])[0],
        'yaw_range': srctools.conv_int(res['YawRange', ''], 90),

        'pitch_inst': resolve_inst(res['pitchInst', ''])[0],
        'pitch_range': srctools.conv_int(res['YawRange', ''], 90),

        'vert_yaw': srctools.conv_float(res['VertYaw', ''], 0)
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
        target, = inst.map.by_target[inst_name + '-target']  # type: Entity
    except ValueError:
        # No targets with that name
        inst.remove()
        return

    for trig in inst.map.by_class['trigger_catapult']:  # type: Entity
        if trig['targetname'].startswith(inst_name):
            trig.remove()

    target_loc = Vec.from_str(target['origin'])
    target.remove()  # Not needed...

    base_loc = Vec.from_str(inst['origin'])

    # Move three times to position the camera arms and lens.
    yaw_pos = Vec(conf['yaw_off']).rotate_by_str(inst['angles'])
    yaw_pos += base_loc

    inst.map.create_ent(
        classname='env_beam',
        targetname=inst['targetname'],
        origin=base_loc,
        targetpoint=target_loc,
        angles=(target_loc - base_loc).to_angle(),
    )

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


@meta_cond(priority=100, only_once=True)
def mon_camera_link(_):
    """Link cameras to monitors."""
    import vbsp

    if not ALL_MONITORS:
        return

    ALL_CAMERAS.sort(key=Camera.cam_pos.fget)

    fog_opt = vbsp.settings['fog']

    vbsp.VMF.create_ent(
        classname='point_camera',
        targetname='@mon_camera',
        spawnflags='0',
        origin=ALL_CAMERAS[0].inst['origin'],

        vscripts='BEE2/mon_camera_args.nut BEE2/mon_camera.nut',
        thinkfunction='Think',

        # Copy fog settings from the skybox.
        fogEnable='1',
        fogMaxDensity='1',
        fogColor=fog_opt['primary'],
        fogStart=fog_opt['start'],
        fogEnd=fog_opt['end'],
    )
    vbsp.PACK_FILES.add('scripts/vscripts/BEE2/mon_camera.nut')

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
