"""Continuously moving belts, like in BTS.
"""
from srctools import Property, Vec, Entity, Output

import conditions
import template_brush
import instanceLocs
import srctools

COND_MOD_NAME = None


@conditions.make_result('ConveyorBelt')
def res_conveyor_belt(inst: Entity, res: Property):
    """Create a conveyor belt.

    Options:
        SegmentInst: Generated at each square. ('track' is the name of the path.)
        TrackTeleport: Set the track points so they teleport trains to the start.
        Speed: The fixup or number for the train speed.
        MotionTrig: If set, a trigger_multiple will be spawned that EnableMotions
          weighted cubes. The value is the name of the relevant filter.
        EndOutput: Adds an output to the last track. The value is the same as
          outputs in VMFs.
        RotateSegments: If true (default), force segments to face in the
          direction of movement
        RailTemplate: A template for the railings. This is made into a non-solid
          func_brush, combining all sections.
    """
    move_dist = srctools.conv_int(inst.fixup['$travel_distance'])

    if move_dist <= 2:
        # There isn't room for a catwalk, so don't bother.
        inst.remove()
        return

    move_dir = Vec(1, 0, 0).rotate_by_str(inst.fixup['$travel_direction'])
    move_dir.rotate_by_str(inst['angles'])
    start_offset = srctools.conv_float(inst.fixup['$starting_position'], 0)
    teleport_to_start = res.bool('TrackTeleport', True)
    segment_inst_file = instanceLocs.resolve_one(res['SegmentInst', ''])
    rail_template = res['RailTemplate', None]

    vmf = inst.map

    track_speed = res['speed', None]

    start_pos = Vec.from_str(inst['origin'])
    end_pos = start_pos + move_dist * move_dir

    if start_offset > 0:
        # If an oscillating platform, move to the closest side..
        offset = start_offset * move_dir
        # The instance is placed this far along, so move back to the end.
        start_pos -= offset
        end_pos -= offset
        if start_offset > 0.5:
            # Swap the direction of movement..
            start_pos, end_pos = end_pos, start_pos
        inst['origin'] = start_pos

    # Find the angle which generates an instance pointing in the direction
    # of movement, with the same normal.
    norm = Vec(z=1).rotate_by_str(inst['angles'])
    for roll in range(0, 360, 90):
        angles = move_dir.to_angle(roll)
        if Vec(z=1).rotate(*angles) == norm:
            break
    else:
        raise ValueError(
            "Can't find angles to give a"
            ' z={} and x={}!'.format(norm, move_dir)
        )

    if res.bool('rotateSegments', True):
        inst['angles'] = angles
    else:
        angles = Vec.from_str(inst['angles'])

    # Add the EnableMotion trigger_multiple seen in platform items.
    # This wakes up cubes when it starts moving.
    motion_filter = res['motionTrig', None]

    # Disable on walls, or if the conveyor can't be turned on.
    if norm != (0, 0, 1) or inst.fixup['$connectioncount'] == '0':
        motion_filter = None

    track_name = conditions.local_name(inst, 'segment_{}')
    rail_temp_solids = []
    last_track = None
    # Place beams at the top, so they don't appear inside wall sections.
    beam_start = start_pos + 48 * norm  # type: Vec
    beam_end = end_pos + 48 * norm  # type: Vec
    for index, pos in enumerate(beam_start.iter_line(beam_end, stride=128), start=1):
        track = vmf.create_ent(
            classname='path_track',
            targetname=track_name.format(index) + '-track',
            origin=pos,
            spawnflags=0,
            orientationtype=0,  # Don't rotate
        )
        if track_speed is not None:
            track['speed'] = track_speed
        if last_track:
            last_track['target'] = track['targetname']

        if index == 1 and teleport_to_start:
            track['spawnflags'] = 16  # Teleport here..

        last_track = track

        # Don't place at the last point - it doesn't teleport correctly,
        # and would be one too many.
        if segment_inst_file and pos != end_pos:
            seg_inst = vmf.create_ent(
                classname='func_instance',
                targetname=track_name.format(index),
                file=segment_inst_file,
                origin=pos,
                angles=angles,
            )
            seg_inst.fixup.update(inst.fixup)

        if rail_template:
            temp = template_brush.import_template(
                rail_template,
                pos,
                angles,
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
            )
            rail_temp_solids.extend(temp.world)

    if rail_temp_solids:
        vmf.create_ent(
            classname='func_brush',
            origin=beam_start,
            spawnflags=1,  # Ignore +USE
            solidity=1,  # Not solid
            vrad_brush_cast_shadows=1,
            drawinfastreflection=1,
        ).solids = rail_temp_solids

    if teleport_to_start:
        # Link back to the first track..
        last_track['target'] = track_name.format(1) + '-track'

    # Generate an env_beam pointing from the start to the end of the track.
    beam_keys = res.find_key('BeamKeys', [])
    if beam_keys.value:
        beam = vmf.create_ent(classname='env_beam')

        # 3 offsets - x = distance from walls, y = side, z = height
        beam_off = beam_keys.vec('origin', 0, 63, 56)

        for prop in beam_keys:
            beam[prop.real_name] = prop.value

        # Localise the targetname so it can be triggered..
        beam['LightningStart'] = beam['targetname'] = conditions.local_name(
            inst,
            beam['targetname', 'beam']
        )
        del beam['LightningEnd']
        beam['origin'] = start_pos + Vec(
            -beam_off.x, beam_off.y, beam_off.z,
        ).rotate(*angles)
        beam['TargetPoint'] = end_pos + Vec(
            +beam_off.x, beam_off.y, beam_off.z,
        ).rotate(*angles)

    # Allow adding outputs to the last path_track.
    for prop in res.find_all('EndOutput'):
        output = Output.parse(prop)
        output.output = 'OnPass'
        output.inst_out = None
        output.comma_sep = False
        output.target = conditions.local_name(inst, output.target)
        last_track.add_out(output)

    if motion_filter is not None:
        motion_trig = vmf.create_ent(
            classname='trigger_multiple',
            targetname=conditions.local_name(inst, 'enable_motion_trig'),
            origin=start_pos,
            filtername=motion_filter,
            startDisabled=1,
            wait=0.1,
        )
        motion_trig.add_out(Output('OnStartTouch', '!activator', 'ExitDisabledState'))
        # Match the size of the original...
        motion_trig.solids.append(vmf.make_prism(
            start_pos + Vec(72, -56, 58).rotate(*angles),
            end_pos + Vec(-72, 56, 144).rotate(*angles),
            mat='tools/toolstrigger',
        ).solid)

    if res.bool('NoPortalFloor'):
        # Block portals on the floor..
        floor_noportal = vmf.create_ent(
            classname='func_noportal_volume',
            origin=beam_start,
        )
        floor_noportal.solids.append(vmf.make_prism(
            start_pos + Vec(-60, -60, -66).rotate(*angles),
            end_pos + Vec(60, 60, -60).rotate(*angles),
            mat='tools/toolsinvisible',
        ).solid)

    # A brush covering under the platform.
    base_trig = vmf.make_prism(
        start_pos + Vec(-64, -64, 48).rotate(*angles),
        end_pos + Vec(64, 64, 56).rotate(*angles),
        mat='tools/toolsinvisible',
    ).solid

    vmf.add_brush(base_trig)

    # Make a paint_cleanser under the belt..
    if res.bool('PaintFizzler'):
        pfizz = vmf.create_ent(
            classname='trigger_paint_cleanser',
            origin=start_pos,
        )
        pfizz.solids.append(base_trig.copy())
        for face in pfizz.sides():
            face.mat = 'tools/toolstrigger'
