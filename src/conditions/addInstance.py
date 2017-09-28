"""Results for generating additional instances.

"""
import conditions
import instanceLocs
import srctools
import vbsp
import vbsp_options
import utils
import comp_consts as const
from conditions import (
    make_result, meta_cond, RES_EXHAUSTED,
    GLOBAL_INSTANCES,
)
from srctools import Vec, Entity, Property, NoKeyError, VMF


COND_MOD_NAME = 'Instance Generation'

LOGGER = utils.getLogger(__name__, 'cond.addInstance')


@make_result('addGlobal')
def res_add_global_inst(res: Property):
    """Add one instance in a specific location.

    Options:
        allow_multiple: Allow multiple copies of this instance. If 0, the
            instance will not be added if it was already added.
        name: The targetname of the instance. IF blank, the instance will
              be given a name of the form 'inst_1234'.
        file: The filename for the instance.
        Angles: The orientation of the instance (defaults to '0 0 0').
        Fixup_style: The Fixup style for the instance. '0' (default) is
            Prefix, '1' is Suffix, and '2' is None.
        Position: The location of the instance. If not set, it will be placed
            in a 128x128 nodraw room somewhere in the map. Objects which can
            interact with nearby object should not be placed there.
    """
    if not res.has_children():
        res = Property('AddGlobal', [Property('File', res.value)])

    if res.bool('allow_multiple') or res['file'] not in GLOBAL_INSTANCES:
        # By default we will skip adding the instance
        # if was already added - this is helpful for
        # items that add to original items, or to avoid
        # bugs.
        new_inst = vbsp.VMF.create_ent(
            classname="func_instance",
            targetname=res['name', ''],
            file=instanceLocs.resolve_one(res['file'], error=True),
            angles=res['angles', '0 0 0'],
            fixup_style=res['fixup_style', '0'],
        )
        try:
            new_inst['origin'] = res['position']
        except IndexError:
            new_inst['origin'] = vbsp_options.get(Vec, 'global_ents_loc')
        GLOBAL_INSTANCES.add(res['file'])
        if new_inst['targetname'] == '':
            new_inst['targetname'] = "inst_"
            new_inst.make_unique()
    return RES_EXHAUSTED


@make_result('addOverlay', 'overlayinst')
def res_add_overlay_inst(inst: Entity, res: Property):
    """Add another instance on top of this one.

    If a single value, this sets only the filename.
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

    if not res.has_children():
        # Use all the defaults.
        res = Property('AddOverlay', [
            Property('File', res.value)
        ])

    angle = res['angles', inst['angles', '0 0 0']]

    orig_name = conditions.resolve_value(inst, res['file', ''])
    filename = instanceLocs.resolve_one(orig_name)

    if not filename:
        if not res.bool('silentLookup'):
            LOGGER.warning('Bad filename for "{}" when adding overlay!', orig_name)
        # Don't bother making a overlay which will be deleted.
        return

    overlay_inst = vbsp.VMF.create_ent(
        classname='func_instance',
        targetname=inst['targetname', ''],
        file=filename,
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
            if inst.fixup.bool(const.FixupVars.PIST_IS_UP):
                folded_off = '<piston_top>'
            else:
                folded_off = '<piston_bottom>'
        elif folded_off == '<piston_end>':
            if inst.fixup.bool(const.FixupVars.PIST_IS_UP):
                folded_off = '<piston_bottom>'
            else:
                folded_off = '<piston_top>'

        if folded_off == '<piston_bottom>':
            offset = Vec(
                z=inst.fixup.int(const.FixupVars.PIST_BTM) * 128,
            )
        elif folded_off == '<piston_top>':
            offset = Vec(
                z=inst.fixup.int(const.FixupVars.PIST_TOP) * 128,
            )
        else:
            # Regular vector
            offset = Vec.from_str(conditions.resolve_value(inst, res['offset']))

        offset.rotate_by_str(
            inst['angles', '0 0 0']
        )
        overlay_inst['origin'] = offset + Vec.from_str(inst['origin'])
    return overlay_inst


@make_result('addCavePortrait')
def res_cave_portrait(inst: Entity, res: Property):
    """A variant of AddOverlay for adding Cave Portraits.

    If the set quote pack is not Cave Johnson, this does nothing.
    Otherwise, this overlays an instance, setting the $skin variable
    appropriately. Config values match that of addOverlay.
    """
    skin = vbsp_options.get(int, 'cave_port_skin')
    if skin is not None:
        new_inst = res_add_overlay_inst(inst, res)
        if new_inst:
            new_inst.fixup['$skin'] = skin
