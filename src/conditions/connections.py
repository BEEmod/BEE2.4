"""Results relating to item connections."""
import srctools
import utils
from conditions import (
    make_flag, make_result, make_result_setup,
    resolve_value, local_name,
    CONNECTIONS,
)
from conditions.instances import GLOBAL_INPUT_ENTS
from srctools import Property, Entity, Output

from typing import Optional, Dict, Tuple

LOGGER = utils.getLogger(__name__, alias='cond.connections')


@make_result_setup('AddOutput')
def res_add_output_setup(res: Property):
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

# Locking Input/Output items.
# This makes for example pedestal buttons lock down until the target
# item shuts itself off.

# targetname -> inst, out_name, out_output, out_relay
LOCKABLE_ITEMS = {}  # type: Dict[str, Tuple[Entity, Optional[str], str, str]]


@make_result('MarkLocking')
def res_locking_output(inst: Entity, res: Property):
    """Marks an output item for locked connections.

    The parameter is an `instance:name;Output` value, which is fired when the
    item resets. This must be executed before `LockingIO`.

    This only applies if `$connectioncount` is 1.
    """
    # Items with more than one connection have AND logic in the mix - it makes
    # it unsafe to lock the input item.
    if inst.fixup['$connectioncount'] != '1':
        return

    if res.has_children():
        name, output = Output.parse_name(res['output'])
        relay_name = res['rl_name', None]
    else:
        name, output = Output.parse_name(res.value)
        relay_name = None

    LOCKABLE_ITEMS[inst['targetname']] = inst, name, output, relay_name


@make_flag('LockingIO')
def res_locking_input(inst: Entity, res: Property) -> str:
    """Executed on the input item, and evaluates to True if successful.

    The parameter is an `instance:name;Input` value, which resets the item.
    This must be executed after the `MarkLocking` results have run.
    """
    from vbsp import IND_ITEM_NAMES, IND_PANEL_NAMES, VMF
    in_name, in_inp = Output.parse_name(res.value)

    targets = {
        out.target
        for out in
        inst.outputs
        # Skip toggle or indicator panel items.
        if out.target not in IND_ITEM_NAMES
    }
    # No outputs, or 2+ - we can't convert in that case
    if len(targets) != 1:
        return False

    target, = targets
    try:
        targ_inst, targ_out_name, targ_out, out_relay = LOCKABLE_ITEMS[target]
    except KeyError:
        # Some other item...
        return False

    # Remove the indicator panel instances.
    ind_panels = {
        out.target
        for out in
        inst.outputs
        # Skip toggle or indicator panel items.
        if out.target in IND_PANEL_NAMES
    }
    for pan_inst in VMF.by_class['func_instance']:
        if pan_inst['targetname'] in ind_panels:
            pan_inst.remove()

    # Add an output pointing in the opposite direction.
    if out_relay is None:
        targ_inst.add_out(Output(
            out=targ_out,
            inst_out=targ_out_name,
            targ=inst['targetname'],
            inp=in_inp,
            inst_in=in_name,
        ))
    else:
        from conditions.instances import add_global_input
        add_global_input(
            inst,
            in_name,
            in_inp,
            rl_name=out_relay,
            output=targ_out,
        )
    return True

LINKED_CUBES = {}  # type: Dict[int, Tuple[Entity, str, Optional[str], str]]


@make_result('_MarkLinkedCube')
def res_linked_cube(inst: Entity, res: Property):
    """Marks a cube to link it to a dropper.

    This assumes some things about the item.
    """
    time = inst.fixup.int('$timer_delay')
    if not (0 < time <= 30):
        # Infinite - this behaviour is disabled..
        return

    if time in LINKED_CUBES:
        raise Exception(
            'Two cubes have the same '
            '"linkage" value set ({})!'.format(
                time,
            )
        )

    resp_out_name, resp_out = Output.parse_name(res.value)

    LINKED_CUBES[time] = (
        inst,
        inst.fixup['$cube_type'],
        resp_out_name, resp_out,
    )


@make_result('LinkedCubeDropper')
def res_linked_cube_dropper(drp_inst: Entity, res: Property):
    """Link a cube and dropper together, to preplace the cube at a location."""
    time = drp_inst.fixup.int('$timer_delay')
    if not (0 < time <= 30):
        # Infinite - this behaviour is disabled..
        return

    try:

        cube_inst, cube_type, resp_out_name, resp_out = LINKED_CUBES[time]
    except KeyError:
        raise Exception('Unknown cube "linkage" value ({}) in dropper!'.format(
            time,
        ))

    # Force the dropper to match the cube..
    #  = cube_type

    # Set auto-drop to False (so there isn't two cubes),
    # and auto-respawn to True (so it actually functions).
    drp_inst.fixup['$disable_autodrop'] = '1'
    drp_inst.fixup['$disable_autorespawn'] = '0'

    fizz_out_name, fizz_out = Output.parse_name(res['FizzleOut'])

    # Output to destroy the cube when the dropper is triggered externally.
    drp_inst.add_out(Output(
        inst_out=fizz_out_name,
        out=fizz_out,
        targ=local_name(cube_inst, 'cube'),
        inp='Dissolve',
        only_once=True,
    ))

    # Cube items don't have proxies, so we need to use AddOutput
    # after it's created (@relay_spawn_3's time).
    try:
        relay_spawn_3 = GLOBAL_INPUT_ENTS['@relay_spawn_3']
    except KeyError:
        relay_spawn_3 = GLOBAL_INPUT_ENTS['@relay_spawn_3'] = cube_inst.map.create_ent(
            classname='logic_relay',
            targetname='@relay_spawn_3',
            origin=cube_inst['origin'],
        )

    respawn_inp = list(res.find_all('RespawnIn'))
    # There's some voice-logic specific to companion cubes.
    respawn_inp.extend(res.find_all(
        'RespawnCcube' if
        drp_inst.fixup['$cube_type'] == '1'
        else 'RespawnCube'
    ))

    for inp in respawn_inp:
        resp_in_name, resp_in = inp.value.split(':', 1)

        out = Output(
            out='OnFizzled',
            targ=drp_inst,
            inst_in=resp_in_name,
            inp=resp_in,
            only_once=True,
        )

        relay_spawn_3.add_out(Output(
            out='OnTrigger',
            targ=local_name(cube_inst, 'cube'),
            inp='AddOutput',
            param=out.gen_addoutput(),
            only_once=True,
            delay=0.01,
        ))
