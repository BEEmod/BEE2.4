
from conditions import (
    make_result, RES_EXHAUSTED,
    INST_ANGLE,
)
import instanceLocs
from srctools import Vec, Property, VMF
import conditions
import utils

COND_MOD_NAME = None

LOGGER = utils.getLogger(__name__, alias='cond.catwalks')

CATWALK_TYPES = {
    utils.CONN_TYPES.straight: 'straight_128',
    utils.CONN_TYPES.corner: 'corner',
    utils.CONN_TYPES.all: 'crossjunction',
    utils.CONN_TYPES.side: 'end',
    utils.CONN_TYPES.triple: 'tjunction',
    utils.CONN_TYPES.none: 'NONE',
}


def place_catwalk_connections(vmf: VMF, instances, point_a: Vec, point_b: Vec):
    """Place catwalk sections to connect two straight points."""
    diff = point_b - point_a

    # The horizontal unit vector in the direction we are placing catwalks
    direction = diff.copy()
    direction.z = 0
    distance = direction.len() - 128
    direction = direction.norm()

    if diff.z > 0:
        angle = INST_ANGLE[direction.as_tuple()]
        # We need to add stairs
        for stair_pos in range(0, int(diff.z), 128):
            # Move twice the vertical horizontally
            # plus 128 so we don't start in point A
            loc = point_a + (2 * stair_pos + 128) * direction
            # Do the vertical offset
            loc.z += stair_pos
            vmf.create_ent(
                classname='func_instance',
                origin=loc.join(' '),
                angles=angle,
                file=instances['stair'],
            )
        # This is the location we start flat sections at
        point_a = loc + 128 * direction
        point_a.z += 128
    elif diff.z < 0:
        # We need to add downward stairs
        # They point opposite to normal ones
        LOGGER.debug('down from {}', point_a)
        angle = INST_ANGLE[(-direction).as_tuple()]
        for stair_pos in range(0, -int(diff.z), 128):
            LOGGER.debug(stair_pos)
            # Move twice the vertical horizontally
            loc = point_a + (2 * stair_pos + 256) * direction  # type: Vec
            # Do the vertical offset plus additional 128 units
            # to account for the moved instance
            loc.z -= (stair_pos + 128)
            vmf.create_ent(
                classname='func_instance',
                origin=loc.join(' '),
                angles=angle,
                file=instances['stair'],
            )
        # Adjust point A to be at the end of the catwalks
        point_a = loc
    # Remove the space the stairs take up from the horiz distance
    distance -= abs(diff.z) * 2

    # Now do straight sections
    LOGGER.debug('Stretching {} {}', distance, direction)
    angle = INST_ANGLE[direction.as_tuple()]
    loc = point_a + (direction * 128)

    # Figure out the most efficent number of sections
    for segment_len in utils.fit(
            distance,
            [512, 256, 128]
            ):
        vmf.create_ent(
            classname='func_instance',
            origin=loc.join(' '),
            angles=angle,
            file=instances['straight_' + str(segment_len)],
        )
        loc += (segment_len * direction)


@make_result('makeCatwalk')
def res_make_catwalk(vmf: VMF, res: Property):
    """Speciallised result to generate catwalks from markers.

    Only runs once, and then quits the condition list.
    Instances:
        MarkerInst: The instance set in editoritems.
        Straight_128/256/512: Straight sections. Extends East
        Corner: A corner piece. Connects on N and W sides.
        TJunction; A T-piece. Connects on all but the East side.
        CrossJunction: A X-piece. Connects on all sides.
        End: An end piece. Connects on the East side.
        Stair: A stair. Starts East and goes Up and West.
        End_wall: Connects a West wall to a East catwalk.
        Support_Wall: A support extending from the East wall.
        Support_Ceil: A support extending from the ceiling.
        Support_Floor: A support extending from the floor.
        Support_Goo: A floor support, designed for goo pits.
        Single_Wall: A section connecting to an East wall.
    """
    LOGGER.info("Starting catwalk generator...")
    marker = instanceLocs.resolve(res['markerInst'])
    output_target = res['output_name', 'MARKER']

    instances = {
        name: instanceLocs.resolve_one(res[name, ''], error=True)
        for name in
        (
            'straight_128', 'straight_256', 'straight_512',
            'corner', 'tjunction', 'crossjunction', 'end', 'stair', 'end_wall',
            'support_wall', 'support_ceil', 'support_floor', 'support_goo',
            'single_wall',
            'markerInst',
        )
    }
    # If there are no attachments remove a catwalk piece
    instances['NONE'] = ''
    if instances['end_wall'] == '':
        instances['end_wall'] = instances['end']

    connections = {}  # The directions this instance is connected by (NSEW)
    markers = {}

    # Find all our markers, so we can look them up by targetname.
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in marker:
            continue
        #                   [North, South, East,  West ]
        connections[inst] = [False, False, False, False]
        markers[inst['targetname']] = inst

        # Snap the markers to the grid. If on glass it can become offset...
        origin = Vec.from_str(inst['origin'])
        origin = origin // 128 * 128  # type: Vec
        origin += 64

        while origin.as_tuple() in conditions.GOO_LOCS:
            # The instance is in goo! Switch to floor orientation, and move
            # up until it's in air.
            inst['angles'] = '0 0 0'
            origin.z += 128

        inst['origin'] = str(origin)

    if not markers:
        return RES_EXHAUSTED

    LOGGER.info('Connections: {}', connections)
    LOGGER.info('Markers: {}', markers)

    # First loop through all the markers, adding connecting sections
    for inst in markers.values():
        for conn in inst.outputs:
            if conn.output != output_target or conn.input != output_target:
                # Indicator toggles or similar, delete these entities.
                # Find the associated overlays too.
                for del_inst in vmf.by_target[conn.target]:
                    conditions.remove_ant_toggle(del_inst)
                continue

            inst2 = markers[conn.target]
            LOGGER.debug('{} <-> {}', inst['targetname'], inst2['targetname'])
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

            LOGGER.debug('Dist = {}, Vert = {}', dist, vert_dist)

            if (dist - 128) // 2 < abs(vert_dist):
                # The stairs are 2 long, 1 high. Check there's enough room
                # Subtract the last block though, since that's a corner.
                LOGGER.warning('Not enough room for stairs!')
                continue

            if dist > 128:
                # add straight sections in between
                place_catwalk_connections(vmf, instances, origin1, origin2)

            # Update the lists based on the directions that were set
            conn_lst1 = connections[inst]
            conn_lst2 = connections[inst2]
            if origin1.x < origin2.x:
                conn_lst1[2] = True  # E
                conn_lst2[3] = True  # W
            elif origin2.x < origin1.x:
                conn_lst1[3] = True  # W
                conn_lst2[2] = True  # E

            if origin1.y < origin2.y:
                conn_lst1[0] = True  # N
                conn_lst2[1] = True  # S
            elif origin2.y < origin1.y:
                conn_lst1[1] = True  # S
                conn_lst2[0] = True  # N

        inst.outputs.clear()  # Remove the outputs now, they're useless

    for inst, dir_mask in connections.items():
        # Set the marker instances based on the attached walkways.
        normal = Vec(0, 0, 1).rotate_by_str(inst['angles'])

        new_type, inst['angles'] = utils.CONN_LOOKUP[tuple(dir_mask)]
        inst['file'] = instances[CATWALK_TYPES[new_type]]

        if new_type is utils.CONN_TYPES.side:
            # If the end piece is pointing at a wall, switch the instance.
            if normal.z == 0:
                # Treat booleans as ints to get the direction the connection is
                # in - True == 1, False == 0
                conn_dir = Vec(
                    x=dir_mask[2] - dir_mask[3],  # +E, -W
                    y=dir_mask[0] - dir_mask[1],  # +N, -S,
                    z=0,
                )
                if normal == conn_dir:
                    inst['file'] = instances['end_wall']
            continue  # We never have normal supports on end pieces
        elif new_type is utils.CONN_TYPES.none:
            # Unconnected catwalks on the wall switch to a special instance.
            # This lets players stand next to a portal surface on the wall.
            if normal.z == 0:
                inst['file'] = instances['single_wall']
                inst['angles'] = INST_ANGLE[normal.as_tuple()]
            else:
                inst.remove()
            continue  # These don't get supports otherwise

        # Add regular supports
        if normal == (0, 0, 1):
            # If in goo, use different supports!
            origin = Vec.from_str(inst['origin'])
            origin.z -= 128
            if origin.as_tuple() in conditions.GOO_LOCS:
                supp = instances['support_goo']
            else:
                supp = instances['support_floor']
        elif normal == (0, 0, -1):
            supp = instances['support_ceil']
        else:
            supp = instances['support_wall']

        if supp:
            vmf.create_ent(
                classname='func_instance',
                origin=inst['origin'],
                angles=INST_ANGLE[normal.as_tuple()],
                file=supp,
            )

    LOGGER.info('Finished catwalk generation!')
    return RES_EXHAUSTED
