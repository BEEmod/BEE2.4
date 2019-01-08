"""Conditions relating to track platforms."""
from typing import Set, Dict, Tuple

import conditions
import srctools.logger
from conditions import (
    make_result, RES_EXHAUSTED,
)
import instanceLocs
from srctools import Vec, Property, Entity, VMF


COND_MOD_NAME = 'Track Platforms'


LOGGER = srctools.logger.get_logger(__name__, alias='cond.trackPlat')


@make_result('trackPlatform')
def res_track_plat(vmf: VMF, res: Property):
    """Logic specific to Track Platforms.

    This allows switching the instances used depending on if the track
    is horizontal or vertical and sets the track
    targetnames to a useful value. This should be run unconditionally, not
    once per item.
    Values:
    
    * `orig_item`: The "<ITEM_ID>" for the track platform, with angle brackets.
      This is used to determine all the instance filenames.
    * `single_plat`: An instance used for the entire platform, if it's
      one rail long (and therefore can't move).
    * `track_name`: If set, rename track instances following the pattern
      `plat_name-track_nameXX`. Otherwise all tracks will receive the name
      of the platform.
    * `plat_suffix`: If set, add a `_vert` or `_horiz` suffix
      to the platform.
    * `plat_var`: If set, save the orientation (`vert`/`horiz`) to the
      provided $fixup variable.
    * `track_var`: If set, save `N`, `S`, `E`, or `W` to the provided $fixup
      variable to indicate the relative direction the top faces.
    """
    # Get the instances from editoritems
    (
        inst_bot_grate, inst_bottom, inst_middle,
        inst_top, inst_plat, inst_plat_oscil, inst_single
    ) = instanceLocs.resolve(res['orig_item'])
    single_plat_inst = instanceLocs.resolve_one(res['single_plat', ''])
    track_targets = res['track_name', '']

    track_files = [inst_bottom, inst_middle, inst_top, inst_single]
    platforms = [inst_plat, inst_plat_oscil]

    # All the track_set in the map, indexed by origin
    track_instances = {
        Vec.from_str(inst['origin']).as_tuple(): inst
        for inst in
        vmf.by_class['func_instance']
        if inst['file'].casefold() in track_files
    }

    LOGGER.debug('Track instances:')
    LOGGER.debug('\n'.join(
        '{!s}: {}'.format(k, v['file'])
        for k, v in
        track_instances.items()
    ))

    if not track_instances:
        return RES_EXHAUSTED

    # Now we loop through all platforms in the map, and then locate their
    # track_set
    for plat_inst in vmf.by_class['func_instance']:
        if plat_inst['file'].casefold() not in platforms:
            continue  # Not a platform!

        LOGGER.debug('Modifying "' + plat_inst['targetname'] + '"!')

        plat_loc = Vec.from_str(plat_inst['origin'])
        # The direction away from the wall/floor/ceil
        normal = Vec(0, 0, 1).rotate_by_str(
            plat_inst['angles']
        )

        for tr_origin, first_track in track_instances.items():
            if plat_loc == tr_origin:
                # Check direction

                if normal == Vec(0, 0, 1).rotate(
                        *Vec.from_str(first_track['angles'])
                        ):
                    break
        else:
            raise Exception('Platform "{}" has no track!'.format(
                plat_inst['targetname']
            ))

        track_type = first_track['file'].casefold()
        if track_type == inst_single:
            # Track is one block long, use a single-only instance and
            # remove track!
            plat_inst['file'] = single_plat_inst
            first_track.remove()
            continue  # Next platform

        track_set = set()  # type: Set[Entity]
        if track_type == inst_top or track_type == inst_middle:
            # search left
            track_scan(
                track_set,
                track_instances,
                first_track,
                middle_file=inst_middle,
                x_dir=-1,
            )
        if track_type == inst_bottom or track_type == inst_middle:
            # search right
            track_scan(
                track_set,
                track_instances,
                first_track,
                middle_file=inst_middle,
                x_dir=+1,
            )

        # Give every track a targetname matching the platform
        for ind, track in enumerate(track_set, start=1):
            if track_targets == '':
                track['targetname'] = plat_inst['targetname']
            else:
                track['targetname'] = (
                    plat_inst['targetname'] +
                    '-' +
                    track_targets + str(ind)
                )

        # Now figure out which way the track faces:

        # The direction of the platform surface
        facing = Vec(-1, 0, 0).rotate_by_str(plat_inst['angles'])

        # The direction horizontal track is offset
        uaxis = Vec(x=1).rotate_by_str(first_track['angles'])
        vaxis = Vec(y=1).rotate_by_str(first_track['angles'])

        if uaxis == facing:
            plat_facing = 'vert'
            track_facing = 'E'
        elif uaxis == -facing:
            plat_facing = 'vert'
            track_facing = 'W'
        elif vaxis == facing:
            plat_facing = 'horiz'
            track_facing = 'N'
        elif vaxis == -facing:
            plat_facing = 'horiz'
            track_facing = 'S'
        else:
            raise ValueError('Facing {} is not U({}) or V({})!'.format(
                facing,
                uaxis,
                vaxis,
            ))

        if res.bool('plat_suffix'):
            conditions.add_suffix(plat_inst, '_' + plat_facing)

        plat_var = res['plat_var', '']
        if plat_var:
            plat_inst.fixup[plat_var] = plat_facing

        track_var = res['track_var', '']
        if track_var:
            plat_inst.fixup[track_var] = track_facing

        for track in track_set:
            track.fixup.update(plat_inst.fixup)

    return RES_EXHAUSTED  # Don't re-run


def track_scan(
    tr_set: Set[Entity],
    track_inst: Dict[Tuple[float, float, float], Entity],
    start_track: Entity,
    middle_file: str,
    x_dir: int,
):
    """Build a set of track instances extending from a point.
    :param track_inst: A dictionary mapping origins to track instances
    :param start_track: The instance we start on
    :param middle_file: The file for the center track piece
    :param x_dir: The direction to look (-1 or 1)
    """
    track = start_track
    move_dir = Vec(x_dir*128, 0, 0).rotate_by_str(track['angles'])
    while track:
        tr_set.add(track)

        next_pos = Vec.from_str(track['origin']) + move_dir
        track = track_inst.get(next_pos.as_tuple(), None)
        if track is None:
            return
        if track['file'].casefold() != middle_file:
            # If the next piece is an end section, add it then quit
            tr_set.add(track)
            return
