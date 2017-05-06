"""Logic for trigger items, allowing them to be resized."""
import conditions
import instanceLocs
import srctools
import utils
import vbsp
import vbsp_options
import comp_consts as const
from conditions import (
    make_result, RES_EXHAUSTED,
)
from srctools import Property, Vec, Entity, Output

COND_MOD_NAME = None

LOGGER = utils.getLogger(__name__, alias='cond.resizeTrig')


@make_result('ResizeableTrigger')
def res_resizeable_trigger(res: Property):
    """Replace two markers with a trigger brush.  

    This is run once to affect all of an item.  
    Options:
    * `markerInst`: <ITEM_ID:1,2> value referencing the marker instances, or a filename.
    * `markerItem`: The item's ID
    * `previewConf`: A item config which enables/disables the preview overlay.
    * `previewinst`: An instance to place at the marker location in preview mode.
        This should contain checkmarks to display the value when testing.
    * `previewMat`: If set, the material to use for an overlay func_brush.
        The brush will be parented to the trigger, so it vanishes once killed.
        It is also non-solid.
    * `previewScale`: The scale for the func_brush materials.
    * `previewActivate`, `previewDeactivate`: The `instance:name;Input` value
        to turn the previewInst on and off.

    * `triggerActivate, triggerDeactivate`: The outputs used when the trigger
        turns on or off.

    * `coopVar`: The instance variable which enables detecting both Coop players.
        The trigger will be a trigger_playerteam.

    * `coopActivate, coopDeactivate`: The outputs used when coopVar is enabled.
        These should be suitable for a logic_coop_manager.
    * `coopOnce`: If true, kill the manager after it first activates.

    * `keys`: A block of keyvalues for the trigger brush. Origin and targetname
        will be set automatically.
    * `localkeys`: The same as above, except values will be changed to use
        instance-local names.
    """
    marker = instanceLocs.resolve(res['markerInst'])

    markers = {}
    for inst in vbsp.VMF.by_class['func_instance']:
        if inst['file'].casefold() in marker:
            markers[inst['targetname']] = inst

    if not markers:  # No markers in the map - abort
        return RES_EXHAUSTED

    trig_act = res['triggerActivate', 'OnStartTouchAll']
    trig_deact = res['triggerDeactivate','OnEndTouchAll']

    coop_var = res['coopVar', None]
    coop_act = res['coopActivate', 'OnChangeToAllTrue']
    coop_deact = res['coopDeactivate', 'OnChangeToAnyFalse']
    coop_only_once = res.bool('coopOnce')

    marker_connection = conditions.CONNECTIONS[res['markerItem'].casefold()]
    mark_act_name, mark_act_out = marker_connection.out_act
    mark_deact_name, mark_deact_out = marker_connection.out_deact
    del marker_connection

    # Display preview overlays if it's preview mode, and the config is true
    if vbsp.IS_PREVIEW and vbsp_options.get_itemconf(res['previewConf', ''], False):
        preview_mat = res['previewMat', '']
        preview_inst_file = res['previewInst', '']
        pre_act_name, pre_act_inp = Output.parse_name(
            res['previewActivate', ''])
        pre_deact_name, pre_deact_inp = Output.parse_name(
            res['previewDeactivate', ''])
        preview_scale = srctools.conv_float(res['previewScale', '0.25'], 0.25)
    else:
        # Deactivate the preview_ options when publishing.
        preview_mat = preview_inst_file = ''
        pre_act_name = pre_deact_name = None
        pre_act_inp = pre_deact_inp = ''
        preview_scale = 0.25

    # Now convert each brush
    # Use list() to freeze it, allowing us to delete from the dict
    for targ, inst in list(markers.items()):  # type: str, VLib.Entity
        for out in inst.output_targets():
            if out in markers:
                other = markers[out]  # type: Entity
                del markers[out]  # Don't let it get repeated
                break
        else:
            if inst.fixup['$connectioncount'] == '0':
                # If the item doesn't have any connections, 'connect'
                # it to itself so we'll generate a 1-block trigger.
                other = inst
            else:
                continue  # It's a marker with an input, the other in the pair
                # will handle everything.

        for ent in {inst, other}:
            # Only do once if inst == other
            ent.remove()

        is_coop = coop_var is not None and vbsp.GAME_MODE == 'COOP' and (
            inst.fixup.bool(coop_var) or
            other.fixup.bool(coop_var)
        )

        bbox_min, bbox_max = Vec.bbox(
            Vec.from_str(inst['origin']),
            Vec.from_str(other['origin'])
        )

        # Extend to the edge of the blocks.
        bbox_min -= 64
        bbox_max += 64

        out_ent = trig_ent = vbsp.VMF.create_ent(
            classname='trigger_multiple',  # Default
            # Use the 1st instance's name - that way other inputs control the
            # trigger itself.
            targetname=targ,
            origin=inst['origin'],
            angles='0 0 0',
        )
        trig_ent.solids = [
            vbsp.VMF.make_prism(
                bbox_min,
                bbox_max,
                mat=const.Tools.TRIGGER,
            ).solid,
        ]

        # Use 'keys' and 'localkeys' blocks to set all the other keyvalues.
        conditions.set_ent_keys(trig_ent, inst, res)

        if is_coop:
            trig_ent['spawnflags'] = '1'  # Clients
            trig_ent['classname'] = 'trigger_playerteam'

            out_ent_name = conditions.local_name(inst, 'man')
            out_ent = vbsp.VMF.create_ent(
                classname='logic_coop_manager',
                targetname=out_ent_name,
                origin=inst['origin']
            )
            if coop_only_once:
                # Kill all the ents when both players are present.
                out_ent.add_out(
                    Output('OnChangeToAllTrue', out_ent_name, 'Kill'),
                    Output('OnChangeToAllTrue', targ, 'Kill'),
                )
            trig_ent.add_out(
                Output('OnStartTouchBluePlayer', out_ent_name, 'SetStateATrue'),
                Output('OnStartTouchOrangePlayer', out_ent_name, 'SetStateBTrue'),
                Output('OnEndTouchBluePlayer', out_ent_name, 'SetStateAFalse'),
                Output('OnEndTouchOrangePlayer', out_ent_name, 'SetStateBFalse'),
            )
            act_out = coop_act
            deact_out = coop_deact
        else:
            act_out = trig_act
            deact_out = trig_deact

        if preview_mat:
            preview_brush = vbsp.VMF.create_ent(
                classname='func_brush',
                parentname=targ,
                origin=inst['origin'],

                Solidity='1',  # Not solid
                drawinfastreflection='1',  # Draw in goo..

                # Disable shadows and lighting..
                disableflashlight='1',
                disablereceiveshadows='1',
                disableshadowdepth='1',
                disableshadows='1',
            )
            preview_brush.solids = [
                # Make it slightly smaller, so it doesn't z-fight with surfaces.
                vbsp.VMF.make_prism(
                    bbox_min + 0.5,
                    bbox_max - 0.5,
                    mat=preview_mat,
                ).solid,
            ]
            for face in preview_brush.sides():
                face.scale = preview_scale

        if preview_inst_file:
            vbsp.VMF.create_ent(
                classname='func_instance',
                targetname=targ + '_preview',
                file=preview_inst_file,
                # Put it at the second marker, since that's usually
                # closest to antlines if present.
                origin=other['origin'],
            )

            if pre_act_name and trig_act:
                out_ent.add_out(Output(
                    trig_act,
                    targ + '_preview',
                    inst_in=pre_act_name,
                    inp=pre_act_inp,
                ))
            if pre_deact_name and trig_deact:
                out_ent.add_out(Output(
                    trig_deact,
                    targ + '_preview',
                    inst_in=pre_deact_name,
                    inp=pre_deact_inp,
                ))

        # Now copy over the outputs from the markers, making it work.
        for out in inst.outputs + other.outputs:
            # Skip the output joining the two markers together.
            if out.target == other['targetname']:
                continue

            if out.inst_out == mark_act_name and out.output == mark_act_out:
                ent_out = act_out
            elif out.inst_out == mark_deact_name and out.output == mark_deact_out:
                ent_out = deact_out
            else:
                continue  # Skip this output - it's somehow invalid for this item.

            if not ent_out:
                continue  # Allow setting the output to "" to skip

            out_ent.add_out(Output(
                ent_out,
                out.target,
                inst_in=out.inst_in,
                inp=out.input,
                param=out.params,
                delay=out.delay,
                times=out.times,
            ))

    return RES_EXHAUSTED
