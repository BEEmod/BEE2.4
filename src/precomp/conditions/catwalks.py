"""Implement Catwalks."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from collections import defaultdict
from enum import Enum

import attrs
from srctools import Keyvalues, VMF
from srctools.math import Angle, FrozenVec, Matrix, Vec, AnyVec, AnyAngle, AnyMatrix, to_matrix
from srctools.logger import get_logger

from precomp import brushLoc, instanceLocs, conditions, tiling, template_brush
from precomp.collisions import Collisions
from precomp.connections import ITEMS
import utils

COND_MOD_NAME: str | None = None
LOGGER = get_logger(__name__, alias='cond.catwalks')


class Instances(Enum):
    """Types of instances placed by catwalks."""
    STRAIGHT_1 = 'straight_128'
    STRAIGHT_2 = 'straight_256'
    STRAIGHT_4 = 'straight_512'
    CORNER = 'corner'
    TJUNCT = 'tjunction'
    XJUNCT = 'crossjunction'
    END = 'end'
    STAIR = 'stair'
    END_WALL = 'end_wall'
    SUPP_END_WALL = 'support_end_wall'
    SUPP_WALL = 'support_wall'
    SUPP_CEIL = 'support_ceil'
    SUPP_FLOOR = 'support_floor'
    SUPP_GOO = 'support_goo'
    SINGLE_WALL = 'single_wall'

CATWALK_TYPES: Mapping[utils.CONN_TYPES, Instances | None] = {
    utils.CONN_TYPES.straight: Instances.STRAIGHT_1,
    utils.CONN_TYPES.corner: Instances.CORNER,
    utils.CONN_TYPES.all: Instances.XJUNCT,
    utils.CONN_TYPES.side: Instances.END,
    utils.CONN_TYPES.triple: Instances.TJUNCT,
    utils.CONN_TYPES.none: None,
}

STRAIGHTS: Mapping[int, Instances] = {
    128: Instances.STRAIGHT_1,
    256: Instances.STRAIGHT_2,
    512: Instances.STRAIGHT_4,
}


@attrs.define
class Link:
    """Record the directions a catwalk connects in."""
    N: bool = False
    S: bool = False
    E: bool = False
    W: bool = False

    def as_tuple(self) -> tuple[bool, bool, bool, bool]:
        """Convert to a tuple."""
        return self.N, self.S, self.E, self.W

    def conn_dir(self) -> Vec:
        """Get the direction the connections point."""
        # If set, the bools are equivalent to 1. So subtract negative directions.
        return Vec(
            x=self.E - self.W,
            y=self.N - self.S,
        )

    def apply_norm(self, norm: Vec) -> None:
        """Enable the side with this normal."""
        if norm.x > 0.5:
            self.E = True
        elif norm.x < -0.5:
            self.W = True
        elif norm.y > 0.5:
            self.N = True
        elif norm.y < -0.5:
            self.S = True


class EmptyLink(Link):
    """Special case link, which is never placed. This ensures straight ends aren't placed on stairs."""
    S = E = W = N = property(fget=lambda self: False, fset=lambda self, val: None)  # type: ignore


EMPTY = EmptyLink()
# Calculates an optimum number of pieces for a given gap.
straight_fit = utils.get_piece_fitter([512, 256, 128])


def check_support_locs(
    origin: AnyVec, orient: AnyMatrix | AnyAngle,
    debug_add: conditions.DebugAdder,
    normal: AnyVec,
    *points: AnyVec,
) -> bool:
    """Check if these tile locations are all present for supports."""
    matrix = to_matrix(orient)
    normal = Vec(normal) @ matrix
    for point in points:
        pos = Vec(point)
        pos.localise(origin, matrix)
        dbg = debug_add(
            'info_particle_system',
            targetname='support_check',
            origin=pos,
            angles=normal.to_angle(),
        )
        try:
            tile, u, v = tiling.find_tile(pos, normal)
        except KeyError:
            dbg.comments = 'Fail: Not present'
            return False
        if not tile[u, v].is_tile:
            dbg.comments = 'Fail: Not a tile'
            return False
    return True


def place_catwalk_connections(
    catwalks: dict[FrozenVec, Link],
    add_inst: Callable[[Instances, str, Vec | FrozenVec, AnyAngle | AnyMatrix], object],
    name: str,
    point_a: Vec, point_b: Vec,
) -> None:
    """Place catwalk sections to connect two straight points."""
    diff = point_b - point_a

    # The horizontal unit vector in the direction we are placing catwalks
    direction = diff.copy()
    direction.z = 0
    distance = direction.len()
    direction = direction.norm()

    loc = point_a
    catwalks[point_a.freeze()].apply_norm(direction)
    catwalks[point_b.freeze()].apply_norm(-direction)

    if diff.z > 0:
        angle = conditions.INST_ANGLE[direction.freeze()]
        # We need to add stairs
        for stair_pos in range(0, int(diff.z), 128):
            # Move twice the vertical horizontally
            # plus 128, so we don't start in point A
            loc = point_a + (2 * stair_pos + 128) * direction
            # Do the vertical offset
            loc.z += stair_pos
            add_inst(Instances.STAIR, name, loc, angle)
            catwalks[loc.freeze()] = EMPTY
            catwalks[(loc + 128 * direction + (0, 0, 128)).freeze()] = EMPTY
        # This is the location we start flat sections at
        point_a = loc + 128 * direction
        point_a.z += 128
    elif diff.z < 0:
        # We need to add downward stairs
        # They point opposite to normal ones
        angle = conditions.INST_ANGLE[(-direction).freeze()]
        for stair_pos in range(0, -int(diff.z), 128):
            # Move twice the vertical horizontally
            loc = point_a + (2 * stair_pos + 256) * direction
            # Do the vertical offset plus additional 128 units
            # to account for the moved instance
            loc.z -= (stair_pos + 128)
            add_inst(Instances.STAIR, name, loc, angle)
            catwalks[loc.freeze()] = EMPTY
            catwalks[(loc - 128 * direction + (0, 0, 128)).freeze()] = EMPTY
        # Adjust point A to be at the end of the catwalks
        point_a = loc
    # Remove the space the stairs take up from the horiz distance
    distance -= abs(diff.z) * 2

    # Now do the straight sections
    straight_points = [
        point_a + dist * direction
        for dist in range(0, round(distance) + 1, 128)
    ]
    for pos in straight_points[:-1]:
        catwalks[pos.freeze()].apply_norm(direction)
    for pos in straight_points[1:]:
        catwalks[pos.freeze()].apply_norm(-direction)


@conditions.make_result('makeCatwalk')
def res_make_catwalk(vmf: VMF, coll: Collisions, res: Keyvalues) -> object:
    """Speciallised result to generate catwalks from markers.

    Only runs once, and then quits the condition list.

    * `markerInst: The instance set in editoritems.
    * `template`: Template ID, with visgroups matching the below instance names.

    * Instances:
        * `straight_128`/`256`/`512`: Straight sections. Extends East.
        * `corner: An L-corner piece. Connects on North and West sides.
        * `TJunction`: A T-piece. Connects on all but the East side.
        * `crossJunction`: A X-piece. Connects on all sides.
        * `end`: An end piece. Connects on the East side.
        * `stair`: A stair. Starts East and goes Up and West.
        * `end_wall`: Connects a West wall to an East catwalk.
        * `support_wall`: A support extending from the East wall.
        * `support_ceil`: A support extending from the ceiling.
        * `support_floor`: A support extending from the floor.
        * `support_goo`: A floor support, designed for goo pits.
        * `support_end_wall`: A support underneath `end_wall`, attaching it to the wall.
        * `single_wall`: A section connecting to an East wall.
    """
    LOGGER.info("Starting catwalk generator...")
    marker = instanceLocs.resolve_filter(res['markerInst'])

    instances: dict[Instances | None, str] = {
        inst_name: instanceLocs.resolve_one(res[inst_name.value, ''], error=True)
        for inst_name in Instances
    }
    # If there are no attachments remove a catwalk piece
    instances[None] = ''

    if not instances[Instances.END_WALL]:
        instances[Instances.END_WALL] = instances[Instances.END]

    template: template_brush.Template | None = None
    try:
        temp_id = res['template']
    except LookupError:
        pass
    else:
        template = template_brush.get_template(temp_id)

    def add_inst(
        instance: Instances | None,
        name: str,
        origin: Vec | FrozenVec,
        angles: AnyAngle | AnyMatrix,
    ) -> None:
        """Add the instance and optionally the template."""
        if instance is None:
            return
        orient = to_matrix(angles)
        filename = instances[instance]
        if filename:
            conditions.add_inst(
                vmf,
                origin=origin,
                angles=orient,
                file=filename,
            )
        if template is not None and instance.value in template.visgroups:
            temp = template_brush.import_template(
                vmf, template,
                origin, orient,
                additional_visgroups=[instance.value],
                targetname=name,
                coll=coll,
            )
            template_brush.retexture_template(temp, origin)

    # The directions this instance is connected by (NSEW)
    catwalks: dict[FrozenVec, Link] = defaultdict(Link)
    markers = {}

    # Find all our markers, so we can look them up by targetname.
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in marker:
            continue
        markers[inst['targetname']] = inst

        # Snap the markers to the grid. If on glass it can become offset...
        origin = Vec.from_str(inst['origin'])
        origin = origin // 128 * 128
        origin += 64

        while brushLoc.POS.lookup_world(origin).is_goo:
            # The instance is in goo! Switch to floor orientation, and move
            # up until it's in air.
            inst['angles'] = '0 0 0'
            origin.z += 128

        catwalks[origin.freeze()] = Link()

        inst['origin'] = str(origin)

    if not markers:
        return conditions.RES_EXHAUSTED

    LOGGER.info('Positions: {}', catwalks)
    LOGGER.info('Markers: {}', markers)

    debug_add = conditions.fetch_debug_visgroup(vmf, 'Catwalks')

    # First loop through all the markers, adding connecting sections
    for marker_name, inst in markers.items():
        mark_item = ITEMS[marker_name]
        mark_item.delete_antlines()
        for conn in list(mark_item.outputs):
            try:
                inst2 = markers[conn.to_item.name]
            except KeyError:
                LOGGER.warning('Catwalk connected to non-catwalk!')
                continue

            conn.remove()

            origin1 = Vec.from_str(inst['origin'])
            origin2 = Vec.from_str(inst2['origin'])
            if origin1.x != origin2.x and origin1.y != origin2.y:
                LOGGER.warning('Instances not aligned!')
                continue

            y_dir = origin1.x == origin2.x  # Which way the connection is
            if y_dir:
                dist = abs(origin1.y - origin2.y)
            else:
                dist = abs(origin1.x - origin2.x)
            vert_dist = origin1.z - origin2.z

            if (dist - 128) // 2 < abs(vert_dist):
                # The stairs are 2 long, 1 high. Check there's enough room
                # Subtract the last block though, since that's a corner.
                LOGGER.warning('Not enough room for stairs!')
                continue

            # Don't place if right on top of each other.
            if dist > 16:
                place_catwalk_connections(catwalks, add_inst, marker_name, origin1, origin2)

    for marker_name, inst in markers.items():
        # Set the marker instances based on the attached walkways.
        normal = FrozenVec(0, 0, 1) @ Angle.from_str(inst['angles'])
        f_origin = FrozenVec.from_str(inst['origin'])
        dir_mask = catwalks[f_origin]
        angle: AnyMatrix | AnyAngle = conditions.INST_ANGLE[normal]

        new_type, _ = utils.CONN_LOOKUP[dir_mask.as_tuple()]
        inst.remove()

        supp: Instances | None = None

        if new_type is utils.CONN_TYPES.side:
            # If the end piece is pointing at a wall, switch the instance.
            if abs(normal.z) < 0.01 and normal == dir_mask.conn_dir():
                angle = conditions.INST_ANGLE[-normal]
                add_inst(Instances.END_WALL, marker_name, f_origin, angle)
                catwalks[f_origin] = EMPTY
                # If there's room below, add special supports.
                if instances[Instances.SUPP_END_WALL] and check_support_locs(
                    f_origin, angle, debug_add, (1.0, 0.0, 0.0),
                    (-64.0, -48.0, -80.0),
                    (-64.0, -16.0, -80.0),
                    (-64.0, +16.0, -80.0),
                    (-64.0, +48.0, -80.0),
                ):
                    add_inst(Instances.SUPP_END_WALL, marker_name, f_origin, angle)
            continue  # We never have normal supports on end pieces
        elif new_type is utils.CONN_TYPES.none:
            # Unconnected catwalks on the wall switch to a special instance.
            # This lets players stand next to a portal surface on the wall.
            if abs(normal.z) < 0.01:
                add_inst(Instances.SINGLE_WALL, marker_name, f_origin, angle)
                catwalks[f_origin] = EMPTY
            continue  # These don't get supports otherwise

        # Add regular supports
        if normal.z > 0.707:
            # If in goo, use different supports!
            if brushLoc.POS.lookup_world(f_origin - (0, 0, 128)).is_goo:
                supp = Instances.SUPP_GOO
            else:
                supp = Instances.SUPP_FLOOR
        elif normal.z < -0.707:
            supp = Instances.SUPP_CEIL
            angle = Matrix()  # Don't flip it upside-down.
        elif instances[Instances.SUPP_WALL] and check_support_locs(
            f_origin, angle, debug_add, (1.0, 0.0, 0.0),
            # Needs to be attachment space below.
            (-64.0, -16.0, -80.0),
            (-64.0, +16.0, -80.0),
        ):
            supp = Instances.SUPP_WALL

        if supp is not None:
            add_inst(supp, marker_name, f_origin, angle)

    if utils.DEV_MODE:
        for f_origin, dir_mask in catwalks.items():
            debug_add(
                'info_null' if dir_mask is EMPTY else 'info_target',
                targetname='catwalk_node',
                origin=f_origin,
                comment=f'N: {dir_mask.N}, S: {dir_mask.S}, E: {dir_mask.E}, W: {dir_mask.W}',
            )

    while catwalks:
        f_origin, dir_mask = catwalks.popitem()
        if dir_mask == EMPTY:
            continue
        new_type, angles = utils.CONN_LOOKUP[dir_mask.as_tuple()]

        if new_type is utils.CONN_TYPES.straight:
            # Look for continuous segments. This must be NS or EW, so easy to check.
            direction = FrozenVec(0, 128, 0) if dir_mask.N else FrozenVec(-128, 0, 0)
            start = end = f_origin
            nextpos = start - direction
            while catwalks[nextpos] == dir_mask:
                start = nextpos
                del catwalks[nextpos]
                nextpos = start - direction

            nextpos = end + direction
            while catwalks[nextpos] == dir_mask:
                end = nextpos
                del catwalks[nextpos]
                nextpos = end + direction

            # Figure out the most efficient number of sections.
            loc = start.copy()
            start -= direction / 2
            end += direction / 2
            diff = end - start
            direction = diff.norm()
            segments = straight_fit(diff.len())
            LOGGER.debug('{} -> ({}) - ({}) = {}', f_origin, start, end, segments)
            for segment_len in segments:
                add_inst(STRAIGHTS[segment_len], 'catwalk', loc, angles)
                loc += (segment_len * direction)
        else:
            add_inst(CATWALK_TYPES[new_type], 'catwalk', f_origin, angles)

    LOGGER.info('Finished catwalk generation!')
    return conditions.RES_EXHAUSTED
