"""Manages parsing and regenerating antlines."""
import random
from collections import namedtuple

from srctools import Vec, Property, conv_float, Entity, VMF, logger
from srctools.vmf import overlay_bounds, make_overlay
import comp_consts as const
from collections import defaultdict
from typing import List, Dict, Tuple, TYPE_CHECKING, Iterator, Optional, Set

from enum import Enum

if TYPE_CHECKING:
    from tiling import TileDef

LOGGER = logger.get_logger(__name__)


class SegType(Enum):
    """Type of segment."""
    STRAIGHT = 0
    CORNER = 1


class AntTex(namedtuple('AntTex', ['texture', 'scale', 'static'])):
    """Represents a single texture, and the parameters it has."""
    @staticmethod
    def parse(prop: Property):
        """Parse from property values.

        The value can be in four forms:
        "prop" "material"
        "prop" "<scale>|material"
        "prop" "<scale>|material|static"
        "prop"
            {
            "tex"    "<mat>"
            "scale"  "<scale>"
            "static" "<is_static>"
            }
        """
        if prop.has_children():
            tex = prop['tex']
            scale = prop.float('scale', 0.25)
            static = prop.bool('static')
        else:
            vals = prop.value.split('|')
            opts = ()
            scale_str = '0.25'

            if len(vals) == 2:
                scale_str, tex = vals
            elif len(vals) > 2:
                scale_str, tex, *opts = vals
            else:
                # Unpack to ensure it only has 1 section
                [tex] = vals
            scale = conv_float(scale_str, 0.25)
            static = 'static' in opts

        return AntTex(tex, scale, static)


class AntType:
    """Defines the style of antline to use.

    For broken antlines, 'broken_chance' is the percentage chance for brokenness
    per dot.

    Corners can be omitted, if corner/straight antlines are the same.
    """
    def __init__(
        self,
        tex_straight: List[AntTex],
        tex_corner: List[AntTex],
        broken_straight: List[AntTex],
        broken_corner: List[AntTex],
        broken_chance: float,
    ) -> None:
        self.tex_straight = tex_straight
        self.tex_corner = tex_corner

        if broken_chance == 0:
            broken_corner = broken_straight = []

        # Cannot have broken corners if corners/straights are the same.
        if not tex_corner:
            broken_corner = []

        self.broken_corner = broken_corner
        self.broken_straight = broken_straight
        self.broken_chance = broken_chance

    @classmethod
    def parse(cls, prop: Property) -> 'AntType':
        """Parse this from a property block."""
        broken_chance = prop.float('broken_chance')
        tex_straight = []  # type: List[AntTex]
        tex_corner = []  # type: List[AntTex]
        brok_straight = []  # type: List[AntTex]
        brok_corner = []  # type: List[AntTex]
        for ant_list, name in zip(
            [tex_straight, tex_corner, brok_straight, brok_corner],
            ('straight', 'corner', 'broken_straight', 'broken_corner'),
        ):
            for sub_prop in prop.find_all(name):
                ant_list.append(AntTex.parse(sub_prop))
        return cls(
            tex_straight,
            tex_corner,
            brok_straight,
            brok_corner,
            broken_chance,
        )

    @classmethod
    def default(cls) -> 'AntType':
        """Make a copy of the original PeTI antline config."""
        return cls(
            [AntTex(const.Antlines.STRAIGHT, 0.25, False)],
            [AntTex(const.Antlines.CORNER, 1, False)],
            [], [], 0,
        )


class Segment:
    """A single section of an antline - a straight section or corner.

    For corners, start == end.
    """
    __slots__ = ['type', 'normal', 'start', 'end', 'tiles']

    def __init__(
        self,
        typ: SegType,
        normal: Vec,
        start: Vec,
        end: Vec,
    ):
        self.type = typ
        self.normal = normal
        # Note, start is end for corners.
        self.start = start
        self.end = end
        # The brushes this segment is attached to.
        self.tiles = set()  # type: Set['TileDef']

    @property
    def on_floor(self) -> bool:
        """Return if this segment is on the floor/wall."""
        return self.normal.z != 0

    def broken_iter(
        self,
        chance: float,
    ) -> Iterator[Tuple[Vec, Vec, bool]]:
        """Iterator to compute positions for straight segments.

        This produces point pairs which fill the space from 0-dist.
        Neighbouring sections will be merged when they have the same
        type.
        """
        offset = self.end - self.start
        dist = offset.mag() // 16
        norm = 16 * offset.norm()

        if dist < 3 or chance == 0:
            # Short antlines always are either on/off.
            yield self.start, self.end, (random.randrange(100) < chance)
        else:
            run_start = self.start
            last_type = random.randrange(100) < chance
            for i in range(1, int(dist)):
                next_type = random.randrange(100) < chance
                if next_type != last_type:
                    yield run_start, self.start + i * norm, last_type
                    last_type = next_type
                    run_start = self.start + i * norm
            yield run_start, self.end, last_type


class Antline:
    """A complete antline."""
    def __init__(
        self,
        name: str,
        line: List[Segment],
    ):
        self.line = line
        self.name = name

    def export(self, vmf: VMF, wall_conf: AntType, floor_conf: AntType) -> None:
        """Add the antlines into the map."""

        # First, do some optimisation. If corners aren't defined, try and
        # optimise those antlines out by merging the straight segment
        # before/after it into the corners.

        if not wall_conf.tex_corner or not floor_conf.tex_corner:
            collapse_line = list(self.line)  # type: List[Optional[Segment]]
            for i, seg in enumerate(collapse_line):
                if seg is None or seg.type is not SegType.STRAIGHT:
                    continue
                if (floor_conf if seg.on_floor else wall_conf).tex_corner:
                    continue
                for corner_ind in [i-1, i+1]:
                    if i == -1:
                        continue
                    try:
                        corner = collapse_line[corner_ind]
                    except IndexError:
                        # Each end of the list.
                        continue

                    if (
                        corner is not None and
                        corner.type is SegType.CORNER and
                        corner.normal == seg.normal
                    ):
                        corner_pos = corner.start
                        if (seg.start - corner_pos).mag_sq() == 8 ** 2:
                            # The line segment is at the border between them,
                            # the corner is at the center. So move double the
                            # distance towards the corner, so it reaches to the
                            # other side of the corner and replaces it.
                            seg.start += 2 * (corner_pos - seg.start)
                            # Remove corner by setting to None, so we aren't
                            # resizing the list constantly.
                            collapse_line[corner_ind] = None
                            # Now merge together the tiledefs.
                            seg.tiles.update(corner.tiles)
                        elif (seg.end - corner_pos).mag_sq() == 8 ** 2:
                            seg.end += 2 * (corner_pos - seg.end)
                            collapse_line[corner_ind] = None
                            seg.tiles.update(corner.tiles)

            self.line[:] = [seg for seg in collapse_line if seg is not None]
            LOGGER.info('Collapsed {} antline corners', collapse_line.count(None))

        for seg in self.line:
            conf = floor_conf if seg.on_floor else wall_conf
            random.seed('ant {} {}'.format(seg.start, seg.end))
            if seg.type is SegType.CORNER:
                if random.randrange(100) < conf.broken_chance:
                    mat = random.choice(conf.broken_corner or conf.broken_straight)  # type: AntTex
                else:
                    mat = random.choice(conf.tex_corner or conf.tex_straight)

                axis_u, axis_v = Vec.INV_AXIS[seg.normal.axis()]
                self._make_overlay(
                    vmf,
                    seg,
                    seg.start,
                    Vec.with_axes(axis_u, 16),
                    Vec.with_axes(axis_v, 16),
                    mat,
                )
            else:  # Straight
                # TODO: Break up these segments.
                for a, b, is_broken in seg.broken_iter(conf.broken_chance):
                    if is_broken:
                        mat = random.choice(conf.broken_straight)
                    else:
                        mat = random.choice(conf.tex_straight)
                    self._make_straight(
                        vmf,
                        seg,
                        a,
                        b,
                        mat,
                    )

    def _make_overlay(
        self,
        vmf: VMF,
        segment: Segment,
        pos: Vec,
        uax: Vec,
        vax: Vec,
        mat: AntTex,
    ) -> None:
        """Construct an antline overlay at this position."""
        overlay = make_overlay(
            vmf,
            segment.normal,
            pos,
            uax,
            vax,
            mat.texture,
            [],
            u_repeat=(uax.mag() / 16) * mat.scale,
        )
        if not mat.static:
            overlay['targetname'] = self.name

        overlay.tiledefs = list(segment.tiles)

    def _make_straight(
        self,
        vmf: VMF,
        segment: Segment,
        start: Vec,
        end: Vec,
        mat: AntTex,
    ) -> None:
        """Construct a straight antline between two points.

        The two points will be the end of the antlines.
        """
        offset = start - end
        forward = offset.norm()
        side = Vec.cross(segment.normal, forward).norm()

        length = offset.mag()

        self._make_overlay(
            vmf,
            segment,
            (start + end) / 2,
            length * forward,
            16 * side,
            mat,
        )


def parse_antlines(vmf: VMF) -> Tuple[
    Dict[str, List[Antline]],
    Dict[int, List[Segment]]
]:
    """Convert overlays in the map into Antline objects.

    This returns two dicts. The first maps targetnames to lists of antlines.
    The second maps solid IDs to segments, for assigning TileDefs to them.
    """
    # We want to reconstruct the shape of the antline path.
    # To do that we find the neighbouring points for each overlay.

    LOGGER.info('Parsing antlines...')

    # segment -> found neighbours of it.
    overlay_joins = defaultdict(set)  # type: Dict[Segment, Set[Segment]]

    segment_to_name = {}  # type: Dict[Segment, str]

    # Points on antlines where two can connect. For corners that's each side,
    # for straight it's each end. Combine that with the targetname
    # so we only join related antlines.
    join_points = {}  # type: Dict[Tuple[str, float, float, float], Segment]

    mat_straight = const.Antlines.STRAIGHT
    mat_corner = const.Antlines.CORNER

    side_to_seg = {}  # type: Dict[int, List[Segment]]
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

            # The order of these isn't correct, but we need the neigbours to
            # fix that.
            start, end = overlay_bounds(over)

            if end[long_axis] - start[long_axis] == 16:
                # Special case.
                # 1-wide antlines don't have the correct
                # rotation, pointing always in the U axis.
                # So we need to figure that out to get the correct links.
                # For now just create the segment with dummy values.
                start = end = origin
                points = []
            else:
                offset = Vec.with_axes(side_axis, 8)
                start += offset
                end -= offset

                points = [start, end]
        else:
            # It's not an antline.
            continue

        seg = Segment(seg_type, normal, start, end)
        segment_to_name[seg] = over_name = over['targetname']

        for side_id in over['sides'].split():
            side_to_seg.setdefault(int(side_id), []).append(seg)

        for point in points:
            # Lookup the point to see if we've already checked it.
            # If not, write us into that spot.
            neighbour = join_points.setdefault(
                (over_name, point.x, point.y, point.z),
                seg,
            )
            if neighbour is seg:
                # None found
                continue
            overlay_joins[neighbour].add(seg)
            overlay_joins[seg].add(neighbour)

        # Remove original from the map.
        over.remove()

    # Now fix the square straight segments.
    for seg, over_name in segment_to_name.items():
        if seg.type is SegType.STRAIGHT and seg.start == seg.end:
            fix_single_straight(seg, over_name, join_points, overlay_joins)

    # Now, finally compute each continuous section.
    for segment, over_name in segment_to_name.items():
        try:
            neighbours = overlay_joins[segment]
        except KeyError:
            continue  # Done already.

        if len(neighbours) != 1:
            continue
        # Found a start point!
        segments = [segment]

        for segment in segments:
            neighbours = overlay_joins.pop(segment)
            # Except KeyError: this segment's already done??
            for neighbour in neighbours:
                if neighbour not in segments:
                    segments.append(neighbour)

        antlines.setdefault(over_name, []).append(Antline(over_name, segments))

    LOGGER.info('Done! ({} antlines)'.format(sum(map(len, antlines.values()))))
    return antlines, side_to_seg


def fix_single_straight(
    seg: Segment,
    over_name: str,
    join_points: Dict[Tuple[str, float, float, float], Segment],
    overlay_joins: Dict[Segment, Set[Segment]],
) -> None:
    """Figure out the correct rotation for 1-long straight antlines."""
    # Check the U and V axis, to see if there's another antline on both
    # sides. If there is that's the correct orientation.
    axis_u, axis_v = Vec.INV_AXIS[seg.normal.axis()]

    center = seg.start.copy()

    for off in [
        Vec.with_axes(axis_u, -8),
        Vec.with_axes(axis_u, +8),
        Vec.with_axes(axis_v, -8),
        Vec.with_axes(axis_v, +8),
    ]:
        pos = center + off
        try:
            neigh = join_points[over_name, pos.x, pos.y, pos.z]
        except KeyError:
            continue

        overlay_joins[seg].add(neigh)
        overlay_joins[neigh].add(seg)

        off_min = center - abs(off)
        off_max = center + abs(off)

        # If corners are on both opposite sides, we can be fairly confident
        # that's the correct orientation. If we don't have that (end of trail),
        # settle for one side.
        if seg.start == seg.end:
            # No points found. This is our best guess.
            seg.start = off_min
            seg.end = off_max
        elif seg.start != off_min or seg.end != off_max:
            # The other side is also present. Only override if we are on both
            # sides.
            opposite = center - off
            if (over_name, opposite.x, opposite.y, opposite.z) in join_points:
                seg.start = off_min
                seg.end = off_max
        # Else: Both equal, we're fine.
    if seg.start == seg.end:
        raise ValueError(
            'Cannot determine orientation '
            'for 1-wide straight '
            'antline at ({})!'.format(seg.start)
        )
