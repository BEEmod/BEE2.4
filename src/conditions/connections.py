"""Results relating to item connections."""
import srctools.logger
import connections
from conditions import (
    make_flag, make_result, make_result_setup,
    resolve_value, local_name,
)
from srctools import Property, Entity, Output

COND_MOD_NAME = 'I/O'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.connections')


@make_result_setup('AddOutput')
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


@make_result('AddOutput')
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
        output = resolve_value(inst, out_id)
        inst_out = resolve_value(inst, inst_out)

    inst.add_out(Output(
        resolve_value(inst, output),
        local_name(inst, resolve_value(inst, targ)) or inst['targetname'],
        resolve_value(inst, input_name),
        resolve_value(inst, parm),
        srctools.conv_float(resolve_value(inst, delay)),
        times=times,
        inst_out=resolve_value(inst, inst_out) or None,
        inst_in=resolve_value(inst, inst_in) or None,
    ))


@make_result('MarkLocking')
def res_locking_output():
    """This result is no longer used."""
    LOGGER.warning('MarkLocking is no longer used. Configure locking items in the enhanced editoritems configuration.')


@make_flag('LockingIO')
def res_locking_input():
    """This flag is no longer used."""
    LOGGER.warning('LockingIO is no longer used. Configure locking items in the enhanced editoritems configuration.')
    return False

