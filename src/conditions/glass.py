"""Adds breakable glass."""
from conditions import make_result_setup, make_result, RES_EXHAUSTED
from instanceLocs import resolve as resolve_inst
from srctools import Property, Vec, Entity, Solid

import utils

LOGGER = utils.getLogger(__name__)

BREAKABLE_GLASS_CONF = {}


@make_result_setup('BreakableGlass')
def res_breakable_glass_setup(res: Property):
    item_id = res.value
    [base_inst] = resolve_inst('<{}:0>'.format(item_id))
    BREAKABLE_GLASS_CONF[base_inst.casefold()] = {
        name: resolve_inst('<{}:bee2_frame_{}>'.format(item_id, name))[0]
        for name in ['edge', 'single', 'ubend', 'corner', 'double']
    }

    return res.value

@make_result('BreakableGlass')
def res_breakable_glass(inst: Entity, res: Property):
    vmf = inst.map

    # targetname -> min, max, normal, config
    glass_items = {}

    for inst in vmf.by_class['func_instance']:  # type: Entity
        try:
            conf = BREAKABLE_GLASS_CONF[inst['file'].casefold()]
        except KeyError:
            continue
        targ = inst['targetname']
        norm = Vec(x=1).rotate_by_str(inst['angles'])
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
        inst['classname'] = 'info_null'

    for targ, (bbox_min, bbox_max, norm, conf) in glass_items.items():
        LOGGER.info('Making glass "{}"', targ)
        norm_axis = norm.axis()
        uaxis, vaxis = Vec.INV_AXIS[norm_axis]
        solid_min = bbox_min.copy()
        solid_max = bbox_max.copy()
        solid_min[uaxis] -= 64
        solid_min[vaxis] -= 64
        solid_max[uaxis] += 64
        solid_max[vaxis] += 64

        # This doesn't choose min/max correctly, but that's fine.
        solid_min -= 1 * norm
        solid_max -= 0.5 * norm

        solid = vmf.make_prism(
            solid_min, solid_max
        )
        breakable_surf = vmf.create_ent(
            classname='func_breakable_surf',
            origin=bbox_min,
        )

    return RES_EXHAUSTED
