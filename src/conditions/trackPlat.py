"""Conditions relating to track platforms."""
import conditions
import srctools
import utils
import vbsp
from conditions import (
    make_result, RES_EXHAUSTED,
)
from instanceLocs import resolve as resolve_inst
from srctools import Vec, Entity


LOGGER = utils.getLogger(__name__, alias='cond.trackPlat')


@make_result('trackPlatform')
def res_track_plat(_, res):
    """Logic specific to Track Platforms.

    This allows switching the instances used depending on if the track
    is horizontal or vertical and sets the track
    targetnames to a useful value.
    Values:
        - Orig_item: The "<ITEM_ID>" for the track platform, with angle brackets
        - Single_plat: An instance used for platform with 1 rail
        - Track_name: The name to give to the tracks.
        - Vert_suffix: Add suffixes to vertical tracks
            (_vert)
        - Horiz_suffix: Add suffixes to horizontal tracks
            (_horiz, _horiz_mirrored)
        - plat_suffix: Also add the above _vert or _horiz suffixes to
            the platform.
        - vert_bottom_suffix: Add '_bottom' / '_vert_bottom' to the track at the
            bottom of vertical platforms.
        - plat_var: If set, save the orientation to the given $fixup variable
    """
    # Get the instances from editoritems
    (
        inst_bot_grate, inst_bottom, inst_middle,
        inst_top, inst_plat, inst_plat_oscil, inst_single
    ) = resolve_inst(res['orig_item'])
    # If invalid, [] = false so ''[0] = ''.
    single_plat_inst = (resolve_inst(res['single_plat', '']) or '')[0]
    track_targets = res['track_name', '']

    track_files = [inst_bottom, inst_middle, inst_top, inst_single]
    platforms = [inst_plat, inst_plat_oscil]

    # All the track_set in the map, indexed by origin
    track_instances = {
        Vec.from_str(inst['origin']).as_tuple(): inst
        for inst in
        vbsp.VMF.by_class['func_instance']
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
    for plat_inst in vbsp.VMF.by_class['func_instance']:
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

        track_set = set()
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

        # The direction horizontal track is offset
        side_dir = Vec(0, 1, 0).rotate_by_str(first_track['angles'])

        # The direction of the platform surface
        facing = Vec(-1, 0, 0).rotate_by_str(plat_inst['angles'])
        if side_dir == facing:
            track_facing = 'HORIZ'
        elif side_dir == -facing:
            track_facing = 'HORIZ_MIRR'
        else:
            track_facing = 'VERT'
        # Now add the suffixes
        if track_facing == 'VERT':
            if srctools.conv_bool(res['vert_suffix', '']):
                for inst in track_set:
                    conditions.add_suffix(inst, '_vert')
                if srctools.conv_bool(res['plat_suffix', '']):
                    conditions.add_suffix(plat_inst, '_vert')
            if srctools.conv_bool(res['vert_bottom_suffix', '']):
                # We want to find the bottom/top track which is facing the
                # same direction as the platform.
                track_dirs = {
                    inst_top: Vec(-1, 0, 0),
                    inst_bottom: Vec(1, 0, 0)
                }
                for inst in track_set:
                    try:
                        norm_off = track_dirs[inst['file'].casefold()]
                    except KeyError:
                        continue

                    if norm_off.rotate_by_str(inst['angles']) == facing:
                        conditions.add_suffix(inst, '_bottom')

        elif track_facing == 'HORIZ_MIRR':
            if srctools.conv_bool(res['horiz_suffix', '']):
                for inst in track_set:
                    conditions.add_suffix(inst, '_horiz_mirrored')
                if srctools.conv_bool(res['plat_suffix', '']):
                    conditions.add_suffix(plat_inst, '_horiz')
        else:  # == 'HORIZ'
            if srctools.conv_bool(res['horiz_suffix', '']):
                for inst in track_set:
                    conditions.add_suffix(inst, '_horiz')
                if srctools.conv_bool(res['plat_suffix', '']):
                    conditions.add_suffix(plat_inst, '_horiz')

        plat_var = res['plat_var', '']
        if plat_var != '':
            # Skip the '_mirrored' section if needed
            plat_inst.fixup[plat_var] = track_facing[:5].lower()

    return RES_EXHAUSTED # Don't re-run


def track_scan(
        tr_set,
        track_inst,
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
