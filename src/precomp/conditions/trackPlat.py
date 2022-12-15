"""Conditions relating to track platforms."""
import math

from typing import Optional, Set, Dict, Tuple

import consts
from precomp import instanceLocs, conditions, brushLoc, texturing
from srctools import Matrix, Vec, Property, Entity, VMF, logger


COND_MOD_NAME = 'Track Platforms'
LOGGER = logger.get_logger(__name__, alias='cond.trackPlat')
FACINGS = {
    (0.0, +1.0): 'N',
    (0.0, -1.0): 'S',
    (+1.0, 0.0): 'E',
    (-1.0, 0.0): 'W',
}


@conditions.make_result('trackPlatform')
def res_track_plat(vmf: VMF, res: Property) -> object:
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
    * `goo_bottom`, `goo_top`: If set, these generate goo brushes if required to continue adjacent
      goo pits into the platform embed area. The two values should be offsets relative to their
      respective end instances. The produced brush will be the bounding box encompassing those two
      points, clipped down to wherever the goo is.
    """
    # Get the instances from editoritems
    (
        inst_bot_grate, inst_bottom, inst_middle,
        inst_top, inst_plat, inst_plat_oscil, inst_single
    ) = instanceLocs.resolve(res['orig_item'])
    single_plat_inst = instanceLocs.resolve_one(res['single_plat', ''], error=False)
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
                # Check direction
                if Vec.dot(normal, Matrix.from_angstr(first_track['angles']).up()) > 0.9:
                    break
        else:
            raise Exception(f'Platform "{plat_inst["targetname"]}" has no track!')

        track_type = first_track['file'].casefold()
        if track_type == inst_single:
            # Track is one block long, use a single-only instance and
            # remove track!
            plat_inst['file'] = single_plat_inst
            conditions.ALL_INST.add(single_plat_inst.casefold())
            first_track.remove()
            continue  # Next platform

        track_set: set[Entity] = set()
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
                track['targetname'] = f"{plat_inst['targetname']}-{track_targets}{ind}"

        # Now figure out which way the track faces:

        # The direction of the platform surface
        facing = Matrix.from_angstr(plat_inst['angles']).forward(-1)

        # The direction horizontal track is offset
        orient = Matrix.from_angstr(first_track['angles'])
        local_facing = round(facing @ orient.transpose(), 3)
        if abs(local_facing.z) > 0.125:
            raise ValueError(
                'Platform facing is not in line with track: \n'
                f'track={first_track["angles"]}, plat={plat_inst["angles"]}, facing={local_facing}'
            )

        plat_facing = 'vert' if abs(local_facing.y) > 0.5 else 'horiz'

        if res.bool('plat_suffix'):
            conditions.add_suffix(plat_inst, '_' + plat_facing)

        plat_var = res['plat_var', '']
        if plat_var:
            plat_inst.fixup[plat_var] = plat_facing

        track_var = res['track_var', '']
        if track_var:
            plat_inst.fixup[track_var] = FACINGS[local_facing.x, local_facing.y]

        for track in track_set:
            track.fixup.update(plat_inst.fixup)

        # Don't generate goo on floors/ceilings. Floors will be hidden, on ceilings it doesn't
        # reach there.
        if True or 'goo_top' not in res or 'goo_bottom' not in res or abs(orient.up().z) > 0.5:
            continue

        top_point: Optional[Vec] = None
        bottom_point: Optional[Vec] = None
        highest_goo_z = -math.inf
        for track in track_set:
            # Go through
            track_type = track['file'].casefold()
            track_pos = Vec.from_str(track['origin'])
            if (track_type == inst_top or track_type == inst_single) and 'goo_top' in res:
                top_point = res.vec('goo_top')
                top_point.localise(track_pos, orient)
            if (track_type == inst_bottom or track_type == inst_single) and 'goo_bottom' in res:
                bottom_point = res.vec('goo_bottom')
                bottom_point.localise(track_pos, orient)

            goo_pos = track_pos + (0.0, 0.0, 32.0)
            if brushLoc.POS.lookup_world(goo_pos).is_goo and highest_goo_z < goo_pos.z:
                highest_goo_z = goo_pos.z

        # If both points are valid, and goo is present, place the brush.
        if top_point is not None and bottom_point is not None and math.isfinite(highest_goo_z):
            bbox_min, bbox_max = Vec.bbox(top_point, bottom_point)
            bbox_max.z = min(bbox_max.z, highest_goo_z)
            if (bbox_max - bbox_min) > (1.0, 1.0, 1.0):  # Ensure we don't generate degenerate solids.
                prism = vmf.make_prism(bbox_min, bbox_max, consts.Tools.NODRAW)
                texturing.apply(texturing.GenCat.SPECIAL, prism.top, 'goo_cheap')
                vmf.add_brush(prism.solid)

    return conditions.RES_EXHAUSTED  # Don't re-run


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
    move_dir = Vec(x_dir*128, 0, 0) @ Matrix.from_angstr(track['angles'])
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
