"""Manages parsing and regenerating antlines."""
import random
from collections import namedtuple

from srctools import Vec, Property, conv_float, Entity, VMF, logger
import srctools.vmf
import comp_consts as const
from collections import defaultdict
from typing import List, Dict, Tuple, TYPE_CHECKING

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

    def apply(self, overlay: Entity):
        """Apply the texture to the overlay."""
        overlay['material'] = self.texture
        overlay['endu'] = self.scale
        if self.static:
            del overlay['targetname']


class AntType:
    """Defines the style of antline to use.

    For broken antlines, 'broken_chance' is the percentage chance for brokenness
    per dot.
    """
    def __init__(
        self,
        tex_straight: List[AntTex],
        tex_corner: List[AntTex],
        broken_straight: List[AntTex],
        broken_corner: List[AntTex],
        broken_chance: float,
    ):
        self.tex_straight = tex_straight
        self.tex_corner = tex_corner

        if broken_chance == 0:
            broken_corner = broken_straight = []

        self.broken_corner = broken_corner
        self.broken_straight = broken_straight
        self.broken_chance = broken_chance

    @classmethod
    def parse(cls, prop: Property):
        """Parse this from a property block."""
        broken_chance = prop.float('broken_chance')
        tex_straight = []
        tex_corner = []
        brok_straight = []
        brok_corner = []
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
    def default(cls):
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



def broken_antline_iter(dist, chance):
    """Iterator used in set_antline_mat().

    This produces min, max pairs which fill the space from 0-dist.
    Neighbouring sections will be merged when they have the same type.
    """
    run_start = 0
    last_type = random.randrange(100) < chance
    for i in range(1, int(dist)):
        next_type = random.randrange(100) < chance
        if next_type != last_type:
            yield run_start, i, last_type
            last_type = next_type
            run_start = i
    yield run_start, int(dist), last_type

    return


def style_antline(over: Entity, conf: AntType, floor_conf: AntType):
    """Retexture an antline.

    floor_conf, if set is an alternate texture set to use on floors and ceilings.
    """
    # Choose a random one
    random.seed(over['origin'])

    # For P1 style, check to see if the antline is on the floor or walls.
    if Vec.from_str(over['basisNormal']).z != 0:
        conf = floor_conf

    if over['material'] == const.Antlines.STRAIGHT:
        mats = conf.tex_straight
        broken_mats = conf.broken_straight
    elif over['material'] == const.Antlines.CORNER:
        mats = conf.tex_corner
        broken_mats = conf.broken_corner
    else:
        raise ValueError('"{}" is not an antline!'.format(over['material']))

    if conf.broken_chance:  # We can have `broken` antlines.
        bbox_min, bbox_max = srctools.vmf.overlay_bounds(over)
        # Number of 'circles' and the length-wise axis
        length = max(bbox_max - bbox_min)
        long_axis = Vec(0, 1, 0).rotate_by_str(over['angles']).axis()

        # It's a corner or short antline - replace instead of adding more
        if length <= 48:
            if random.randrange(100) < conf.broken_chance:
                mats = broken_mats
        else:
            # Generate multiple for broken overlays.
            min_origin = Vec.from_str(over['origin'])
            min_origin[long_axis] -= length / 2

            broken_iter = broken_antline_iter(
                length // 16,
                conf.broken_chance,
            )
            for sect_min, sect_max, is_broken in broken_iter:
                sect_mats = broken_mats if is_broken else mats

                sect_length = sect_max - sect_min

                # Make a section - base it off the original, and shrink it
                new_over = over.copy()
                over.map.add_ent(new_over)

                # Repeats lengthways
                new_over['startV'] = sect_length
                sect_center = (sect_min + sect_max) / 2

                sect_origin = min_origin.copy()
                sect_origin[long_axis] += sect_center * 16
                new_over['basisorigin'] = new_over['origin'] = sect_origin

                # Set the 4 corner locations to determine the overlay size.
                # They're in local space - x is -8/+8, y=length, z=0
                # Match the sign of the current value
                for axis in '0123':
                    pos = Vec.from_str(new_over['uv' + axis])
                    if pos.y < 0:
                        pos.y = -8 * sect_length
                    else:
                        pos.y = 8 * sect_length
                    new_over['uv' + axis] = pos.join(' ')

                random.choice(sect_mats).apply(new_over)
            # Remove the original overlay
            over.remove()
            return  # Don't texture the original.

    random.choice(mats).apply(over)
