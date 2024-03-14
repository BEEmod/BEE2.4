"""Manages parsing and regenerating antlines."""
from __future__ import annotations
from typing import Callable, Dict, Mapping, Tuple, final, List, Optional, Sequence

from collections import defaultdict
from collections.abc import Iterator, Container
from enum import Enum
import math

import attrs
from srctools import EmptyMapping, FrozenVec, Vec, Matrix, Keyvalues, conv_float, logger
from srctools.vmf import Output, VMF, overlay_bounds, make_overlay

from precomp import options, tiling, rand
from connections import get_outputs, TimerModes
import consts
import editoritems


LOGGER = logger.get_logger(__name__)


class SegType(Enum):
    """Type of segment."""
    STRAIGHT = 0
    CORNER = 1


class PanelSwitchingStyle(Enum):
    """How the panel instance does its switching."""
    CUSTOM = 'custom'      # Some logic, we don't do anything.
    EXTERNAL = 'external'  # Provide a toggle to the instance.
    INTERNAL = 'internal'  # The inst has a toggle or panel, so we can reuse it.


@attrs.define
class AntTex:
    """Represents a single texture, and the parameters it has."""
    texture: str
    scale: float
    static: bool

    @classmethod
    def parse(cls, kv: Keyvalues) -> AntTex:
        """Parse from keyvalue blocks.

        The value can be in four forms:
        "antline_kind" "material"
        "antline_kind" "<scale>|material"
        "antline_kind" "<scale>|material|static"
        "antline_kind"
            {
            "tex"    "<mat>"
            "scale"  "<scale>"
            "static" "<is_static>"
            }
        """
        if kv.has_children():
            tex = kv['tex']
            scale = kv.float('scale', 0.25)
            static = kv.bool('static')
        else:
            vals = kv.value.split('|')
            opts: Container[str] = ()
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

        return cls(tex, scale, static)


@attrs.define(eq=False)
class AntType:
    """Defines the style of antline to use.

    For broken antlines, 'broken_chance' is the percentage chance for brokenness
    per dot.

    Corners can be omitted, if corner/straight antlines are the same.
    """
    tex_straight: list[AntTex]
    tex_corner: list[AntTex]

    broken_straight: list[AntTex]
    broken_corner: list[AntTex]
    broken_chance: float

    @classmethod
    def parse(cls, kv: Keyvalues) -> AntType:
        """Parse this from a property block."""
        broken_chance = kv.float('broken_chance')
        tex_straight: list[AntTex] = []
        tex_corner: list[AntTex] = []
        brok_straight: list[AntTex] = []
        brok_corner: list[AntTex] = []
        for ant_list, name in zip(
            [tex_straight, tex_corner, brok_straight, brok_corner],
            ('straight', 'corner', 'broken_straight', 'broken_corner'),
        ):
            for sub_prop in kv.find_all(name):
                ant_list.append(AntTex.parse(sub_prop))

        if broken_chance < 0.0:
            LOGGER.warning('Antline broken chance must be between 0-100, got "{}"!', kv['broken_chance'])
            broken_chance = 0.0
        if broken_chance > 100.0:
            LOGGER.warning('Antline broken chance must be between 0-100, got "{}"!', kv['broken_chance'])
            broken_chance = 100.0

        if broken_chance == 0.0:
            brok_straight.clear()
            brok_corner.clear()

        # Cannot have broken corners if corners/straights are the same.
        if not tex_corner:
            brok_corner.clear()

        return cls(
            tex_straight,
            tex_corner,
            brok_straight,
            brok_corner,
            broken_chance,
        )

    @classmethod
    def default(cls) -> AntType:
        """Make a copy of the original PeTI antline config."""
        return AntType(
            [AntTex(consts.Antlines.STRAIGHT, 0.25, False)],
            [AntTex(consts.Antlines.CORNER, 1.0, False)],
            [], [], 0.0,
        )


@final
@attrs.frozen(eq=False, kw_only=True)
class IndicatorStyle:
    """Represents complete configuration for antlines and indicator panels."""
    wall: AntType
    floor: AntType

    # Instance to use for checkmark signs.
    check_inst: str
    check_switching: PanelSwitchingStyle
    # Sign inputs to swap the two versions.
    check_cmd: Sequence[Output]
    cross_cmd: Sequence[Output]

    # Instance to use for timer signs.
    timer_inst: str
    timer_switching: PanelSwitchingStyle
    # Outputs to use for the advanced version to swap skins, and to control the indicator.
    timer_blue_cmd: Sequence[Output]
    timer_oran_cmd: Sequence[Output]
    timer_adv_cmds: Mapping[TimerModes, Sequence[Output]]
    # And the simplified on/off inputs.
    timer_basic_start_cmd: Sequence[Output]
    timer_basic_stop_cmd: Sequence[Output]

    @classmethod
    def parse(cls, kv: Keyvalues, desc: str, parent: IndicatorStyle) -> IndicatorStyle:
        """Parse the style from a configuration block.

        If sections are not specified, they will be inherited from the parent.
        """
        return cls.parser(kv, desc)(parent)

    @classmethod
    def parser(cls, kv: Keyvalues, desc: str) -> Callable[[IndicatorStyle], IndicatorStyle]:
        """Parse the style from a configuration block.

        This parses immediately, then returns a callable to allows passing in the parent to inherit
        from later.
        """
        wall: Optional[AntType] = None
        floor: Optional[AntType] = None
        if 'floor' in kv:
            floor = AntType.parse(kv.find_key('floor'))
        if 'wall' in kv:
            wall = AntType.parse(kv.find_key('wall'))

        # Allow 'antline' to specify both.
        if wall is None and floor is None:
            if 'antline' in kv:
                wall = floor = AntType.parse(kv.find_key('antline'))
            # If both are not there but some textures are, allow omitting the subkey.
            elif 'straight' in kv or 'corner' in kv:
                wall = floor = AntType.parse(kv)

        # If only one is defined, use that for both.
        if wall is None and floor is not None:
            wall = floor
        elif floor is None and wall is not None:
            floor = wall

        timer_inst: Optional[str] = None
        check: Optional[Tuple[str, List[Output], List[Output]]] = None
        timer_adv_cmds: Dict[TimerModes, Sequence[Output]] = {}
        timer_blue_cmd: Optional[List[Output]] = None
        timer_oran_cmd: Optional[List[Output]] = None
        timer_basic_start_cmd: Optional[List[Output]] = None
        timer_basic_stop_cmd: Optional[List[Output]] = None
        check_switching = PanelSwitchingStyle.CUSTOM
        timer_switching = PanelSwitchingStyle.CUSTOM

        check_kv = kv.find_block('check', or_blank=True)
        if bool(check_kv):
            check_inst = check_kv['inst']
            try:
                check_switching = PanelSwitchingStyle(check_kv['switching'])
            except (LookupError, ValueError):
                check_switching = PanelSwitchingStyle.CUSTOM  #  Assume no optimisations
            check_cmd = get_outputs(check_kv, desc, 'check_cmd')
            cross_cmd = get_outputs(check_kv, desc, 'cross_cmd')
            check = check_inst, check_cmd, cross_cmd

        timer_kv = kv.find_block('timer', or_blank=True)
        if bool(timer_kv):
            timer_inst = timer_kv['inst']
            try:
                timer_switching = PanelSwitchingStyle(timer_kv['switching'])
            except (LookupError, ValueError):
                timer_switching = PanelSwitchingStyle.CUSTOM  #  Assume no optimisations
            timer_blue_cmd = get_outputs(timer_kv, desc, 'blue_cmd')
            timer_oran_cmd = get_outputs(timer_kv, desc, 'oran_cmd')
            timer_basic_start_cmd = get_outputs(timer_kv, desc, 'basic_start_cmd')
            timer_basic_stop_cmd = get_outputs(timer_kv, desc, 'basic_stop_cmd')
            for mode in TimerModes:
                outs = get_outputs(timer_kv, desc, f'adv_{mode.value}_cmd')
                if outs:
                    timer_adv_cmds[mode] = outs

        def build(parent: IndicatorStyle) -> IndicatorStyle:
            """Build the config, using parent params if not specified."""
            conf = attrs.evolve(
                parent,
                wall=wall or parent.wall,
                floor=floor or parent.floor,
            )
            if check is not None:
                check_inst, check_cmd, cross_cmd = check
                conf = attrs.evolve(
                    conf,
                    check_inst=check_inst,
                    check_switching=check_switching,
                    check_cmd=check_cmd,
                    cross_cmd=cross_cmd,
                )
            if timer_inst is not None:
                conf = attrs.evolve(
                    conf,
                    timer_inst=timer_inst,
                    timer_switching=timer_switching,
                    timer_adv_cmds=timer_adv_cmds or EmptyMapping,
                    timer_blue_cmd=timer_blue_cmd or (),
                    timer_oran_cmd=timer_oran_cmd or (),
                    timer_basic_start_cmd=timer_basic_start_cmd or (),
                    timer_basic_stop_cmd=timer_basic_stop_cmd or (),
                )
            return conf
        return build

    @classmethod
    def from_legacy(cls, id_to_item: dict[str, editoritems.Item]) -> IndicatorStyle:
        """Produce the original legacy configs by reading from editoritems."""
        check_item = id_to_item['item_indicator_panel']
        timer_item = id_to_item['item_indicator_panel_timer']

        return cls(
            wall=AntType.default(),
            floor=AntType.default(),
            check_inst=str(check_item.instances[0].inst) if check_item.instances else '',
            check_switching=options.IND_PAN_CHECK_SWITCHING.as_enum(PanelSwitchingStyle),
            check_cmd=check_item.conn_config.enable_cmd if check_item.conn_config is not None else (),
            cross_cmd=check_item.conn_config.disable_cmd if check_item.conn_config is not None else (),

            timer_inst=str(timer_item.instances[0].inst) if timer_item.instances else '',
            timer_switching=options.IND_PAN_TIMER_SWITCHING.as_enum(PanelSwitchingStyle),
            timer_basic_start_cmd=timer_item.conn_config.enable_cmd if timer_item.conn_config is not None else (),
            timer_basic_stop_cmd=timer_item.conn_config.disable_cmd if timer_item.conn_config is not None else (),
            # No advanced configs
            timer_adv_cmds=EmptyMapping,
            timer_blue_cmd=(),
            timer_oran_cmd=(),
        )

    def has_advanced_timer(self) -> bool:
        """Check if this has advanced timer options."""
        return bool(self.timer_adv_cmds)


@attrs.define(eq=False)
class Segment:
    """A single section of an antline - a straight section or corner.

    For corners, start == end.
    """
    type: SegType
    normal: Vec
    start: Vec
    end: Vec
    # The brushes this segment is attached to.
    tiles: set[tiling.TileDef] = attrs.Factory(set)

    @property
    def on_floor(self) -> bool:
        """Return if this segment is on the floor/wall."""
        return abs(self.normal.z) > 1e-6

    def broken_iter(
        self,
        chance: float,
    ) -> Iterator[tuple[Vec, Vec, bool]]:
        """Iterator to compute positions for straight segments.

        This produces point pairs which fill the space from 0-dist.
        Neighbouring sections will be merged when they have the same
        type.
        """
        rng = rand.seed(b'ant_broken', self.start, self.end, float(chance))
        offset = self.end - self.start
        dist = offset.mag() // 16
        norm = 16 * offset.norm()

        if dist < 3 or chance == 0.0:
            # Short antlines always are either on/off.
            yield self.start, self.end, (rng.randrange(100) < chance)
        else:
            run_start = self.start
            last_type = rng.randrange(100) < chance
            for i in range(1, int(dist)):
                next_type = rng.randrange(100) < chance
                if next_type != last_type:
                    yield run_start, self.start + i * norm, last_type
                    last_type = next_type
                    run_start = self.start + i * norm
            yield run_start, self.end, last_type


@attrs.define(eq=False)
class Antline:
    """A complete antline."""
    name: str
    line: list[Segment]

    def export(self, vmf: VMF, style: IndicatorStyle) -> None:
        """Add the antlines into the map."""

        # First, do some optimisation. If corners aren't defined, try and
        # optimise those antlines out by merging the straight segment
        # before/after it into the corners.

        collapse_line: list[Segment | None]
        if not style.wall.tex_corner or not style.floor.tex_corner:
            collapse_line = list(self.line)
            for i, seg in enumerate(collapse_line):
                if seg is None or seg.type is not SegType.STRAIGHT:
                    continue
                if (style.floor if seg.on_floor else style.wall).tex_corner:
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
            conf = style.floor if seg.on_floor else style.wall
            # Check tiledefs in the voxels, and assign just in case.
            # antline corner items don't have them defined, and some embed-faces don't work
            # properly. But we keep any segments actually defined also.
            mins, maxs = Vec.bbox(seg.start, seg.end)
            norm_axis = seg.normal.axis()
            u_axis, v_axis = Vec.INV_AXIS[norm_axis]
            for pos in Vec.iter_line(mins, maxs, 128):
                pos[u_axis] = pos[u_axis] // 128 * 128 + 64
                pos[v_axis] = pos[v_axis] // 128 * 128 + 64
                pos -= 64 * seg.normal
                try:
                    tile = tiling.TILES[pos.as_tuple(), seg.normal.as_tuple()]
                except KeyError:
                    pass
                else:
                    seg.tiles.add(tile)

            rng = rand.seed(b'antline', seg.start, seg.end)
            if seg.type is SegType.CORNER:
                mat: AntTex
                if rng.randrange(100) < conf.broken_chance:
                    mat = rng.choice(conf.broken_corner or conf.broken_straight)
                else:
                    mat = rng.choice(conf.tex_corner or conf.tex_straight)

                # Because we can, apply a random rotation to mix up the texture.
                orient = Matrix.from_angle(seg.normal.to_angle(
                    rng.choice((0.0, 90.0, 180.0, 270.0))
                ))
                self._make_overlay(
                    vmf,
                    seg,
                    seg.start,
                    16.0 * orient.left(),
                    16.0 * orient.up(),
                    mat,
                )
            else:  # Straight
                # TODO: Break up these segments.
                for a, b, is_broken in seg.broken_iter(conf.broken_chance):
                    if is_broken:
                        mat = rng.choice(conf.broken_straight)
                    else:
                        mat = rng.choice(conf.tex_straight)
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

        for tile in segment.tiles:
            tile.bind_overlay(overlay)

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


def parse_antlines(vmf: VMF) -> tuple[
    dict[str, list[Antline]],
    dict[int, list[Segment]]
]:
    """Convert overlays in the map into Antline objects.

    This returns two dicts. The first maps targetnames to lists of antlines.
    The second maps solid IDs to segments, for assigning TileDefs to them.
    """
    # We want to reconstruct the shape of the antline path.
    # To do that we find the neighbouring points for each overlay.

    LOGGER.info('Parsing antlines...')

    # segment -> found neighbours of it.
    overlay_joins: defaultdict[Segment, set[Segment]] = defaultdict(set)

    segment_to_name: dict[Segment, str] = {}

    # Points on antlines where two can connect. For corners that's each side, for straight it's
    # each end. Combine that with the targetname, so we only join related antlines.
    join_points: dict[tuple[str, FrozenVec], Segment] = {}

    mat_straight = consts.Antlines.STRAIGHT
    mat_corner = consts.Antlines.CORNER

    side_to_seg: dict[int, list[Segment]] = {}
    antlines: dict[str, list[Antline]] = {}
    points: list[Vec]
    single_straights: list[tuple[Segment, str]] = []

    for over in vmf.by_class['info_overlay']:
        mat = over['material']
        origin = Vec.from_str(over['basisorigin'])
        normal = Vec.from_str(over['basisnormal'])
        orient = Matrix.from_angstr(over['angles'])

        if mat == mat_corner:
            seg_type = SegType.CORNER
            start = end = origin

            # One on each side - we know the size.
            points = [
                origin + orient.left(-8.0),
                origin + orient.left(+8.0),
                origin + orient.forward(-8.0),
                origin + orient.forward(+8.0),
            ]
        elif mat == mat_straight:
            seg_type = SegType.STRAIGHT

            # We want to determine the length first.
            long_axis = orient.left()
            side_axis = orient.forward()

            # The order of these isn't correct, but we need the neighbours to
            # fix that.
            start, end = overlay_bounds(over)
            # For whatever reason, Valve sometimes generates antlines which are
            # shortened by 1 unit. So snap those to grid.
            start = round(start / 16, 0) * 16
            end = round(end / 16, 0) * 16

            if math.isclose(abs(Vec.dot(end - start, long_axis)), 16.0):
                # Special case.
                # 1-wide antlines don't have the correct
                # rotation, pointing always in the U axis.
                # So we need to figure that out to get the correct links.
                # For now just create the segment with dummy values.
                start = end = origin
                points = []
            else:
                # These are the endpoints.
                offset: Vec = round(abs(8 * side_axis), 0)
                start += offset
                end -= offset

                points = [start, end]
        else:
            # It's not an antline.
            continue

        seg = Segment(seg_type, normal, start, end)
        segment_to_name[seg] = over_name = over['targetname']

        if not points:  # Single-straight
            single_straights.append((seg, over_name))

        for side_id in over['sides'].split():
            side_to_seg.setdefault(int(side_id), []).append(seg)

        for point in points:
            # Lookup the point to see if we've already checked it.
            # If not, write us into that spot.
            neighbour = join_points.setdefault(
                (over_name, round(point, 0).freeze()),
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
    for seg, over_name in single_straights:
        fix_single_straight(seg, over_name, join_points, overlay_joins)

    # Now, finally compute each continuous section.
    for start_seg, over_name in segment_to_name.items():
        try:
            neighbours = overlay_joins[start_seg]
        except KeyError:
            continue  # Done already.

        if len(neighbours) != 1:
            continue
        # Found a start point!
        segments = [start_seg]

        for segment in segments:
            neighbours = overlay_joins.pop(segment)
            # Except KeyError: this segment's already done??
            for neighbour in neighbours:
                if neighbour not in segments:
                    segments.append(neighbour)

        antlines.setdefault(over_name, []).append(Antline(over_name, segments))

    LOGGER.info(f'Done! ({sum(map(len, antlines.values()))} antlines)')
    return antlines, side_to_seg


def fix_single_straight(
    seg: Segment,
    over_name: str,
    join_points: dict[tuple[str, FrozenVec], Segment],
    overlay_joins: dict[Segment, set[Segment]],
) -> None:
    """Figure out the correct rotation for 1-long straight antlines."""
    # Check the U and V axis, to see if there's another antline on both
    # sides. If there is that's the correct orientation.
    orient = Matrix.from_basis(x=seg.normal)

    center = seg.start

    for off in [
        orient.left(-8.0),
        orient.left(+8.0),
        orient.up(-8.0),
        orient.up(+8.0),
    ]:
        try:
            neigh = join_points[over_name, round(center + off, 0).freeze()]
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
            if (over_name, round(center - off, 0).freeze()) in join_points:
                seg.start = off_min
                seg.end = off_max
        # Else: Both equal, we're fine.
    if seg.start == seg.end:
        raise ValueError(
            'Cannot determine orientation for 1-wide straight '
            f'antline "{over_name}" at ({seg.start})!'
        )
