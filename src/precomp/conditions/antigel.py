"""Implements the antigel marker item."""
from srctools import VMF, Vec, Matrix, FrozenVec
import attrs
from srctools.logger import get_logger

import user_errors
import utils
from precomp import conditions, connections, instanceLocs, texturing
from transtoken import TransToken


@attrs.frozen
class Marker:
    """A marker item."""
    item: connections.Item
    grid_pos: FrozenVec  # Original marker voxel.
    set_voxel: bool  # Whether to change the voxel.
    normal: FrozenVec | None  # If set, also apply to surfaces.

    def apply(self, grid_pos: FrozenVec) -> None:
        """Modify the specified location."""
        if self.set_voxel:
            texturing.ANTIGEL_LOCS.add(grid_pos)
        if self.normal is not None:
            # Only place if along the same plane as our marker.
            if abs(self.normal.dot(self.grid_pos) - self.normal.dot(grid_pos)) < 0.25:
                texturing.ANTIGEL_BY_NORMAL[self.normal].add(grid_pos - self.normal)


LOGGER = get_logger(__name__)
COND_MOD_NAME: str | None = None
PACKAGE_ID = utils.special_id('BEE2_BLOCKS')


@conditions.make_result('MarkAntigel', valid_before=conditions.MetaCond.Connections)
def res_antigel(vmf: VMF) -> object:
    """Implement the Antigel marker.

    This has no configuration, and is run once to modify all markers.
    """
    markers: dict[str, Marker] = {}

    inst_filter = instanceLocs.resolve_filter('<ITEM_BEE2_ANTIGEL_MARKER>', silent=True)
    if not inst_filter:
        return conditions.RES_EXHAUSTED

    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in inst_filter:
            continue
        inst.remove()
        origin = FrozenVec.from_str(inst['origin'])
        orient = Matrix.from_angstr(inst['angles'])
        norm: FrozenVec | None = FrozenVec(round(orient.up(), 6))
        grid_pos = origin // 128
        match inst.fixup['$cube_type']:
            case '0':
                set_voxel = True
            case '1':
                set_voxel = False
            case '2':
                set_voxel = True
                norm = None
            case '3' | '4':
                raise user_errors.UserError(
                    TransToken(PACKAGE_ID, PACKAGE_ID, 'BAD_ANTIGEL_CUBE_TYPE', {}),
                    voxels=[origin],
                )
            case invalid:
                raise ValueError(f'Invalid cube type "{invalid}"!')
        item = connections.ITEMS[inst['targetname'].casefold()]
        item.delete_antlines()
        markers[item.name] = mark = Marker(item, grid_pos, set_voxel, norm)
        mark.apply(grid_pos)

    for inst_name, marker_a in markers.items():
        for out in list(marker_a.item.outputs):
            try:
                marker_b = markers[out.to_item.name]
            except KeyError as exc:
                raise user_errors.UserError(
                    TransToken(PACKAGE_ID, PACKAGE_ID, 'BAD_ANTIGEL_OUTPUT_ITEM', {}),
                    voxels=[
                        Vec.from_str(marker_a.item.inst['origin']),
                        Vec.from_str(out.to_item.inst['origin']),
                    ]
                ) from exc
            out.remove()
            bbox_min, bbox_max = FrozenVec.bbox(marker_a.grid_pos, marker_b.grid_pos)
            for pos in FrozenVec.iter_grid(bbox_min, bbox_max, 1):
                marker_a.apply(pos)
                marker_b.apply(pos)

    export_antigel_pos(vmf)
    return conditions.RES_EXHAUSTED


def export_antigel_pos(vmf: VMF) -> None:
    """Export ents to identify antigel locations."""
    add_debug = conditions.fetch_debug_visgroup(vmf, 'AntiGel')

    for pos in texturing.ANTIGEL_LOCS:
        add_debug(
            'info_target',
            origin=pos * 128 + (64, 64, 64),
        )
    for norm, locs in texturing.ANTIGEL_BY_NORMAL.items():
        ang = norm.to_angle()
        for pos in locs:
            add_debug(
                'info_particle_system',
                origin=pos * 128 + (64, 64, 64),
                angles=ang,
            )
