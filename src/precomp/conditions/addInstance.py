"""Results for generating additional instances.

"""
from typing import Optional, Callable
from srctools import Vec, Entity, Property, VMF, Angle
import srctools.logger

from precomp import instanceLocs, options, collisions, conditions, rand, corridor


COND_MOD_NAME = 'Instance Generation'

LOGGER = srctools.logger.get_logger(__name__, 'cond.addInstance')


@conditions.make_result('addGlobal')
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
    file = instanceLocs.resolve_one(res['file'], error=True)

    if res.bool('allow_multiple') or file.casefold() not in conditions.GLOBAL_INSTANCES:
        # By default we will skip adding the instance
        # if was already added - this is helpful for
        # items that add to original items, or to avoid
        # bugs.
        new_inst = vmf.create_ent(
            classname="func_instance",
            targetname=res['name', ''],
            file=file,
            angles=res['angles', '0 0 0'],
            fixup_style=res['fixup_style', '0'],
        )
        try:
            new_inst['origin'] = res['position']
        except IndexError:
            new_inst['origin'] = options.get(Vec, 'global_ents_loc')
        conditions.GLOBAL_INSTANCES.add(file.casefold())
        conditions.ALL_INST.add(file.casefold())
        if new_inst['targetname'] == '':
            new_inst['targetname'] = "inst_"
            new_inst.make_unique()
    return conditions.RES_EXHAUSTED


@conditions.make_result('addOverlay', 'overlayinst')
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

    overlay_inst = conditions.add_inst(
        vmf,
        targetname=inst['targetname', ''],
        file=filename,
        angles=angles,
        origin=inst['origin'],
        fixup_style=res.int('fixup_style'),
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


@conditions.make_result('addShuffleGroup')
def res_add_shuffle_group(
    vmf: VMF, coll: collisions.Collisions, info: corridor.Info, res: Property,
) -> Callable[[Entity], None]:
    """Pick from a pool of instances to randomise decoration.

    For each sub-condition that succeeds, a random instance is placed, with
    a fixup set to a value corresponding to the condition.

    Parameters:
        - Var: The fixup variable to set on each item. This is used to tweak it
          to match the condition.
        - Conditions: Each value here is the value to produce if this instance
          is required. The contents of the block is then a condition flag to
          check.
        - Pool: A list of instances to randomly allocate to the conditions. There
          should be at least as many pool values as there are conditions.
        - Seed: Value to modify the seed with before placing.
    """
    conf_variable = res['var']
    conf_seed = 'sg' + res['seed', '']
    conf_pools: dict[str, list[str]] = {}
    for prop in res.find_children('pool'):
        if prop.has_children():
            raise ValueError('Instances in pool cannot be a property block!')
        conf_pools.setdefault(prop.name, []).append(prop.value)

    # (flag, value, pools)
    conf_selectors: list[tuple[list[Property], str, frozenset[str]]] = []
    for prop in res.find_all('selector'):
        conf_value = prop['value', '']
        conf_flags = list(prop.find_children('conditions'))
        try:
            picked_pools = prop['pools'].casefold().split()
        except LookupError:
            picked_pools = frozenset(conf_pools)
        else:
            for pool_name in picked_pools:
                if pool_name not in conf_pools:
                    raise ValueError(f'Unknown pool name {pool_name}!')
        conf_selectors.append((conf_flags, conf_value, frozenset(picked_pools)))

    all_pools = [
        (name, inst)
        for name, instances in conf_pools.items()
        for inst in instances
    ]
    all_pools.sort()  # Ensure consistent order.

    def add_group(inst: Entity) -> None:
        """Place the group."""
        rng = rand.seed(b'shufflegroup', conf_seed, inst)
        pools = all_pools.copy()
        for (flags, value, potential_pools) in conf_selectors:
            for flag in flags:
                if not conditions.check_flag(flag, coll, info, inst):
                    break
            else:  # Succeeded.
                allowed_inst = [
                    (name, inst)
                    for (name, inst) in pools
                    if name in potential_pools
                ]
                name, filename = rng.choice(allowed_inst)
                pools.remove((name, filename))
                conditions.add_inst(
                    vmf,
                    targetname=inst['targetname'],
                    file=filename,
                    angles=inst['angles'],
                    origin=inst['origin'],
                ).fixup[conf_variable] = value
    return add_group


@conditions.make_result('addCavePortrait')
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
