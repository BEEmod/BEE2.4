"""Implements the cutomisable vactube items.
"""
from __future__ import annotations
from collections.abc import Iterator, Iterable

import attrs
from srctools import Vec, Keyvalues, Entity, VMF, Solid, Matrix
import srctools.logger

from precomp import tiling, instanceLocs, conditions, connections, template_brush
from precomp.brushLoc import POS as BLOCK_POS
import utils

COND_MOD_NAME = None

LOGGER = srctools.logger.get_logger(__name__, alias='cond.vactubes')

PUSH_SPEED = 700  # The speed of the push triggers.
UP_PUSH_SPEED = 900  # Make it slightly faster when up to counteract gravity
DN_PUSH_SPEED = 400  # Slow down when going down since gravity also applies..

PUSH_TRIGS: dict[tuple[float, float, float], Entity] = {}
VAC_TRACKS: list[tuple[Marker, dict[str, Marker]]] = []  # Tuples of (start, group)


@attrs.define
class Config:
    """Configuration for a vactube item set."""
    inst_corner: list[str]
    temp_corner: list[tuple[template_brush.Template | None, Iterable[str]]]
    trig_radius: float
    inst_support: str  # Placed on each side with an adjacent wall.
    inst_support_ring: str  # If any support is placed, this is placed.
    inst_exit: str

    inst_entry_floor: str
    inst_entry_wall: str
    inst_entry_ceil: str

    # For straight instances, a size (multiple of 128) -> instance.
    inst_straight: dict[int, str]
    # And those sizes from large to small.
    inst_straight_sizes: list[int] = attrs.field(init=False)
    @inst_straight_sizes.default
    def _straight_size(self) -> list[int]:
        return sorted(self.inst_straight.keys(), reverse=True)


@attrs.define
class Marker:
    """A single node point."""
    ent: Entity = attrs.field(on_setattr=attrs.setters.frozen)
    conf: Config
    size: int
    no_prev: bool = True
    next: str | None = None
    orient: Matrix = attrs.field(init=False, on_setattr=attrs.setters.frozen)

    # noinspection PyUnresolvedReferences
    @orient.default
    def _init_orient(self) -> Matrix:
        """We need to rotate the orient, because items have forward as negative X."""
        rot = Matrix.from_angstr(self.ent['angles'])
        return Matrix.from_yaw(180) @ rot

    def follow_path(self, vac_list: dict[str, Marker]) -> Iterator[tuple[Marker, Marker]]:
        """Follow the provided vactube path, yielding each pair of nodes."""
        vac_node = self
        while True:
            try:
                next_ent = vac_list[vac_node.next]
            except KeyError:
                return
            yield vac_node, next_ent
            vac_node = next_ent


# Store the configs for vactube items to allow us to join them together.
# Multiple item types can participate in the same vactube track.
VAC_CONFIGS: dict[str, dict[str, tuple[Config, int]]] = {}


@conditions.make_result('CustVactube')
def res_vactubes(vmf: VMF, res: Keyvalues) -> conditions.ResultCallable:
    """Specialised result to parse vactubes from markers.

    Only runs once, and then quits the condition list. After priority 400,
    the ents will actually be placed.
    """
    group = res['group', 'DEFAULT_GROUP']

    if group not in VAC_CONFIGS:
        # Store our values in the CONFIGS dictionary
        inst_config = VAC_CONFIGS[group] = {}
    else:
        # Grab the already-filled values, and add to them
        inst_config = VAC_CONFIGS[group]

    def get_temp(key: str) -> tuple[template_brush.Template | None, Iterable[str]]:
        """Read the template, handling errors."""
        try:
            temp_name = block['temp_' + key]
        except LookupError:
            return None, ()
        temp_id, visgroups = template_brush.parse_temp_name(temp_name)
        try:
            return template_brush.get_template(temp_id), visgroups
        except template_brush.InvalidTemplateName:
            LOGGER.warning('Invalid template "{}" for vactube group {}!', temp_name, group)
            return None, ()

    for block in res.find_all("Instance"):
        # Configuration info for each instance set...
        straight_block = block.find_key('straight_inst', '')
        if straight_block.has_children():
            straight = {
                int(prop.name): prop.value
                for prop in straight_block
            }
        else:
            straight = {128: straight_block.value}
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
            trig_radius=block.float('trig_size', 64.0) / 2.0,
            inst_straight=straight,
            # Supports attach to the 4 sides of the straight part,
            # if there's a brush there.
            inst_support=block['support_inst', ''],
            # If a support is placed, this is also placed once.
            inst_support_ring=block['support_ring_inst', ''],
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

            inst_config.update(
                dict.fromkeys(instanceLocs.resolve_filter(file), (conf, size))
            )

    def result(_: Entity) -> object:
        """Create the vactubes."""
        if group not in VAC_CONFIGS:
            # We've already executed this config group
            return conditions.RES_EXHAUSTED

        del VAC_CONFIGS[group]  # Don't let this run twice

        markers: dict[str, Marker] = {}

        # Find all our markers, so we can look them up by targetname.
        for inst in vmf.by_class['func_instance']:
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
                # No next-instances were found - mark as no-connections.
                marker.next = None

        # We do generation only from the start of chains.
        for marker in markers.values():
            if marker.no_prev:
                VAC_TRACKS.append((marker, markers))

        return conditions.RES_EXHAUSTED
    return result


@conditions.meta_cond(400)
def vactube_gen(vmf: VMF) -> None:
    """Generate the vactubes, after most conditions have run."""
    if not VAC_TRACKS:
        return
    LOGGER.info('Generating vactubes...')
    for start, all_markers in VAC_TRACKS:
        start_normal = start.orient.forward()

        # First create the start section
        start_logic = start.ent.copy()
        vmf.add_ent(start_logic)

        if start_normal.z > 0:
            start_logic['file'] = fname = start.conf.inst_entry_ceil
        elif start_normal.z < 0:
            start_logic['file'] = fname = start.conf.inst_entry_floor
        else:
            start_logic['file'] = fname = start.conf.inst_entry_wall
        conditions.ALL_INST.add(fname.casefold())

        end = start

        for inst, end in start.follow_path(all_markers):
            join_markers(vmf, inst, end, inst is start)

        end_loc = Vec.from_str(end.ent['origin'])
        end_norm = end.orient.forward()

        # join_markers creates straight parts up-to the marker, but not at its location.
        # Create the last one.
        make_straight(
            vmf,
            end_loc,
            end_norm,
            128,
            end.conf,
        )

        # If the end is placed in goo, don't add logic - it isn't visible, and
        # the object is on a one-way trip anyway.
        if not (BLOCK_POS.lookup_world(end_loc).is_goo and end_norm.z < -1e-6):
            end_logic = end.ent.copy()
            vmf.add_ent(end_logic)
            end_logic['file'] = end.conf.inst_exit
            conditions.ALL_INST.add(end.conf.inst_exit.casefold())


def push_trigger(vmf: VMF, loc: Vec, normal: Vec, solids: list[Solid]) -> None:
    """Generate the push trigger for these solids."""
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
                UP_PUSH_SPEED if normal.z > 1e-6 else
                DN_PUSH_SPEED if normal.z < -1e-6 else
                PUSH_SPEED
            ),
            spawnflags='1103',  # Clients, Physics, Everything
        )

    ent.solids.extend(solids)


def motion_trigger(vmf: VMF, *solids: Solid) -> None:
    """Create the antigravity trigger, and force crouching."""
    motion_trig = vmf.create_ent(
        classname='trigger_vphysics_motion',
        SetGravityScale='0.0',
        origin=solids[0].get_origin(),
        spawnflags='1103',  # Clients, Physics, Everything
    )
    duck_trig = vmf.create_ent(
        classname='trigger_playermovement',
        origin=motion_trig['origin'],
        spawnflags=1 | 2048,  # Clients, Auto-duck while in trigger.
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
    is_start: bool = False,
) -> None:
    """Make a straight line of instances from one point to another."""
    angles = round(normal, 6).to_angle()
    orient = Matrix.from_angle(angles)

    # The starting brush needs to stick out a bit further, to cover the
    # point_push entity.
    start_off = -96 if is_start else -64

    p1, p2 = Vec.bbox(
        origin + Vec(start_off, -config.trig_radius, -config.trig_radius) @ orient,
        origin + Vec(dist - 64, config.trig_radius, config.trig_radius) @ orient,
    )

    solid = vmf.make_prism(p1, p2, mat='tools/toolstrigger').solid

    motion_trigger(vmf, solid.copy())

    push_trigger(vmf, origin, normal, [solid])

    off = 0
    for seg_dist in utils.fit(dist, config.inst_straight_sizes):
        conditions.add_inst(
            vmf,
            origin=origin + off * orient.forward(),
            angles=angles,
            file=config.inst_straight[seg_dist],
        )
        off += seg_dist
    # Supports.
    if config.inst_support:
        for off in range(0, int(dist), 128):
            position = origin + off * normal
            placed_support = False
            for supp_dir in [
                orient.up(), orient.left(),
                -orient.left(), -orient.up()
            ]:
                try:
                    tile = tiling.TILES[
                        (position - 128 * supp_dir).as_tuple(),
                        supp_dir.norm().as_tuple()
                    ]
                except KeyError:
                    continue
                # Check all 4 center tiles are present.
                if all(tile[u, v].is_tile for u in (1, 2) for v in (1, 2)):
                    conditions.add_inst(
                        vmf,
                        origin=position,
                        angles=Matrix.from_basis(x=normal, z=supp_dir).to_angle(),
                        file=config.inst_support,
                    )
                    placed_support = True
            if placed_support and config.inst_support_ring:
                conditions.add_inst(
                    vmf,
                    origin=position,
                    angles=angles,
                    file=config.inst_support_ring,
                )


def make_corner(
    vmf: VMF,
    origin: Vec,
    start_dir: Vec,
    end_dir: Vec,
    size: int,
    config: Config,
) -> None:
    """Place a corner."""
    angles = Matrix.from_basis(z=start_dir, x=end_dir)
    conditions.add_inst(
        vmf,
        origin=origin,
        angles=angles,
        file=config.inst_corner[int(size)],
    )

    temp, visgroups = config.temp_corner[int(size)]
    if temp is not None:
        temp_solids = template_brush.import_template(
            vmf,
            temp,
            additional_visgroups=visgroups,
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
    config: Config,
    max_size: int,
    is_start: bool = False,
) -> None:
    """Make a corner and the straight sections leading into it."""
    off = origin_b - origin_a
    # The distance to move first, then second.
    first_movement = round(Vec.dot(off, norm_a))
    sec_movement = round(Vec.dot(off, norm_b))

    # The size of the corner ranges from 1-3. It's
    # limited by the user's setting and the distance we have in each direction
    corner_size = int(min(
        first_movement // 128, sec_movement // 128,
        3, max_size + 1,
    ))

    straight_a = first_movement - (corner_size - 1) * 128
    straight_b = sec_movement - corner_size * 128

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
    config: Config,
    max_size: int,
    is_start: bool = False,
) -> None:
    """Create U-shaped bends."""
    offset = origin_b - origin_a

    out_axis = normal.axis()
    out_off = int(offset[out_axis])
    offset[out_axis] = 0

    if len(offset) == 2:
        # Len counts the non-zero values.
        # If 2, the U-bend is diagonal, and it's ambiguous where to put the bends.
        return

    side_norm = offset.norm()

    for side_axis, side_dist_flt in zip('xyz', offset):
        if abs(side_dist_flt) > 0.01:
            side_dist = int(abs(side_dist_flt)) + 128
            break
    else:
        # The two tube items are on top of another, that's
        # impossible to generate.
        return

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

        side_straight = (side_dist // 128 - first_size - second_size) * 128

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

        side_straight = (side_dist // 128 - first_size - second_size) * 128
    else:
        return  # Not possible...

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

    norm_a = mark_a.orient.forward()
    norm_b = mark_b.orient.forward()

    config = mark_a.conf

    LOGGER.debug(
        'Connect markers: {} @ {} -> {} @ {}, dot={}\n{}',
        origin_a, norm_a,
        origin_b, norm_b,
        Vec.dot(norm_a, norm_b),
        config,
    )

    if norm_a == norm_b:
        # Either straight-line, or s-bend.
        dist = round((origin_a - origin_b).mag())

        if origin_a + (norm_a * dist) == origin_b:
            make_straight(
                vmf,
                origin_a,
                norm_a,
                dist,
                config,
                is_start,
            )
        # else: S-bend, we don't do the geometry for this.
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
    if abs(side_off_a - side_off_b) < 1e-6:
        make_bend(
            vmf,
            origin_a,
            origin_b,
            norm_a,
            norm_b,
            config,
            max_size=mark_a.size,
        )
    else:
        LOGGER.warning(
            'Cannot connect markers: {} @ {} -> {} @ {}\n '
            'Sides: {:.12f} {:.12f}\n{}',
            origin_a, norm_a,
            origin_b, norm_b,
            side_off_a, side_off_b,
            config,
        )
