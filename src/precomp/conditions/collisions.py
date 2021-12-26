"""Conditions which query or modify item collisions."""
from __future__ import annotations
from srctools import Angle, Matrix, Vec, Property, VMF, Entity, conv_float, logger

from precomp import conditions, instance_traits
from precomp.collisions import CollideType, Collisions, BBox

from typing import Callable


LOGGER = logger.get_logger('cond.collisions')
CollModification = Callable[[Entity, Collisions], None]


@conditions.make_result('Collisions')
def res_mod_conditions(vmf: VMF, inst: Entity, coll: Collisions, res: Property) -> None:
    """Modify conditions on the current item. Each block inside is applied one by one:

    - BBox: Add a new collision box for this item:
        - type: Space-seperated list of collision types this collision will contain.
        - tags: Space-seperated list of 'tags' to associate with these collisions.
        - pos1, pos2: The two positions for this bounding box.
        - off1, off2: May be repeated in any order, to apply shifts to the positions.
          Each must have a 'dir' and 'dist' value pair. The direction is scaled by the distance,
          then added to the position.
    - Remove: Remove bounding boxes from this item with the tags specified in the value.
    - TrackPlat: Add a bounding box across the whole of a track platform's movement volume. This
        takes the same parameters as BBox, except that the left and right sides (X) are positioned
        relative to those ends of the track.
    """
    name = inst['targetname']
    LOGGER.info('"{}":{} -> coll {}', name, inst['file'], coll.collisions_for_item(inst['targetname']))
    origin = Vec.from_str(inst['origin'])
    orient = Matrix.from_angle(Angle.from_str(inst['angles']))

    # Offset from platform of the track start and end.
    track_center = origin.copy()
    track_dir = Vec(1, 0, 0)
    track_dist = 0.0
    track_orient = orient.copy()
    if 'trackplat' in res:
        # We need the orientation of the track, so search all ents :(
        for track_inst in vmf.by_class['func_instance']:
            if Vec.from_str(track_inst['origin']) != origin:
                continue
            if 'track' not in instance_traits.get(track_inst):
                # Not a track.
                continue
            track_orient = Matrix.from_angle(Angle.from_str(track_inst['angles']))
            if Vec.dot(orient.up(), track_orient.up()) > 0.99:
                # Found pointing the same way, it's ours.
                break
        else:
            LOGGER.warning('No track found for track "{}" @ {}!', name, origin)
            # Just assume track is pointed the same direction as the platform.
            track_orient = orient.copy()
        # Now, get the track direction relative to the track instances.
        # The angle is currently local to the platform, so go to world and back.
        plat_track_dir = track_dir @ Angle.from_str(inst.fixup['travel_direction'])
        world_track_dir = plat_track_dir @ orient
        track_dir = world_track_dir @  track_orient.transpose()
        track_dist = conv_float(inst.fixup.float('travel_distance'))
        # Oscillating might move the midpoint of the track.
        track_pos = inst.fixup.float('starting_position', 0.0)
        track_center += (0.5 - track_pos) * track_dist * world_track_dir
        inst.map.create_ent('info_target', origin=track_center)

    for prop in res:
        if prop.name == 'remove':
            tags = frozenset(map(str.casefold, inst.fixup.substitute(prop.value).split()))
            for bbox in coll.collisions_for_item(name):
                if bbox.tags & tags:
                    coll.remove_bbox(bbox)
        elif prop.name in ('bbox', 'trackplat'):
            pos1 = Vec.from_str(inst.fixup.substitute(prop['pos1']), -64, -64, -64)
            pos2 = Vec.from_str(inst.fixup.substitute(prop['pos2']), +64, +64, +64)
            tags = frozenset(map(str.casefold, inst.fixup.substitute(prop['tags', '']).split()))
            content = CollideType.parse(inst.fixup.substitute(prop['type']))

            if prop.name == 'trackplat':
                for pos in [pos1, pos2]:
                    dot = Vec.dot(pos, track_dir)
                    if dot > 0.01:
                        pos += (track_dist / 2) * track_dir
                    elif dot < -0.01:
                        pos -= (track_dist / 2) * track_dir
                rotation = track_orient
                box_pos = track_center
            else:
                rotation = orient
                box_pos = origin
            vmf.create_ent('info_target', origin=box_pos, angles=rotation.to_angle()).comments = f'{track_dist} @ {track_dir}'
            for subprop in prop:
                if subprop.name not in ('off1', 'off2'):
                    continue
                if subprop.has_children():
                    dist = conv_float(inst.fixup.substitute(subprop['dist', '1.0']))
                    direction = Vec.from_str(inst.fixup.substitute(subprop['dir']))
                    offset = direction * dist
                else:
                    offset = Vec.from_str(inst.fixup.substitute(subprop.value))

                if subprop.name == 'off1':
                    pos1 += offset
                else:
                    pos2 += offset

            coll.add(BBox(
                pos1 @ rotation + box_pos,
                pos2 @ rotation + box_pos,
                content, tags, name,
            ))
        else:
            LOGGER.warning('Unknown collision option "{}"!', prop.name)
