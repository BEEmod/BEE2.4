"""Results relating to item connections."""
from typing import List

import connections
import srctools.logger
import conditions
from srctools import Property, Entity, Output, VMF, Vec


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


@conditions.meta_cond(-900)
def antline_layouter(vmf: VMF) -> None:
    """Implements the Antline Corner item."""
    try:
        corner_type = connections.ITEM_TYPES['item_bee2_antline_corner']
    except KeyError:
        # Item not installed.
        return

    corners = []  # type: List[Corner]

    for item in connections.ITEMS.values():
        if item.item_type is corner_type:
            timer_delay = item.inst.fixup.int('$timer_delay')
            pos = CORNER_POS[max(0, timer_delay - 3) % 8].copy()
            pos.localise(
                Vec.from_str(item.inst['origin']),
                Vec.from_str(item.inst['angles']),
            )
            corners.append(Corner(item, pos))

