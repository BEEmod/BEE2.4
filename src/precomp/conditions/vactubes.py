"""Implements the cutomisable vactube items.
"""
from collections import namedtuple
from typing import Dict, Tuple, List, Iterator, Optional

from srctools import Vec, Vec_tuple, Property, Entity, VMF, Solid
import srctools.logger

from precomp import tiling, instanceLocs, connections, template_brush
from precomp.brushLoc import POS as BLOCK_POS
from precomp.conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
    meta_cond
)
import vbsp

COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.vactubes')

PUSH_SPEED = 700  # The speed of the push triggers.
UP_PUSH_SPEED = 900  # Make it slightly faster when up to counteract gravity
DN_PUSH_SPEED = 400  # Slow down when going down since gravity also applies..

PUSH_TRIGS = {}
VAC_TRACKS: List[Tuple['Marker', Dict[str, 'Marker']]] = []  # Tuples of (start, group)

CornerAng = namedtuple('CornerAng', 'ang, axis')

xp = Vec_tuple(1, 0, 0)
xn = Vec_tuple(-1, 0, 0)
yp = Vec_tuple(0, 1, 0)
yn = Vec_tuple(0, -1, 0)
zp = Vec_tuple(0, 0, 1)
zn = Vec_tuple(0, 0, -1)

# start, end normals -> angle of corner instance and the unchanged axis
CORNER_ANG = {
    (zp, xp): CornerAng('0 0 0', 'y'),
    (zp, xn): CornerAng('0 180 0', 'y'),
    (zp, yp): CornerAng('0 90 0', 'x'),
    (zp, yn): CornerAng('0 270 0', 'x'),

    (zn, xp): CornerAng('0 0 180', 'y'),
    (zn, xn): CornerAng('0 180 180', 'y'),
    (zn, yp): CornerAng('0 90 180', 'x'),
    (zn, yn): CornerAng('0 270 180', 'x'),

    (xp, yp): CornerAng('0 90 90', 'z'),
    (xp, yn): CornerAng('0 270 270', 'z'),
    (xp, zp): CornerAng('270 180 0', 'y'),
    (xp, zn): CornerAng('90 0 0', 'y'),

    (xn, yp): CornerAng('0 90 270', 'z'),
    (xn, yn): CornerAng('0 270 90', 'z'),
    (xn, zp): CornerAng('270 0 0', 'y'),
    (xn, zn): CornerAng('90 180 0', 'y'),

    (yp, zp): CornerAng('270 270 0', 'x'),
    (yp, zn): CornerAng('90 90 0', 'x'),
    (yp, xp): CornerAng('0 0 270', 'z'),
    (yp, xn): CornerAng('0 180 90', 'z'),

    (yn, zp): CornerAng('270 90 0', 'x'),
    (yn, zn): CornerAng('90 270 0', 'x'),
    (yn, xn): CornerAng('0 180 270', 'z'),
    (yn, xp): CornerAng('0 0 90', 'z'),
}

SUPPORT_POS: Dict[Tuple[float, float, float], List[Tuple[Vec, Vec]]] = {}


def _make_support_table() -> None:
    """Make a table of angle/offset values for each direction."""
    for norm in (xp, xn, yp, yn, zp, zn):
        table = SUPPORT_POS[norm] = []
        for x in range(0, 360, 90):
            ang = Vec(norm).to_angle(roll=x)
            table.append((
                ang,
                Vec(0, 0, -128).rotate(*ang)
            ))
_make_support_table()  # Ensure local vars are destroyed

del xp, xn, yp, yn, zp, zn


class Marker:
    """A single node point."""
    next: Optional[str]

    def __init__(self, inst: Entity, conf: dict, size: int) -> None:
        self.ent = inst
        self.conf = conf
        self.next = None
        self.no_prev = True
        self.size = size

    def follow_path(self, vac_list: Dict[str, 'Marker']) -> Iterator[Tuple['Marker', 'Marker']]:
        """Follow the provided vactube path, yielding each pair of nodes."""
        vac_node = self
        while True:
            try:
                next_ent = vac_list[vac_node.next]
            except KeyError:
                return
            yield vac_node, next_ent
            vac_node = next_ent

# Store the configs for vactube items so we can
# join them together - multiple item types can participate in the same
# vactube track.
VAC_CONFIGS = {}


@make_result_setup('CustVactube')
def res_vactube_setup(res: Property):
    group = res['group', 'DEFAULT_GROUP']

    if group not in VAC_CONFIGS:
        # Store our values in the CONFIGS dictionary
        config, inst_configs = VAC_CONFIGS[group] = {}, {}
    else:
        # Grab the already-filled values, and add to them
        config, inst_configs = VAC_CONFIGS[group]

    for block in res.find_all("Instance"):
        # Configuration info for each instance set..
        conf = {
            # The three sizes of corner instance
            ('corner', 1): block['corner_small_inst', ''],
            ('corner', 2): block['corner_medium_inst', ''],
            ('corner', 3): block['corner_large_inst', ''],

            ('corner_temp', 1): block['temp_corner_small', ''],
            ('corner_temp', 2): block['temp_corner_medium', ''],
            ('corner_temp', 3): block['temp_corner_large', ''],

            # Straight instances connected to the next part
            'straight': block['straight_inst', ''],

            # Supports attach to the 4 sides of the straight part,
            # if there's a brush there.
            'support': block['support_inst', ''],

            'is_tsection': srctools.conv_bool(block['is_tsection', '0']),

            ('entry', 'wall'): block['entry_inst'],
            ('entry', 'floor'): block['entry_floor_inst'],
            ('entry', 'ceiling'): block['entry_ceil_inst'],

            'exit': block['exit_inst'],
        }

        for prop in block.find_all("File"):
            try:
                size, file = prop.value.split(":", 1)
            except ValueError:
                size = 1
                file = prop.value

            for inst in instanceLocs.resolve(file):
                inst_configs[inst] = conf, srctools.conv_int(size, 1)

    return group


@make_result('CustVactube')
def res_make_vactubes(vmf: VMF, res: Property):
    """Specialised result to parse vactubes from markers.

    Only runs once, and then quits the condition list. After priority 400,
    the ents will actually be placed.
    """
    if res.value not in VAC_CONFIGS:
        # We've already executed this config group
        return RES_EXHAUSTED

    CONFIG, INST_CONFIGS = VAC_CONFIGS[res.value]
    del VAC_CONFIGS[res.value]  # Don't let this run twice

    markers: Dict[str, Marker] = {}

    # Find all our markers, so we can look them up by targetname.
    for inst in vmf.by_class['func_instance']:  # type: Entity
        try:
            config, inst_size = INST_CONFIGS[inst['file'].casefold()]
        except KeyError:
            continue  # Not a marker

        # Remove the original instance from the level - we spawn entirely new
        # ones.
        inst.remove()

        markers[inst['targetname']] = Marker(inst, config, inst_size)

    for mark_name, marker in markers.items():
        marker_item = connections.ITEMS[mark_name]

        marker_item.delete_antlines()

        next_marker = None
        for conn in list(marker_item.outputs):
            try:
                next_marker = markers[conn.to_item.name]
            except KeyError:
                LOGGER.warning(
                    'Vactube connected to non-vactube ("{}")!',
                    conn.to_item.name,
                )
                continue

            conn.remove()
                
            if marker.next is not None:
                raise ValueError('Vactube connected to two targets!')
            marker.next = conn.to_item.name
            next_marker.no_prev = False

        if next_marker is None:
            # No next-instances were found..
            # Mark as no-connections
            marker.next = None

    # We do generation only from the start of chains.
    for marker in markers.values():
        if marker.no_prev:
            VAC_TRACKS.append((marker, markers))

    return RES_EXHAUSTED


@meta_cond(400)
def vactube_gen(vmf: VMF) -> None:
    """Generate the vactubes, after most conditions have run."""
    if not VAC_TRACKS:
        return
    LOGGER.info('Generating vactubes...')
    for start, all_markers in VAC_TRACKS:
        start_normal = Vec(-1, 0, 0).rotate_by_str(start.ent['angles'])

        # First create the start section..
        start_logic = start.ent.copy()
        vmf.add_ent(start_logic)

        start_logic['file'] = start.conf['entry', (
            'ceiling' if (start_normal.z > 0) else
            'floor' if (start_normal.z < 0) else
            'wall'
        )]

        end = start

        for inst, end in start.follow_path(all_markers):
            join_markers(vmf, inst, end, inst is start)

        end_loc = Vec.from_str(end.ent['origin'])
        end_norm = Vec(-1, 0, 0).rotate_by_str(end.ent['angles'])

        # join_markers creates straight parts up-to the marker, but not at it's
        # location - create the last one.
        make_straight(
            vmf,
            end_loc,
            end_norm,
            128,
            end.conf,
        )

        # If the end is placed in goo, don't add logic - it isn't visible, and
        # the object is on a one-way trip anyway.
        if BLOCK_POS['world': end_loc].is_goo and end_norm == (0, 0, -1):
            end_logic = end.ent.copy()
            vmf.add_ent(end_logic)
            end_logic['file'] = end.conf['exit']


def push_trigger(vmf: VMF, loc: Vec, normal: Vec, solids: List[Solid]) -> None:
    # We only need one trigger per direction, for now.
    try:
        ent = PUSH_TRIGS[normal.as_tuple()]
    except KeyError:
        ent = PUSH_TRIGS[normal.as_tuple()] = vmf.create_ent(
            classname='trigger_push',
            origin=loc,
            # The z-direction is reversed..
            pushdir=normal.to_angle(),
            speed=(
                UP_PUSH_SPEED if normal.z > 0 else
                DN_PUSH_SPEED if normal.z < 0 else
                PUSH_SPEED
            ),
            spawnflags='1103',  # Clients, Physics, Everything
        )

    ent.solids.extend(solids)


def motion_trigger(vmf: VMF, *solids: Solid) -> None:
    """Create the anti-gravity trigger, and force crouching."""
    motion_trig = vmf.create_ent(
        classname='trigger_vphysics_motion',
        SetGravityScale='0.0',
        origin=solids[0].get_origin(),
        spawnflags='1103',  # Clients, Physics, Everything
    )
    duck_trig = vmf.create_ent(
        classname='trigger_playermovement',
        origin=motion_trig['origin'],
        spawnflags=1 + 2048,  # Clients, Auto-duck while in trigger.
    )
    for solid in solids:
        motion_trig.solids.append(solid.copy())
        duck_trig.solids.append(solid.copy())


def make_straight(
    vmf: VMF,
    origin: Vec,
    normal: Vec,
    dist: int,
    config: dict,
    is_start=False,
) -> None:
    """Make a straight line of instances from one point to another."""

    # 32 added to the other directions, plus extended dist in the direction
    # of the normal - 1
    p1 = origin + (normal * ((dist // 128 * 128) - 96))
    # The starting brush needs to
    # stick out a bit further, to cover the
    # point_push entity.
    p2 = origin - (normal * (96 if is_start else 32))

    # bbox before +- 32 to ensure the above doesn't wipe it out
    p1, p2 = Vec.bbox(p1, p2)

    solid = vmf.make_prism(
        # Expand to 64x64 in the other two directions
        p1 - 32, p2 + 32,
        mat='tools/toolstrigger',
    ).solid

    motion_trigger(vmf, solid.copy())

    push_trigger(vmf, origin, normal, [solid])

    angles = normal.to_angle()

    support_file = config['support']
    straight_file = config['straight']
    support_positions = (
        SUPPORT_POS[normal.as_tuple()]
        if support_file else
        []
    )

    for off in range(0, int(dist), 128):
        position = origin + off * normal
        vmf.create_ent(
            classname='func_instance',
            origin=position,
            angles=angles,
            file=straight_file,
        )

        for supp_ang, supp_off in support_positions:
            try:
                tile = tiling.TILES[
                    (position + supp_off).as_tuple(),
                    (-supp_off).norm().as_tuple()
                ]
            except KeyError:
                continue
            # Check all 4 center tiles are present.
            if all(tile[u, v].is_tile for u in (1,2) for v in (1, 2)):
                vmf.create_ent(
                    classname='func_instance',
                    origin=position,
                    angles=supp_ang,
                    file=support_file,
                )


def make_corner(vmf: VMF, origin: Vec, angle: str, size: int, config: dict) -> None:
    vmf.create_ent(
        classname='func_instance',
        origin=origin,
        angles=angle,
        file=config['corner', size],
    )

    temp = config['corner_temp', size]
    if temp:
        temp_solids = template_brush.import_template(
            vmf,
            temp,
            origin=origin,
            angles=Vec.from_str(angle),
            force_type=template_brush.TEMP_TYPES.world,
            add_to_map=False,
        ).world
        motion_trigger(*temp_solids)


def make_bend(
    vmf: VMF,
    origin_a: Vec,
    origin_b: Vec,
    norm_a: Vec,
    norm_b: Vec,
    corner_ang: str,
    config,
    max_size: int,
    is_start=False,
) -> None:
    """Make a corner and the straight sections leading into it."""
    off = origin_b - origin_a
    # The distance to move first, then second.
    first_movement = off.norm_mask(norm_a)
    sec_movement = off.norm_mask(norm_b)

    # The size of the corner ranges from 1-3. It's
    # limited by the user's setting and the distance we have in each direction
    corner_size = min(
        first_movement.mag() // 128, sec_movement.mag() // 128,
        3, max_size,
    )

    straight_a = first_movement.mag() - (corner_size - 1) * 128
    straight_b = sec_movement.mag() - (corner_size * 128)

    if corner_size < 1:
        return  # No room!

    if straight_a > 0:
        make_straight(
            vmf,
            origin_a,
            norm_a,
            straight_a,
            config,
            is_start,
        )

    corner_origin = origin_a + norm_a * straight_a
    make_corner(
        vmf,
        corner_origin,
        corner_ang,
        corner_size,
        config,
    )

    if straight_b > 0:
        make_straight(
            vmf,
            origin_b - (straight_b * norm_b),
            norm_b,
            straight_b,
            config,
        )


def make_ubend(
    vmf: VMF,
    origin_a: Vec,
    origin_b: Vec,
    normal: Vec,
    config,
    max_size: int,
    is_start=False,
):
    """Create u-shaped bends."""
    offset = origin_b - origin_a

    out_axis = normal.axis()
    out_off = offset[out_axis]
    offset[out_axis] = 0

    if len(offset) == 2:
        # Len counts the non-zero values..
        # If 2, the ubend is diagonal so it's ambigous where to put the bends.
        return []

    side_norm = offset.norm()

    for side_axis, side_dist in zip('xyz', offset):
        if side_dist:
            side_dist = abs(side_dist) + 128
            break
    else:
        # The two tube items are on top of another, that's
        # impossible to generate.
        return []

    # Calculate the size of the various parts.
    # first/second _size = size of the corners.
    # first/second _straight = length of straight sections
    # off_straight = length of straight in between corners
    if out_off == 0:
        # Both tubes are parallel to each other - use half the distance
        # for the bends.
        first_size = second_size = min(
            3,
            max_size,
            side_dist // (128 * 2),
        )
        first_straight = second_straight = 0
        side_straight = side_dist - 2 * 128 * first_size
    elif out_off > 0:
        # The second tube is further away than the first - the first bend
        # should be largest.
        # We need 1 spot for the second bend.
        first_size = min(
            3,
            max_size,
            side_dist // 128 - 1,
            out_off,
        )
        second_size = min(3, side_dist // 128 - first_size, max_size)

        first_straight = (out_off + 128) - 128 * second_size
        second_straight = (first_size - second_size) * 128

        side_straight = (side_dist / 128 - first_size - second_size) * 128

    elif out_off < 0:
        # The first tube is further away than the second - the second bend
        # should be largest.
        second_size = min(
            3,
            max_size,
            side_dist // 128 - 1,
            -out_off  # -out = abs()
        )
        first_size = min(3, side_dist // 128 - second_size, max_size)

        first_straight = (second_size - first_size) * 128
        second_straight = (-out_off + 128) - 128 * second_size

        side_straight = (side_dist / 128 - first_size - second_size) * 128
    else:
        return []  # Not possible..

    # We always have a straight segment at the first marker point - move
    # everything up slightly.

    first_straight += 128

    LOGGER.info(
        'Ubend {}: {}, c={}, {}, c={}, {}',
        out_off,
        first_straight,
        first_size,
        side_straight,
        second_size,
        second_straight,
    )

    make_straight(
        vmf,
        origin_a,
        normal,
        first_straight,
        config,
        is_start,
    )

    first_corner_loc = origin_a + (normal * first_straight)

    make_corner(
        vmf,
        first_corner_loc,
        CORNER_ANG[normal.as_tuple(), side_norm.as_tuple()].ang,
        first_size,
        config,
    )

    off_straight_loc = first_corner_loc + normal * (128 * (first_size - 1))
    off_straight_loc += side_norm * (128 * first_size)

    if side_straight > 0:
        make_straight(
            vmf,
            off_straight_loc,
            side_norm,
            side_straight,
            config,
        )

    sec_corner_loc = off_straight_loc + side_norm * side_straight

    make_corner(
        vmf,
        sec_corner_loc,
        CORNER_ANG[side_norm.as_tuple(), (-normal).as_tuple()].ang,
        second_size,
        config,
    )

    if second_straight > 0:
        make_straight(
            vmf,
            sec_corner_loc - normal * (128 * second_size),
            -normal,
            second_straight,
            config,
        )


def join_markers(vmf: VMF, mark_a: Marker, mark_b: Marker, is_start: bool=False) -> None:
    """Join two marker ents together with corners."""
    origin_a = Vec.from_str(mark_a.ent['origin'])
    origin_b = Vec.from_str(mark_b.ent['origin'])

    norm_a = Vec(-1, 0, 0).rotate_by_str(mark_a.ent['angles'])
    norm_b = Vec(-1, 0, 0).rotate_by_str(mark_b.ent['angles'])

    config = mark_a.conf

    if norm_a == norm_b:
        # Either straight-line, or s-bend.
        dist = (origin_a - origin_b).mag()

        if origin_a + (norm_a * dist) == origin_b:
            make_straight(
                vmf,
                origin_a,
                norm_a,
                dist,
                config,
                is_start,
            )
        # else: S-bend, we don't do the geometry for this..
        return

    if norm_a == -norm_b:
        # U-shape bend..
        make_ubend(
            vmf,
            origin_a,
            origin_b,
            norm_a,
            config,
            max_size=mark_a.size,
        )
        return

    try:
        corner_ang, flat_angle = CORNER_ANG[norm_a.as_tuple(), norm_b.as_tuple()]

        if origin_a[flat_angle] != origin_b[flat_angle]:
            # It needs to be flat in this angle!
            raise ValueError
    except ValueError:
        # The tubes need two corners to join together - abort for that.
        return
    else:
        make_bend(
            vmf,
            origin_a,
            origin_b,
            norm_a,
            norm_b,
            corner_ang,
            config,
            max_size=mark_a.size,
        )
