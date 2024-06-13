"""Conditions relating to track platforms."""

from srctools import FrozenVec, Matrix, Vec, Keyvalues, Entity, VMF, conv_int, logger

from precomp import instanceLocs, conditions
from precomp.lazy_value import LazyValue
import utils



COND_MOD_NAME = 'Track Platforms'
LOGGER = logger.get_logger(__name__, alias='cond.trackPlat')
FACINGS = {
    (0.0, +1.0): 'N',
    (0.0, -1.0): 'S',
    (+1.0, 0.0): 'E',
    (-1.0, 0.0): 'W',
}


@conditions.make_result('trackPlatform')
def res_track_plat(vmf: VMF, res: Keyvalues) -> object:
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
    * `multi_track`: If set, replace the track instances with combined versions.
       Each sub-key should be the length of the piece, with the value the instance to use instead.
    * `multi_overlap_ends`: If true, the multi-instances will include the space spanned by the
       top/bottom tracks (but those instances will remain).
    * `track_name`: If set, rename track instances following the pattern
      `plat_name-track_nameXX`. Otherwise, all tracks will receive the name
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
    ) = map(str.casefold, instanceLocs.resolve(res['orig_item']))
    single_plat_inst = instanceLocs.resolve_one(res['single_plat', ''], error=False)
    track_targets = res['track_name', '']

    track_files = [inst_bottom, inst_middle, inst_top, inst_single]
    platforms = [inst_plat, inst_plat_oscil]

    # All the track_set in the map, indexed by origin
    track_instances: dict[FrozenVec, Entity] = {
        FrozenVec.from_str(inst['origin']): inst
        for inst in
        vmf.by_class['func_instance']
        if inst['file'].casefold() in track_files
    }

    multi_sizes = {
        conv_int(kv.name): instanceLocs.resolve_one(kv.value, error=True)
        for kv in
        res.find_children('multi_track')
    }
    multi_fitter = utils.get_piece_fitter(multi_sizes)
    multi_overlap_ends = LazyValue.parse(
        res['multi_overlap_ends', ''],
        allow_invert=True,
    ).as_bool()

    LOGGER.debug('Track instances:')
    LOGGER.debug('\n'.join(
        '{!s}: {}'.format(k, v['file'])
        for k, v in
        track_instances.items()
    ))

    if not track_instances:
        return conditions.RES_EXHAUSTED

    # Now we loop through all platforms in the map, and then locate their
    # track_set
    for plat_inst in vmf.by_class['func_instance']:
        if plat_inst['file'].casefold() not in platforms:
            continue  # Not a platform!

        LOGGER.debug('Modifying "{}"!', plat_inst['targetname'])

        plat_loc = Vec.from_str(plat_inst['origin'])
        # The direction away from the wall/floor/ceil
        normal = Matrix.from_angstr(plat_inst['angles']).up()

        for tr_origin, first_track in track_instances.items():
            if plat_loc == tr_origin:
                # Check direction, in case multiple are in this voxel somehow.
                if Vec.dot(normal, Matrix.from_angstr(first_track['angles']).up()) > 0.9:
                    break
        else:
            raise Exception(f'Platform "{plat_inst["targetname"]}" has no track!')

        track_type = first_track['file'].casefold()
        if track_type == inst_single and single_plat_inst:
            # Track is one block long, use a single-only instance and
            # remove track!
            plat_inst['file'] = single_plat_inst
            conditions.ALL_INST.add(single_plat_inst.casefold())
            first_track.remove()
            continue  # Next platform

        track_set = {first_track}
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

        # The direction horizontal track is offset
        track_ang = first_track['angles']
        track_orient = Matrix.from_angstr(track_ang)

        # Sort to put them in the right order.
        track_dir = track_orient.forward()
        track_list = sorted(track_set, key=lambda ent: Vec.dot(
            track_dir,
            Vec.from_str(ent['origin']),
        ))
        del track_set

        if multi_sizes:
            # Adjust positions to be the ends, not voxel centers. If keep ends is false, ignore the ends.
            adjust = (-64.0 if multi_overlap_ends(plat_inst) else +64.0) * track_dir
            pos_a = Vec.from_str(track_list[0]['origin']) + adjust
            pos_b = Vec.from_str(track_list[-1]['origin']) - adjust
            offset = 0.0
            length = round((pos_b - pos_a).mag())
            if length:  # Ignore if only the ends.
                # Remove originals.
                for track in track_list[1:-1]:
                    track.remove()
                last_track = track_list.pop()
                for size in multi_fitter(length):
                    track_list.append(conditions.add_inst(
                        vmf,
                        file=multi_sizes[size],
                        origin=pos_a + (offset + size / 2) * track_dir,
                        angles=track_ang,
                    ))
                    offset += size
                track_list.append(last_track)

        # Give every track a targetname matching the platform
        for ind, track in enumerate(track_list, start=1):
            if track_targets == '':
                track['targetname'] = plat_inst['targetname']
            else:
                track['targetname'] = f"{plat_inst['targetname']}-{track_targets}{ind}"

        # Now figure out which way the track faces:

        # The direction of the platform surface
        facing = Matrix.from_angstr(plat_inst['angles']).forward(-1)

        local_facing = round(facing @ track_orient.transpose(), 3)
        LOGGER.debug('Platform {} has facing {} with orient {}', plat_inst['targetname'], local_facing, track_orient)
        if abs(local_facing.z) > 0.125:
            raise ValueError(
                'Platform facing is not in line with track: \n'
                f'track={first_track["angles"]}, plat={plat_inst["angles"]}, facing={local_facing}'
            )

        plat_facing = 'vert' if abs(local_facing.x) > 0.5 else 'horiz'

        if res.bool('plat_suffix'):
            conditions.add_suffix(plat_inst, '_' + plat_facing)

        plat_var = res['plat_var', '']
        if plat_var:
            plat_inst.fixup[plat_var] = plat_facing

        track_var = res['track_var', '']
        if track_var:
            plat_inst.fixup[track_var] = FACINGS[local_facing.x, local_facing.y]

        for track in track_list:
            track.fixup.update(plat_inst.fixup)

    return conditions.RES_EXHAUSTED  # Don't re-run


def track_scan(
    tr_set: set[Entity],
    track_inst: dict[FrozenVec, Entity],
    start_track: Entity,
    middle_file: str,
    x_dir: int,
) -> None:
    """Build a set of track instances extending from a point.
    :param tr_set: The set of all tracks to add new ones to.
    :param track_inst: A dictionary mapping origins to track instances
    :param start_track: The instance we start on
    :param middle_file: The file for the center track piece
    :param x_dir: The direction to look (-1 or 1)
    """
    track: Entity | None = start_track
    move_dir = Vec(x_dir*128, 0, 0) @ Matrix.from_angstr(start_track['angles'])
    while track:
        tr_set.add(track)

        next_pos = FrozenVec.from_str(track['origin']) + move_dir
        track = track_inst.get(next_pos, None)
        if track is None:
            return
        if track['file'].casefold() != middle_file:
            # If the next piece is an end section, add it then quit
            tr_set.add(track)
            return
