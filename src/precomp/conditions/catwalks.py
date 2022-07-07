"""Implement Catwalks."""
from enum import Enum
from typing import Optional, Dict, Tuple, Mapping

from srctools import Angle, Vec, Property, VMF, Entity
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


class Link:
    """Record the directions a catwalk connects in."""
    __slots__ = ['N', 'S', 'E', 'W']
    def __init__(self) -> None:
        self.N = self.S = self.E = self.W = False

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


def place_catwalk_connections(vmf: VMF, instances: Dict[Instances, str], point_a: Vec, point_b: Vec) -> None:
    """Place catwalk sections to connect two straight points."""
    diff = point_b - point_a

    # The horizontal unit vector in the direction we are placing catwalks
    direction = diff.copy()
    direction.z = 0
    distance = direction.len() - 128
    direction = direction.norm()

    loc = point_a

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
        # Adjust point A to be at the end of the catwalks
        point_a = loc
    # Remove the space the stairs take up from the horiz distance
    distance -= abs(diff.z) * 2

    # Now do the straight sections
    LOGGER.debug('Stretching {} {}', distance, direction)
    angle = conditions.INST_ANGLE[direction.as_tuple()]
    loc = point_a + (direction * 128)

    # Figure out the most efficient number of sections
    for segment_len in utils.fit(distance, [512, 256, 128]):
        conditions.add_inst(
            vmf,
            origin=loc,
            angles=angle,
            file=instances[STRAIGHTS[segment_len]],
        )
        loc += (segment_len * direction)


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
    links: Dict[Entity, Link] = {}
    markers = {}

    # Find all our markers, so we can look them up by targetname.
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in marker:
            continue
        links[inst] = Link()
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

        inst['origin'] = str(origin)

    if not markers:
        return conditions.RES_EXHAUSTED

    LOGGER.info('Connections: {}', links)
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

            if dist > 128:
                # add straight sections in between
                place_catwalk_connections(vmf, instances, origin1, origin2)

            # Update the lists based on the directions that were set
            conn_lst1 = links[inst]
            conn_lst2 = links[inst2]
            if origin1.x < origin2.x:
                conn_lst1.E = conn_lst2.W = True
            elif origin2.x < origin1.x:
                conn_lst1.W = conn_lst2.E = True

            if origin1.y < origin2.y:
                conn_lst1.N = conn_lst2.S = True
            elif origin2.y < origin1.y:
                conn_lst1.S = conn_lst2.N = True

    for inst, dir_mask in links.items():
        # Set the marker instances based on the attached walkways.
        normal = Vec(0, 0, 1) @ Angle.from_str(inst['angles'])

        new_type, inst['angles'] = utils.CONN_LOOKUP[dir_mask.as_tuple()]
        inst['file'] = filename = instances[CATWALK_TYPES[new_type]]
        conditions.ALL_INST.add(filename.casefold())

        if new_type is utils.CONN_TYPES.side:
            # If the end piece is pointing at a wall, switch the instance.
            if normal.z == 0:
                if normal == dir_mask.conn_dir():
                    inst['file'] = instances[Instances.END_WALL]
                    conditions.ALL_INST.add(instances[Instances.END_WALL].casefold())
            continue  # We never have normal supports on end pieces
        elif new_type is utils.CONN_TYPES.none:
            # Unconnected catwalks on the wall switch to a special instance.
            # This lets players stand next to a portal surface on the wall.
            if normal.z == 0:
                inst['file'] = instances[Instances.SINGLE_WALL]
                conditions.ALL_INST.add(instances[Instances.SINGLE_WALL].casefold())
                inst['angles'] = conditions.INST_ANGLE[normal.as_tuple()]
            else:
                inst.remove()
            continue  # These don't get supports otherwise

        # Add regular supports
        supp = None
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

    LOGGER.info('Finished catwalk generation!')
    return conditions.RES_EXHAUSTED
