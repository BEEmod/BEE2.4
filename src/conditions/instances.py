"""Flags and Results relating to instances or instance variables.

"""
import operator

from typing import Dict, Optional, Union

import conditions
import srctools
from conditions import (
    make_flag, make_result, make_result_setup,
    ALL_INST,
)
import instanceLocs
from srctools import Property, Vec, Entity, Output, VMF


COND_MOD_NAME = 'Instances'


@make_flag('instance')
def flag_file_equal(inst: Entity, flag: Property):
    """Evaluates True if the instance matches the given file."""
    return inst['file'].casefold() in instanceLocs.resolve(flag.value)


@make_flag('instFlag', 'InstPart')
def flag_file_cont(inst: Entity, flag: Property):
    """Evaluates True if the instance contains the given portion."""
    return flag.value in inst['file'].casefold()


@make_flag('hasInst')
def flag_has_inst(flag: Property):
    """Checks if the given instance is present anywhere in the map."""
    flags = instanceLocs.resolve(flag.value)
    return any(
        inst.casefold() in flags
        for inst in
        ALL_INST
    )

INSTVAR_COMP = {
    '=': operator.eq,
    '==': operator.eq,

    '!=': operator.ne,
    '<>': operator.ne,
    '=/=': operator.ne,

    '<': operator.lt,
    '>': operator.gt,

    '>=': operator.ge,
    '=>': operator.ge,
    '<=': operator.le,
    '=<': operator.le,
}


@make_flag('instVar')
def flag_instvar(inst: Entity, flag: Property):
    """Checks if the $replace value matches the given value.

    The flag value follows the form `$start_enabled == 1`, with or without
    the `$`.
    The operator can be any of `=`, `==`, `<`, `>`, `<=`, `>=`, `!=`.
    If omitted, the operation is assumed to be `==`.
    """
    values = flag.value.split(' ', 3)
    if len(values) == 3:
        variable, op, comp_val = values
        value = inst.fixup[variable]
        try:
            # Convert to floats if possible, otherwise handle both as strings
            comp_val, value = float(comp_val), float(value)
        except ValueError:
            pass
        return INSTVAR_COMP.get(op, operator.eq)(value, comp_val)
    else:
        variable, value = values
        return inst.fixup[variable] == value


@make_result('rename', 'changeInstance')
def res_change_instance(inst: Entity, res: Property):
    """Set the file to a value."""
    inst['file'] = instanceLocs.resolve_one(res.value, error=True)


@make_result('suffix', 'instSuffix')
def res_add_suffix(inst: Entity, res: Property):
    """Add the specified suffix to the filename."""
    conditions.add_suffix(inst, '_' + res.value)


@make_result('setKey')
def res_set_key(inst: Entity, res: Property):
    """Set a keyvalue to the given value.

    The name and value should be separated by a space.
    """
    key, value = res.value.split(' ', 1)
    inst[key] = value


@make_result('instVar', 'instVarSuffix')
def res_add_inst_var(inst: Entity, res: Property):
    """Append the value of an instance variable to the filename.

    Pass either the variable name, or a set of value->suffix pairs for a
    lookup.
    """
    if res.has_children():
        val = inst.fixup[res['variable', '']]
        for rep in res:  # lookup the number to determine the appending value
            if rep.name == 'variable':
                continue  # this isn't a lookup command!
            if rep.name == val:
                conditions.add_suffix(inst, '_' + rep.value)
                break
    else:  # append the value
        conditions.add_suffix(inst, '_' + inst.fixup[res.value, ''])


@make_result('setInstVar')
def res_set_inst_var(inst: Entity, res: Property):
    """Set an instance variable to the given value.

    Values follow the format `$start_enabled 1`, with or without the `$`.
    `$out $in` will copy the value of `$in` into `$out`.
    """
    var_name, val = res.value.split(' ', 1)
    inst.fixup[var_name] = conditions.resolve_value(inst, val)


@make_result_setup('mapInstVar')
def res_map_inst_var_setup(res: Property):
    table = {}
    res_iter = iter(res)
    first_prop = next(res_iter)
    in_name, out_name = first_prop.name, first_prop.value
    for prop in res_iter:
        table[prop.real_name] = prop.value

    out = in_name, out_name, table
    return out if all(out) else None


@make_result('mapInstVar')
def res_map_inst_var(inst: Entity, res: Property):
    """Set one instance var based on the value of another.

    The first value is the in -> out var, and all following are values to map.
    """
    in_name, out_name, table = res.value  # type: str, str, dict
    try:
        inst.fixup[out_name] = table[inst.fixup[in_name]]
    except KeyError:
        pass


@make_result('clearOutputs', 'clearOutput')
def res_clear_outputs(inst: Entity):
    """Remove the outputs from an instance."""
    inst.outputs.clear()


@make_result('removeFixup', 'deleteFixup', 'removeInstVar', 'deleteInstVar')
def res_rem_fixup(inst: Entity, res: Property):
    """Remove a fixup from the instance."""
    del inst.fixup[res.value]


@make_result('localTarget')
def res_local_targetname(inst: Entity, res: Property):
    """Generate a instvar with an instance-local name.

    Useful with AddOutput commands, or other values which use
    targetnames in the parameter.
    The result takes the form `<prefix><instance name>[-<local>]<suffix>`.
    """
    local_name = res['name', '']
    if local_name:
        name = inst['targetname', ''] + '-' + local_name
    else:
        name = inst['targetname', '']
    inst.fixup[res['resultVar']] = res['prefix', ''] + name + res['suffix', '']


@make_result('replaceInstance')
def res_replace_instance(inst: Entity, res: Property):
    """Replace an instance with another entity.

    `keys` and `localkeys` defines the new keyvalues used.
    `targetname` and `angles` are preset, and `origin` will be used to offset
    the given amount from the current location.
    If keep_instance` is true, the instance entity will be kept instead of
    removed.
    """
    import vbsp

    origin = Vec.from_str(inst['origin'])
    angles = inst['angles']

    if not srctools.conv_bool(res['keep_instance', '0'], False):
        inst.remove()  # Do this first to free the ent ID, so the new ent has
        # the same one.

    # We copy to allow us to still access the $fixups and other values.
    new_ent = inst.copy(des_id=inst.id)
    new_ent.clear_keys()
    # Ensure there's a classname, just in case.
    new_ent['classname'] = 'info_null'

    vbsp.VMF.add_ent(new_ent)

    conditions.set_ent_keys(new_ent, inst, res)

    origin += Vec.from_str(new_ent['origin']).rotate_by_str(angles)
    new_ent['origin'] = origin
    new_ent['angles'] = angles
    new_ent['targetname'] = inst['targetname']


GLOBAL_INPUT_ENTS = {}  # type: Dict[Optional[str], Entity]


@make_result_setup('GlobalInput')
def res_global_input_setup(res: Property):
    target = res['target', ''] or None
    name = res['name', ''] or None
    output = res['output', 'OnTrigger']
    param = res['param', '']
    delay = srctools.conv_float(res['delay', ''])
    inp_name, inp_command = Output.parse_name(res['input'])

    return name, inp_name, inp_command, output, delay, param, target


@make_result('GlobalInput')
def res_global_input(vmf: VMF, inst: Entity, res: Property):
    """Trigger an input either on map spawn, or when a relay is triggered.

    Arguments:  
    
    - `Input`: the input to use, either a name or an `instance:` command.
    - `Target`: If set, a local name to send commands to.
    - `Delay`: Number of seconds to delay the input.
    - `Name`: If set the name of the `logic_relay` which must be triggered.
        If not set the output will fire `OnMapSpawn`.
    - `Output`: The name of the output, defaulting to `OnTrigger`. Ignored
        if Name is not set.
    - `Param`: The parameter for the output.
    """
    relay_name, proxy_name, command, relay_out, delay, param, target = res.value

    if relay_name is not None:
        relay_name = conditions.resolve_value(inst, relay_name)
    if target is not None:
        target = conditions.resolve_value(inst, target)

    output = Output(
        out=relay_out,
        targ=(
            conditions.local_name(inst, target)
            if target else
            inst['targetname']
        ),
        inp=command,
        inst_in=proxy_name,
        delay=delay,
        param=conditions.resolve_value(inst, param),
    )

    global_input(vmf, inst['origin'], output, relay_name)


def global_input(
    vmf: VMF,
    pos: Union[Vec, str],
    output: Output,
    relay_name: str=None,
):
    """Create a global input."""
    try:
        glob_ent = GLOBAL_INPUT_ENTS[relay_name]
    except KeyError:
        if relay_name is None:
            glob_ent = GLOBAL_INPUT_ENTS[None] = vmf.create_ent(
                classname='logic_auto',
                spawnflags='1',  # Remove on fire
                origin=pos,
            )
        else:
            glob_ent = GLOBAL_INPUT_ENTS[relay_name] = vmf.create_ent(
                classname='logic_relay',
                targetname=relay_name,
                origin=pos,
            )
    if relay_name is None:
        output.output = 'OnMapSpawn'
        output.only_once = True
    glob_ent.add_out(output)


@make_result('ScriptVar')
def res_script_var(vmf: VMF, inst: Entity, res: Property):
    """Set a variable on a script, via a logic_auto.

    Name is the local name for the script entity.
    Var is the variable name.
    Value is the value to set.
    """
    global_input(
        vmf,
        inst['origin'],
        Output(
            'OnMapSpawn',
            conditions.local_name(inst, res['name']),
            'RunScriptCode',
            param='{} <- {}'.format(
                res['var'],
                conditions.resolve_value(inst, res['value']),
            ),
        ),
    )
