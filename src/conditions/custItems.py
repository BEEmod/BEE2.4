"""Results for customising the behaviour of certain items - antlines, faith plates,

"""
import antlines
import connections
import conditions
import srctools.logger
import template_brush
import vbsp
from srctools import Property, Vec, Entity

from typing import Optional, Tuple

COND_MOD_NAME = 'Custom Items'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.custItems')


@conditions.make_result_setup('custAntline')
def res_cust_antline_setup(res: Property):
    if 'wall' in res:
        wall_type = antlines.AntType.parse(res.find_key('wall'))
    else:
        wall_type = None

    if 'floor' in res:
        floor_type = antlines.AntType.parse(res.find_key('floor'))
    else:
        floor_type = wall_type

    return (
        wall_type,
        floor_type,
        res.bool('remove_signs'),
        res['toggle_var', ''],
    )

CustAntValue = Tuple[Optional[antlines.AntType], Optional[antlines.AntType], bool, str]


@conditions.make_result('custAntline')
def res_cust_antline(inst: Entity, res: Property):
    """Customise the output antlines.

    Options:
    * `wall`: The configuration for antlines on walls. Same as global
        style options.
    * `floor`: The configuration for floor/ceiling antlines. If not provided,
        this is assumed to be the same as `wall`.
    * `remove_signs`: If true, remove the indicator signs.
    * `toggle_var`: If set, this item controls the toggle state fully of its
        antlines. This is a fixup var which will be set to the name of the
        overlays, for user control.
    """
    wall_style, floor_style, remove_signs, toggle_var = res.value  # type: CustAntValue

    item = connections.ITEMS[inst['targetname']]
    if wall_style is not None:
        item.ant_wall_style = wall_style
    if floor_style is not None:
        item.ant_floor_style = floor_style

    if remove_signs:
        for sign in item.ind_panels:
            sign.remove()
        item.ind_panels.clear()

    if toggle_var:
        item.ant_toggle_var = toggle_var


@conditions.make_result('changeOutputs')
def res_change_outputs():
    """Deprecated, use ChangeIOType."""
    LOGGER.warning('ChangeOutputs is deprecated. Use ChangeIOType.')
    return conditions.RES_EXHAUSTED


@conditions.make_result('changeInputs')
def res_change_inputs():
    """Deprecated, use ChangeIOType."""
    LOGGER.warning('ChangeInputs is deprecated. Use ChangeIOType.')
    return conditions.RES_EXHAUSTED


@conditions.make_result('faithMods')
def res_faith_mods(inst: Entity, res: Property):
    """Modify the `trigger_catapult` that is created for `ItemFaithPlate` items.

    Values:
      
    - `raise_trig`: Raise or lower the `trigger_catapult`s by this amount.
    - `angled_targ`, `angled_in`: Instance entity and input for angled plates
    - `straight_targ`, `straight_in`: Instance entity and input for
      straight plates
    - `instvar`: A $replace value to set to either 'angled' or '
      'straight'.
    - `enabledVar`: A `$replace` value which will be copied to the main
      trigger's Start Disabled value (and inverted).
    - `trig_temp`: An ID for a template brush to add. This will be offset by
      the trigger's position (in the case of the `helper` trigger).
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
