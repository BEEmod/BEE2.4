"""Results relating to item connections."""
from typing import Callable, Dict, List

from precomp import connections, conditions
from srctools import Keyvalues, Entity, Output, logger
import srctools

COND_MOD_NAME = 'I/O'
LOGGER = logger.get_logger(__name__, alias='cond.connections')


@conditions.make_result('AddOutput')
def res_add_output(res: Keyvalues) -> Callable[[Entity], None]:
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


@conditions.make_result('ChangeIOType')
def res_change_io_type(kv: Keyvalues) -> Callable[[Entity], None]:
    """Switch an item to use different inputs or outputs.

    Must be done before priority level -250.
    The contents are the same as that allowed in the input BEE2 block in
    editoritems.
    """
    conf = connections.Config.parse(f'<ChangeIOType: {id(kv):X}>', kv)

    def change_item(inst: Entity) -> None:
        """Alter the type of each item passed in."""
        try:
            item = connections.ITEMS[inst['targetname']]
        except KeyError:
            raise ValueError(f'No item with name "{inst["targetname"]}"!') from None

        item.config = conf

        # Overwrite these as well.
        item.enable_cmd = conf.enable_cmd
        item.disable_cmd = conf.disable_cmd

        item.sec_enable_cmd = conf.sec_enable_cmd
        item.sec_disable_cmd = conf.sec_disable_cmd

    return change_item


@conditions.make_result('AppendConnInputs')
def res_append_io_type(res: Keyvalues) -> Callable[[Entity], None]:
    """Append additional outputs to an item's connections, which are fired when inputs change.

    Must be done before priority level -250. This has the same format of the editoritems BEE2 block,
    but only accepts any number of the following:
    - `enable_cmd`
    - `disable_cmd`
    - `sec_enable_cmd`
    - `sec_disable_cmd`
    """
    prop_lists: Dict[str, List[Output]] = {
        name: []
        for name in ['enable_cmd', 'disable_cmd', 'sec_enable_cmd', 'sec_disable_cmd']
    }

    for prop in res:
        try:
            lst = prop_lists[prop.name]
        except KeyError:
            raise ValueError(f'Unknown input command type "{prop.real_name}"!') from None
        prop.name = ''  # Discard this from the output.
        lst.append(Output.parse(prop))
    # Collect into tuples for appending later, discard any blanks.
    prop_tups = [
        (name, tuple(out_list))
        for name, out_list in prop_lists.items()
        if out_list
    ]
    LOGGER.info('Append inputs: {}', prop_tups)

    def append_to(inst: Entity) -> None:
        """Append inputs to the item."""
        try:
            item = connections.ITEMS[inst['targetname']]
        except KeyError:
            raise ValueError('No item with name "{}"!'.format(inst['targetname'])) from None
        # Assign item.enable_cmd += out_tup, for all of them.
        for name, out_tup in prop_tups:
            setattr(item, name, getattr(item, name) + out_tup)

    return append_to
