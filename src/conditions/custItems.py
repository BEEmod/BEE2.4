"""Results for customising the behaviour of certain items - antlines, faith plates,

"""
from collections import defaultdict

import conditions
import srctools
import template_brush
import utils
import vbsp
import vbsp_options
import comp_consts as consts
from conditions import (
    Condition, make_result, make_result_setup,
    CONNECTIONS,
)
import instanceLocs
from srctools import Property, Vec, Entity, Output

COND_MOD_NAME = 'Custom Items'

# Map sign_type values to the item ID and the resolveInst ID.
IND_PANEL_TYPES = {
    'check': ('item_indicator_panel', '[indPanCheck]'),
    'timer': ('item_indicator_panel_timer', '[indPanTimer]'),
    'none': '',
}

LOGGER = utils.getLogger(__name__, alias='cond.custItems')


@make_result_setup('custOutput')
def res_cust_output_setup(res: Property):
    conds = [
        Condition.parse(sub_res)
        for sub_res in res
        if sub_res.name == 'targcondition'
    ]
    outputs = list(res.find_all('addOut'))
    dec_con_count = srctools.conv_bool(res["decConCount", '0'], False)
    sign_type = IND_PANEL_TYPES.get(res['sign_type', None], None)

    if sign_type is None:
        sign_act = sign_deact = (None, '')
    else:
        # The outputs which trigger the sign.
        sign_act = Output.parse_name(res['sign_activate', ''])
        sign_deact = Output.parse_name(res['sign_deactivate', ''])

    return outputs, dec_con_count, conds, sign_type, sign_act, sign_deact



@make_result('custOutput')
def res_cust_output(inst: Entity, res: Property):
    """Add an additional output to the instance with any values.

    Always points to the targeted item.

    If DecConCount is 1, connections
    """
    (
        outputs,
        dec_con_count,
        targ_conditions,
        force_sign_type,
        (sign_act_name, sign_act_out),
        (sign_deact_name, sign_deact_out),
    ) = res.value

    over_name = '@' + inst['targetname'] + '_indicator'
    for toggle in vbsp.VMF.by_class['func_instance']:
        if toggle.fixup['indicator_name', ''] == over_name:
            toggle_name = toggle['targetname']
            break
    else:
        toggle_name = ''  # we want to ignore the toggle instance, if it exists

    # Build a mapping from names to targets.
    # This is also the set of all output items, plus indicators.
    targets = defaultdict(list)
    for out in inst.outputs:
        if out.target != toggle_name:
            targets[out.target].append(out)

    pan_files = instanceLocs.resolve('[indPan]')

    # These all require us to search through the instances.
    if force_sign_type or dec_con_count or targ_conditions:
        for con_inst in vbsp.VMF.by_class['func_instance']:  # type: Entity
            if con_inst['targetname'] not in targets:
                # Not our instance
                continue

            # Is it an indicator panel, and should we be modding it?
            if force_sign_type is not None and con_inst['file'].casefold() in pan_files:
                # Remove the panel
                if force_sign_type == '':
                    con_inst.remove()
                    continue

                # Overwrite the signage instance, and then add the
                # appropriate outputs to control it.
                sign_id, sign_file_id = force_sign_type
                con_inst['file'] = instanceLocs.resolve_one(sign_file_id, error=True)

                # First delete the original outputs:
                for out in targets[con_inst['targetname']]:
                    inst.outputs.remove(out)

                inputs = CONNECTIONS[sign_id]
                act_name, act_inp = inputs.in_act
                deact_name, deact_inp = inputs.in_deact

                LOGGER.info(
                    'outputs: a="{}" d="{}"\n'
                    'inputs: a="{}" d="{}"'.format(
                        (sign_act_name, sign_act_out),
                        (sign_deact_name, sign_deact_out),
                        inputs.in_act,
                        inputs.in_deact
                    )
                )

                if act_inp and sign_act_out:
                    inst.add_out(Output(
                        inst_out=sign_act_name,
                        out=sign_act_out,
                        inst_in=act_name,
                        inp=act_inp,
                        targ=con_inst['targetname'],
                    ))

                if deact_inp and sign_deact_out:
                    inst.add_out(Output(
                        inst_out=sign_deact_name,
                        out=sign_deact_out,
                        inst_in=deact_name,
                        inp=deact_inp,
                        targ=con_inst['targetname'],
                    ))
            if dec_con_count and 'connectioncount' in con_inst.fixup:
                # decrease ConnectionCount on the ents,
                # so they can still process normal inputs
                try:
                    val = int(con_inst.fixup['connectioncount'])
                    con_inst.fixup['connectioncount'] = str(val-1)
                except ValueError:
                    # skip if it's invalid
                    LOGGER.warning(
                        con_inst['targetname'] +
                        ' has invalid ConnectionCount!'
                    )

            if targ_conditions:
                for cond in targ_conditions:  # type: Condition
                    cond.test(con_inst)

    if outputs:
        for targ in targets:
            for out in outputs:
                conditions.add_output(inst, out, targ)


@make_result_setup('custAntline')
def res_cust_antline_setup(res: Property):
    def find(cat):
        """Helper to reduce code duplication."""
        return [p.value for p in res.find_all(cat)]

    # Allow overriding these options. If unset use the style's value - the
    # amount of destruction will usually be the same.
    broken_chance = res.float(
        'broken_antline_chance',
        vbsp_options.get(float, 'broken_antline_chance'),
    )
    broken_dist = res.int(
        'broken_antline_distance',
        vbsp_options.get(int, 'broken_antline_distance'),
    )

    toggle_inst = res['instance', '']
    toggle_out = list(res.find_all('addOut'))

    # These textures are required - the base ones.
    straight_tex = find('straight')
    corner_tex = find('corner')

    # Arguments to pass to setAntlineMat
    straight_args = [
        straight_tex,
        find('straightFloor') or (),
        # Extra broken antline textures / options, if desired.
        broken_chance,
        broken_dist,
        find('brokenStraight') or (),
        find('brokenStraightFloor') or (),
    ]

    # The same but for corners.
    corner_args = [
        corner_tex,
        find('cornerFloor') or (),
        broken_chance,
        broken_dist,
        find('brokenCorner') or (),
        find('brokenCornerFloor') or (),
    ]

    if not straight_tex or not corner_tex:
        # If we don't have two textures, something's wrong. Remove this result.
        LOGGER.warning('custAntline has no textures!')
        return None
    else:
        return straight_args, corner_args, toggle_inst, toggle_out


@make_result('custAntline')
def res_cust_antline(inst: Entity, res: Property):
    """Customise the output antline texture, toggle instances.

    This allows adding extra outputs between the instance and the toggle.
    Values:
        straight: The straight overlay texture.
        corner: The corner overlay texture.
        straightFloor: Alt texture used on straight floor segements (P1 style)
        cornerFloor: Alt texture for floor corners (P1 style)
          If these aren't set, the wall textures will be used.
        instance: Use the given indicator_toggle instance instead
        addOut: A set of additional ouputs to add, pointing at the
          toggle instance
    """
    straight_args, corner_args, toggle_inst, toggle_out = res.value

    # The original textures for straight and corner antlines
    straight_ant = consts.Antlines.STRAIGHT
    corner_ant = consts.Antlines.CORNER

    over_name = '@' + inst['targetname'] + '_indicator'

    for over in (
            vbsp.VMF.by_class['info_overlay'] &
            vbsp.VMF.by_target[over_name]
            ):
        folded_mat = over['material'].casefold()
        if folded_mat == straight_ant:
            vbsp.set_antline_mat(over, *straight_args)
        elif folded_mat == corner_ant:
            vbsp.set_antline_mat(over, *corner_args)

        # Ensure this isn't overriden later!
        vbsp.IGNORED_OVERLAYS.add(over)

    # allow replacing the indicator_toggle instance
    if toggle_inst:
        for toggle in vbsp.VMF.by_class['func_instance']:
            if toggle.fixup['indicator_name', ''] != over_name:
                continue
            toggle['file'] = toggle_inst
            if len(toggle_out) > 0:
                for out in inst.outputs[:]:
                    if out.target == toggle['targetname']:
                        # remove the original outputs
                        inst.outputs.remove(out)
                for out in toggle_out:
                    # Allow adding extra outputs to customly
                    # trigger the toggle
                    conditions.add_output(inst, out, toggle['targetname'])
            break  # Stop looking!


@make_result_setup('changeOutputs')
def res_change_outputs_setup(res: Property):
    return [
        (
            Output.parse_name(prop.real_name),
            Output.parse_name(prop.value)
        )
        for prop in
        res
    ]


@make_result('changeOutputs')
def res_change_outputs(inst: Entity, res: Property):
    """Switch the outputs on an instance.

    Each child is a original -> replace value. These match the values
    in editoritems.txt. Use a blank value to indicate it should be deleted.
    """
    for output in inst.outputs[:]:  # type: Output
        for (orig_name, orig_comm), rep in res.value:
            if output.inst_out == orig_name and output.output == orig_comm:
                if rep == (None, ''):
                    inst.outputs.remove(output)
                else:
                    output.inst_out, output.output = rep


@make_result_setup('changeInputs')
def res_change_inputs_setup(res: Property):
    vals = {}
    for prop in res:
        out_key = Output.parse_name(prop.real_name)
        if prop.has_children():
            vals[out_key] = (
                prop['inst_in', None],
                prop['input'],
                prop['params', ''],
                srctools.conv_float(prop['delay', 0.0]),
                1 if srctools.conv_bool(prop['only_once', '0']) else -1,
            )
        else:
            vals[out_key] = None
    return vals


@make_result('changeInputs')
def res_change_inputs(inst: Entity, res: Property):
    """Switch the inputs for an instance.

    Each child is an input to replace. The name is the original input, matching
    the values in editoritems.txt. If 'inst_in' is set, this is the local entity
    to trigger via proxy (otherwise it controls the instance). 'input',
    'params', 'delay', and 'only_once' match the values in Hammer.

    Use empty quotes instead of a block to indicate it should be deleted.
    This replaces all outputs which target this instance name.
    """
    name = inst['targetname'].casefold()
    if not name:
        LOGGER.warning('Empty targetname for changeInputs...')
        return  # No name, it can't be triggered...

    # ReplaceInstance might make some not instances anymore..
    for inst in vbsp.VMF.entities:
        for out in inst.outputs[:]:  # type: Output
            if out.target.casefold() != name:
                continue

            try:
                new_vals = res.value[out.inst_in, out.input]
            except KeyError:
                LOGGER.warning(
                    'Unknown output for changeInputs({}):\n {}',
                    name,
                    out
                )
                continue
            if new_vals is None:
                inst.outputs.remove(out)
                continue
            (
                out.inst_in,
                out.input,
                out.params,
                out.delay,
                out.times,
            ) = new_vals


@make_result('faithMods')
def res_faith_mods(inst: Entity, res: Property):
    """Modify the trigger_catrapult that is created for ItemFaithPlate items.

    Values:
        - raise_trig: Raise or lower the trigger_catapults by this amount.
        - angled_targ, angled_in: Instance entity and input for angled plates
        - straight_targ, straight_in: Instance entity and input for
            straight plates
        - instvar: A $replace value to set to either 'angled' or '
            'straight'.
        - enabledVar: A $replace value which will be copied to the main
            trigger's Start Disabled value (and inverted).
        - trig_temp: An ID for a template brush to add. This will be offset by
            the trigger's position (in the case of the 'helper' trigger).
    """
    # Get data about the trigger this instance uses for flinging
    fixup_var = res['instvar', '']
    trig_enabled = res['enabledVar', None]
    trig_temp = res['trig_temp', '']
    offset = srctools.conv_int(res['raise_trig', '0'])
    if offset:
        offset = Vec(0, 0, offset).rotate_by_str(inst['angles', '0 0 0'])
    else:
        offset = Vec()

    if trig_enabled is not None:
        trig_enabled = srctools.conv_bool(inst.fixup[trig_enabled])
    else:
        trig_enabled = None

    for trig in vbsp.VMF.by_class['trigger_catapult']:
        if inst['targetname'] not in trig['targetname']:
            continue

        # Edit both the normal and the helper trigger..
        trig_origin = trig['origin'] = Vec.from_str(trig['origin']) + offset

        if offset and not trig_temp:
            # No template, shift the current brushes.
            for solid in trig.solids:
                solid.translate(offset)
        elif trig_temp:
            trig.solids = template_brush.import_template(
                temp_name=trig_temp,
                origin=trig_origin,
                angles=Vec.from_str(inst['angles']),
                force_type=template_brush.TEMP_TYPES.world,
            ).world
            # Remove the trigger solids from worldspawn..
            for solid in trig.solids:
                vbsp.VMF.remove_brush(solid)

        if trig_enabled is not None and 'helper' not in trig['targetname']:
            trig['startdisabled'] = srctools.bool_as_int(not trig_enabled)

        # Inspect the outputs to determine the type.
        # We also change them if desired, since that's not possible
        # otherwise.

        for out in trig.outputs:
            if out.inst_in == 'animate_angled_relay':
                # Instead of an instance: output, use local names.
                # This allows us to strip the proxy, as well as use
                # overlay instances.
                out.inst_in = None
                out.target = conditions.local_name(
                    inst,
                    res['angled_targ', 'animate_angled_relay']
                )
                out.input = res['angled_in', 'Trigger']
                if fixup_var:
                    inst.fixup[fixup_var] = 'angled'
                break  # There's only one output we want to look for...

            elif out.inst_in == 'animate_straightup_relay':
                out.inst_in = None
                out.target = conditions.local_name(
                    inst,
                    res[
                        'straight_targ',
                        'animate_straightup_relay'
                    ],
                )
                out.input = res['straight_in', 'Trigger']

                if fixup_var:
                    inst.fixup[fixup_var] = 'straight'
                break
