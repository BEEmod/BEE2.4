import math

from precomp.conditions import make_result, make_result_setup, meta_cond, local_name
from precomp import instanceLocs, connections, options, faithplate, voice_line
from srctools import Property, Vec, Entity, VMF, Output
import srctools.logger

from typing import List, NamedTuple


COND_MOD_NAME = 'Monitors'

LOGGER = srctools.logger.get_logger(__name__, 'cond.monitor')


class Camera(NamedTuple):
    """Generated camera positions."""
    inst: Entity
    cam_pos: Vec
    cam_angles: Vec

ALL_CAMERAS: List[Camera] = []

# Do any monitors exist?
HAS_MONITOR: bool = False

# ai_relationships used for monitors.
# If non-emtpy we have monitors to shoot by turrets.
MONITOR_RELATIONSHIP_ENTS: List[Entity] = []


def get_studio_pose() -> Vec:
    """Return the position of the studio camera."""
    return voice_line.get_studio_loc() + options.get(Vec, 'voice_studio_cam_loc')


def scriptvar_set(
    targ: Entity,
    pos: Vec,
    varname: str,
    value: object='',
    *,
    mode: str='const',
    index: int=None,
    angles: object='0 0 0',
) -> None:
    """Add in a comp_scriptvar_setter entity."""
    if index is not None:
        varname = f'{varname}[{index}]'
    targ.map.create_ent(
        'comp_scriptvar_setter',
        origin=pos,
        angles=str(angles),
        target=targ['targetname'],
        variable=varname,
        mode=mode,
        const=str(value),
    )


@make_result_setup('Monitor')
def res_monitor_setup(res: Property):
    """Pre-parse options for monitors."""
    return (
        res['bullseye_name', ''],
        res.vec('bullseye_loc'),
        res['bullseye_parent', ''],
    )


@make_result('Monitor')
def res_monitor(inst: Entity, res: Property) -> None:
    """Result for the monitor component.

    Options:
    - bullseye_name: If possible to break this, this is the name to give the npc_bullseye.
    - bullseye_loc: This is the position to place the bullseye at.
    - bullseye_parent: This is the parent to give the bullseye.

    The fixup variable $is_breakable is set to True if lasers or turrets
    are present to indicate the func_breakable should be added.
    """
    global HAS_MONITOR
    import vbsp

    (
        bullseye_name,
        bullseye_loc,
        bullseye_parent,
    ) = res.value

    HAS_MONITOR = True

    has_laser = vbsp.settings['has_attr']['laser']
    # Allow turrets if the monitor is setup to allow it, and the actor should
    # be shot.
    needs_turret = bullseye_name and options.get(bool, 'voice_studio_should_shoot')

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
            parentname=bullseye_name,  # When killed, destroy this too.
            spawnflags=2,  # Notify turrets about monitor locations
            disposition=1,  # Hate
            origin=loc,
            subject='npc_portal_turret_floor',
            target=bullseye_name,
        )
        MONITOR_RELATIONSHIP_ENTS.append(relation)


@make_result_setup('Camera')
def res_camera_setup(res: Property):
    """Pre-parse the data for cameras."""
    return {
        'cam_off': Vec.from_str(res['CamOff', '']),
        'yaw_off': Vec.from_str(res['YawOff', '']),
        'pitch_off': Vec.from_str(res['PitchOff', '']),

        'yaw_inst': instanceLocs.resolve_one(res['yawInst', '']),
        'pitch_inst': instanceLocs.resolve_one(res['pitchInst', '']),

        'yaw_range': srctools.conv_int(res['YawRange', ''], 90),
        'pitch_range': srctools.conv_int(res['PitchRange', ''], 90),
    }


@make_result('Camera')
def res_camera(inst: Entity, res: Property):
    """Result for the camera item.

    Options:
    - cam_off: The position that the camera yaws around.
    - yaw_off: The offset from cam_off that the camera rotates up/down.
    - pitch_off: The offset from yaw_off that is where the sensor is.

    - yaw_inst: The instance to place for the yaw rotation.
    - pitch_inst: The instance to place for the up/down rotation.

    - yaw_range: How many degrees can the camera rotate from a forward position?
    - pitch_range: How many degrees can the camera rotate up/down?
    """
    conf = res.value
    normal = Vec(0, 0, 1).rotate_by_str(inst['angles'])
    if normal.z != 0:
        # Can't be on floor/ceiling!
        inst.remove()
        return
    base_yaw = math.degrees(math.atan2(normal.y, normal.x)) % 360
    inst['angles'] = '0 {:g} 0'.format(base_yaw)

    base_loc = Vec.from_str(inst['origin'])

    try:
        plate = faithplate.PLATES.pop(inst['targetname'])
    except KeyError:
        LOGGER.warning(
            'No faith plate info found for camera {}!',
            inst['targetname'],
        )
        inst.remove()
        return

    # Remove the triggers.
    plate.trig.remove()

    if isinstance(plate, faithplate.StraightPlate):
        # Just point straight ahead.
        target_loc = base_loc + 512 * normal
        # And remove the helper.
        plate.helper_trig.remove()
    else:
        if isinstance(plate.target, Vec):
            target_loc = plate.target
        else:
            # We don't particularly care about aiming to the front of angled
            # panels.
            target_loc = plate.target.pos + 64 * plate.target.normal
            # Remove the helper and a bullseye.
            plate.target.remove_portal_helper()
            plate.target.bullseye_count -= 1

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

    ALL_CAMERAS.append(Camera(inst, cam_pos, cam_angles))


@meta_cond(priority=-275)
def mon_camera_link(vmf: VMF) -> None:
    """Link cameras to monitors."""
    import vbsp

    if not HAS_MONITOR:
        return

    ALL_CAMERAS.sort(key=lambda cam: cam.cam_pos)

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
        # No cameras start active, we need to be positioned elsewhere.
        if options.get(str, 'voice_studio_inst'):
            # Start at the studio, if it exists.
            start_pos = get_studio_pose()
            start_angles = '{:g} {:g} 0'.format(
                options.get(float, 'voice_studio_cam_pitch'),
                options.get(float, 'voice_studio_cam_yaw'),
            )
            # If we start at the studio, make the ai_relationships
            # for turret fire start active.
            for relation in MONITOR_RELATIONSHIP_ENTS:
                relation['StartActive'] = '1'
        else:
            # Start in arrival_departure_transition_ents...
            start_pos = Vec(-2500, -2500, 0)
            start_angles = '0 90 0'

    cam_ent = vmf.create_ent(
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
    )

    if not ALL_CAMERAS:
        return
        # We only need the script if we're moving at all.
    cam_ent['vscripts'] = 'BEE2/mon_camera.nut'
    cam_ent['thinkfunction'] = 'Think'

    # Now start adding all the variables the script needs.
    # Tell it the number of cameras, and how many start active.
    # That lets it trivially determine when they're all off.
    # We keep the list of active counts to reuse after.
    active_counts = [
        srctools.conv_int(cam.inst.fixup['$start_enabled', '0'])
        for cam in
        ALL_CAMERAS
    ]
    scriptvar_set(cam_ent, start_pos - (0, 0, 16), 'CAM_NUM', len(ALL_CAMERAS))
    scriptvar_set(cam_ent, start_pos - (0, 0, 16), 'CAM_ACTIVE_NUM', sum(active_counts))
    # Then add the values for each camera. We can use the setter's modes
    # to include the position as the actual loc.
    for i, (cam, active) in enumerate(zip(ALL_CAMERAS, active_counts)):
        scriptvar_set(
            cam_ent,
            cam.cam_pos,
            'CAM_LOC',
            index=i,
            angles=cam.cam_angles,
            mode='pos',
        )
        scriptvar_set(
            cam_ent,
            cam.cam_pos,
            'CAM_ANGLES',
            index=i,
            angles=cam.cam_angles,
            mode='ang',
        )
        scriptvar_set(
            cam_ent,
            cam.cam_pos + (0, 0, 8),
            'CAM_ACTIVE',
            index=i,
            value=active,
        )

    if options.get(str, 'voice_studio_inst'):
        # We have a voice studio, send values to the script.
        scriptvar_set(cam_ent, get_studio_pose(), 'CAM_STUDIO_LOC', mode='pos')
        scriptvar_set(
            cam_ent, get_studio_pose(), 'CAM_STUDIO_ANG', mode='ang',
            angles='{:g} {:g} 0'.format(
                options.get(float, 'voice_studio_cam_pitch'),
                options.get(float, 'voice_studio_cam_yaw'),
            ),
        )
        use_turret = '1' if MONITOR_RELATIONSHIP_ENTS else '0'
        swap_chance = options.get(float, 'voice_studio_inter_chance')
    else:
        use_turret = '0'
        swap_chance = -1

    scriptvar_set(cam_ent, start_pos + (0, 0, 16), 'CAM_STUDIO_TURRET', use_turret)
    scriptvar_set(cam_ent, start_pos + (0, 0, 16), 'CAM_STUDIO_CHANCE', swap_chance)


def make_voice_studio(vmf: VMF) -> bool:
    """Create the voice-line studio.

    This is either an instance (if monitors are present), or a nodraw room.
    """

    studio_file = options.get(str, 'voice_studio_inst')
    loc = voice_line.get_studio_loc()

    if HAS_MONITOR and studio_file:
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
