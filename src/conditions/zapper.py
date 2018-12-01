"""Implements the Still Alive/Flash Version electric zapper device."""
from typing import List, Tuple, Set

import conditions
import connections
import instanceLocs
import template_brush
import comp_consts as const
from srctools.logger import get_logger
from srctools import Property, VMF, Entity, Vec, Side, Solid, Output


LOGGER = get_logger(__name__, alias='cond.SAZapper')


def find_link(item: connections.Item, filenames: Set[str]):
    """Find the other marker this item is linked to.

    This ensures they are positioned correctly relative to each other.
    It also clears all the marker-only links.
    """
    possible_links = []

    for conn in list(item.outputs):
        if conn.to_item.inst['file'].casefold() in filenames:
            possible_links.append(conn.to_item)
        conn.remove()

    for conn in list(item.inputs):
        if conn.from_item.inst['file'].casefold() in filenames:
            possible_links.append(conn.from_item)
            conn.remove()

    norm_a = Vec(z=1).rotate_by_str(item.inst['angles'])
    pos_a = Vec.from_str(item.inst['origin'])

    for other_item in possible_links:
        norm_b = Vec(z=1).rotate_by_str(other_item.inst['angles'])
        pos_b = Vec.from_str(other_item.inst['origin'])

        # Facing the same way?
        if norm_a == norm_b:
            axis = norm_a.axis()

            # On the same plane?
            if pos_a[axis] == pos_b[axis]:
                return other_item

    # If the marker doesn't have any connections, 'connect'
    # it to itself so we'll generate a 128x128 section.
    return item


@conditions.make_result('SAZapper')
def res_sa_zapper(vmf: VMF, res: Property):
    """Implements the Still Alive / Flash Version zapper device."""
    inst_names = instanceLocs.resolve(res['markeritem'])
    temp_border = template_brush.get_template(res['template'])
    border_width = res.float('width', 24)
    grate_height = res.float('grate_height', 16)
    grating_mat = res['grate_mat']

    base_height = res.float('base_height', 8)
    base_mat = res['base_mat']

    if border_width >= 64:
        raise ValueError('Border width is too large!')

    markers = set()  # type: Set[connections.Item]

    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in inst_names:
            continue

        item = connections.ITEMS[inst['targetname']]
        item.delete_antlines()

        markers.add(item)

    if not markers:
        return conditions.RES_EXHAUSTED

    while markers:
        start_item = markers.pop()
        end_item = find_link(start_item, inst_names)
        markers.discard(end_item)

        # If they're two items, get rid of one of them.
        if start_item is not end_item:
            for conn in list(end_item.inputs):
                conn.from_item = start_item

            # Then destroy the other one.
            del connections.ITEMS[end_item.name]
            end_item.inst.remove()

        bbox_min, bbox_max = Vec.bbox(
            Vec.from_str(start_item.inst['origin']),
            Vec.from_str(end_item.inst['origin']),
        )
        normal = Vec(z=1).rotate_by_str(start_item.inst['angles'])
        axis_norm = normal.axis()
        axis_u, axis_v = Vec.INV_AXIS[axis_norm]

        # Now construct the brushes. We need 3:
        # - func_brush border (with FX material)
        # - func_detail grating, nodrawed border.
        # - trigger_hurt trigger
        ent_detail = vmf.create_ent('func_detail')
        ent_fx = vmf.create_ent(
            'func_brush',
            origin=bbox_min,
            solidity='1',  # Never solid.
            drawinfastreflection='1',
            targetname=conditions.local_name(start_item.inst, 'fx'),
        )

        for border_axis, border_mag in zip(
            [axis_u, axis_u, axis_v, axis_v],
            (-1, 1, -1, 1),
        ):
            border_dir = Vec.with_axes(border_axis, border_mag)
            # Compute the angle which points the template in the direction.
            border_ang = border_dir.to_angle_roll(normal)

            side_dir = Vec(y=-1).rotate(*border_ang)
            side_axis = side_dir.axis()
            beam_pos = bbox_min.copy()
            if side_dir[side_axis] > 0:
                beam_pos[side_axis] = bbox_max[side_axis]

            border_solids = template_brush.import_template(
                temp_border,
                beam_pos,
                border_ang,
                force_type=template_brush.TEMP_TYPES.world,
                add_to_map=False,
            ).world  # type: List[Solid]

            # Now translate the positive-side diagonal fact forwards,
            # so it matches up with the other side.
            border_length = bbox_max[border_axis] - bbox_min[border_axis]
            for brush in border_solids:
                for face in brush.sides:
                    if all(
                        point[border_axis] > bbox_min[border_axis]
                        for point in
                        face.planes
                    ):
                        face.translate(Vec.with_axes(border_axis, border_length))

                ent_fx.solids.append(brush)

                # Construct a duplicate func_detail, textured with nodraw.
                collision = brush.copy()
                ent_detail.solids.append(collision)
                for face in collision.sides:
                    face.mat = const.Tools.NODRAW

        def make_center_brush(
            top_off: float,
            bottom_off: float,
            top_mat: str,
        ) -> Solid:
            """Construct a brush filling the middle deadly part of the
            surface."""
            top_off -= 64
            bottom_off -= 64

            solid = vmf.make_prism(
                Vec.with_axes(
                    axis_norm,
                    bbox_min[axis_norm] + top_off * normal[axis_norm],
                    axis_u, bbox_min[axis_u] - 64 + border_width,
                    axis_v, bbox_min[axis_v] - 64 + border_width,
                ),
                Vec.with_axes(
                    axis_norm,
                    bbox_min[axis_norm] + bottom_off * normal[axis_norm],
                    axis_u, bbox_max[axis_u] + 64 - border_width,
                    axis_v, bbox_max[axis_v] + 64 - border_width,
                ),
            ).solid
            for face in solid:
                if -face.normal() == normal:
                    face.mat = top_mat
            return solid

        # Add the grating.
        ent_detail.solids.append(make_center_brush(
            grate_height,
            grate_height - 1,
            grating_mat,
        ))

        # The base brush is duplicated, so it is unpaintable.
        base_brush = make_center_brush(base_height, 0, base_mat)
        # Construct a duplicate func_detail, textured with nodraw.
        ent_fx.solids.append(base_brush.copy())
        ent_detail.solids.append(base_brush)
        for face in base_brush:
            face.mat = const.Tools.NODRAW

        # Now the trigger
        ent_trigger = vmf.create_ent(
            'trigger_hurt',
            origin=bbox_max,
            targetname=conditions.local_name(start_item.inst, 'hurt'),
            startDisabled='1',
            damage='10000',
            damagetype='256',  # SHOCK
            nodamageforce='1',
            spawnflags='1',  # Clients
        )
        trig_brush = make_center_brush(128, grate_height, const.Tools.TRIGGER)
        for face in trig_brush:
            face.mat = const.Tools.TRIGGER
        ent_trigger.solids.append(trig_brush)
        ent_trigger.add_out(Output(
            'OnHurtPlayer',
            conditions.local_name(start_item.inst, 'script'),
            'CallScriptFunction',
            'died',
        ))
        # Need to split this so Hammer doesn't blow up on the keyvalue...
        start_item.inst.fixup['$code1'] = 'inverted <- {0}; '.format(
                start_item.inst.fixup['$start_enabled'],
        )
        start_item.inst.fixup['$code2'] = (
            'bbox_min <- Vector({0.x:g}, '
            '{0.y:g}, {0.z:g}); '.format(bbox_min)
        )
        start_item.inst.fixup['$code3'] = (
            'bbox_max <- Vector({0.x:g}, '
            '{0.y:g}, {0.z:g})'.format(bbox_max)
        )

    return conditions.RES_EXHAUSTED
