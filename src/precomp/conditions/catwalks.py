"""Implement Catwalks."""
from collections import defaultdict
from enum import Enum
from typing import Optional, Dict, Tuple, Mapping

import attrs
from srctools import Angle, Vec, Property, VMF
import srctools.logger

from precomp import brushLoc, instanceLocs, conditions
from precomp.connections import ITEMS
import utils

COND_MOD_NAME = None
LOGGER = srctools.logger.get_logger(__name__, alias='cond.catwalks')


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
    SUPP_WALL = 'support_wall'
    SUPP_CEIL = 'support_ceil'
    SUPP_FLOOR = 'support_floor'
    SUPP_GOO = 'support_goo'
    SINGLE_WALL = 'single_wall'
    MARKER = 'markerInst'

CATWALK_TYPES: Mapping[utils.CONN_TYPES, Instances] = {
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

    def as_tuple(self) -> Tuple[bool, bool, bool, bool]:
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
    @property
    def N(self) -> bool:
        """Always unset."""
        return False
    @N.setter
    def N(self, value: bool) -> None:
        """Setting does nothing."""
    S = E = W = N


EMPTY = EmptyLink()


def place_catwalk_connections(
    catwalks: Dict[Tuple[float, float, float], Link],
    vmf: VMF,
    instances: Dict[Instances, str],
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
    catwalks[point_a.as_tuple()].apply_norm(direction)
    catwalks[point_b.as_tuple()].apply_norm(-direction)

    if diff.z > 0:
        angle = conditions.INST_ANGLE[direction.as_tuple()]
        # We need to add stairs
        for stair_pos in range(0, int(diff.z), 128):
            # Move twice the vertical horizontally
            # plus 128, so we don't start in point A
            loc = point_a + (2 * stair_pos + 128) * direction
            # Do the vertical offset
            loc.z += stair_pos
            conditions.add_inst(
                vmf,
                origin=loc,
                angles=angle,
                file=instances[Instances.STAIR],
            )
            catwalks[loc.as_tuple()] = EMPTY
            catwalks[(loc + 128 * direction - (0, 0, 128)).as_tuple()] = EMPTY
        # This is the location we start flat sections at
        point_a = loc + 128 * direction
        point_a.z += 128
    elif diff.z < 0:
        # We need to add downward stairs
        # They point opposite to normal ones
        angle = conditions.INST_ANGLE[(-direction).as_tuple()]
        for stair_pos in range(0, -int(diff.z), 128):
            LOGGER.debug(stair_pos)
            # Move twice the vertical horizontally
            loc = point_a + (2 * stair_pos + 256) * direction
            # Do the vertical offset plus additional 128 units
            # to account for the moved instance
            loc.z -= (stair_pos + 128)
            conditions.add_inst(
                vmf,
                origin=loc,
                angles=angle,
                file=instances[Instances.STAIR],
            )
            catwalks[loc.as_tuple()] = EMPTY
            catwalks[(loc - 128 * direction + (0, 0, 128)).as_tuple()] = EMPTY
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
        catwalks[pos.as_tuple()].apply_norm(direction)
    for pos in straight_points[1:]:
        catwalks[pos.as_tuple()].apply_norm(-direction)


@conditions.make_result('makeCatwalk')
def res_make_catwalk(vmf: VMF, res: Property):
    """Speciallised result to generate catwalks from markers.

    Only runs once, and then quits the condition list.

    * Instances:
        * `markerInst: The instance set in editoritems.
        * `straight_128`/`256`/`512`: Straight sections. Extends East.
        * `corner: An L-corner piece. Connects on North and West sides.
        * `TJunction`: A T-piece. Connects on all but the East side.
        * `crossJunction`: A X-piece. Connects on all sides.
        * `end`: An end piece. Connects on the East side.
        * `stair`: A stair. Starts East and goes Up and West.
        * `end_wall`: Connects a West wall to a East catwalk.
        * `support_wall`: A support extending from the East wall.
        * `support_ceil`: A support extending from the ceiling.
        * `support_floor`: A support extending from the floor.
        * `support_goo`: A floor support, designed for goo pits.
        * `single_wall`: A section connecting to an East wall.
    """
    LOGGER.info("Starting catwalk generator...")
    marker = instanceLocs.resolve(res['markerInst'])

    instances: Dict[Optional[Instances], str] = {
        inst_name: instanceLocs.resolve_one(res[inst_name.value, ''], error=True)
        for inst_name in Instances
    }
    # If there are no attachments remove a catwalk piece
    instances[None] = ''

    if not instances[Instances.END_WALL]:
        instances[Instances.END_WALL] = instances[Instances.END]

    # The directions this instance is connected by (NSEW)
    catwalks: Dict[Tuple[float, float, float], Link] = defaultdict(Link)
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

        while brushLoc.POS['world': origin].is_goo:
            # The instance is in goo! Switch to floor orientation, and move
            # up until it's in air.
            inst['angles'] = '0 0 0'
            origin.z += 128

        catwalks[origin.as_tuple()] = Link()

        inst['origin'] = str(origin)

    if not markers:
        return conditions.RES_EXHAUSTED

    LOGGER.info('Positions: {}', catwalks)
    LOGGER.info('Markers: {}', markers)

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
                place_catwalk_connections(catwalks, vmf, instances, origin1, origin2)

    for inst in markers.values():
        # Set the marker instances based on the attached walkways.
        normal = Vec(0, 0, 1) @ Angle.from_str(inst['angles'])
        pos_tup = srctools.parse_vec_str(inst['origin'])
        dir_mask = catwalks[pos_tup]

        new_type, _ = utils.CONN_LOOKUP[dir_mask.as_tuple()]
        inst.remove()

        if new_type is utils.CONN_TYPES.side:
            # If the end piece is pointing at a wall, switch the instance.
            if normal.z == 0:
                if normal == dir_mask.conn_dir():
                    conditions.add_inst(
                        vmf,
                        file=instances[Instances.END_WALL],
                        origin=inst['origin'],
                        angles=inst['angles'],
                    )
                    catwalks[pos_tup] = EMPTY
            continue  # We never have normal supports on end pieces
        elif new_type is utils.CONN_TYPES.none:
            # Unconnected catwalks on the wall switch to a special instance.
            # This lets players stand next to a portal surface on the wall.
            if normal.z == 0:
                conditions.add_inst(
                    vmf,
                    file=instances[Instances.SINGLE_WALL],
                    origin=inst['origin'],
                    angles=conditions.INST_ANGLE[normal.as_tuple()],
                )
                catwalks[pos_tup] = EMPTY
            continue  # These don't get supports otherwise

        # Add regular supports
        if normal.z > 0.707:
            # If in goo, use different supports!
            origin = Vec.from_str(inst['origin'])
            origin.z -= 128
            if brushLoc.POS['world': origin].is_goo:
                supp = instances[Instances.SUPP_GOO]
            else:
                supp = instances[Instances.SUPP_FLOOR]
        elif normal.z < -0.707:
            supp = instances[Instances.SUPP_CEIL]
        else:
            supp = instances[Instances.SUPP_WALL]

        if supp:
            conditions.add_inst(
                vmf,
                origin=inst['origin'],
                angles=conditions.INST_ANGLE[normal.as_tuple()],
                file=supp,
            )

    while catwalks:
        pos_tup, dir_mask = catwalks.popitem()
        if dir_mask == EMPTY:
            continue
        new_type, angles = utils.CONN_LOOKUP[dir_mask.as_tuple()]

        if new_type is utils.CONN_TYPES.straight:
            # Look for continuous segments. This must be NS or EW, so easy to check.
            direction = Vec(0, 128, 0) if dir_mask.N else Vec(-128, 0, 0)
            start = Vec(pos_tup)
            end = Vec(pos_tup)
            while catwalks[(nextpos := start - direction).as_tuple()] == dir_mask:
                start = nextpos
                del catwalks[nextpos.as_tuple()]
            while catwalks[(nextpos := end + direction).as_tuple()] == dir_mask:
                end = nextpos
                del catwalks[nextpos.as_tuple()]

            # Figure out the most efficient number of sections.
            loc = start.copy()
            start -= direction / 2
            end += direction / 2
            diff = end - start
            direction = diff.norm()
            LOGGER.info('{} -> ({}) - ({}) = {}', pos_tup, start, end, list(utils.fit(diff.len(), [512, 256, 128])))
            for segment_len in utils.fit(diff.len(), [512, 256, 128]):
                conditions.add_inst(
                    vmf,
                    origin=loc,
                    angles=angles,
                    file=instances[STRAIGHTS[segment_len]],
                )
                loc += (segment_len * direction)
        else:
            conditions.add_inst(
                vmf,
                origin=Vec(pos_tup),
                angles=angles,
                file=instances[CATWALK_TYPES[new_type]],
            )

    LOGGER.info('Finished catwalk generation!')
    return conditions.RES_EXHAUSTED
