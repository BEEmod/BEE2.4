"""Tests and Results relating to instances or instance variables.

"""
from __future__ import annotations

from typing import NewType
import operator

import srctools.logger
from precomp import instance_traits, instanceLocs, conditions, options
from srctools import Keyvalues, Angle, Vec, Entity, Output, VMF, conv_bool

from precomp.lazy_value import LazyValue


LOGGER = srctools.logger.get_logger(__name__, 'cond.instances')
COND_MOD_NAME = 'Instances'


@conditions.make_test('instance')
def check_file_equal(kv: Keyvalues) -> conditions.TestCallable:
    """Evaluates True if the instance matches the given file."""
    conf_inst_list = LazyValue.parse(kv.value).map(instanceLocs.resolve_filter)

    def check_inst(inst: Entity) -> bool:
        """Each time, check if no matching instances exist, so we can skip conditions."""
        inst_list = conf_inst_list(inst)
        if conf_inst_list.is_constant() and conditions.ALL_INST.isdisjoint(inst_list):
            raise conditions.Unsatisfiable
        return inst['file'].casefold() in inst_list
    return check_inst


@conditions.make_test('instFlag', 'InstPart')
def check_file_cont(inst: Entity, kv: Keyvalues) -> bool:
    """Evaluates True if the instance contains the given portion."""
    return kv.value in inst['file'].casefold()


@conditions.make_test('hasInst')
def check_has_inst(kv: Keyvalues) -> conditions.TestCallable:
    """Checks if the given instance is present anywhere in the map."""
    inst_filter = LazyValue.parse(kv.value).map(instanceLocs.resolve_filter)

    return lambda inst: inst_filter(inst).isdisjoint(conditions.ALL_INST)


@conditions.make_test('hasTrait')
def check_has_trait(inst: Entity, kv: Keyvalues) -> bool:
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
    * `preplaced`: The various pre-existing instances:
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
        * `cust_shape`: Set if the fizzler has been moved to a custom position
          by ReshapeFizzler.
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
    return kv.value.casefold() in instance_traits.get(inst)


@conditions.make_test('instVar')
def test_instvar(inst: Entity, kv: Keyvalues) -> bool:
    """Checks if the $replace value matches the given value.

    The test value follows the form `A == B`, with any of the three permitted
    to be variables.
    The operator can be any of `=`, `==`, `<`, `>`, `<=`, `>=`, `!=`.
    If omitted, the operation is assumed to be `==`.
    If only a single value is present, it is tested as a boolean.
    """
    match kv.value.split(' ', 2):
        case [val_a, op, val_b]:
            return conditions.instvar_comp(inst, val_a, op, val_b)
        case [val_a, val_b]:
            # Might be omitted operand, or value is blank. instvar_comp will check.
            return conditions.instvar_comp(inst, val_a, None, val_b)
        case [var]:
            # Single name, treat as boolean.
            return conv_bool(inst.fixup.substitute(var))
        case err:  # Only 1 - 3 values are possible.
            raise AssertionError(err)


@conditions.make_test('offsetDist')
def check_offset_distance(inst: Entity, kv: Keyvalues) -> bool:
    """Check if the given instance is in an offset position.

    This computes the distance between the instance location and the center
    of the voxel.
    The value can be the distance for an exact check, '< x', '> $var', etc.
    """
    origin = Vec.from_str(inst['origin'])
    grid_pos = origin // 128 * 128 + 64
    offset = (origin - grid_pos).mag()

    try:
        op, comp_val = kv.value.split()
    except ValueError:
        # A single value.
        op = '='
        comp_val = kv.value

    try:
        value = float(inst.fixup.substitute(comp_val))
    except ValueError:
        return False

    func = conditions.INSTVAR_COMP.get(op, operator.eq)

    try:
        return bool(func(offset, value))
    except (TypeError, ValueError) as exc:
        LOGGER.warning(
            'Distance comparison failed: {} {} {}',
            offset, op, value, exc_info=exc,
        )
        return False


@conditions.make_result('rename', 'changeInstance')
def res_change_instance(inst: Entity, res: Keyvalues) -> None:
    """Set the file to a value."""
    inst['file'] = filename = instanceLocs.resolve_one(inst.fixup.substitute(res.value), error=True)
    conditions.ALL_INST.add(filename.casefold())


@conditions.make_result('suffix', 'instSuffix')
def res_add_suffix(inst: Entity, res: Keyvalues) -> None:
    """Add the specified suffix to the filename."""
    suffix = inst.fixup.substitute(res.value)
    if suffix:
        conditions.add_suffix(inst, '_' + suffix)


@conditions.make_result('setKey')
def res_set_key(inst: Entity, res: Keyvalues) -> None:
    """Set a keyvalue to the given value.

    The name and value should be separated by a space.
    """
    data = inst.fixup.substitute(res.value, allow_invert=True)
    try:
        key, value = data.split(' ', 1)
    except ValueError:
        raise ValueError(f'setKey requires a space-separated name and value, got {data!r}!') from None
    inst[key] = value
    if key.casefold() == 'file':
        LOGGER.warning('Use changeInstance for setting instance filenames, not setKey.')
        conditions.ALL_INST.add(value)


@conditions.make_result('instVar', 'instVarSuffix')
def res_add_inst_var(inst: Entity, res: Keyvalues) -> None:
    """Append the value of an instance variable to the filename.

    Pass either the variable name, or a set of value->suffix pairs for a
    lookup.
    """
    if res.has_children():
        val = inst.fixup[res['variable', '']]
        for rep in res:  # lookup the number to determine the appending value
            if rep.name == 'variable':
                continue  # this isn't a lookup command!
            if inst.fixup.substitute(rep.name) == val:
                conditions.add_suffix(inst, '_' + inst.fixup.substitute(rep.value))
                break
    else:  # Append the value, equivalent to regular suffix now.
        res_add_suffix(inst, res)


@conditions.make_result('setInstVar', 'assign', 'setFixupVar')
def res_set_inst_var(inst: Entity, res: Keyvalues) -> None:
    """Set an instance variable to the given value.

    Values follow the format `$start_enabled 1`, with or without the `$`.
    `$out $in` will copy the value of `$in` into `$out`.
    """
    var_name, val = res.value.split(' ', 1)
    inst.fixup[var_name] = inst.fixup.substitute(val, allow_invert=True)


@conditions.make_result('mapInstVar')
def res_map_inst_var(res: Keyvalues) -> conditions.ResultCallable:
    """Set one instance var based on the value of another.

    The first value is the in -> out var, and all following are values to map.
    """
    table: dict[str, LazyValue] = {}
    res_iter = iter(res)
    first_prop = next(res_iter)
    in_name, out_name = first_prop.name, first_prop.value
    for prop in res_iter:
        table[prop.real_name] = LazyValue.parse(prop.value)

    def modify_inst(inst: Entity) -> None:
        """Map the variables on an instance."""
        try:
            inst.fixup[out_name] = table[inst.fixup[in_name]](inst)
        except KeyError:
            pass
    return modify_inst


@conditions.make_result('clearOutputs', 'clearOutput')
def res_clear_outputs(inst: Entity) -> None:
    """Remove the outputs from an instance."""
    inst.outputs.clear()


@conditions.make_result('removeFixup', 'deleteFixup', 'removeInstVar', 'deleteInstVar')
def res_rem_fixup(inst: Entity, res: Keyvalues) -> None:
    """Remove a fixup from the instance."""
    del inst.fixup[res.value]


@conditions.make_result('localTarget')
def res_local_targetname(inst: Entity, res: Keyvalues) -> None:
    """Generate a instvar with an instance-local name.

    Useful with AddOutput commands, or other values which use
    targetnames in the parameter.
    The result takes the form `<prefix><instance name>[-<local>]<suffix>`.
    """
    local_name = inst.fixup.substitute(res['name', ''])
    prefix = inst.fixup.substitute(res['prefix', ''])
    suffix = inst.fixup.substitute(res['suffix', ''])
    name = inst['targetname', '']
    if local_name:
        name = f'{name}-{local_name}'
    inst.fixup[res['resultVar']] = f"{prefix}{name}{suffix}"


@conditions.make_result('replaceInstance')
def res_replace_instance(vmf: VMF, inst: Entity, res: Keyvalues) -> None:
    """Replace an instance with another entity.

    `keys` and `localkeys` defines the new keyvalues used.
    `targetname` and `angles` are preset, and `origin` will be used to offset
    the given amount from the current location.
    If `keep_instance` is true, the instance entity will be kept instead of
    removed.
    """
    origin = Vec.from_str(inst['origin'])
    angles = Angle.from_str(inst['angles'])

    if not conv_bool(inst.fixup.substitute(res['keep_instance', '0'], allow_invert=True)):
        inst.remove()  # Do this first to free the ent ID, so the new ent has
        # the same one.

    # We copy to allow us to still access the $fixups and other values.
    new_ent = inst.copy(des_id=inst.id)
    new_ent.clear_keys()
    # Ensure there's a classname, just in case.
    new_ent['classname'] = 'info_null'

    vmf.add_ent(new_ent)

    conditions.set_ent_keys(new_ent, inst, res)

    new_ent['origin'] = Vec.from_str(new_ent['origin']) @ angles + origin
    new_ent['angles'] = angles
    new_ent['targetname'] = inst['targetname']


OnLoad = NewType('OnLoad', object)
GLOBAL_INPUT_ENTS: dict[str | OnLoad | None, Entity] = {}
ON_LOAD = OnLoad(object())


@conditions.make_result('GlobalInput')
def res_global_input(vmf: VMF, res: Keyvalues) -> conditions.ResultCallable:
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
    - `AlsoOnLoad`: If output is firing on map spawn, also fire it on save load too.

    Alternatively pass a string VMF-style output, which only provides
    OnMapSpawn functionality.
    """
    on_load = False
    if res.has_children():
        name = res['name', '']
        if not name and res.bool('alsoonload'):
            name = ''
            on_load = True
        inp_name, inp_command = Output.parse_name(res['input'])
        relay_name = name
        conf_output = Output(
            out=res['output', 'OnTrigger'],
            targ=res['target', ''],
            inp=inp_command,
            inst_in=inp_name,
            delay=srctools.conv_float(res['delay', '']),
            param=res['param', ''],
        )
    else:
        conf_output = Output.parse(res)
        conf_output.output = ''  # Don't need to store GlobalInput...
        relay_name = ''

    def add_global(inst: Entity) -> None:
        """Add the output."""
        output = conf_output.copy()

        if output.target:
            output.target = conditions.local_name(
                inst,
                inst.fixup.substitute(output.target),
            )
        else:
            output.target = inst['targetname']

        output.output = inst.fixup.substitute(output.output)
        output.params = inst.fixup.substitute(output.params)
        if output.inst_in is not None:
            output.inst_in = inst.fixup.substitute(output.inst_in)
        if output.inst_out is not None:
            output.input = inst.fixup.substitute(output.input)

        if on_load:
            try:
                ent = GLOBAL_INPUT_ENTS[ON_LOAD]
            except KeyError:
                ent = GLOBAL_INPUT_ENTS[ON_LOAD] = vmf.create_ent(
                    'logic_auto',
                    origin=options.GLOBAL_ENTS_LOC(),
                    spawnflags='0',  # Don't remove on fire.
                )
            load_out = output.copy()
            output.output = 'OnMapSpawn'
            load_out.output = 'OnLoadGame'
            output.only_once = True
            ent.add_out(output, load_out)
        else:
            global_input(vmf, inst['origin'], output, inst.fixup.substitute(relay_name))
    return add_global


def global_input(
    vmf: VMF,
    pos: Vec | str,
    output: Output,
    relay_name: str | None = None,
) -> None:
    """Create a global input, either from a relay or logic_auto.

    If the name is empty, a logic_auto is created.
    The position is used to place the entity if this is the first time.
    """
    try:
        glob_ent = GLOBAL_INPUT_ENTS[relay_name]
    except KeyError:
        if not relay_name:
            glob_ent = GLOBAL_INPUT_ENTS[''] = vmf.create_ent(
                classname='logic_auto',
                spawnflags='1',  # Remove on fire
                origin=options.GLOBAL_ENTS_LOC()
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


@conditions.make_result('ScriptVar')
def res_script_var(vmf: VMF, inst: Entity, res: Keyvalues) -> None:
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
            conditions.local_name(inst, inst.fixup.substitute(res['name'])),
            'RunScriptCode',
            param='{} <- {}'.format(
                res['var'],
                inst.fixup.substitute(res['value']),
            ),
        ),
    )
