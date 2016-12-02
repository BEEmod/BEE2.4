"""Adds breakable glass."""
from conditions import make_result_setup, make_result, RES_EXHAUSTED
from instanceLocs import resolve as resolve_inst
from srctools import Property, Vec, Entity, Solid, Side, VMF

import utils

from typing import Iterator, Any, Tuple, Dict, List

LOGGER = utils.getLogger(__name__)

BREAKABLE_GLASS_CONF = {}

# For each direction, whether min/max
CORNER_NAMES = ['lowerleft', 'lowerright', 'upperleft', 'upperright']
CORNER_POINTS = {
    Vec.N: [
        (min, 0, min),
        (max, 0, min),
        (min, 0, max),
        (max, 0, max),
    ],
    Vec.S: [
        (max, 0, min),
        (min, 0, min),
        (max, 0, max),
        (min, 0, max),
    ],
    Vec.E: [
        (0, max, min),
        (0, min, min),
        (0, max, max),
        (0, min, max),
    ],
    Vec.W: [
        (0, min, min),
        (0, max, min),
        (0, min, max),
        (0, max, max),
    ],
    Vec.T: [
        (min, min, 0),
        (min, max, 0),
        (max, min, 0),
        (max, max, 0),
    ],
    Vec.B: [
        (min, max, 0),
        (min, min, 0),
        (max, max, 0),
        (max, min, 0),
    ]
}  # type: Dict[Tuple[float, float, float], List[Tuple[Any, Any, Any]]]

def glass_item_setup(conf, item_id, config_dict):
    [base_inst] = resolve_inst('<{}:0>'.format(item_id))
    config_dict[base_inst.casefold()] = conf


def find_glass_items(config, vmf: VMF) -> Iterator[Tuple[str, Vec, Vec, Vec, dict]]:
    # targetname -> min, max, normal, config
    glass_items = {}
    for inst in vmf.by_class['func_instance']:  # type: Entity
        try:
            conf = BREAKABLE_GLASS_CONF[inst['file'].casefold()]
        except KeyError:
            continue
        targ = inst['targetname']
        norm = Vec(x=-1).rotate_by_str(inst['angles'])
        origin = Vec.from_str(inst['origin']) + 64 * norm
        try:
            bbox_min, bbox_max, group_norm, group_conf = glass_items[targ]
        except KeyError:
            # First of this group..
            bbox_min, bbox_max = origin.copy(), origin.copy()
            group_norm = norm.copy()
            glass_items[targ] = bbox_min, bbox_max, group_norm, conf
        else:
            bbox_min.min(origin)
            bbox_max.max(origin)
            assert group_norm == norm, '"{}" is inconsistently rotated!'.format(targ)
            assert group_conf is conf, '"{}" has multiple configs!'.format(targ)
        inst.remove()

    for targ, (bbox_min, bbox_max, norm, conf) in glass_items.items():
        yield targ, bbox_min, bbox_max, norm, conf



@make_result_setup('BreakableGlass')
def res_breakable_glass_setup(res: Property):
    item_id = res['item']
    conf = {
        name: resolve_inst('<{}:bee2_frame_{}>'.format(item_id, name))[0]
        for name in ['edge', 'single', 'ubend', 'corner', 'double']
    }
    conf['material'] = res['material']
    conf['offset'] = abs(res.float('offset', 0.5))
    # Distance inward from the frames the glass should span.
    conf['border_size'] = abs(res.float('border_size', 0))

    glass_item_setup(conf, item_id, BREAKABLE_GLASS_CONF)

    return res.value


@make_result('BreakableGlass')
def res_breakable_glass(inst: Entity, res: Property):
    vmf = inst.map

    glass_items = find_glass_items(BREAKABLE_GLASS_CONF, vmf)

    for targ, bbox_min, bbox_max, norm, conf in glass_items:
        LOGGER.info('Making glass "{}"', targ)
        norm_axis = norm.axis()
        uaxis, vaxis = Vec.INV_AXIS[norm_axis]
        solid_min = bbox_min.copy()
        solid_max = bbox_max.copy()
        uv_off = 64 - conf['border_size']
        solid_min[uaxis] -= uv_off
        solid_min[vaxis] -= uv_off
        solid_max[uaxis] += uv_off
        solid_max[vaxis] += uv_off

        # This doesn't choose min/max correctly, but that's fine.
        solid_min -= 1 * norm
        solid_max -= 0.5 * norm

        solid = vmf.make_prism(  # type: Solid
            solid_min, solid_max,
        ).solid
        for face in solid:  # type: Side
            if face.normal() == norm:
                face.mat = conf['material']

        breakable_surf = vmf.create_ent(
            classname='func_breakable_surf',
            targetname=targ,
            spawnflags=3,  # 'Physics damage decals, and take damage from held
            drawinfastreflection=1,
            propdata=24,  # Glass.Window
            performancemode=2,  # Full gibs on all platforms
            surfacetype=0,  # Glass
            fragility=100,  # Amount of damage  shattered fragments can take.
            health=1,
        )
        breakable_surf.solids = [solid]

        # We need to set "lowerleft", "upperright" etc keyvalues to the corner
        # locations.
        # These are used to place the shattered glass, when it breaks.
        for name, points in zip(CORNER_NAMES, CORNER_POINTS[norm.as_tuple()]):
            corner = Vec()
            for axis, axis_type in zip('xyz', points):
                if axis == norm_axis:  # solid_min is aligned to the front.
                    corner[axis] = solid_min[axis]
                elif axis_type is max:
                    corner[axis] = solid_max[axis]
                elif axis_type is min:
                    corner[axis] = solid_min[axis]
            breakable_surf[name] = corner

    return RES_EXHAUSTED
