"""Implements the cutomisable vactube items.
"""
from collections import namedtuple
from typing import Dict, Tuple, List, Iterator, Optional, NamedTuple

from srctools import Vec, Vec_tuple, Property, Entity, VMF, Solid, Matrix, Angle
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


class Config(NamedTuple):
    inst_corner: List[str]
    temp_corner: List[Optional[template_brush.Template]]
    inst_straight: str
    inst_support: str
    inst_exit: str

    inst_entry_floor: str
    inst_entry_wall: str
    inst_entry_ceil: str


class Marker:
    """A single node point."""
    next: Optional[str]

    def __init__(self, inst: Entity, conf: Config, size: int) -> None:
        self.ent = inst
        self.conf = conf
        self.next = None
        self.no_prev = True
        self.size = size
        self.orient = Matrix.from_angle(Angle.from_str(inst['angles']))

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
VAC_CONFIGS: Dict[str, Dict[str, Tuple[Config, int]]] = {}


@make_result_setup('CustVactube')
def res_vactube_setup(res: Property):
    group = res['group', 'DEFAULT_GROUP']

    if group not in VAC_CONFIGS:
        # Store our values in the CONFIGS dictionary
        inst_configs = VAC_CONFIGS[group] = {}
    else:
        # Grab the already-filled values, and add to them
        inst_configs = VAC_CONFIGS[group]

    def get_temp(key):
        try:
            temp_id = block['temp_' + key]
        except LookupError:
            return None
        try:
            return template_brush.get_template(temp_id)
        except template_brush.InvalidTemplateName:
            LOGGER.warning('Invalid template "{}" for vactube group {}!', temp_id, group)
            return None

    for block in res.find_all("Instance"):
        # Configuration info for each instance set..
        conf = Config(
            # The three sizes of corner instance
            inst_corner=[
                block['corner_small_inst', ''],
                block['corner_medium_inst', ''],
                block['corner_large_inst', ''],
            ],
            temp_corner=[
                get_temp('corner_small'),
                get_temp('corner_medium'),
                get_temp('corner_large'),
            ],
            # Straight instances connected to the next part
            inst_straight=block['straight_inst', ''],
            # Supports attach to the 4 sides of the straight part,
            # if there's a brush there.
            inst_support=block['support_inst', ''],
            inst_entry_floor=block['entry_floor_inst'],
            inst_entry_wall=block['entry_inst'],
            inst_entry_ceil=block['entry_ceil_inst'],
            inst_exit=block['exit_inst'],
        )

        for prop in block.find_all("File"):
            try:
                size_str, file = prop.value.split(":", 1)
                # Users enter 1-3, use 0-2 in code.
                size = srctools.conv_int(size_str, 1) - 1
            except ValueError:
                size = 0
                file = prop.value

            for inst in instanceLocs.resolve(file):
                inst_configs[inst] = conf, size

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

    inst_config = VAC_CONFIGS[res.value]
    del VAC_CONFIGS[res.value]  # Don't let this run twice

    markers: Dict[str, Marker] = {}

    # Find all our markers, so we can look them up by targetname.
    for inst in vmf.by_class['func_instance']:  # type: Entity
        try:
            config, inst_size = inst_config[inst['file'].casefold()]
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
        start_normal = -start.orient.forward()

        # First create the start section..
        start_logic = start.ent.copy()
        vmf.add_ent(start_logic)

        if start_normal.z > 0:
            start_logic['file'] = start.conf.inst_entry_ceil
        elif start_normal.z < 0:
            start_logic['file'] = start.conf.inst_entry_floor
        else:
            start_logic['file'] = start.conf.inst_entry_wall

        end = start

        for inst, end in start.follow_path(all_markers):
            join_markers(vmf, inst, end, inst is start)

        end_loc = Vec.from_str(end.ent['origin'])
        end_norm = -end.orient.forward()

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
        if BLOCK_POS['world': end_loc].is_goo and end_norm.z < 0:
            end_logic = end.ent.copy()
            vmf.add_ent(end_logic)
            end_logic['file'] = end.conf.inst_exit


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
    config: Config,
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
    orient = Matrix.from_angle(angles)

    for off in range(0, int(dist), 128):
        position = origin + off * normal
        vmf.create_ent(
            classname='func_instance',
            origin=position,
            angles=orient.to_angle(),
            file=config.inst_straight,
        )

        for supp_dir in [orient.up(), orient.left(), -orient.left(), -orient.up()]:
            try:
                tile = tiling.TILES[
                    (position - 128 * supp_dir).as_tuple(),
                    supp_dir.norm().as_tuple()
                ]
            except KeyError:
                continue
            # Check all 4 center tiles are present.
            if all(tile[u, v].is_tile for u in (1,2) for v in (1, 2)):
                vmf.create_ent(
                    classname='func_instance',
                    origin=position,
                    angles=Matrix.from_basis(x=normal, z=supp_dir).to_angle(),
                    file=config.inst_support,
                )


def make_corner(
    vmf: VMF,
    origin: Vec,
    start_dir: Vec,
    end_dir: Vec,
    size: int,
    config: Config,
) -> None:
    angles = Matrix.from_basis(z=start_dir, x=end_dir).to_angle()
    vmf.create_ent(
        classname='func_instance',
        origin=origin,
        angles=angles,
        file=config.inst_corner[size],
    )

    temp = config.temp_corner[size]
    if temp:
        temp_solids = template_brush.import_template(
            vmf,
            temp,
            origin=origin,
            angles=angles,
            force_type=template_brush.TEMP_TYPES.world,
            add_to_map=False,
        ).world
        motion_trigger(vmf, *temp_solids)


def make_bend(
    vmf: VMF,
    origin_a: Vec,
    origin_b: Vec,
    norm_a: Vec,
    norm_b: Vec,
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
    corner_size = int(min(
        first_movement.mag() // 128, sec_movement.mag() // 128,
        3, max_size,
    ))

    straight_a = first_movement.mag() - (corner_size - 1) * 128
    straight_b = sec_movement.mag() - (corner_size) * 128

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
        norm_a,
        norm_b,
        corner_size - 1,
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
        normal,
        side_norm,
        first_size - 1,
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
        side_norm,
        -normal,
        second_size - 1,
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

    # Lastly try a regular curve. Check they are on the same plane.
    side_dir = Vec.cross(norm_a, norm_b)
    side_off_a = side_dir.dot(origin_a)
    side_off_b = side_dir.dot(origin_b)
    if side_off_a == side_off_b:
        make_bend(
            vmf,
            origin_a,
            origin_b,
            norm_a,
            norm_b,
            config,
            max_size=mark_a.size,
        )
