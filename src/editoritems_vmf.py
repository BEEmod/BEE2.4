"""Use pseudo-entities to make creating editoritems data more easily."""
from __future__ import annotations

from typing import Callable
from srctools import FrozenVec, Matrix, Angle, Vec, logger, conv_int
from srctools.vmf import VMF, Entity

from collisions import BBox
from editoritems import Item, ConnSide, OccuType, AntlinePoint, Coord, OccupiedVoxel, bounding_boxes


LOGGER = logger.get_logger(__name__)
LOAD_FUNCS: dict[str, Callable[[Item, Entity], None]] = {}
SAVE_FUNCS: list[Callable[[Item, VMF], None]] = []


def load(item: Item, vmf: VMF) -> None:
    """Search the map for important entities, and apply it to the item."""
    with logger.context(item.id):
        for ent in vmf.entities:
            classname = ent['classname'].casefold()
            if ent.hidden:
                continue
            try:
                func = LOAD_FUNCS[classname]
            except KeyError:
                if classname.startswith('bee2_editor_'):
                    LOGGER.warning('Unknown item configuration entity "{}"!', classname)
            else:
                func(item, ent)


def save(item: Item) -> VMF:
    """Export out relevant item options into a VMF."""
    vmf = VMF()
    with logger.context(item.id):
        for func in SAVE_FUNCS:
            func(item, vmf)
    return vmf


SKIN_TO_CONN_OFFSETS: dict[str, FrozenVec] = {
    # Skin -> antline offset.
    '1': FrozenVec(-0.5, +0.5),
    '2': FrozenVec(-0.5, -0.5),
    '3': FrozenVec(+0.5, +0.5),
    '4': FrozenVec(+0.5, -0.5),
}
# Opposite transform.
CONN_OFFSET_TO_SKIN: dict[FrozenVec, str] = {
    (2 * vec): skin
    for skin, vec in SKIN_TO_CONN_OFFSETS.items()
}


def parse_occutype(value: str) -> OccuType:
    """Parse an occupation type specification from the VMF."""
    val = OccuType.NOTHING
    for word in value.split():
        word = word.upper()
        if word.startswith('COLLIDE_'):
            word = word[8:]
        try:
            val |= OccuType[word]
        except KeyError:
            LOGGER.warning('Unknown collide type "{}"', word)
    return val


def load_editor_connectionpoint(item: Item, ent: Entity) -> None:
    """Allow more conveniently defining connectionpoints."""
    origin = Vec.from_str(ent['origin'])
    angles = Angle.from_str(ent['angles'])
    if round(angles.pitch) != 0.0 or round(angles.roll) != 0.0:
        LOGGER.warning(
            "Connection Point at {} is not flat on the floor, PeTI doesn't allow this.",
            origin,
        )
        return
    try:
        side = ConnSide.from_yaw(round(angles.yaw))
    except ValueError:
        LOGGER.warning(
            "Connection Point at {} must point in a cardinal direction, not {}!",
            origin, angles,
        )
        return

    orient = Matrix.from_yaw(round(angles.yaw))

    center = (origin - (-56, 56, 0)) / 16
    center.z = 0
    center.y = -center.y
    try:
        offset = SKIN_TO_CONN_OFFSETS[ent['skin']] @ orient
    except KeyError:
        LOGGER.warning('Connection Point at {} has invalid skin "{}"!', origin)
        return
    ant_pos = Coord(round(center.x + offset.x), round(center.y - offset.y), 0)
    sign_pos = Coord(round(center.x - offset.x), round(center.y + offset.y), 0)

    group_str = ent['group_id']

    item.antline_points[side].append(AntlinePoint(
        ant_pos,
        sign_pos,
        conv_int(ent['priority']),
        int(group_str) if group_str.strip() else None
    ))


def save_editor_connectionpoint(item: Item, vmf: VMF) -> None:
    """Write connectionpoints to a VMF."""
    for side, points in item.antline_points.items():
        yaw = side.yaw
        inv_orient = Matrix.from_yaw(-yaw)
        for point in points:
            ant_pos = Vec(point.pos.x, -point.pos.y, -64)
            sign_pos = Vec(point.sign_off.x, -point.sign_off.y, -64)

            offset: Vec = (ant_pos - sign_pos) @ inv_orient
            try:
                skin = CONN_OFFSET_TO_SKIN[offset.freeze()]
            except KeyError:
                LOGGER.warning('Pos=({}), Sign=({}) -> ({}) is not a valid offset for signs!', point.pos, point.sign_off, offset)
                continue
            pos: Vec = round((ant_pos + sign_pos) / 2.0 * 16.0, 0)

            vmf.create_ent(
                'bee2_editor_connectionpoint',
                origin=Vec(pos.x - 56, pos.y + 56, -64),
                angles=f'0 {yaw} 0',
                skin=skin,
                priority=point.priority,
                group_id='' if point.group is None else point.group,
            )


def load_editor_embeddedvoxel(item: Item, ent: Entity) -> None:
    """Parse embed definitions contained in the VMF."""
    bbox_min, bbox_max = ent.get_bbox()
    bbox_min = round(bbox_min, 0)
    bbox_max = round(bbox_max, 0)

    if bbox_min % 128 != (64.0, 64.0, 64.0) or bbox_max % 128 != (64.0, 64.0, 64.0):
        LOGGER.warning(
            'Embedded voxel definition ({}) - ({}) is not aligned to grid!',
            bbox_min, bbox_max,
        )
        return

    item.embed_voxels.update(map(Coord.from_vec, Vec.iter_grid(
        (bbox_min + (64, 64, 64 + 128)) / 128,
        (bbox_max + (-64, -64, -64 + 128)) / 128,
    )))


def save_editor_embeddedvoxel(item: Item, vmf: VMF) -> None:
    """Save embedded voxel volumes."""
    for bbox_min, bbox_max in bounding_boxes(item.embed_voxels):
        vmf.create_ent('bee2_editor_embeddedvoxel').solids.append(vmf.make_prism(
            Vec(bbox_min) * 128 + (-64.0, -64.0, -192.0),
            Vec(bbox_max) * 128 + (+64.0, +64.0, -64.0),
            # Entirely ignored, but makes it easier to distinguish.
            'tools/toolshint',
        ).solid)


def load_editor_occupiedvoxel(item: Item, ent: Entity) -> None:
    """Parse voxel collisions contained in the VMF."""
    bbox_min, bbox_max = ent.get_bbox()
    bbox_min = round(bbox_min, 0)
    bbox_max = round(bbox_max, 0)

    coll_type = parse_occutype(ent['coll_type'])
    if ent['coll_against']:
        coll_against = parse_occutype(ent['coll_against'])
    else:
        coll_against = None

    if bbox_min % 128 == (64.0, 64.0, 64.0) and bbox_max % 128 == (64.0, 64.0, 64.0):
        # Full voxels.
        for voxel in Vec.iter_grid(
            (bbox_min + (64, 64, 64)) / 128,
            (bbox_max - (64, 64, 64)) / 128,
        ):
            item.occupy_voxels.add(OccupiedVoxel(
                coll_type, coll_against,
                Coord.from_vec(voxel),
            ))
        return
    elif bbox_min % 32 == (0.0, 0.0, 0.0) and bbox_max % 32 == (0.0, 0.0, 0.0):
        # Subvoxel sections.
        for subvoxel in Vec.iter_grid(
            bbox_min / 32,
            (bbox_max - (32.0, 32.0, 32.0)) / 32,
        ):
            item.occupy_voxels.add(OccupiedVoxel(
                coll_type, coll_against,
                Coord.from_vec((subvoxel + (2, 2, 2)) // 4),
                Coord.from_vec((subvoxel - (2, 2, 2)) % 4),
            ))
        return
    # else, is this a surface definition?
    size = round(bbox_max - bbox_min, 0)
    for axis in ['x', 'y', 'z']:
        if size[axis] < 8:
            u, v = Vec.INV_AXIS[axis]
            # Figure out if we're aligned to the min or max side of the voxel.
            # Compute the normal, then flatten to zero thick.
            if bbox_min[axis] % 32 == 0:
                norm = +1
                plane_dist = bbox_max[axis] = bbox_min[axis]
            elif bbox_max[axis] % 32 == 0:
                norm = -1
                plane_dist = bbox_min[axis] = bbox_max[axis]
            else:
                # Both faces aren't aligned to the grid, skip to error.
                break

            if bbox_min[u] % 128 == bbox_min[v] % 128 == bbox_max[v] % 128 == bbox_max[v] % 128 == 64.0:
                # Full voxel surface definitions.
                for voxel in Vec.iter_grid(
                    Vec.with_axes(u, bbox_min[u] + 64, v, bbox_min[v] + 64, axis, plane_dist + 64 * norm) / 128,
                    Vec.with_axes(u, bbox_max[u] - 64, v, bbox_max[v] - 64, axis, plane_dist + 64 * norm) / 128,
                ):
                    item.occupy_voxels.add(OccupiedVoxel(
                        coll_type, coll_against,
                        Coord.from_vec(voxel),
                        normal=Coord.from_vec(Vec.with_axes(axis, norm)),
                    ))
                return
            elif bbox_min[u] % 32 == bbox_min[v] % 32 == bbox_max[v] % 32 == bbox_max[v] % 32 == 0.0:
                # Subvoxel surface definitions.
                # TODO
                return
            else:
                # Not aligned to grid, skip to error.
                break

    LOGGER.warning(
        'Unknown occupied voxel definition: ({}) - ({}), type="{}", against="{}"',
        bbox_min, bbox_max, ent['coll_type'], ent['coll_against'],
    )


def save_editor_occupiedvoxel(item: Item, vmf: VMF) -> None:
    """Save occupied voxel volumes."""
    for voxel in item.occupy_voxels:
        pos = Vec(voxel.pos) * 128

        if voxel.subpos is not None:
            pos += Vec(voxel.subpos) * 32 - (48, 48, 48)
            p1 = pos - (16.0, 16.0, 16.0)
            p2 = pos + (16.0, 16.0, 16.0)
            norm_dist = 32.0 - 4.0
        else:
            p1 = pos - (64.0, 64.0, 64.0)
            p2 = pos + (64.0, 64.0, 64.0)
            norm_dist = 128.0 - 4.0

        if voxel.normal is not None:
            for axis in ['x', 'y', 'z']:
                val = getattr(voxel.normal, axis)
                if val == +1:
                    p2[axis] -= norm_dist
                elif val == -1:
                    p1[axis] += norm_dist

        if voxel.against is not None:
            against = str(voxel.against).replace('COLLIDE_', '')
        else:
            against = ''

        vmf.create_ent(
            'bee2_editor_occupiedvoxel',
            coll_type=str(voxel.type).replace('COLLIDE_', ''),
            coll_against=against,
        ).solids.append(vmf.make_prism(
            p1, p2,
            # Use clip for voxels, invisible for normals.
            # Entirely ignored, but makes it easier to use.
            'tools/toolsclip' if voxel.normal is None else 'tools/toolsinvisible',
        ).solid)


def load_collision_bbox(item: Item, ent: Entity) -> None:
    """Load precise BEE collisions."""
    item.collisions.extend(BBox.from_ent(ent))


def save_collision_bbox(item: Item, vmf: VMF) -> None:
    """Export precise BEE collisions."""
    for coll in item.collisions:
        coll.as_ent(vmf)


LOAD_FUNCS.update({
    'bee2' + name[4:]: func
    for name, func in globals().items()
    if name.startswith('load_')
})
SAVE_FUNCS.extend([
    func
    for name, func in globals().items()
    if name.startswith('save_')
])
