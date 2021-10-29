"""Use pseudo-entities to make creating editoritems data more easily."""
from __future__ import annotations
from typing import Callable, Iterator
from srctools import Matrix, Angle, Vec, logger, conv_int
from srctools.vmf import VMF, Entity, ValidKVs

from editoritems import Item, ConnSide, AntlinePoint, Coord


LOGGER = logger.get_logger(__name__)
LOAD_FUNCS: dict[str, Callable[[Item, Entity], None]] = {}
SAVE_FUNCS: list[tuple[str, Callable[[Item], Iterator[dict[str, ValidKVs]]]]] = []


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


CONNECTION_OFFSETS = {
    # Skin -> antline offset.
    '1': Vec(+0.5, +0.5),
    '2': Vec(+0.5, -0.5),
    '3': Vec(-0.5, +0.5),
    '4': Vec(-0.5, -0.5),
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
        offset = CONNECTION_OFFSETS[ent['skin']] @ orient
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
