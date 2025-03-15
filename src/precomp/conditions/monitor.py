import math

from precomp import instanceLocs, connections, conditions, faithplate
from srctools import FrozenVec, Matrix, Keyvalues, Vec, Entity, VMF, Output, Angle
import srctools.logger

from typing import NamedTuple, Literal

from quote_pack import QuoteInfo


COND_MOD_NAME = 'Monitors'
LOGGER = srctools.logger.get_logger(__name__, 'cond.monitor')


class Camera(NamedTuple):
    """Generated camera positions."""
    inst: Entity
    cam_pos: Vec
    cam_angles: Angle


ALL_CAMERAS: list[Camera] = []

# Do any monitors exist?
HAS_MONITOR: bool = False

# ai_relationships used for monitors.
# If non-emtpy we have monitors to shoot by turrets.
MONITOR_RELATIONSHIP_ENTS: list[Entity] = []

# The location of arrival_departure_transition_ents, which has toolsblack.
BLACK_SCREEN_LOC = FrozenVec(-2500, -2500, 0)


def get_studio_pose(voice: QuoteInfo) -> Vec | FrozenVec:
    """Return the position of the studio camera."""
    if voice.id and voice.monitor is not None:
        return voice.position + voice.monitor.cam_loc
    else:
        # No voice line set or no studio specified, use a black screen.
        return BLACK_SCREEN_LOC


def scriptvar_set(
    targ: Entity,
    pos: Vec | FrozenVec,
    varname: str,
    value: object = '',
    *,
    mode: Literal[
        'const', 'string', 'bool', 'inv_bool', 'name', 'handle', 'keyvalue',
        'pos', 'ang', 'off', 'dist', 'x', 'y', 'z', 'pos_x', 'pos_y', 'pos_z',
    ] = 'const',
    index: int | None = None,
    angles: object = '0 0 0',
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


@conditions.make_result('Monitor', valid_before=conditions.MetaCond.MonCameraLink)
def res_monitor(info: conditions.MapInfo, voice: QuoteInfo, res: Keyvalues) -> conditions.ResultCallable:
    """Result for the monitor component.

    Options:
    - bullseye_name: If possible to break this, this is the name to give the npc_bullseye.
    - bullseye_loc: This is the position to place the bullseye at.
    - bullseye_parent: This is the parent to give the bullseye.

    The fixup variable $is_breakable is set to True if lasers or turrets
    are present to indicate the func_breakable should be added.
    """
    conf_bullseye_name = res['bullseye_name', '']
    bullseye_loc = res.vec('bullseye_loc')
    bullseye_parent = res['bullseye_parent', '']

    def add_monitor(inst: Entity) -> None:
        """Adds the monitor to the map."""
        global HAS_MONITOR
        HAS_MONITOR = True

        has_laser = info.has_attr('laser')
        # Allow turrets if the monitor is setup to allow it, and the actor should
        # be shot.
        needs_turret = conf_bullseye_name and voice.monitor is not None and voice.monitor.turret_hate

        inst.fixup['$is_breakable'] = has_laser or needs_turret

        # We need to generate an ai_relationship, which makes turrets hate
        # a bullseye.
        if needs_turret:
            loc = Vec(bullseye_loc)
            loc.localise(
                Vec.from_str(inst['origin']),
                Angle.from_str(inst['angles']),
            )
            bullseye_name = conditions.local_name(inst, conf_bullseye_name)
            inst.map.create_ent(
                classname='npc_bullseye',
                targetname=bullseye_name,
                parentname=conditions.local_name(inst, bullseye_parent),
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
    return add_monitor


@conditions.make_result('Camera', valid_before=conditions.MetaCond.MonCameraLink)
def res_camera(vmf: VMF, res: Keyvalues) -> conditions.ResultCallable:
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
    cam_off = Vec.from_str(res['CamOff', ''])
    yaw_off = Vec.from_str(res['YawOff', ''])
    pitch_off = Vec.from_str(res['PitchOff', ''])

    yaw_inst = instanceLocs.resolve_one(res['yawInst', ''], error=False)
    pitch_inst = instanceLocs.resolve_one(res['pitchInst', ''], error=False)

    # TODO: pitch/yaw range?

    def add_camera(inst: Entity) -> None:
        """Add the camera."""
        normal = Vec(z=1) @ Angle.from_str(inst['angles'])
        if abs(normal.z) > 0.1:
            # Can't be on floor/ceiling!
            inst.remove()
            return
        base_yaw = math.degrees(math.atan2(normal.y, normal.x)) % 360
        orient = Matrix.from_yaw(base_yaw)
        inst['angles'] = orient.to_angle()

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
            plate.helper_trig.remove()

        if plate.target is None:
            # Just point straight ahead.
            target_loc = base_loc + 512 * normal
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
        yaw_pos = yaw_off.copy() @ orient + base_loc

        pitch, yaw, _ = (target_loc - yaw_pos).to_angle()

        conditions.add_inst(
            vmf,
            targetname=inst['targetname'],
            file=yaw_inst,
            angles=Angle(yaw=yaw),
            origin=yaw_pos,
        )

        pitch_pos = (pitch_off.copy() @ Matrix.from_yaw(yaw)) @ orient + yaw_pos

        conditions.add_inst(
            vmf,
            targetname=inst['targetname'],
            file=pitch_inst,
            angles=Angle(pitch, yaw),
            origin=pitch_pos,
        )

        cam_pos = cam_off.copy() @ Angle(pitch, yaw) + pitch_pos

        # Recompute, since this can be slightly different if the camera is large.
        cam_angles = (target_loc - cam_pos).to_angle()

        ALL_CAMERAS.append(Camera(inst, cam_pos, cam_angles))
    return add_camera


@conditions.MetaCond.MonCameraLink.register
def mon_camera_link(vmf: VMF, voice: QuoteInfo) -> None:
    """Link cameras to monitors."""
    import vbsp

    if not HAS_MONITOR:
        return

    # Arbitrary but consistent.
    ALL_CAMERAS.sort(key=lambda cam: cam.cam_pos)

    fog_opt = vbsp.settings['fog']

    active_counts = [
        cam.inst.fixup.bool('$start_enabled')
        for cam in
        ALL_CAMERAS
    ]

    for index, cam in enumerate(ALL_CAMERAS):
        if cam.inst.fixup.int('$connectioncount') == 0:
            continue

        conn_item = connections.ITEMS[cam.inst['targetname']]
        # Generate an input to the VScript which turns on/off this camera.
        # Everything's by index.
        conn_item.enable_cmd = (Output(
            '',
            '@camera',
            'RunScriptCode',
            f'CamEnable({index})',
        ), )
        conn_item.disable_cmd = (Output(
            '',
            '@camera',
            'RunScriptCode',
            f'CamDisable({index})',
        ), )

    start_pos: Vec | FrozenVec
    for is_act, cam in zip(active_counts, ALL_CAMERAS, strict=True):
        if is_act:
            start_pos = cam.cam_pos
            start_angles = cam.cam_angles
            break
    else:
        # No cameras start active, we need to be positioned elsewhere.
        if voice.monitor is not None:
            # Start at the studio, if it exists.
            start_pos = get_studio_pose(voice)
            start_angles = voice.monitor.cam_angle
            # If we start at the studio, make the ai_relationships
            # for turret fire start active.
            for relation in MONITOR_RELATIONSHIP_ENTS:
                relation['StartActive'] = '1'
        else:
            # Start in arrival_departure_transition_ents...
            start_pos = BLACK_SCREEN_LOC
            start_angles = Angle(0, 90, 0)

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
    for i, (cam, active) in enumerate(zip(ALL_CAMERAS, active_counts, strict=True)):
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

    if voice.monitor is not None:
        # We have a voice studio, send values to the script.
        studio_pos = get_studio_pose(voice)
        scriptvar_set(cam_ent, studio_pos, 'CAM_STUDIO_LOC', mode='pos')
        scriptvar_set(
            cam_ent, studio_pos, 'CAM_STUDIO_ANG', mode='ang',
            angles=voice.monitor.cam_angle,
        )
        use_turret = '1' if MONITOR_RELATIONSHIP_ENTS else '0'
        swap_chance = voice.monitor.interrupt
    else:
        use_turret = '0'
        swap_chance = -1

    scriptvar_set(cam_ent, start_pos + (0, 0, 16), 'CAM_STUDIO_TURRET', use_turret)
    scriptvar_set(cam_ent, start_pos + (0, 0, 16), 'CAM_STUDIO_CHANCE', swap_chance)


def make_voice_studio(vmf: VMF, voice: QuoteInfo) -> bool:
    """Create the voice-line studio.

    This is either an instance (if monitors are present), or a nodraw room.
    """
    assert voice.id, "No voiceline defined?"

    if HAS_MONITOR and voice.monitor is not None:
        conditions.add_inst(
            vmf,
            file=voice.monitor.studio,
            origin=voice.position,
        )
        return True
    else:
        # If there aren't monitors, the studio instance isn't used.
        # We need to seal anyway.
        vmf.add_brushes(vmf.make_hollow(
            voice.position - 256,
            voice.position + 256,
            thick=32,
        ))
        return False
