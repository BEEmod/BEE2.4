"""Flags and Results relating to instances or instance variables.

"""
import operator

from typing import Dict, Optional, Union

import conditions
import srctools.logger
from conditions import (
    make_flag, make_result, make_result_setup,
    ALL_INST,
)
import instanceLocs
import instance_traits
from srctools import Property, Vec, Entity, Output, VMF

LOGGER = srctools.logger.get_logger(__name__, 'cond.instances')

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


@make_flag('hasTrait')
def flag_has_trait(inst: Entity, flag: Property):
    """Check if the instance has a specific 'trait', which is set by code.

    Current traits:
        * `white`, `black`: If editoritems indicates the colour of the item.
        * `arrival_departure_transition`: `arrival_departure_transition_ents`.
        * `barrier`: Glass/grating instances:
            * `barrier_128`: Segment instance.
            * `barrier_frame`: Any frame part.
                * `frame_convex_corner`: Convex corner (unused).
                * `frame_short`: Shortened frame to fit a corner.
                * `frame_straight`: Straight frame section.
                * `frame_corner`: Frame corner section.
                * `frame_left`: Left half of the frame.
                * `frame_right`: Right half of the frame.
        * `floor_button`: ItemButtonFloor type item:
            * `btn_ball`: Button Type = Sphere.
            * `btn_cube`: Button Type = Cube
            * `weighted`: Button Type = Weighted
        * `dropperless`: A dropperless Cube:
            * `cube_standard`: Normal Cube.
            * `cube_companion`: Companion Cube.
            * `cube_ball`: Edgeless Safety Cube.
            * `cube_reflect`: Discouragment Redirection Cube.
            * `cube_franken`: FrankenTurret.
        * `coop_corridor`: A Coop exit Corridor.
        * `sp_corridor`: SP entry or exit corridor.
        * `corridor_frame`: White/black door frame.
        * `corridor_1`-`7`: The specified entry/exit corridor.
        * `elevator`: An elevator instance.
        * `entry_elevator`: Entry Elevator.
        * `exit_elevator`: Exit Elevator.
        * `entry_corridor`: Entry SP Corridor.
        * `exit_corridor`: Exit SP/Coop Corridor.
        * `fizzler`: A fizzler item:
            * `fizzler_base`: Logic instance.
            * `fizzler_model`: Model instance.
        * `locking_targ`: Target of a locking pedestal button.
        * `locking_btn`: Locking pedestal button.
        * `paint_dropper`: Gel Dropper:
            * `paint_dropper_bomb`: Bomb-type dropper.
            * `paint_dropper_sprayer`: Sprayer-type dropper.
        * `panel_angled`: Angled Panel-type item.
        * `track_platform`: Track Platform-style item:
            * `plat_bottom`: Bottom frame.
            * `plat_bottom_grate`: Grating.
            * `plat_middle`: Middle frame.
            * `plat_single`: One-long frame.
            * `plat_top`: Top frame.
            * `plat_non_osc`: Non-oscillating platform.
            * `plat_osc`: Oscillating platform.
        * `tbeam_emitter`: Funnel emitter.
        * `tbeam_frame`: Funnel frame.
    """
    return flag.value.casefold() in instance_traits.get(inst)


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
    If only the variable name is present, it is tested as a boolean flag.
    """
    values = flag.value.split(' ', 3)
    if len(values) == 3:
        variable, op, comp_val = values
        value = inst.fixup[variable]
        comp_val = conditions.resolve_value(inst, comp_val)
        try:
            # Convert to floats if possible, otherwise handle both as strings.
            # That ensures we normalise different number formats (1 vs 1.0)
            comp_val, value = float(comp_val), float(value)
        except ValueError:
            pass
        return INSTVAR_COMP.get(op, operator.eq)(value, comp_val)
    elif len(values) == 2:
        variable, value = values
        return inst.fixup[variable] == value
    else:
        # For just a name.
        return inst.fixup.bool(flag.value)


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
    if res.has_children():
        name = res['name', '']
        inp_name, inp_command = Output.parse_name(res['input'])
        return name, Output(
            out=res['output', 'OnTrigger'],
            targ=res['target', ''],
            inp=inp_command,
            inst_in=inp_name,
            delay=srctools.conv_float(res['delay', '']),
            param=res['param', ''],
        )
    else:
        out = Output.parse(res)
        out.output = ''  # Don't need to store GlobalInput...
        return '', out


@make_result('GlobalInput')
def res_global_input(vmf: VMF, inst: Entity, res: Property):
    """Trigger an input either on map spawn, or when a relay is triggered.

    Arguments:  
    
    - `Input`: the input to use, either a name or an `instance:` command.
    - `Target`: If set, a local name to send commands to. Otherwise, the instance itself.
    - `Delay`: Number of seconds to delay the input.
    - `Name`: If set the name of the `logic_relay` which must be triggered.
        If not set the output will fire `OnMapSpawn`.
    - `Output`: The name of the output, defaulting to `OnTrigger`. Ignored
        if Name is not set.
    - `Param`: The parameter for the output.

    Alternatively pass a string VMF-style output, which only provides
    OnMapSpawn functionality.
    """
    relay_name, out = res.value

    output = out.copy()  # type: Output

    if output.target:
        output.target = conditions.local_name(
            inst,
            conditions.resolve_value(inst, output.target)
        )
    else:
        output.target = inst['targetname']

    relay_name = conditions.resolve_value(inst, relay_name)
    output.params = conditions.resolve_value(inst, output.params)

    global_input(vmf, inst['origin'], output, relay_name)


def global_input(
    vmf: VMF,
    pos: Union[Vec, str],
    output: Output,
    relay_name: str=None,
):
    """Create a global input, either from a relay or logic_auto.

    The position is used to place the relay if this is the first time.
    """
    try:
        glob_ent = GLOBAL_INPUT_ENTS[relay_name]
    except KeyError:
        if relay_name == '':
            glob_ent = GLOBAL_INPUT_ENTS[''] = vmf.create_ent(
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
    if not relay_name:
        output.output = 'OnMapSpawn'
        output.only_once = True
    output.comma_sep = False
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
