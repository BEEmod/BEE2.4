"""Results relating to item connections."""
import srctools.logger
from precomp import connections, conditions
from srctools import Property, Entity, Output

COND_MOD_NAME = 'I/O'
LOGGER = srctools.logger.get_logger(__name__, alias='cond.connections')


@conditions.make_result('AddOutput')
def res_add_output(res: Property):
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
    conf_output = res['output']
    input_name = res['input']
    inst_in = res['inst_in', '']
    conf_inst_out = res['inst_out', '']
    targ = res['target', '']
    only_once = srctools.conv_bool(res['only_once', None])
    times = 1 if only_once else srctools.conv_int(res['times', None], -1)
    delay = res['delay', '0.0']
    parm = res['parm', '']

    if conf_output.startswith('<') and conf_output.endswith('>'):
        out_id, out_type = conf_output.strip('<>').split(':', 1)
        out_id = out_id.casefold()
        out_type = out_type.strip().casefold()
    else:
        out_id = conf_output
        out_type = 'const'

    def add_output(inst: Entity) -> None:
        """Add the output."""
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
            output = out_id
            inst_out = conf_inst_out

        inst.add_out(Output(
            inst.fixup.substitute(output),
            conditions.local_name(inst, inst.fixup.substitute(targ)) or inst['targetname'],
            inst.fixup.substitute(input_name),
            inst.fixup.substitute(parm),
            srctools.conv_float(inst.fixup.substitute(delay)),
            times=times,
            inst_out=inst.fixup.substitute(inst_out) or None,
            inst_in=inst.fixup.substitute(inst_in) or None,
        ))
    return add_output
