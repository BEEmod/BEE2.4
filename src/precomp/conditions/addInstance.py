"""Results for generating additional instances.

"""
from typing import Optional
from srctools import Vec, Entity, Property, VMF, Angle
import srctools.logger

from precomp import instanceLocs, options, conditions
from precomp.conditions import make_result, RES_EXHAUSTED, GLOBAL_INSTANCES


COND_MOD_NAME = 'Instance Generation'

LOGGER = srctools.logger.get_logger(__name__, 'cond.addInstance')


@make_result('addGlobal')
def res_add_global_inst(vmf: VMF, res: Property):
    """Add one instance in a specific location.

    Options:

    - `allow_multiple`: Allow multiple copies of this instance. If 0, the
        instance will not be added if it was already added.
    - `name`: The targetname of the instance. If blank, the instance will
          be given a name of the form `inst_1234`.
    - `file`: The filename for the instance.
    - `angles`: The orientation of the instance (defaults to `0 0 0`).
    - `fixup_style`: The Fixup style for the instance. `0` (default) is
        Prefix, `1` is Suffix, and `2` is None.
    - `position`: The location of the instance. If not set, it will be placed
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
        new_inst = vmf.create_ent(
            classname="func_instance",
            targetname=res['name', ''],
            file=instanceLocs.resolve_one(res['file'], error=True),
            angles=res['angles', '0 0 0'],
            fixup_style=res['fixup_style', '0'],
        )
        try:
            new_inst['origin'] = res['position']
        except IndexError:
            new_inst['origin'] = options.get(Vec, 'global_ents_loc')
        GLOBAL_INSTANCES.add(res['file'])
        if new_inst['targetname'] == '':
            new_inst['targetname'] = "inst_"
            new_inst.make_unique()
    return RES_EXHAUSTED


@make_result('addOverlay', 'overlayinst')
def res_add_overlay_inst(vmf: VMF, inst: Entity, res: Property) -> Optional[Entity]:
    """Add another instance on top of this one.

    If a single value, this sets only the filename.
    Values:

    - `file`: The filename.
    - `fixup_style`: The Fixup style for the instance. '0' (default) is
            Prefix, '1' is Suffix, and '2' is None.
    - `copy_fixup`: If true, all the `$replace` values from the original
            instance will be copied over.
    - `move_outputs`: If true, outputs will be moved to this instance.
    - `offset`: The offset (relative to the base) that the instance
        will be placed. Can be set to `<piston_top>` and
        `<piston_bottom>` to offset based on the configuration.
        `<piston_start>` will set it to the starting position, and
        `<piston_end>` will set it to the ending position of the Piston
        Platform's handles.
    - `rotation`: Rotate the instance by this amount.
    - `angles`: If set, overrides `rotation` and the instance angles entirely.
    - `fixup`/`localfixup`: Keyvalues in this block will be copied to the
            overlay entity.
        - If the value starts with `$`, the variable will be copied over.
        - If this is present, `copy_fixup` will be disabled.
    """

    if not res.has_children():
        # Use all the defaults.
        res = Property('AddOverlay', [
            Property('File', res.value)
        ])

    if 'angles' in res:
        angles = Angle.from_str(res['angles'])
        if 'rotation' in res:
            LOGGER.warning('"angles" option overrides "rotation"!')
    else:
        angles = Angle.from_str(res['rotation', '0 0 0'])
        angles @= Angle.from_str(inst['angles', '0 0 0'])

    orig_name = conditions.resolve_value(inst, res['file', ''])
    filename = instanceLocs.resolve_one(orig_name)

    if not filename:
        if not res.bool('silentLookup'):
            LOGGER.warning('Bad filename for "{}" when adding overlay!', orig_name)
        # Don't bother making a overlay which will be deleted.
        return None

    overlay_inst = vmf.create_ent(
        classname='func_instance',
        targetname=inst['targetname', ''],
        file=filename,
        angles=angles,
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
        overlay_inst['origin'] = conditions.resolve_offset(inst, res['offset'])

    return overlay_inst


@make_result('addCavePortrait')
def res_cave_portrait(vmf: VMF, inst: Entity, res: Property) -> None:
    """A variant of AddOverlay for adding Cave Portraits.

    If the set quote pack is not Cave Johnson, this does nothing.
    Otherwise, this overlays an instance, setting the $skin variable
    appropriately. Config values match that of addOverlay.
    """
    skin = options.get(int, 'cave_port_skin')
    if skin is not None:
        new_inst = res_add_overlay_inst(vmf, inst, res)
        if new_inst is not None:
            new_inst.fixup['$skin'] = skin
