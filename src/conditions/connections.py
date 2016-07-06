"""Results relating to item connections."""
import srctools
from conditions import make_result, make_result_setup, resolve_value
from srctools import Property, Entity, Output


@make_result_setup('AddOutput')
def res_add_output_setup(res):
    output = res['output']
    input_name = res['input']
    inst_in = res['inst_out', '']
    inst_out = res['inst_out', '']
    targ = res['target']
    only_once = srctools.conv_bool(res['only_once', None])
    times = 1 if only_once else srctools.conv_int(res['times', None], -1)
    delay = res['delay', '0.0']
    parm = res['parm', '']

    return (
        output,
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
    """Add an output from an instance to a global name.

    Values:
    - target: The name of the target entity
    - input: The input to give
    - parm: Parameters for the input
    - delay: Delay for the output
    - only_once: True to make the input last only once (overrides times)
    - times: The number of times to trigger the input
    """
    (
        output,
        targ,
        input_name,
        parm,
        delay,
        times,
        inst_in,
        inst_out,
    ) = res.value

    inst.add_out(Output(
        resolve_value(inst, output),
        resolve_value(inst, targ),
        resolve_value(inst, input_name),
        resolve_value(inst, parm),
        srctools.conv_float(resolve_value(inst, delay)),
        times=times,
        inst_out=resolve_value(inst, inst_out),
        inst_in=resolve_value(inst, inst_in),
    ))
