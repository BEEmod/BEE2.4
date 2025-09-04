"""Results relating to item connections."""
from collections.abc import Callable

import utils
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
      to look up the output from that item type. (This is unrelated to instance lookups.)
    - `target`: The name of the target entity, local to the instance (if not starting
      with `@` or `!`). If the target is blank, it is fired directly at the instance. That
      is only useful if [`replaceInstance`](#replaceInstance) has been used to convert the
      instance into another entity.
    - `input`: The input to give.
    - `parm`: Parameters for the input.
    - `delay`: Delay for the output.
    - `only_once`: True to make the input last only once (overrides times).
    - `times`: The number of times to trigger the input.
    """
    conf_output = res['output']
    input_name = res['input']
    inst_in = res['inst_in', '']
    conf_inst_out = res['inst_out', '']
    targ = res['target', '']
    only_once = res.bool('only_once')
    times = 1 if only_once else res.int('times', -1)
    delay = res['delay', '0.0']
    parm = res['parm', '']

    out_type: str | None
    if conf_output.startswith('<') and conf_output.endswith('>'):
        out_id_str, out_type = conf_output.strip('<>').split(':', 1)
        out_id = utils.obj_id(out_id_str, 'item')
        out_type = out_type.strip().casefold()
    else:
        out_id = utils.obj_id(conf_output, 'item')
        out_type = None

    def add_output(inst: Entity) -> None:
        """Add the output."""
        if out_type in ('activate', 'deactivate'):
            try:
                item_type = connections.ITEM_TYPES[out_id]
            except KeyError:
                LOGGER.warning('"{}" has no connections!', out_id)
                return
            if out_type == 'activate':
                if item_type.output_act is None:
                    LOGGER.warning('"{}" has no activation output!', out_id)
                    return

                inst_out, output = item_type.output_act
            else:
                if item_type.output_deact is None:
                    LOGGER.warning('"{}" has no deactivation output!', out_id)
                    return
                inst_out, output = item_type.output_deact
        elif out_type is None:
            output = out_id
            inst_out = conf_inst_out
        else:
            LOGGER.warning(
                'Unknown output type "{}", expected "activate" or "deactivate"!',
                out_type,
            )
            return

        inst.add_out(Output(
            inst.fixup.substitute(output),
            conditions.local_name(inst, inst.fixup.substitute(targ)) or inst['targetname'],
            inst.fixup.substitute(input_name),
            inst.fixup.substitute(parm),
            srctools.conv_float(inst.fixup.substitute(delay)),
            times=times,
            inst_out=inst.fixup.substitute(inst_out) if inst_out else None,
            inst_in=inst.fixup.substitute(inst_in) if inst_in else None,
        ))
    return add_output


@conditions.make_result('ChangeIOType', valid_before=conditions.MetaCond.Connections)
def res_change_io_type(kv: Keyvalues) -> Callable[[Entity], None]:
    """Switch an item to use different inputs or outputs.

    The contents are the same as that allowed in the input BEE2 block in
    editoritems.
    """
    conf = connections.Config.parse(utils.special_id(f'<ChangeIOType: {id(kv):X}>'), kv)

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


@conditions.make_result('AppendConnInputs', valid_before=conditions.MetaCond.Connections)
def res_append_io_type(res: Keyvalues) -> Callable[[Entity], None]:
    """Append additional outputs to an item's connections, which are fired when inputs change.

    This has the same format of the editoritems BEE2 block,
    but only accepts any number of the following:
    - `enable_cmd`
    - `disable_cmd`
    - `sec_enable_cmd`
    - `sec_disable_cmd`
    """
    prop_lists: dict[str, list[Output]] = {
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
