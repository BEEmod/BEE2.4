"""Manages parsing and regenerating antlines."""
from collections import defaultdict
from typing import List, Dict, Tuple, TYPE_CHECKING

from enum import Enum

import utils
from srctools import Vec, VMF, Entity
import comp_consts as const
import srctools.vmf

if TYPE_CHECKING:
    from tiling import TileDef

LOGGER = utils.getLogger(__name__)


class SegType(Enum):
    """Type of segment."""
    STRAIGHT = 0
    CORNER = 1


class Segment:
    """A single section of an antline - a straight section or corner.

    For corners, start == end.
    """
    __slots__ = ['type', 'normal', 'start', 'end', 'tiles']

    def __init__(
        self,
        type: SegType,
        normal: Vec,
        start: Vec,
        end: Vec,
    ):
        self.type = type
        self.normal = normal
        # Note, start is end for corners.
        self.start = start
        self.end = end
        # The brushes this segment is attached to.
        self.tiles = []  # type: List['TileDef']


class Antline:
    """A complete antline."""
    def __init__(
        self,
        name: str,
        line: List[Segment],
    ):
        self.line = line
        self.name = name


def parse_antlines(vmf: VMF) -> Tuple[Dict[str, List[Antline]], Dict[str, List[Segment]]]:
    """Convert overlays in the map into Antline objects.

    This returns two dicts. The first maps targetnames to lists of antlines.
    The second maps solid IDs to segments.
    """
    # We want to reconstruct the shape of the antline path.
    # To do that we find the neighbouring points for each overlay.

    LOGGER.info('Parsing antlines...')

    overlay_segment = {}  # type: Dict[Entity, Segment]
    # overlay -> found neighbours of it.
    overlay_joins = defaultdict(list)  # type: Dict[Entity, List[Entity]]

    # Points on antlines where two can connect. For corners that's each side,
    # for straight it's each end. Combine that with the targetname
    # so we only join related antlines.
    join_points = {}  # type: Dict[Tuple[str, float, float, float], Entity]

    mat_straight = const.Antlines.STRAIGHT
    mat_corner = const.Antlines.CORNER

    side_to_seg = {}  # type: Dict[str, List[Segment]]
    antlines = {}  # type: Dict[str, List[Antline]]

    for over in vmf.by_class['info_overlay']:
        mat = over['material']
        origin = Vec.from_str(over['basisorigin'])
        normal = Vec.from_str(over['basisnormal'])
        u, v = Vec.INV_AXIS[normal.axis()]

        if mat == mat_corner:
            seg_type = SegType.CORNER
            start = end = origin

            # One on each side - we know the size.
            points = [
                origin + Vec.with_axes(u, +8),
                origin + Vec.with_axes(u, -8),
                origin + Vec.with_axes(v, +8),
                origin + Vec.with_axes(v, -8),
            ]
        elif mat == mat_straight:
            seg_type = SegType.STRAIGHT

            # We want to determine the length first.
            long_axis = Vec(y=1).rotate_by_str(over['angles']).axis()
            side_axis = Vec(x=1).rotate_by_str(over['angles']).axis()
            # The order of these isn't correct, but we don't know enough to
            # fix that yet.
            start, end = srctools.vmf.overlay_bounds(over)

            offset = Vec.with_axes(side_axis, 8)
            points = [start + offset, end - offset]

            offset[long_axis] = 8
            start += offset
            end -= offset
        else:
            # It's not an antline.
            continue

        overlay_segment[over] = seg = Segment(seg_type, normal, start, end)

        for side_id in over['sides'].split():
            side_to_seg.setdefault(side_id, []).append(seg)

        for point in points:
            # Lookup the point to see if we've already checked it.
            # If not, write us into that spot.
            neighbour = join_points.setdefault(
                (over['targetname'], point.x, point.y, point.z),
                over,
            )
            if neighbour is over:
                # None found
                continue
            overlay_joins[neighbour].append(over)
            overlay_joins[over].append(neighbour)

    for over, segment in overlay_segment.items():
        neighbours = overlay_joins[over]
        if len(neighbours) != 1:
            continue
        # Found a start point!
        [current] = neighbours
        segments = [over, current]
        previous = over
        while True:
            neighbours = overlay_joins[current]
            for neighbour in neighbours:
                if neighbour is not previous:
                    segments.append(neighbour)
                    previous, current = current, neighbour
                    break
            else:
                # No neighbours we haven't got already.
                # Break the while loop.
                break

        name = over['targetname']

        antlines.setdefault(name, []).append(Antline(name, segments))

    LOGGER.info('Done!')
    return antlines, side_to_seg
