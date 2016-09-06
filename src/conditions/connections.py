"""Results relating to item connections."""
import srctools
import utils
from conditions import make_result, make_result_setup, resolve_value, local_name, CONNECTIONS
from srctools import Property, Entity, Output

LOGGER = utils.getLogger(__name__, alias='cond.connections')


@make_result_setup('AddOutput')
def res_add_output_setup(res):
    output = res['output']
    input_name = res['input']
    inst_in = res['inst_in', '']
    inst_out = res['inst_out', '']
    targ = res['target']
    only_once = srctools.conv_bool(res['only_once', None])
    times = 1 if only_once else srctools.conv_int(res['times', None], -1)
    delay = res['delay', '0.0']
    parm = res['parm', '']

    if output.startswith('<') and output.endswith('>'):
        out_id, out_type = output.strip('<>').split(':', 1)
        out_id = out_id.casefold()
        out_type = out_type.strip().casefold()
    else:
        out_id, out_type = output, 'const'

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
    - output: The output name.Can be <ITEM_ID:activate> or <ITEM_ID:deactivate>
      to lookup that item type.
    - target: The name of the target entity
    - input: The input to give
    - parm: Parameters for the input
    - delay: Delay for the output
    - only_once: True to make the input last only once (overrides times)
    - times: The number of times to trigger the input
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

    LOGGER.info('Conn: {}', res.value)

    if out_type in ('activate', 'deactivate'):
        try:
            connection = CONNECTIONS[out_id]
        except KeyError:
            LOGGER.warning('"{}" has no connections!', out_id)
            return
        if out_type[0] == 'a':
            inst_out, output = connection.out_act
        else:
            inst_out, output = connection.out_deact
    else:
        output = resolve_value(inst, out_id)
        inst_out = resolve_value(inst, inst_out)

    inst.add_out(Output(
        resolve_value(inst, output),
        local_name(inst, resolve_value(inst, targ)),
        resolve_value(inst, input_name),
        resolve_value(inst, parm),
        srctools.conv_float(resolve_value(inst, delay)),
        times=times,
        inst_out=resolve_value(inst, inst_out) or None,
        inst_in=resolve_value(inst, inst_in) or None,
    ))
