from collections import namedtuple, defaultdict
import os
import math

from conditions import (
    make_result, make_result_setup, meta_cond, RES_EXHAUSTED
)
from instanceLocs import resolve as resolve_inst
from srctools import Property, Vec, Entity, VMF
import srctools
import utils

LOGGER = utils.getLogger(__name__, 'cond.monitor')

ALL_MONITORS = []
ALL_CAMERAS = []

# Keep a counter of the number of monitor bullseyes at a pos.
# This allows us to ensure we don't remove catapults also aiming here,
# and that we remove when more than one camera is pointed here.
BULLSYE_LOCS = defaultdict(int)

MON_ARGS_SCRIPT = os.path.join('BEE2', 'inject', 'monitor_args.nut')

Camera = namedtuple('Camera', 'inst config cam_pos cam_angles')
Monitor = namedtuple('Monitor', 'inst config')

# The location of the voiceline room, used to position the camera.
VOICELINE_LOC = Vec()


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

        'io_inst': resolve_inst(res['IO_inst'])[0],
        'yaw_inst': resolve_inst(res['yawInst', ''])[0],
        'pitch_inst': resolve_inst(res['pitchInst', ''])[0],

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
def mon_remove_bullseyes(inst: Entity):
    """Remove bullsyes used for cameras."""
    if not BULLSYE_LOCS:
        return RES_EXHAUSTED

    if inst['file'].casefold() not in resolve_inst('<ITEM_CATAPULT_TARGET>'):
        return

    LOGGER.info('Bullseye {}', BULLSYE_LOCS)

    origin = Vec(0, 0, -64)
    origin.localise(Vec.from_str(inst['origin']), Vec.from_str(inst['angles']))
    origin = origin.as_tuple()

    LOGGER.info('Pos: {} -> ', origin, BULLSYE_LOCS[origin])

    if BULLSYE_LOCS[origin]:
        BULLSYE_LOCS[origin] -= 1
        inst.remove()


#  Note that we happen after voiceline adding!


@meta_cond(priority=150, only_once=True)
def mon_camera_link(_):
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

        io_ent = cam.inst.copy()
        io_ent.map.add_ent(io_ent)
        io_ent['file'] = cam.config['io_inst']
        io_ent.fixup['$toggle_func'] = 'ToggleCam({})'.format(index)

    for is_act, cam in zip(active_counts, ALL_CAMERAS):
        if is_act:
            start_pos = cam.cam_pos
            start_angles = cam.cam_angles
            break
    else:
        if vbsp.get_opt('voice_studio_inst'):
            # Start at the studio, if it exists.
            start_pos = VOICELINE_LOC
            start_angles = '{:g} {:g} 0'.format(
                srctools.conv_float(vbsp.get_opt('voice_studio_cam_pitch')),
                srctools.conv_float(vbsp.get_opt('voice_studio_cam_yaw')),
            )
        else:
            # Start in arrival_departure_transition_ents...
            start_pos = '-2500 -2500 0'
            start_angles = '0 90 0'

    vbsp.VMF.create_ent(
        classname='point_camera',
        targetname='@camera',
        spawnflags='0',  # Start on
        origin=start_pos,
        angles=start_angles,
        fov='60',

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

        if vbsp.get_opt('voice_studio_inst'):
            # We have a voice studio, send values to the script.
            scr.write(
                'CAM_STUDIO_LOC <- Vector({0.x:.3f}, '
                '{0.y:.3f}, {0.z:.3f});\n'.format(VOICELINE_LOC),
            )
            scr.write(
                'CAM_STUDIO_CHANCE <- {chance};\n'
                'CAM_STUDIO_PITCH <- {pitch};\n'
                'CAM_STUDIO_YAW <- {yaw};\n'.format(
                    chance=srctools.conv_float(vbsp.get_opt('voice_studio_inter_chance')),
                    pitch=srctools.conv_float(vbsp.get_opt('voice_studio_cam_pitch')),
                    yaw=srctools.conv_float(vbsp.get_opt('voice_studio_cam_yaw')),
                )
            )
        else:
            scr.write('CAM_STUDIO_CHANCE <- -1;\n')


def make_voice_studio(vmf: VMF, loc: Vec):
    """Create the voice-line studio.

    This is either an instance (if monitors are present), or a nodraw room.
    """
    global VOICELINE_LOC
    import vbsp

    # Blank = don't use.
    studio_file = vbsp.get_opt('voice_studio_inst')

    if ALL_MONITORS and studio_file:
        vmf.create_ent(
            classname='func_instance',
            file=studio_file,
            origin=loc,
            angles='0 0 0',
        )
        VOICELINE_LOC = loc + Vec.from_str(vbsp.get_opt('voice_studio_cam_loc'))
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
