"""Logic for trigger items, allowing them to be resized."""
from __future__ import annotations

from contextlib import suppress
from typing import Optional

from srctools import Keyvalues, Vec, Output, VMF
import srctools.logger

from precomp import instanceLocs, connections, options, conditions
import consts


COND_MOD_NAME: str | None = None
LOGGER = srctools.logger.get_logger(__name__, alias='cond.resizeTrig')


@conditions.make_result('ResizeableTrigger')
def res_resizeable_trigger(vmf: VMF, info: conditions.MapInfo, res: Keyvalues) -> object:
    """Replace two markers with a trigger brush.

    This is run once to affect all of an item.
    Options:

    * `markerInst`: <ITEM_ID:1,2> value referencing the marker instances, or a filename.
    * `markerItem`: The item's ID
    * `previewConf`: A item config which enables/disables the preview overlay.
    * `previewInst`: An instance to place at the marker location in preview mode.
        This should contain checkmarks to display the value when testing.
    * `previewMat`: If set, the material to use for an overlay func_brush.
        The brush will be parented to the trigger, so it vanishes once killed.
        It is also non-solid.
    * `previewScale`: The scale for the func_brush materials.
    * `previewActivate`, `previewDeactivate`: The VMF output to turn the
        previewInst on and off.
    * `triggerActivate, triggerDeactivate`: The `instance:name;Output`
        outputs used when the trigger turns on or off.
    * `coopVar`: The instance variable which enables detecting both Coop players.
        The trigger will be a trigger_playerteam.
    * `coopActivate, coopDeactivate`: The `instance:name;Output` outputs used
        when coopVar is enabled. These should be suitable for a logic_coop_manager.
    * `coopOnce`: If true, kill the manager after it first activates.
    * `keys`: A block of keyvalues for the trigger brush. Origin and targetname
        will be set automatically.
    * `localkeys`: The same as above, except values will be changed to use
        instance-local names.
    """
    marker = instanceLocs.resolve_filter(res['markerInst'])

    marker_names = set()

    inst = None
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() in marker:
            marker_names.add(inst['targetname'])
            # Unconditionally delete from the map, so it doesn't
            # appear even if placed wrongly.
            inst.remove()
    del inst  # Make sure we don't use this later.

    if not marker_names:  # No markers in the map - abort
        return conditions.RES_EXHAUSTED

    item_id = res['markerItem']

    # Synthesise the connection config used for the final trigger.
    conn_conf_sp = connections.Config(
        item_id=item_id + ':TRIGGER',
        output_act=Output.parse_name(res['triggerActivate', 'OnStartTouchAll']),
        output_deact=Output.parse_name(res['triggerDeactivate', 'OnEndTouchAll']),
    )

    # For Coop, we add a logic_coop_manager in the mix so both players can
    # be handled.
    coop_var: Optional[str]
    try:
        coop_var = res['coopVar']
    except LookupError:
        coop_var = conn_conf_coop = None
        coop_only_once = False
    else:
        coop_only_once = res.bool('coopOnce')
        conn_conf_coop = connections.Config(
            item_id=item_id + ':TRIGGER',
            output_act=Output.parse_name(res['coopActivate', 'OnChangeToAllTrue']),
            output_deact=Output.parse_name(res['coopDeactivate', 'OnChangeToAnyFalse']),
        )

    # Display preview overlays if it's preview mode, and the config is true
    pre_act: Optional[Output] = None
    pre_deact: Optional[Output] = None
    if not info.is_publishing and options.get_itemconf(res['previewConf', ''], False):
        preview_mat = res['previewMat', '']
        preview_inst_file = res['previewInst', '']
        preview_scale = res.float('previewScale', 0.25)
        # None if not found.
        with suppress(LookupError):
            pre_act = Output.parse(res.find_key('previewActivate'))
        with suppress(LookupError):
            pre_deact = Output.parse(res.find_key('previewDeactivate'))
    else:
        # Deactivate the preview_ options when publishing.
        preview_mat = preview_inst_file = ''
        preview_scale = 0.25

    # Now go through each brush.
    # We do while + pop to allow removing both names each loop through.
    todo_names = set(marker_names)
    while todo_names:
        targ = todo_names.pop()

        mark1 = connections.ITEMS.pop(targ)
        for conn in mark1.outputs:
            if conn.to_item.name in marker_names:
                mark2 = conn.to_item
                conn.remove()  # Delete this connection.
                todo_names.discard(mark2.name)
                del connections.ITEMS[mark2.name]
                break
        else:
            if not mark1.inputs:
                # If the item doesn't have any connections, 'connect'
                # it to itself so we'll generate a 1-block trigger.
                mark2 = mark1
            else:
                # It's a marker with an input, the other in the pair
                # will handle everything.
                # But reinstate it in ITEMS.
                connections.ITEMS[targ] = mark1
                continue

        inst1 = mark1.inst
        inst2 = mark2.inst

        is_coop = coop_var is not None and info.is_coop and (
            inst1.fixup.bool(coop_var) or
            inst2.fixup.bool(coop_var)
        )

        bbox_min, bbox_max = Vec.bbox(
            Vec.from_str(inst1['origin']),
            Vec.from_str(inst2['origin'])
        )
        origin = (bbox_max + bbox_min) / 2

        # Extend to the edge of the blocks.
        bbox_min -= 64
        bbox_max += 64

        out_ent = trig_ent = vmf.create_ent(
            classname='trigger_multiple',  # Default
            targetname=targ,
            origin=options.GLOBAL_ENTS_LOC(),
            angles='0 0 0',
        )
        trig_ent.solids = [
            vmf.make_prism(
                bbox_min,
                bbox_max,
                mat=consts.Tools.TRIGGER,
            ).solid,
        ]

        # Use 'keys' and 'localkeys' blocks to set all the other keyvalues.
        conditions.set_ent_keys(trig_ent, inst1, res)

        if is_coop:
            assert coop_var is not None and conn_conf_coop is not None
            trig_ent['spawnflags'] = '1'  # Clients
            trig_ent['classname'] = 'trigger_playerteam'

            out_ent = manager = vmf.create_ent(
                classname='logic_coop_manager',
                targetname=conditions.local_name(inst1, 'man'),
                origin=origin,
            )

            item = connections.Item(
                out_ent,
                conn_conf_coop,
                ind_style=mark1.ind_style,
            )

            if coop_only_once:
                # Kill all the ents when both players are present.
                manager.add_out(
                    Output('OnChangeToAllTrue', manager, 'Kill'),
                    Output('OnChangeToAllTrue', targ, 'Kill'),
                )
            trig_ent.add_out(
                Output('OnStartTouchBluePlayer', manager, 'SetStateATrue'),
                Output('OnStartTouchOrangePlayer', manager, 'SetStateBTrue'),
                Output('OnEndTouchBluePlayer', manager, 'SetStateAFalse'),
                Output('OnEndTouchOrangePlayer', manager, 'SetStateBFalse'),
            )
        else:
            item = connections.Item(
                trig_ent,
                conn_conf_sp,
                ind_style=mark1.ind_style,
            )

        # Register, and copy over all the antlines.
        connections.ITEMS[item.name] = item
        item.ind_panels = mark1.ind_panels | mark2.ind_panels
        item.antlines = mark1.antlines | mark2.antlines
        item.shape_signs = mark1.shape_signs + mark2.shape_signs

        if preview_mat:
            preview_brush = vmf.create_ent(
                classname='func_brush',
                parentname=targ,
                origin=origin,

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
                vmf.make_prism(
                    bbox_min + 0.5,
                    bbox_max - 0.5,
                    mat=preview_mat,
                ).solid,
            ]
            for face in preview_brush.sides():
                face.scale = preview_scale

        if preview_inst_file:
            pre_inst = conditions.add_inst(
                vmf,
                targetname=targ + '_preview',
                file=preview_inst_file,
                # Put it at the second marker, since that's usually
                # closest to antlines if present.
                origin=inst2['origin'],
            )

            if pre_act is not None and (out_act := item.output_act()) is not None:
                out = pre_act.copy()
                out.inst_out, out.output = out_act
                out.target = conditions.local_name(pre_inst, out.target)
                out_ent.add_out(out)
            if pre_deact is not None and (out_deact := item.output_deact()) is not None:
                out = pre_deact.copy()
                out.inst_out, out.output = out_deact
                out.target = conditions.local_name(pre_inst, out.target)
                out_ent.add_out(out)

        for conn in mark1.outputs | mark2.outputs:
            conn.from_item = item

    return conditions.RES_EXHAUSTED
