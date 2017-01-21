"""Results for generating additional instances.

"""
import conditions
import srctools
import vbsp
import vbsp_options
from conditions import (
    make_result, RES_EXHAUSTED,
    GLOBAL_INSTANCES,
)
from instanceLocs import resolve as resolve_inst
from srctools import Vec, Entity, Property


@make_result('addGlobal')
def res_add_global_inst(res: Property):
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
                srctools.conv_bool(res['allow_multiple', '0']) or
                res['file'] not in GLOBAL_INSTANCES):
            # By default we will skip adding the instance
            # if was already added - this is helpful for
            # items that add to original items, or to avoid
            # bugs.
            new_inst = Entity(vbsp.VMF, keys={
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
def res_add_overlay_inst(inst: Entity, res: Property):
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
            '<piston_bottom>' to offset based on the configuration.
            '<piston_start>' will set it to the starting position, and
            '<piston_end>' will set it to the ending position.
            of piston platform handles.
        angles: If set, overrides the base instance angles. This does
            not affect the offset property.
        fixup/localfixup: Keyvalues in this block will be copied to the
            overlay entity.
            If the value starts with $, the variable will be copied over.
            If this is present, copy_fixup will be disabled.
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
    if srctools.conv_bool(res['copy_fixup', '1']):
        if 'fixup' not in res and 'localfixup' not in res:
            # Copy the fixup values across from the original instance
            for fixup, value in inst.fixup.items():
                overlay_inst.fixup[fixup] = value

    conditions.set_ent_keys(overlay_inst.fixup, inst, res, 'fixup')

    if res.bool('move_outputs', False):
        overlay_inst.outputs = inst.outputs
        inst.outputs = []

    if 'offset' in res:
        folded_off = res['offset'].casefold()
        # Offset the overlay by the given distance
        # Some special placeholder values:
        if folded_off == '<piston_start>':
            if srctools.conv_bool(inst.fixup['$start_up', '']):
                folded_off = '<piston_top>'
            else:
                folded_off = '<piston_bottom>'
        elif folded_off == '<piston_end>':
            if srctools.conv_bool(inst.fixup['$start_up', '']):
                folded_off = '<piston_bottom>'
            else:
                folded_off = '<piston_top>'

        if folded_off == '<piston_bottom>':
            offset = Vec(
                z=srctools.conv_int(inst.fixup['$bottom_level']) * 128,
            )
        elif folded_off == '<piston_top>':
            offset = Vec(
                z=srctools.conv_int(inst.fixup['$top_level'], 1) * 128,
            )
        else:
            # Regular vector
            offset = Vec.from_str(conditions.resolve_value(inst, res['offset']))

        offset.rotate_by_str(
            inst['angles', '0 0 0']
        )
        overlay_inst['origin'] = (
            offset + Vec.from_str(inst['origin'])
        ).join(' ')
    return overlay_inst


@make_result('addCavePortrait')
def res_cave_portrait(inst: Entity, res: Property):
    """A variant of AddOverlay for adding Cave Portraits.

    If the set quote pack is not Cave Johnson, this does nothing.
    Otherwise, this overlays an instance, setting the $skin variable
    appropriately.
    """
    skin = vbsp_options.get(int, 'cave_port_skin')
    if skin is not None:
        new_inst = res_add_overlay_inst(inst, res)
        new_inst.fixup['$skin'] = skin
