"""Controls placing custom barrier (glass/grating) items."""
from typing import Any, Literal, assert_never

from srctools import FrozenVec, Keyvalues, Vec, VMF, Entity, Output
import srctools.logger

import utils
from precomp import conditions, connections, barriers
import consts
import user_errors


COND_MOD_NAME = 'Glass / Grating Barriers'

LOGGER = srctools.logger.get_logger(__name__)

# For each direction, the positions of the func_breakable_surf keyvalues.
MIN: Literal[-1] = -1
MAX: Literal[1] = 1
Direction = Literal[-1, 0, 1]
CORNER_NAMES = ['lowerleft', 'lowerright', 'upperleft', 'upperright']
CORNER_POINTS: dict[FrozenVec, list[tuple[Direction, Direction, Direction]]] = {
    Vec.N: [
        (MIN, 0, MIN),
        (MAX, 0, MIN),
        (MIN, 0, MAX),
        (MAX, 0, MAX),
    ],
    Vec.S: [
        (MAX, 0, MIN),
        (MIN, 0, MIN),
        (MAX, 0, MAX),
        (MIN, 0, MAX),
    ],
    Vec.E: [
        (0, MAX, MIN),
        (0, MIN, MIN),
        (0, MAX, MAX),
        (0, MIN, MAX),
    ],
    Vec.W: [
        (0, MIN, MIN),
        (0, MAX, MIN),
        (0, MIN, MAX),
        (0, MAX, MAX),
    ],
    Vec.T: [
        (MIN, MIN, 0),
        (MIN, MAX, 0),
        (MAX, MIN, 0),
        (MAX, MAX, 0),
    ],
    Vec.B: [
        (MIN, MAX, 0),
        (MIN, MIN, 0),
        (MAX, MAX, 0),
        (MAX, MIN, 0),
    ]
}


@conditions.make_result('CustomBarrier')
def res_cust_barrier(inst: Entity, res: Keyvalues) -> None:
    """Convert regular glass/grating into a custom barrier type.

    The parameter is just the ID of the barrier type to produce.
    The item this executes on needs to have an output which is connected to a glass/grating item.
    """
    try:
        barrier_type = barriers.BARRIER_TYPES[utils.obj_id(res.value)]
    except KeyError as exc:
        raise user_errors.UserError(
            user_errors.TOK_UNKNOWN_ID.format(kind='Barrier Type', id=res.value)
        ) from exc

    try:
        cust_item = connections.ITEMS[inst['targetname']]
    except KeyError as exc:
        raise user_errors.UserError(
            user_errors.TOK_NO_CONNECTION_ITEM.format(inst=inst['file']),
            points=[Vec.from_str(inst['origin'])],
        ) from exc
    cust_item.delete_antlines()
    barrier: barriers.Barrier | None = None
    for conn in list(cust_item.outputs):
        targ_item = conn.to_item
        conn.remove()
        try:
            gls_barrier = barriers.BARRIERS_BY_NAME.pop(targ_item.name)
        except KeyError as exc:
            raise user_errors.UserError(
                user_errors.TOK_WRONG_ITEM_TYPE.format(
                    item=targ_item.config.id,
                    kind=user_errors.TOK_BARRIER_ITEMNAME,
                    inst=inst['file'],
                    points=[Vec.from_str(inst['origin'])],
                )
            ) from exc
        # Transfer over connections.
        targ_item.transfer_antlines(cust_item)
        for gls_conn in list(targ_item.outputs):
            gls_conn.from_item = cust_item
        for gls_conn in list(targ_item.inputs):
            gls_conn.to_item = cust_item

        # If None, this is the first glass item, and we want to edit inplace.
        # Otherwise, we want to go overwrite everywhere this item is.
        if barrier is None:
            barrier = gls_barrier
            barrier.type = barrier_type
            barrier.item = cust_item
            barrier.name = cust_item.name
            barriers.BARRIERS_BY_NAME[cust_item.name] = barrier
        else:
            # Check each location first, because it could have been changed to
            # something else.
            barrier.instances.extend(gls_barrier.instances)
            for slice_key, start_u, start_v in gls_barrier.original_voxels:
                plane = barriers.BARRIERS[slice_key]
                for u in range(start_u, start_u + 4):
                    for v in range(start_v, start_v + 4):
                        if plane[u, v] is gls_barrier:
                            plane[u, v] = barrier


# TODO: Reimplement
def res_breakable_glass(vmf: VMF, inst: Entity, res: Keyvalues) -> object:
    """Adds breakable glass to the map.

    Parameters:

    * `thickness`: Thickness of the collision brushes.
    * `offset`: Distance into the block to place the surface.
    * `border_size`: Distance on borders to inset by (so the shatter effects
          appear on the border.)
    * `material`: Name of the func_breakable_surf material.
    """
    glass_items: Any = ...

    damage_filter: Entity | None = None

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
        solid_min += conf['offset'] * norm
        solid_max += (conf['offset'] + 1) * norm

        surf_solid = vmf.make_prism(solid_min, solid_max).solid
        for face in surf_solid:
            if face.normal() == norm:
                conf['template'].apply(face, change_mat=True)

        breakable_surf = vmf.create_ent(
            classname='func_breakable_surf',
            targetname=targ + '-surf',
            spawnflags=1,  # 'Physics damage decals
            drawinfastreflection=1,
            # propdata=24,  # Glass.Window
            health=20,
            performancemode=2,  # Full gibs on all platforms
            surfacetype=0,  # Glass
            fragility=30,  # Lower fragility, so less shatters with collisions.

            error=0,  # Our corners are fine..
        )
        breakable_surf.solids.append(surf_solid)
        solid_min += norm
        solid_max -= norm

        # func_breakable_surf allows several P2 things to pass through.
        # Place a thin func_breakable inside the surf to block collisions.
        # Since it's inside, the surf will recieve physics impacts to
        # destroy it. This recieves explosive impacts.
        clip_min = bbox_min.copy()
        clip_max = bbox_max.copy()
        clip_min[uaxis] -= 64
        clip_min[vaxis] -= 64
        clip_max[uaxis] += 64
        clip_max[vaxis] += 64
        clip_min += (conf['offset'] + 0.3) * norm
        clip_max += (conf['offset'] + 0.6) * norm

        if damage_filter is None:
            damage_filter = vmf.create_ent(
                'filter_damage_type',
                # BURN = 8
                # BLAST = 64
                damagetype=64,
                targetname='@brk_glass_filter',
                origin=bbox_min - 32 * norm,
            )

        clip = vmf.create_ent(
            targetname=targ + '-clip',
            classname='func_breakable',
            # Make sure it's inside the map.
            origin=bbox_min - 32 * norm,
            spawnflags=3072,  # No physics damage, no bullet penetration
            damagefilter='@brk_glass_filter',
            material=0,  # Glass
            health=10,
        )
        clip.solids.append(
            vmf.make_prism(
                clip_min,
                clip_max,
                mat=consts.Tools.NODRAW,
            ).solid
        )

        breakable_surf.add_out(
            Output('OnBreak', targ + '-clip', 'Kill', only_once=True),
        )
        clip.add_out(
            Output('OnBreak', targ + '-surf', 'Shatter', '.5 .5 0', only_once=True),
        )

        # We need to set "lowerleft", "upperright" etc keyvalues to the corner
        # locations.
        # These are used to place the shattered glass, when it breaks.
        for name, points in zip(CORNER_NAMES, CORNER_POINTS[norm.freeze()], strict=True):
            corner = Vec()
            for ind, axis_type in enumerate(points):
                if axis_type == 0:  # solid_min is aligned to the front.
                    corner[ind] = solid_min[ind]
                elif axis_type == MAX:
                    corner[ind] = solid_max[ind]
                elif axis_type == MIN:
                    corner[ind] = solid_min[ind]
                else:
                    assert_never(axis_type)
            breakable_surf[name] = corner

    return conditions.RES_EXHAUSTED
