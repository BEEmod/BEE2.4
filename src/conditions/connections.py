"""Results relating to item connections."""
from typing import List, Dict, Iterable, Set

import connections
import srctools.logger
import conditions
import comp_consts as consts
from srctools import Property, Entity, Output, VMF, Vec
from srctools.vmf import make_overlay, Side


COND_MOD_NAME = 'I/O'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.connections')


@conditions.make_result_setup('AddOutput')
def res_add_output_setup(res: Property):
    output = res['output']
    input_name = res['input']
    inst_in = res['inst_in', '']
    inst_out = res['inst_out', '']
    targ = res['target', '']
    only_once = srctools.conv_bool(res['only_once', None])
    times = 1 if only_once else srctools.conv_int(res['times', None], -1)
    delay = res['delay', '0.0']
    parm = res['parm', '']

    if output.startswith('<') and output.endswith('>'):
        out_id, out_type = output.strip('<>').split(':', 1)
        out_id = out_id.casefold()
        out_type = out_type.strip().casefold()
    else:
        out_id = output
        out_type = 'const'

    return (
        out_type,
        out_id,
        targ,
        input_name,
        parm,
        delay,
        times,
        inst_in,
        inst_out,
    )


@conditions.make_result('AddOutput')
def res_add_output(inst: Entity, res: Property):
    """Add an output from an instance to a global or local name.

    Values:
    - `output`: The output name. Can be `<ITEM_ID:activate>` or `<ITEM_ID:deactivate>`
      to lookup that item type.
    - `target`: The name of the target entity
    - `input`: The input to give
    - `parm`: Parameters for the input
    - `delay`: Delay for the output
    - `only_once`: True to make the input last only once (overrides times)
    - `times`: The number of times to trigger the input
    """
    (
        out_type,
        out_id,
        targ,
        input_name,
        parm,
        delay,
        times,
        inst_in,
        inst_out,
    ) = res.value

    if out_type in ('activate', 'deactivate'):
        try:
            item_type = connections.ITEM_TYPES[out_id.casefold()]
        except KeyError:
            LOGGER.warning('"{}" has no connections!', out_id)
            return
        if out_type[0] == 'a':
            if item_type.output_act is None:
                return

            inst_out, output = item_type.output_act
        else:
            if item_type.output_deact is None:
                return
            inst_out, output = item_type.output_deact
    else:
        output = conditions.resolve_value(inst, out_id)
        inst_out = conditions.resolve_value(inst, inst_out)

    inst.add_out(Output(
        conditions.resolve_value(inst, output),
        conditions.local_name(inst, conditions.resolve_value(inst, targ)) or inst['targetname'],
        conditions.resolve_value(inst, input_name),
        conditions.resolve_value(inst, parm),
        srctools.conv_float(conditions.resolve_value(inst, delay)),
        times=times,
        inst_out=conditions.resolve_value(inst, inst_out) or None,
        inst_in=conditions.resolve_value(inst, inst_in) or None,
    ))


@conditions.make_result('MarkLocking')
def res_locking_output() -> None:
    """This result is no longer used."""
    LOGGER.warning('MarkLocking is no longer used. Configure locking items in the enhanced editoritems configuration.')


@conditions.make_flag('LockingIO')
def res_locking_input() -> bool:
    """This flag is no longer used."""
    LOGGER.warning('LockingIO is no longer used. Configure locking items in the enhanced editoritems configuration.')
    return False


CORNER_POS = [
    Vec(8, 56, -64),
    Vec(8, 40, -64),
    Vec(8, 24, -64),
    Vec(8, 8, -64),
    Vec(-8, 56, -64),
    Vec(-8, 40, -64),
    Vec(-8, 24, -64),
    Vec(-8, 8, -64),
]


class Corner:
    """Antline Corner item."""
    def __init__(self, item: connections.Item, pos: Vec):
        self.item = item
        self.pos = pos
        self.normal = Vec(z=1).rotate_by_str(item.inst['angles'])


def get_surf_faces(normal: Vec, start: Vec, end: Vec) -> Set[Side]:
    """Get the brush face between two positions."""
    faces = set()
    axis_norm = normal.axis()
    axis_u, axis_v = Vec.INV_AXIS[axis_norm]

    # Snap to center of the block.
    start[axis_u] = start[axis_u] // 128 * 128 + 64
    start[axis_v] = start[axis_v] // 128 * 128 + 64
    end[axis_u]   = end[axis_u]   // 128 * 128 + 64
    end[axis_v]   = end[axis_v]   // 128 * 128 + 64

    for pos in start.iter_line(end, 128):
        try:
            group = conditions.SOLIDS[pos.as_tuple()]
        except KeyError:
            continue
        faces.add(group.face)

    return faces


def create_antline_corner(
    vmf: VMF,
    normal: Vec,
    pos: Vec,
) -> Entity:
    """Construct an antline corner at this position."""
    axis_norm = normal.axis()
    axis_u, axis_v = Vec.INV_AXIS[axis_norm]

    return make_overlay(
        vmf,
        normal,
        pos,
        Vec.with_axes(axis_u, 16),
        Vec.with_axes(axis_v, 16),
        consts.Antlines.CORNER,
        # 'signage/indicator_lights/indicator_neon_straight',
        get_surf_faces(normal, pos, pos),
    )


def create_antline_straight(
    vmf: VMF,
    normal: Vec,
    start: Vec,
    end: Vec,
) -> Entity:
    """Construct a straight antline between two points.

    The two points will be the centers of the antlines.
    """
    offset = start - end
    forward = offset.norm()
    side = Vec.cross(normal, forward).norm()

    vmf.create_ent('info_null', origin=start)
    vmf.create_ent('info_null', origin=end)

    length = offset.mag() + 16

    return make_overlay(
        vmf,
        normal,
        (start + end) / 2,
        length * forward,
        16 * side,
        consts.Antlines.STRAIGHT,
        get_surf_faces(normal, start, end),
        u_repeat=length // 4,
    )


@conditions.meta_cond(-900)
def antline_layouter(vmf: VMF) -> None:
    """Implements the Antline Corner item."""
    try:
        corner_type = connections.ITEM_TYPES['item_bee2_antline_corner']
    except KeyError:
        # Item not installed.
        return

    corners = {}  # type: Dict[str, Corner]

    for item in connections.ITEMS.values():
        if item.item_type is not corner_type:
            continue

        timer_delay = item.inst.fixup.int('$timer_delay')
        # We treat inf, 1, 2 and 3 as the same, to get around the 1/2 not
        # being selectable issue.
        pos = CORNER_POS[max(0, timer_delay - 3) % 8].copy()
        pos.localise(
            Vec.from_str(item.inst['origin']),
            Vec.from_str(item.inst['angles']),
        )
        corners[item.name] = corn = Corner(item, pos)

        # Antline corners go at the start of antlines, but not at the end.
        create_antline_corner(vmf, corn.normal, pos)

        u, v = Vec.INV_AXIS[corn.normal.axis()]
        for offset in [
            Vec.with_axes(u, -16),
            Vec.with_axes(u, 16),
            Vec.with_axes(v, -16),
            Vec.with_axes(v, 16),
        ]:
            create_antline_straight(vmf, corn.normal, pos + offset, pos + 8*offset)

