"""Use pseudo-entities to make creating editoritems data more easily."""
from __future__ import annotations

from typing import Callable, Iterator, Dict
from srctools import Matrix, Angle, Vec, logger, conv_int
from srctools.vmf import VMF, Entity, ValidKVs

from editoritems import Item, ConnSide, AntlinePoint, Coord


LOGGER = logger.get_logger(__name__)
LOAD_FUNCS: dict[str, Callable[[Item, Entity], None]] = {}
SaveResult = Iterator[Dict[str, ValidKVs]]
SAVE_FUNCS: list[tuple[str, Callable[[Item], SaveResult]]] = []


def load(item: Item, vmf: VMF) -> None:
    """Search the map for important entities, and apply it to the item."""
    with logger.context(item.id):
        for ent in vmf.entities:
            try:
                func = LOAD_FUNCS[ent['classname'].casefold()]
            except KeyError:
                LOGGER.warning('Unknown item configuration entity "{}"!', ent['classname'])
            else:
                func(item, ent)


def save(item: Item) -> VMF:
    """Export out relevant item options into a VMF."""
    vmf = VMF()
    with logger.context(item.id):
        for ent_class, func in SAVE_FUNCS:
            for ent_data in func(item):
                vmf.create_ent(ent_class, **ent_data)
    return vmf


SKIN_TO_CONN_OFFSETS = {
    # Skin -> antline offset.
    '1': Vec(+0.5, +0.5),
    '2': Vec(+0.5, -0.5),
    '3': Vec(-0.5, +0.5),
    '4': Vec(-0.5, -0.5),
}
# Opposite transform.
CONN_OFFSET_TO_SKIN = {
    (2 * vec).as_tuple(): skin
    for skin, vec in SKIN_TO_CONN_OFFSETS.items()
}


def load_connectionpoint(item: Item, ent: Entity) -> None:
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
    ant_pos = Coord(round(center.x + offset.x), round(center.y + offset.y), 0)
    sign_pos = Coord(round(center.x - offset.x), round(center.y - offset.y), 0)

    group_str = ent['group_id']

    item.antline_points[side].append(AntlinePoint(
        ant_pos,
        sign_pos,
        conv_int(ent['priority']),
        int(group_str) if group_str.strip() else None
    ))


def save_connectionpoint(item: Item) -> SaveResult:
    """Write connectionpoints to a VMF."""
    for side, points in item.antline_points.items():
        yaw = side.yaw
        orient = Matrix.from_yaw(yaw)
        inv_orient = Matrix.from_yaw(-yaw)
        for point in points:
            ant_pos = Vec(point.pos.x, -point.pos.y, -64)
            sign_pos = Vec(point.sign_off.x, -point.sign_off.y, -64)

            offset = (ant_pos - sign_pos) @ inv_orient
            offset.x = -offset.x
            try:
                skin = CONN_OFFSET_TO_SKIN[offset.as_tuple()]
            except KeyError:
                LOGGER.warning('Pos=({}), Sign=({}) -> ({}) is not a valid offset for signs!', point.pos, point.sign_off, offset)
                continue
            pos: Vec = round((ant_pos + sign_pos) / 2.0 * 16.0, 0)

            yield {
                'origin': Vec(pos.x - 56, pos.y + 56, -64),
                'angles': f'0 {yaw} 0',
                'skin': skin,
                'priority': point.priority,
                'group_id': '' if point.group is None else point.group,
            }


def save_occupied_subvoxel(item: Item) -> SaveResult:
    """Save occupied subvoxel volumes."""
    for voxel in item.occupy_voxels:
        if voxel.subpos is not None and voxel.normal is None:
            pos = Vec(voxel.pos) * 128 + Vec(voxel.subpos) * 32 - (48, 48, 48)
            pos.y = -pos.y
            yield {
                'origin': pos,
                'coll_type': str(voxel.type).replace('COLLIDE_', ''),
                'coll_against': str(voxel.against).replace('COLLIDE_', ''),
            }


def save_occupied_voxel(item: Item) -> SaveResult:
    """Save occupied full-voxel volumes."""
    for voxel in item.occupy_voxels:
        if voxel.subpos is None and voxel.normal is None:
            pos = Vec(voxel.pos) * 128
            pos.y = -pos.y
            yield {
                'origin': pos,
                'coll_type': str(voxel.type).replace('COLLIDE_', ''),
                'coll_against': str(voxel.against).replace('COLLIDE_', ''),
            }


LOAD_FUNCS.update({
    'bee2_editor' + name[4:]: func
    for name, func in globals().items()
    if name.startswith('load_')
})
SAVE_FUNCS.extend([
    ('bee2_editor' + name[4:], func)
    for name, func in globals().items()
    if name.startswith('save_')
])
