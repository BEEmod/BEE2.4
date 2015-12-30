"""Results for generating additional instances.

"""
from conditions import (
    make_result, make_result_setup, RES_EXHAUSTED,
    GLOBAL_INSTANCES,
)
from property_parser import Property
from instanceLocs import resolve as resolve_inst
from utils import Vec
import utils
import vmfLib as VLib
import vbsp


@make_result('addGlobal')
def res_add_global_inst(_, res):
    """Add one instance in a location.

    Options:
        allow_multiple: Allow multiple copies of this instance. If 0, the
            instance will not be added if it was already added.
        name: The targetname of the instance. IF blank, the instance will
              be given a name of the form 'inst_1234'.
        file: The filename for the instance.
        Angles: The orientation of the instance (defaults to '0 0 0').
        Origin: The location of the instance (defaults to '0 0 -10000').
        Fixup_style: The Fixup style for the instance. '0' (default) is
            Prefix, '1' is Suffix, and '2' is None.
    """
    if res.value is not None:
        if (
                utils.conv_bool(res['allow_multiple', '0']) or
                res['file'] not in GLOBAL_INSTANCES):
            # By default we will skip adding the instance
            # if was already added - this is helpful for
            # items that add to original items, or to avoid
            # bugs.
            new_inst = VLib.Entity(vbsp.VMF, keys={
                "classname": "func_instance",
                "targetname": res['name', ''],
                "file": resolve_inst(res['file'])[0],
                "angles": res['angles', '0 0 0'],
                "origin": res['position', '0 0 -10000'],
                "fixup_style": res['fixup_style', '0'],
                })
            GLOBAL_INSTANCES.add(res['file'])
            if new_inst['targetname'] == '':
                new_inst['targetname'] = "inst_"
                new_inst.make_unique()
            vbsp.VMF.add_ent(new_inst)
    return RES_EXHAUSTED


@make_result('addOverlay', 'overlayinst')
def res_add_overlay_inst(inst, res):
    """Add another instance on top of this one.

    Values:
        File: The filename.
        Fixup Style: The Fixup style for the instance. '0' (default) is
            Prefix, '1' is Suffix, and '2' is None.
        Copy_Fixup: If true, all the $replace values from the original
            instance will be copied over.
        move_outputs: If true, outputs will be moved to this instance.
        offset: The offset (relative to the base) that the instance
            will be placed. Can be set to '<piston_top>' and
            '<piston_bottom>' to offset based on the configuration
            of piston platform handles.
        angles: If set, overrides the base instance angles. This does
            not affect the offset property.
        fixup: Keyvalues in this block will be copied to the overlay entity.
            If the value starts with $, the variable will be copied over.
            If this is present, copy_fixup will be disabled
    """

    angle = res['angles', inst['angles', '0 0 0']]
    overlay_inst = vbsp.VMF.create_ent(
        classname='func_instance',
        targetname=inst['targetname', ''],
        file=resolve_inst(res['file', ''])[0],
        angles=angle,
        origin=inst['origin'],
        fixup_style=res['fixup_style', '0'],
    )
    # Don't run if the fixup block exists..
    if utils.conv_bool(res['copy_fixup', '1']) and 'fixup' not in res:
        # Copy the fixup values across from the original instance
        for fixup, value in inst.fixup.items():
            overlay_inst.fixup[fixup] = value

    # Copy additional fixup values over
    for prop in res.find_key('Fixup', []):  # type: Property
        if prop.value.startswith('$'):
            overlay_inst.fixup[prop.real_name] = inst.fixup[prop.value]
        else:
            overlay_inst.fixup[prop.real_name] = prop.value

    if utils.conv_bool(res['move_outputs', '0']):
        overlay_inst.outputs = inst.outputs
        inst.outputs = []

    if 'offset' in res:
        folded_off = res['offset'].casefold()
        # Offset the overlay by the given distance
        # Some special placeholder values:
        if folded_off == '<piston_bottom>':
            offset = Vec(
                z=utils.conv_int(inst.fixup['$bottom_level']) * 128,
            )
        elif folded_off == '<piston_top>':
            offset = Vec(
                z=utils.conv_int(inst.fixup['$top_level'], 1) * 128,
            )
        else:
            # Regular vector
            offset = Vec.from_str(res['offset'])

        offset.rotate_by_str(
            inst['angles', '0 0 0']
        )
        overlay_inst['origin'] = (
            offset + Vec.from_str(inst['origin'])
        ).join(' ')
    return overlay_inst


@make_result('addCavePortrait')
def res_cave_portrait(inst, res):
    """A variant of AddOverlay for adding Cave Portraits.

    If the set quote pack is not Cave Johnson, this does nothing.
    Otherwise, this overlays an instance, setting the $skin variable
    appropriately.
    """
    import vbsp
    skin = vbsp.get_opt('cave_port_skin')
    if skin != '':
        new_inst = res_add_overlay_inst(inst, res)
        new_inst.fixup['$skin'] = skin


@make_result('OffsetInst', 'offsetinstance')
def res_translate_inst(inst, res):
    """Translate the instance locally by the given amount.

    The special values <piston>, <piston_bottom> and <piston_top> can be
    used to offset it based on the starting position, bottom or top position
    of a piston platform.
    """
    folded_val = res.value.casefold()
    if folded_val == '<piston>':
        folded_val = (
            '<piston_top>' if
            utils.conv_bool(inst.fixup['$start_up'])
            else '<piston_bottom>'
        )

    if folded_val == '<piston_top>':
        val = Vec(z=128 * utils.conv_int(inst.fixup['$top_level', '1'], 1))
    elif folded_val == '<piston_bottom>':
        val = Vec(z=128 * utils.conv_int(inst.fixup['$bottom_level', '0'], 0))
    else:
        val = Vec.from_str(res.value)

    offset = val.rotate_by_str(inst['angles'])
    inst['origin'] = (offset + Vec.from_str(inst['origin'])).join(' ')
