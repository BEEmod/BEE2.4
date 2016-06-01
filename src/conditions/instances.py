"""Flags and Results relating to instances or instance variables.

"""
import operator

import conditions
import srctools
import srctools.vmfLib as VLib
from conditions import (
    make_flag, make_result,
    ALL_INST,
)
from instanceLocs import resolve as resolve_inst
from srctools import Vec


@make_flag('instance')
def flag_file_equal(inst, flag):
    """Evaluates True if the instance matches the given file."""
    return inst['file'].casefold() in resolve_inst(flag.value)


@make_flag('instFlag', 'InstPart')
def flag_file_cont(inst, flag):
    """Evaluates True if the instance contains the given portion."""
    return flag.value in inst['file'].casefold()


@make_flag('hasInst')
def flag_has_inst(_, flag):
    """Checks if the given instance is present anywhere in the map."""
    flags = resolve_inst(flag.value)
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
def flag_instvar(inst, flag):
    """Checks if the $replace value matches the given value.

    The flag value follows the form "$start_enabled == 1", with or without
    the $.
    The operator can be any of '=', '==', '<', '>', '<=', '>=', '!='.
    If ommitted, the operation is assumed to be ==.
    """
    values = flag.value.split(' ')
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
def res_change_instance(inst, res):
    """Set the file to a value."""
    inst['file'] = resolve_inst(res.value)[0]


@make_result('suffix', 'instSuffix')
def res_add_suffix(inst, res):
    """Add the specified suffix to the filename."""
    conditions.add_suffix(inst, '_' + res.value)


@make_result('setKey')
def res_set_key(inst, res):
    """Set a keyvalue to the given value.

    The name and value should be separated by a space.
    """
    key, value = res.value.split(' ', 1)
    inst[key] = value


@make_result('instVar', 'instVarSuffix')
def res_add_inst_var(inst, res):
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
def res_set_inst_var(inst, res):
    """Set an instance variable to the given value.

    Values follow the format "$start_enabled 1", with or without the $.
    "$out $in" will copy the value of $in into $out.
    """
    var_name, val = res.value.split(' ', 1)
    inst.fixup[var_name] = conditions.resolve_value(inst, val)


@make_result('clearOutputs', 'clearOutput')
def res_clear_outputs(inst, res):
    """Remove the outputs from an instance."""
    inst.outputs.clear()


@make_result('removeFixup')
def res_rem_fixup(inst, res):
    """Remove a fixup from the instance."""
    del inst.fixup[res.value]


@make_result('localTarget')
def res_local_targetname(inst, res):
    """Generate a instvar with an instance-local name.

    Useful with AddOutput commands, or other values which use
    targetnames in the parameter.
    The result takes the form "<prefix><instance name>[-<local>]<suffix>".
    """
    local_name = res['name', '']
    if local_name:
        name = inst['targetname', ''] + '-' + local_name
    else:
        name = inst['targetname', '']
    inst.fixup[res['resultVar']] = res['prefix', ''] + name + res['suffix', '']


@make_result('replaceInstance')
def res_replace_instance(inst: VLib.Entity, res):
    """Replace an instance with another entity.

    'keys' and 'localkeys' defines the new keyvalues used.
    'targetname' and 'angles' are preset, and 'origin' will be used to offset
    the given amount from the current location.
    If 'keep_instance' is true, the instance entity will be kept instead of
    removed.
    """
    import vbsp

    origin = Vec.from_str(inst['origin'])
    angles = inst['angles']

    if not srctools.conv_bool(res['keep_instance', '0'], False):
        inst.remove()  # Do this first to free the ent ID, so the new ent has
        # the same one.

    # We copy to allow us to still acess the $fixups and other values.
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
