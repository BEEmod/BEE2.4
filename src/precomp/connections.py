"""Manages PeTI item connections.

This allows checking which items are connected to what, and also regenerates
the outputs with optimisations and custom settings.
"""
from collections import defaultdict

from typing_extensions import assert_never

from connections import InputType, FeatureMode, Config, ConnType, OutNames
from srctools import conv_bool
from srctools.math import Vec, Angle, format_float
from srctools.vmf import VMF, EntityFixup, Entity, Output
from precomp.antlines import Antline, AntType, IndicatorStyle, PanelSwitchingStyle
from precomp import instance_traits, options, packing, conditions
import editoritems
import consts
import srctools.logger

from typing import Optional, Iterable, Dict, List, Sequence, Set, Tuple, Iterator, Union
import user_errors


COND_MOD_NAME = "Item Connections"

LOGGER = srctools.logger.get_logger(__name__)

ITEM_TYPES: Dict[str, Optional[Config]] = {}

# Targetname -> item
ITEMS: Dict[str, 'Item'] = {}

# We need different names for each kind of input type, so they don't
# interfere with each other. We use the 'inst_local' pattern not 'inst-local'
# deliberately so the actual item can't affect the IO input.
COUNTER_NAME: Dict[str, str] = {
    consts.FixupVars.CONN_COUNT: '_counter',
    consts.FixupVars.CONN_COUNT_TBEAM: '_counter_polarity',
    consts.FixupVars.BEE_CONN_COUNT_A: '_counter_a',
    consts.FixupVars.BEE_CONN_COUNT_B: '_counter_b',
}


# A script to play timer sounds - avoids needing the ambient_generic.
TIMER_SOUND_SCRIPT = '''
function Precache() {{
    self.PrecacheSoundScript("{snd}");
}}
function snd() {{
    self.EmitSound("{snd}");
}}
'''

CONN_NAMES = {
    ConnType.DEFAULT: 'DEF',
    ConnType.PRIMARY: 'A',
    ConnType.SECONDARY: 'B',
    ConnType.BOTH: 'A+B',
}

# The order signs are used in maps.
SIGN_ORDER = [
    consts.Signage.SHAPE_SQUARE,
    consts.Signage.SHAPE_CROSS,
    consts.Signage.SHAPE_DOT,
    consts.Signage.SHAPE_MOON,
    consts.Signage.SHAPE_SLASH,
    consts.Signage.SHAPE_TRIANGLE,
    consts.Signage.SHAPE_SINE,
    consts.Signage.SHAPE_STAR,
    consts.Signage.SHAPE_CIRCLE,
    consts.Signage.SHAPE_WAVY
]

SIGN_ORDER_LOOKUP: Dict[Union[consts.Signage, str], int] = {
    sign: index
    for index, sign in
    enumerate(SIGN_ORDER)
}


class ShapeSignage:
    """Represents a pair of signage shapes."""
    __slots__ = (
        'overlays',
        'name',
        'index',
        'repeat_group',
        'overlay_frames',
    )

    def __init__(self, overlays: List[Entity]):
        if not overlays:
            raise ValueError('No overlays')
        self.overlays = list(overlays)
        self.name = self.overlays[0]['targetname']

        # Index in SIGN_ORDER
        mat = self.overlays[0]['material']
        self.index = SIGN_ORDER_LOOKUP[mat]

        # Not useful...
        for overlay in self.overlays:
            del overlay['targetname']

        # Groups these into repeats of the shapes.
        self.repeat_group = 0

        self.overlay_frames = []  # type: List[Entity]

    def __iter__(self) -> Iterator[Entity]:
        return iter(self.overlays)

    def __lt__(self, other: object) -> bool:
        """Allow sorting in a consistent order."""
        if isinstance(other, ShapeSignage):
            return self.name < other.name
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        """Allow sorting in a consistent order."""
        if isinstance(other, ShapeSignage):
            return self.name > other.name
        return NotImplemented


class Item:
    """Represents one item/instance with IO."""
    __slots__ = [
        'inst', 'config', '_kv_setters',
        'ind_panels',
        'antlines', 'shape_signs',
        'ind_style',
        'timer',
        'inputs', 'outputs',
        'enable_cmd', 'disable_cmd',
        'sec_enable_cmd', 'sec_disable_cmd',
        'ant_toggle_var',
    ]

    def __init__(
        self,
        inst: Entity,
        item_type: Config,
        *,  # Don't mix up antlines!
        ind_style: IndicatorStyle,
        panels: Iterable[Entity]=(),
        antlines: Iterable[Antline]=(),
        shape_signs: Iterable[ShapeSignage]=(),
        timer_count: int=None,
        ant_toggle_var: str='',
    ):
        self.inst = inst
        self.config = item_type

        # Associated indicator panels and antlines
        self.ind_panels = set(panels)  # type: Set[Entity]
        self.antlines = set(antlines)
        self.shape_signs = list(shape_signs)

        # And the style to use for the antlines.
        self.ind_style = ind_style

        # If set, the item has special antlines. This is a fixup var,
        # which gets the antline name filled in for us.
        self.ant_toggle_var = ant_toggle_var

        # None = Infinite/normal.
        self.timer = timer_count

        # From this item
        self.outputs: Set[Connection] = set()
        # To this item
        self.inputs: Set[Connection] = set()

        # Copy these, allowing them to be altered for a specific item.
        self.enable_cmd = item_type.enable_cmd
        self.disable_cmd = item_type.disable_cmd

        self.sec_enable_cmd = item_type.sec_enable_cmd
        self.sec_disable_cmd = item_type.sec_disable_cmd

        # The postcompiler entities to add outputs to the instance.
        # This eliminates needing io_proxies.
        # The key is the name of the local ent.
        self._kv_setters: Dict[str, Entity] = {}

        assert self.name, 'Blank name!'

    @property
    def ant_floor_style(self) -> AntType:
        return self.ind_style.floor

    @property
    def ant_wall_style(self) -> AntType:
        return self.ind_style.wall

    def __repr__(self) -> str:
        return '<Item {}: "{}">'.format(self.config.id, self.name)

    @property
    def traits(self) -> Set[str]:
        """Return the set of instance traits for the item."""
        return instance_traits.get(self.inst)

    @property
    def is_logic(self) -> bool:
        """Check if the input type is a logic type."""
        return self.config.input_type.is_logic

    @property
    def name(self) -> str:
        """Return the targetname of the item."""
        return self.inst['targetname']

    @name.setter
    def name(self, value: str) -> None:
        """Set the targetname of the item."""
        self.inst['targetname'] = value

    def output_act(self) -> Optional[Tuple[Optional[str], str]]:
        """Return the output used when this is activated."""
        if self.config.spawn_fire.valid(bool(self.inputs)) and self.is_logic:
            return None, 'OnUser2'

        if self.config.input_type is InputType.DAISYCHAIN:
            if self.inputs:
                return None, consts.COUNTER_AND_ON
        elif self.config.input_type is InputType.AND_LOGIC:
            return None, consts.COUNTER_AND_ON
        elif self.config.input_type is InputType.OR_LOGIC:
            return None, consts.COUNTER_OR_ON

        return self.config.output_act

    def output_deact(self) -> Optional[Tuple[Optional[str], str]]:
        """Return the output to use when this is deactivated."""
        if self.config.spawn_fire.valid(bool(self.inputs)) and self.is_logic:
            return None, 'OnUser1'

        if self.config.input_type is InputType.DAISYCHAIN:
            if self.inputs:
                return None, consts.COUNTER_AND_OFF
        elif self.config.input_type is InputType.AND_LOGIC:
            return None, consts.COUNTER_AND_OFF
        elif self.config.input_type is InputType.OR_LOGIC:
            return None, consts.COUNTER_OR_OFF

        return self.config.output_deact

    def delete_antlines(self) -> None:
        """Delete the antlines and checkmarks outputting from this item."""
        for ent in self.ind_panels:
            ent.remove()
        for sign in self.shape_signs:
            for ent in sign.overlays:
                ent.remove()

        self.antlines.clear()
        self.ind_panels.clear()
        self.shape_signs.clear()

    def transfer_antlines(self, item: 'Item') -> None:
        """Transfer the antlines and checkmarks from this item to another."""
        item.antlines.update(self.antlines)
        item.ind_panels.update(self.ind_panels)
        item.shape_signs.extend(self.shape_signs)

        self.antlines.clear()
        self.ind_panels.clear()
        self.shape_signs.clear()

    def add_io_command(
        self,
        output: Optional[Tuple[Optional[str], str]],
        target: Union[Entity, str],
        inp_cmd: str,
        params: str = '',
        delay: float = 0.0,
        times: int = -1,
        inst_in: Optional[str]=None,
    ) -> None:
        """Add an output to this item.

        For convenience, if the output is None this does nothing.
        """
        if output is None:
            return

        out_name, out_cmd = output

        # Dump the None.
        out_name = self.inst.fixup.substitute(out_name or '')

        if isinstance(target, Entity):
            target = target['targetname']

        try:
            kv_setter = self._kv_setters[out_name]
        except KeyError:
            if out_name:
                full_name = conditions.local_name(self.inst, out_name)
            else:
                full_name = self.name
            kv_setter = self._kv_setters[out_name] = self.inst.map.create_ent(
                'comp_kv_setter',
                origin=self.inst['origin'],
                target=full_name,
            )

        kv_setter.add_out(Output(
            self.inst.fixup.substitute(out_cmd),
            target,
            inp_cmd,
            params,
            delay=delay,
            times=times,
            inst_in=inst_in,
        ))


class Connection:
    """Represents a connection between two items."""

    __slots__ = [
        '_to', '_from', 'type', 'outputs',
    ]
    def __init__(
        self,
        to_item: Item,   # Item this is triggering
        from_item: Item,  # Item this comes from
        conn_type=ConnType.DEFAULT,
        outputs: Iterable[Output]=(),
    ) -> None:
        self._to = to_item
        self._from = from_item
        self.type = conn_type
        self.outputs = list(outputs)

    def __repr__(self) -> str:
        return '<Connection {} {} -> {}>'.format(
            CONN_NAMES[self.type],
            self._from.name,
            self._to.name,
        )

    def add(self) -> None:
        """Add this to the directories."""
        self._from.outputs.add(self)
        self._to.inputs.add(self)

    def remove(self) -> None:
        """Remove this from the directories."""
        self._from.outputs.discard(self)
        self._to.inputs.discard(self)

    @property
    def to_item(self) -> Item:
        """The item this connection is going to."""
        return self._to

    @to_item.setter
    def to_item(self, item: Item):
        self._to.inputs.discard(self)
        self._to = item
        item.inputs.add(self)

    @property
    def from_item(self) -> Item:
        """The item this connection comes from."""
        return self._from

    @from_item.setter
    def from_item(self, item: Item) -> None:
        self._from.outputs.discard(self)
        self._from = item
        item.outputs.add(self)


def collapse_item(item: Item) -> None:
    """Remove an item with a single input, transferring all IO."""
    input_conn: Connection
    try:
        [input_conn] = item.inputs
        input_item = input_conn.from_item
    except ValueError:
        raise ValueError('Too many inputs for "{}"!'.format(item.name))

    LOGGER.debug('Merging "{}" into "{}"...', item.name, input_item.name)

    input_conn.remove()

    input_item.antlines |= item.antlines
    input_item.ind_panels |= item.ind_panels
    input_item.shape_signs += item.shape_signs

    item.antlines.clear()
    item.ind_panels.clear()
    item.shape_signs.clear()

    for conn in list(item.outputs):
        conn.from_item = input_item

    del ITEMS[item.name]
    item.inst.remove()


def read_configs(all_items: Iterable[editoritems.Item]) -> None:
    """Load our connection configuration from the config files."""
    for item in all_items:
        if item.id.casefold() in ITEM_TYPES:
            raise ValueError('Duplicate item type "{}"'.format(item.id))
        if item.conn_config is None and (item.force_input or item.force_output):
            # The item has no config, but it does force input/output.
            # Generate a blank config so the Item is created.
            ITEM_TYPES[item.id.casefold()] = Config(item.id)
        else:
            ITEM_TYPES[item.id.casefold()] = item.conn_config

    # These must exist.
    for item_id in ['item_indicator_panel', 'item_indicator_panel_timer']:
        if ITEM_TYPES.get(item_id) is None:
            raise user_errors.UserError(
                user_errors.TOK_CONNECTION_REQUIRED_ITEM.format(item=item_id.upper())
            )


def calc_connections(
    vmf: VMF,
    antlines: Dict[str, List[Antline]],
    shape_frame_tex: List[str],
    enable_shape_frame: bool,
    ind_style: IndicatorStyle,
) -> None:
    """Compute item connections from the map file.

    This also fixes cases where items have incorrect checkmark/timer signs.
    Instance Traits must have been calculated.
    It also applies frames to shape signage to distinguish repeats.
    """
    # First we want to match targetnames to item types.
    toggles: dict[str, Entity] = {}
    # Accumulate all the signs into groups, so the list should be 2-long:
    # sign_shapes[name, material][0/1]
    sign_shape_overlays: dict[tuple[str, str], list[Entity]] = defaultdict(list)

    # Indicator panels
    panels: dict[str, Entity] = {}

    # We only need to pay attention for TBeams, other items we can
    # just detect any output.
    tbeam_polarity = {OutNames.IN_SEC_ACT, OutNames.IN_SEC_DEACT}
    # Also applies to other items, but not needed for this analysis.
    tbeam_io = {OutNames.IN_ACT, OutNames.IN_DEACT}

    # Corridors have a numeric suffix depending on the corridor index.
    # That's no longer valid, so we want to strip it.
    corridors: list[Entity] = []

    for inst in vmf.by_class['func_instance']:
        inst_name = inst['targetname']
        # Ignore to-be-removed instances, or those which won't have I/O...
        if not inst_name or not inst['file']:
            continue

        traits = instance_traits.get(inst)

        if 'indicator_toggle' in traits:
            toggles[inst_name] = inst
            # We do not use toggle instances.
            inst.remove()
        elif 'indicator_panel' in traits:
            panels[inst_name] = inst
        elif 'fizzler_model' in traits:
            # Ignore fizzler models - they shouldn't have the connections.
            # Just the base itself.
            pass
        else:
            # Normal item.
            item_id = instance_traits.get_item_id(inst)
            if item_id is None:
                LOGGER.warning('No item ID for "{}"!', inst)
                continue
            try:
                item_type = ITEM_TYPES[item_id.casefold()]
            except KeyError:
                LOGGER.warning('No item type for "{}"!', item_id)
                continue
            if item_type is None:
                # It exists, but has no I/O.
                continue

            # Pass in the defaults for antline styles.
            ITEMS[inst_name] = Item(
                inst, item_type,
                ind_style=ind_style,
            )

            # Strip off the original connection count variables, these are
            # invalid.
            if item_type.input_type is InputType.DUAL:
                del inst.fixup[consts.FixupVars.CONN_COUNT]
                del inst.fixup[consts.FixupVars.CONN_COUNT_TBEAM]

            if 'corridor' in traits:
                corridors.append(inst)

    for over in vmf.by_class['info_overlay']:
        name = over['targetname']
        mat = over['material']
        if mat in SIGN_ORDER_LOOKUP:
            sign_shape_overlays[name, mat.casefold()].append(over)

    # Name -> signs pairs
    sign_shapes = defaultdict(list)  # type: Dict[str, List[ShapeSignage]]
    # By material index, for group frames.
    sign_shape_by_index = defaultdict(list)  # type: Dict[int, List[ShapeSignage]]
    for (name, mat), sign_pair in sign_shape_overlays.items():
        # It's possible - but rare - for more than 2 to be in a pair.
        # We have to just treat them as all in their 'pair'.
        # Shouldn't be an issue, it'll be both from one item...
        shape = ShapeSignage(sign_pair)
        sign_shapes[name].append(shape)
        sign_shape_by_index[shape.index].append(shape)

    # Now build the connections and items.
    for item in ITEMS.values():
        input_items: List[Item] = []  # Instances we trigger
        inputs: Dict[str, List[Output]] = defaultdict(list)

        if item.inst.outputs and item.config is None:
            raise ValueError(
                'No connections for item "{}", '
                'but outputs in the map!'.format(
                    instance_traits.get_item_id(item.inst)
                )
            )

        for out in item.inst.outputs:
            inputs[out.target].append(out)

        # Remove the original outputs, we've consumed those already.
        item.inst.outputs.clear()

        # Pre-set the timer value, for items without antlines but with an output.
        if consts.FixupVars.TIM_DELAY in item.inst.fixup:
            if item.config.output_act or item.config.output_deact:
                item.timer = tim = item.inst.fixup.int(consts.FixupVars.TIM_DELAY)
                if not (1 <= tim <= 30):
                    # These would be infinite.
                    item.timer = None

        for out_name in inputs:
            # Fizzler base -> model/brush outputs, ignore these (discard).
            # fizzler.py will regenerate as needed.
            if out_name.rstrip('0123456789').endswith(('_modelStart', '_modelEnd', '_brush')):
                continue

            if out_name in toggles:
                inst_toggle = toggles[out_name]
                try:
                    item.antlines.update(
                        antlines[inst_toggle.fixup['indicator_name']]
                    )
                except KeyError:
                    pass
            elif out_name in panels:
                pan = panels[out_name]
                item.ind_panels.add(pan)
                if pan.fixup.bool(consts.FixupVars.TIM_ENABLED):
                    item.timer = tim = pan.fixup.int(consts.FixupVars.TIM_DELAY)
                    if not (1 <= tim <= 30):
                        # These would be infinite.
                        item.timer = None
                else:
                    item.timer = None
            else:
                try:
                    inp_item = ITEMS[out_name]
                except KeyError:
                    raise user_errors.UserError(
                        user_errors.TOK_CONNECTIONS_UNKNOWN_INSTANCE.format(item=out_name)
                    )
                else:
                    input_items.append(inp_item)
                    if inp_item.config is None:
                        raise user_errors.UserError(
                            user_errors.TOK_CONNECTIONS_INSTANCE_NO_IO.format(
                                inst=inp_item.inst['filename'],
                            )
                        )

        for inp_item in input_items:
            # Default A/B type.
            conn_type = ConnType.DEFAULT
            in_outputs = inputs[inp_item.name]

            if inp_item.config.id == 'ITEM_TBEAM':
                # It's a funnel - we need to figure out if this is polarity,
                # or normal on/off.
                for out in in_outputs:
                    try:
                        funnel_out = OutNames(out.input.upper())
                    except ValueError:
                        LOGGER.warning('Unknown input for funnel: {}', out)
                        continue
                    if funnel_out in tbeam_polarity:
                        conn_type = ConnType.TBEAM_DIR
                        break
                    elif funnel_out in tbeam_io:
                        conn_type = ConnType.TBEAM_IO
                        break
                    else:
                        raise AssertionError(f'Input is an output name? {out}')
                else:
                    raise ValueError(
                        f'Excursion Funnel "{inp_item.name}" has inputs, but no '
                        f'valid types: {[out.input for out in in_outputs]}'
                    )

            conn = Connection(
                inp_item,
                item,
                conn_type,
                in_outputs,
            )
            conn.add()

    # Make signage frames
    shape_frame_tex = [mat for mat in shape_frame_tex if mat]
    if shape_frame_tex and enable_shape_frame:
        for shape_mat in sign_shape_by_index.values():
            # Sort so which gets what frame is consistent.
            shape_mat.sort()
            for index, shape in enumerate(shape_mat):
                shape.repeat_group = index
                if index == 0:
                    continue  # First, no frames..
                frame_mat = shape_frame_tex[(index-1) % len(shape_frame_tex)]

                for overlay in shape:
                    frame = overlay.copy()
                    shape.overlay_frames.append(frame)
                    vmf.add_ent(frame)
                    frame['material'] = frame_mat
                    frame['renderorder'] = 1  # On top

    # Now we've computed everything, strip numbers.
    for inst in corridors:
        old_name = inst['targetname']
        new_name = inst['targetname'] = old_name.rstrip('0123456789')
        try:
            ITEMS[new_name] = ITEMS.pop(old_name)
        except KeyError:
            pass


def do_item_optimisation(vmf: VMF) -> None:
    """Optimise redundant logic items."""
    needs_global_toggle = False

    for item in list(ITEMS.values()):
        # We can't remove items that have functionality, or don't have IO.
        if item.config is None or not item.config.input_type.is_logic:
            continue

        prim_inverted = conv_bool(item.inst.fixup.substitute(item.config.invert_var, allow_invert=True))
        sec_inverted = conv_bool(item.inst.fixup.substitute(item.config.sec_invert_var, allow_invert=True))

        # Don't optimise if inverted.
        if prim_inverted or sec_inverted:
            continue
        inp_count = len(item.inputs)
        if inp_count == 0:
            # Totally useless, remove.
            # We just leave the panel entities, and tie all the antlines
            # to the same toggle.
            needs_global_toggle = True
            for ant in item.antlines:
                ant.name = '_static_ind'

            del ITEMS[item.name]
            item.inst.remove()
        elif inp_count == 1:
            # Only one input, so AND or OR are useless.
            # Transfer input item to point to the output(s).
            collapse_item(item)

    # The antlines need a toggle entity, otherwise they'll copy random other
    # overlays.
    if needs_global_toggle:
        vmf.create_ent(
            classname='env_texturetoggle',
            origin=options.get(Vec, 'global_ents_loc'),
            targetname='_static_ind_tog',
            target='_static_ind',
        )


@conditions.meta_cond(-250, only_once=True)
def gen_item_outputs(vmf: VMF) -> None:
    """Create outputs for all items with connections.

    This performs an optimization pass over items with outputs to remove
    redundancy, then applies all the outputs to the instances. Before this,
    connection count and inversion values are not valid. After this point,
    items may not have connections altered.
    """
    LOGGER.info('Generating item IO...')

    # For logic items without inputs, collect the instances to fix up later.
    dummy_logic_ents: list[Entity] = []

    # Apply input A/B types to connections.
    # After here, all connections are primary or secondary only.
    for item in ITEMS.values():
        for conn in item.outputs:
            # If not a dual item, it's primary.
            if conn.to_item.config.input_type is not InputType.DUAL:
                conn.type = ConnType.PRIMARY
                continue
            # If already set, that is the priority.
            if conn.type is not ConnType.DEFAULT:
                continue
            # Our item set the type of outputs.
            if item.config.output_type is not ConnType.DEFAULT:
                conn.type = item.config.output_type
            else:
                # Use the affinity of the target.
                conn.type = conn.to_item.config.default_dual

    do_item_optimisation(vmf)

    # We go 'backwards', creating all the inputs for each item.
    # That way we can change behaviour based on item counts.
    for item in ITEMS.values():
        if item.config is None:
            continue

        # Try to add the locking IO.
        add_locking(item)

        # Check we actually have timers, and that we want the relay.
        if item.timer is not None and (
            item.config.timer_sound_pos is not None or
            item.config.timer_done_cmd
        ):
            has_sound = item.config.force_timer_sound or len(item.ind_panels) > 0
            add_timer_relay(item, has_sound)

        # Add outputs for antlines.
        if item.antlines or item.ind_panels:
            add_item_indicators(item, item.ind_style)

        if item.config.input_type is InputType.DUAL:
            prim_inputs = [
                conn
                for conn in item.inputs
                if conn.type is ConnType.PRIMARY or conn.type is ConnType.BOTH
            ]
            sec_inputs = [
                conn
                for conn in item.inputs
                if conn.type is ConnType.SECONDARY or conn.type is ConnType.BOTH
            ]
            add_item_inputs(
                dummy_logic_ents,
                item,
                InputType.AND,
                prim_inputs,
                consts.FixupVars.BEE_CONN_COUNT_A,
                item.enable_cmd,
                item.disable_cmd,
                item.config.invert_var,
                item.config.spawn_fire,
                '_prim_inv_rl',
            )
            add_item_inputs(
                dummy_logic_ents,
                item,
                InputType.AND,
                sec_inputs,
                consts.FixupVars.BEE_CONN_COUNT_B,
                item.sec_enable_cmd,
                item.sec_disable_cmd,
                item.config.sec_invert_var,
                item.config.sec_spawn_fire,
                '_sec_inv_rl',
            )
        else:
            add_item_inputs(
                dummy_logic_ents,
                item,
                item.config.input_type,
                list(item.inputs),
                consts.FixupVars.CONN_COUNT,
                item.enable_cmd,
                item.disable_cmd,
                item.config.invert_var,
                item.config.spawn_fire,
                '_inv_rl',
            )

    logic_auto = vmf.create_ent(
        'logic_auto',
        origin=options.get(Vec, 'global_ents_loc')
    )

    for ent in dummy_logic_ents:
        # Condense all these together now.
        # User2 is the one that enables the target.
        ent.remove()
        for out in ent.outputs:
            if out.output == 'OnUser2':
                out.output = 'OnMapSpawn'
                logic_auto.add_out(out)
                out.only_once = True

    LOGGER.info('Item IO generated.')


def add_locking(item: Item) -> None:
    """Create IO to control buttons from the target item.

    This allows items to customise how buttons behave.
    """
    if item.config.output_lock is None and item.config.output_unlock is None:
        return
    if item.config.input_type is InputType.DUAL:
        LOGGER.warning(
            'Item type ({}) with locking IO, but dual inputs. '
            'Locking functionality is ignored!',
            item.config.id
        )
        return

    # If more than one, it's not logical to lock the button.
    try:
        [lock_conn] = item.inputs
    except ValueError:
        return

    lock_button = lock_conn.from_item

    if item.config.inf_lock_only and lock_button.timer is not None:
        return

    # Check the button doesn't also activate other things -
    # we need exclusive control.
    # Also the button actually needs to be lockable.
    if len(lock_button.outputs) != 1 or not lock_button.config.lock_cmd:
        return

    instance_traits.get(item.inst).add('locking_targ')
    instance_traits.get(lock_button.inst).add('locking_btn')

    # Force the button to not have a timer.
    for pan in lock_button.ind_panels:
        pan.remove()
    lock_button.ind_panels.clear()

    for output, input_cmds in [
        (item.config.output_lock, lock_button.config.lock_cmd),
        (item.config.output_unlock, lock_button.config.unlock_cmd)
    ]:
        if not output:
            continue

        for cmd in input_cmds:
            if cmd.target:
                target = conditions.local_name(lock_button.inst, cmd.target)
            else:
                target = lock_button.inst['targetname']
            item.add_io_command(
                output,
                target,
                cmd.input,
                cmd.params,
                delay=cmd.delay,
                times=cmd.times,
            )


def localise_output(
    out: Output, out_name: str, inst: Entity,
    *,
    delay: float=0.0, only_once: bool=False,
) -> Output:
    """Create a copy of an output, with instance fixups substituted and with names localised."""
    return Output(
        out_name,
        conditions.local_name(inst, inst.fixup.substitute(out.target)) or inst['targetname'],
        inst.fixup.substitute(out.input),
        inst.fixup.substitute(out.params, allow_invert=True),
        inst_in=out.inst_in,
        delay=out.delay + delay,
        times=1 if only_once else out.times,
    )


def add_timer_relay(item: Item, has_sounds: bool) -> None:
    """Make a relay to play timer sounds, or fire once the outputs are done."""
    assert item.timer is not None

    rl_name = item.name + '_timer_rl'

    relay = item.inst.map.create_ent(
        'logic_relay',
        targetname=rl_name,
        startDisabled=0,
        spawnflags=0,
    )

    if item.config.timer_sound_pos:
        relay_loc = item.config.timer_sound_pos.copy()
        relay_loc.localise(
            Vec.from_str(item.inst['origin']),
            Angle.from_str(item.inst['angles']),
        )
        relay['origin'] = relay_loc
    else:
        relay['origin'] = item.inst['origin']

    for cmd in item.config.timer_done_cmd:
        if cmd:
            relay.add_out(localise_output(cmd, 'OnTrigger', item.inst, delay=item.timer))

    if item.config.timer_sound_pos is not None and has_sounds:
        timer_sound = options.get(str, 'timer_sound')
        timer_cc = options.get(str, 'timer_sound_cc')

        # The default sound has 'ticking' closed captions.
        # So reuse that if the style doesn't specify a different noise.
        # If explicitly set to '', we don't use this at all!
        if timer_cc is None and timer_sound != 'Portal.room1_TickTock':
            timer_cc = 'Portal.room1_TickTock'
        if timer_cc:
            timer_cc = 'cc_emit ' + timer_cc

        # Write out the VScript code to precache the sound, and play it on
        # demand.
        relay['vscript_init_code'] = (
            'function Precache() {'
            f'self.PrecacheSoundScript(`{timer_sound}`)'
            '}'
        )
        relay['vscript_init_code2'] = (
            'function snd() {'
            f'self.EmitSound(`{timer_sound}`)'
            '}'
        )
        packing.pack_files(item.inst.map, timer_sound, file_type='sound')

        for delay in range(item.timer):
            relay.add_out(Output(
                'OnTrigger',
                '!self',
                'CallScriptFunction',
                'snd',
                delay=delay,
            ))
            if timer_cc:
                relay.add_out(Output(
                    'OnTrigger',
                    '@command',
                    'Command',
                    timer_cc,
                    delay=delay,
                ))

    if item.config.timer_outputs:
        for tim_cmd in item.config.timer_outputs:
            if tim_cmd.mode.is_count:
                inp_cmd = 'Trigger'
            elif tim_cmd.mode.is_reset:
                inp_cmd = 'CancelPending'
            else:
                continue
            item.add_io_command(tim_cmd.output, rl_name, inp_cmd)
    else:  # Just regular I/O.
        item.add_io_command(item.output_act(), rl_name, 'Trigger')
        item.add_io_command(item.output_deact(), rl_name, 'CancelPending')


def add_item_inputs(
    dummy_logic_ents: List[Entity],
    item: Item,
    logic_type: InputType,
    inputs: List[Connection],
    count_var: str,
    enable_cmd: Iterable[Output],
    disable_cmd: Iterable[Output],
    invert_var: str,
    spawn_fire: FeatureMode,
    inv_relay_name: str,
) -> None:
    """Handle either the primary or secondary inputs to an item."""
    item.inst.fixup[count_var] = len(inputs)

    if len(inputs) == 0:
        # Special case - spawnfire items with no inputs need to fire
        # off the outputs. There's no way to control those, so we can just
        # fire it off.
        if spawn_fire is FeatureMode.ALWAYS:
            if item.is_logic:
                # Logic gates need to trigger their outputs. Make this item a logic_auto
                # temporarily, then we'll fix them up into an OnMapSpawn output properly at the end.
                item.inst.clear_keys()
                item.inst['classname'] = 'logic_auto'
                dummy_logic_ents.append(item.inst)
            else:
                is_inverted = conv_bool(item.inst.fixup.substitute(invert_var, '', allow_invert=True))
                logic_auto = item.inst.map.create_ent(
                    'logic_auto',
                    origin=item.inst['origin'],
                    spawnflags=1,
                )
                for cmd in (enable_cmd if is_inverted else disable_cmd):
                    try:
                        logic_auto.add_out(localise_output(
                            cmd, 'OnMapSpawn', item.inst,
                            only_once=True
                        ))
                    except KeyError as exc:  # Fixup missing, skip this output.
                        LOGGER.warning(
                            'Item "{}" missing fixups for OnMapSpawn output:',
                            item.name, exc_info=exc,
                        )
        return  # The rest of this function requires at least one input.

    if logic_type is InputType.DEFAULT:
        # 'Original' PeTI proxy style inputs. We're not actually using the
        # proxies though.
        for conn in inputs:
            inp_item = conn.from_item
            for output, input_cmds in [
                (inp_item.output_act(), enable_cmd),
                (inp_item.output_deact(), disable_cmd)
            ]:
                for cmd in input_cmds:
                    try:
                        inp_item.add_io_command(
                            output,
                            conditions.local_name(
                                item.inst, item.inst.fixup.substitute(cmd.target),
                            ) or item.inst,
                            item.inst.fixup.substitute(cmd.input),
                            item.inst.fixup.substitute(cmd.params, allow_invert=True),
                            inst_in=cmd.inst_in,
                            delay=cmd.delay,
                        )
                    except KeyError as exc:  # Fixup missing, skip this output.
                        LOGGER.warning(
                            'Item "{}" missing fixups for proxy output:',
                            item.name, exc_info=exc,
                        )
        return
    elif logic_type is InputType.DAISYCHAIN:
        # Another special case, these items AND themselves with their inputs.
        # Create the counter for that.

        # Note that we use the instance name itself for the counter.
        # This will break if we've got dual inputs, but we're only
        # using this for laser catchers...
        # We have to do this so that the name is something that can be
        # targeted by other items.
        # TODO: Do this by generating an AND gate proxy-instance...
        counter = item.inst.map.create_ent(
            'math_counter',
            origin=item.inst['origin'],
            targetname=item.name,
            min=0,
            max=len(inputs) + 1,
        )

        if (
            count_var is consts.FixupVars.BEE_CONN_COUNT_A or
            count_var is consts.FixupVars.BEE_CONN_COUNT_B
        ):
            LOGGER.warning(
                '{}: Daisychain logic type is '
                'incompatible with dual inputs in item type {}! '
                'This will not work well...',
                item.name,
                item.config.id,
            )

        # Use the item type's output, we've overridden the normal one.
        item.add_io_command(
            item.config.output_act,
            counter, 'Add', '1',
        )
        item.add_io_command(
            item.config.output_deact,
            counter, 'Subtract', '1',
        )

        for conn in inputs:
            inp_item = conn.from_item
            inp_item.add_io_command(inp_item.output_act(), counter, 'Add', '1')
            inp_item.add_io_command(inp_item.output_deact(), counter, 'Subtract', '1')

        return

    is_inverted = conv_bool(item.inst.fixup.substitute(invert_var, default='', allow_invert=True))

    invert_lag = 0.0
    if is_inverted:
        enable_cmd, disable_cmd = disable_cmd, enable_cmd

        # Inverted logic items get a short amount of lag, so loops will just oscillate indefinitely
        # as time passes instead of infinitely looping.
        if item.inputs and item.outputs:
            invert_lag = 0.1

    needs_counter = len(inputs) > 1

    # If this option is enabled, generate additional logic to fire the disabling output after spawn
    # (but only if it's not triggered normally.)

    # We just use a relay to do this.
    # User2 is the real enable input, User1 is the real disable input.

    # The relay allows cancelling the 'disable' output that fires shortly after
    # spawning.
    if spawn_fire is not FeatureMode.NEVER:
        if logic_type.is_logic:
            # We have to handle gates specially, and make us the instance
            # so future evaluation applies to this.
            origin = item.inst['origin']
            name = item.name

            spawn_relay = item.inst
            spawn_relay.clear_keys()

            spawn_relay['origin'] = origin
            spawn_relay['targetname'] = name
            spawn_relay['classname'] = 'logic_relay'
            # This needs to be blank so it'll be substituted by the instance
            # name in enable/disable_cmd.
            relay_cmd_name = ''
        else:
            relay_cmd_name = f'@{item.name}{inv_relay_name}'
            spawn_relay = item.inst.map.create_ent(
                classname='logic_relay',
                targetname=relay_cmd_name,
                origin=item.inst['origin'],
            )

        if is_inverted:
            enable_user = 'User1'
            disable_user = 'User2'
        else:
            enable_user = 'User2'
            disable_user = 'User1'

        spawn_relay['spawnflags'] = '0'
        spawn_relay['startdisabled'] = '0'

        spawn_relay.add_out(
            Output('OnTrigger', '!self', 'Fire' + disable_user, only_once=True),
            Output('OnSpawn', '!self', 'Trigger', delay=0.1),
        )
        for output_name, input_cmds in [
            ('On' + enable_user, enable_cmd),
            ('On' + disable_user, disable_cmd)
        ]:
            for cmd in input_cmds:
                try:
                    spawn_relay.add_out(localise_output(cmd, output_name, item.inst))
                except KeyError as exc:  # Missing fixups, skip.
                    LOGGER.warning(
                        'Item "{}" missing fixups for spawn relay:',
                        item.name, exc_info=exc,
                    )

        # Now overwrite input commands to redirect to the relay.
        enable_cmd = [
            Output('', relay_cmd_name, 'Fire' + enable_user),
            Output('', relay_cmd_name, 'Disable', only_once=True),
        ]
        disable_cmd = [
            Output('', relay_cmd_name, 'Fire' + disable_user),
            Output('', relay_cmd_name, 'Disable', only_once=True),
        ]
        # For counters, swap out the input type.
        if logic_type is InputType.AND_LOGIC:
            logic_type = InputType.AND
        elif logic_type is InputType.OR_LOGIC:
            logic_type = InputType.OR

    if needs_counter:
        if logic_type.is_logic:
            # Logic items are just the counter. The instance is useless, so
            # remove that from the map.
            counter_name = item.name
            item.inst.remove()
        else:
            counter_name = item.name + COUNTER_NAME[count_var]

        counter = item.inst.map.create_ent(
            classname='math_counter',
            targetname=counter_name,
            origin=item.inst['origin'],
        )

        counter['min'] = counter['startvalue'] = counter['StartDisabled'] = 0
        counter['max'] = len(inputs)

        for conn in inputs:
            inp_item = conn.from_item
            inp_item.add_io_command(inp_item.output_act(), counter, 'Add', '1')
            inp_item.add_io_command(inp_item.output_deact(), counter, 'Subtract', '1')

        if logic_type is InputType.AND:
            count_on = consts.COUNTER_AND_ON
            count_off = consts.COUNTER_AND_OFF
        elif logic_type is InputType.OR:
            count_on = consts.COUNTER_OR_ON
            count_off = consts.COUNTER_OR_OFF
        elif logic_type.is_logic:
            # We don't add outputs here, the outputted items do that.
            # counter is item.inst, so those are added to that.
            return
        else:
            # Should never happen, not other types.
            raise ValueError(
                f'Unknown counter logic type "{logic_type}" in item {item.config.id}!'
            )

        for output_name, input_cmds in [
            (count_on, enable_cmd),
            (count_off, disable_cmd)
        ]:
            for cmd in input_cmds:
                try:
                    counter.add_out(localise_output(cmd, output_name, item.inst, delay=invert_lag))
                except KeyError as exc:  # Fixup missing, skip this output.
                    LOGGER.warning(
                        'Item "{}" missing fixups for input command:',
                        item.name, exc_info=exc,
                    )

    else:  # No counter - fire directly.
        for conn in inputs:
            inp_item = conn.from_item
            for output, input_cmds in [
                (inp_item.output_act(), enable_cmd),
                (inp_item.output_deact(), disable_cmd)
            ]:
                for cmd in input_cmds:
                    try:
                        inp_item.add_io_command(
                            output,
                            conditions.local_name(
                                item.inst,
                                item.inst.fixup.substitute(cmd.target),
                            ) or item.inst['targetname'],
                            item.inst.fixup.substitute(cmd.input),
                            item.inst.fixup.substitute(cmd.params, allow_invert=True),
                            delay=cmd.delay + invert_lag,
                            times=cmd.times,
                        )
                    except KeyError as exc:  # Fixup missing, skip this output.
                        LOGGER.warning(
                            'Item "{}" missing fixups for input command:',
                            item.name, exc_info=exc,
                        )


def add_item_indicators(
    item: Item,
    style: IndicatorStyle,
) -> None:
    """Generate the commands for antlines and the overlays themselves."""
    ant_name = '@{}_overlay'.format(item.name)
    has_sign = len(item.ind_panels) > 0
    has_ant = len(item.antlines) > 0
    timer_delay = item.timer

    for ant in item.antlines:
        ant.name = ant_name

        ant.export(item.inst.map, item.ind_style)

    # Special case - the item wants full control over its antlines.
    if has_ant and item.ant_toggle_var:
        item.inst.fixup[item.ant_toggle_var] = ant_name
        # We don't have antlines to control.
        has_ant = False

    # If either is defined, the item wants to do custom control over the timer.
    independent_timer = bool(item.config.timer_outputs)
    # If that is defined, use advanced/custom timer logic if the style supports it.
    adv_timer = independent_timer and style.has_advanced_timer()

    conn_pairs: List[Tuple[Tuple[Optional[str], str], float, Sequence[Output]]]
    panel_fixup = EntityFixup(item.inst.fixup.copy_values())
    if timer_delay is not None:  # We have a timer.
        inst_type = style.timer_switching
        pan_filename = style.timer_inst
        if adv_timer:
            conn_pairs = [
                (item.output_act(), 0.0, style.timer_oran_cmd),
                (item.output_deact(), 0.0, style.timer_blue_cmd),
            ]
            for timer_cmd in item.config.timer_outputs:
                delay = timer_cmd.delay
                fade_time = timer_cmd.fadetime
                if timer_cmd.delay_add_timer:
                    delay += item.timer
                if timer_cmd.fadetime_add_timer:
                    fade_time += item.timer
                panel_fixup['$time'] = format_float(fade_time)
                # This gives the appropriate SetPlaybackRate input for a 30s timer dial.
                panel_fixup['$playback'] = format_float(30.0 / fade_time) if fade_time != 0.0 else '0'
                conn_pairs.append((timer_cmd.output, delay, [
                    Output(
                        '', out.target, out.input,
                        panel_fixup.substitute(out.params, allow_invert=True),
                        out.delay,
                        times=out.times,
                        inst_in=out.inst_in,
                        inst_out=out.inst_out,
                    )
                    for out in style.timer_adv_cmds.get(timer_cmd.mode, ())
                ]))
        elif independent_timer:
            # Item wants independent timer, but there's no advanced version.
            # Use basic start/stop to approximate.
            conn_pairs = []
            for timer_cmd in item.config.timer_outputs:
                delay = timer_cmd.delay
                if timer_cmd.delay_add_timer:
                    delay += item.timer
                if timer_cmd.mode.is_count:
                    conn_pairs.append((timer_cmd.output, delay, style.timer_basic_start_cmd))
                elif timer_cmd.mode.is_reset:
                    conn_pairs.append((timer_cmd.output, delay, style.timer_basic_stop_cmd))
        else:
            # Regular timer.
            conn_pairs = [
                (item.output_act(), 0.0, style.timer_basic_start_cmd),
                (item.output_deact(), 0.0, style.timer_basic_stop_cmd),
            ]
    else:
        inst_type = style.check_switching
        pan_filename = style.check_inst
        conn_pairs = [
            (item.output_act(), 0.0, style.check_cmd),
            (item.output_deact(), 0.0, style.cross_cmd),
        ]
    if pan_filename and item.ind_panels:
        conditions.ALL_INST.add(pan_filename.casefold())

    if timer_delay is not None:
        panel_fixup['$time'] = format_float(timer_delay)
        panel_fixup['$playback'] = format_float(30.0 / timer_delay) if timer_delay != 0.0 else '0'

    if inst_type is PanelSwitchingStyle.CUSTOM:
        needs_toggle = has_ant
    elif inst_type is PanelSwitchingStyle.EXTERNAL:
        needs_toggle = has_ant or has_sign
    elif inst_type is PanelSwitchingStyle.INTERNAL:
        if independent_timer:
            # We need to not tie antline control to the timer.
            needs_toggle = has_ant
            inst_type = PanelSwitchingStyle.CUSTOM
        else:
            needs_toggle = has_ant and not has_sign
    else:
        raise assert_never(inst_type)

    first_inst = True

    for pan in item.ind_panels:
        if inst_type is PanelSwitchingStyle.EXTERNAL:
            pan.fixup[consts.FixupVars.TOGGLE_OVERLAY] = ant_name
        # Ensure only one gets the indicator name.
        elif first_inst and inst_type is PanelSwitchingStyle.INTERNAL:
            pan.fixup[consts.FixupVars.TOGGLE_OVERLAY] = ant_name if has_ant else ' '
            first_inst = False
        else:
            # VBSP and/or Hammer seems to get confused with totally empty
            # instance var, so give it a blank name.
            pan.fixup[consts.FixupVars.TOGGLE_OVERLAY] = '-'

        if pan_filename:
            pan['file'] = pan_filename

        # Overwrite the timer delay value, in case a sign changed ownership.
        if timer_delay is not None:
            pan.fixup[consts.FixupVars.TIM_DELAY] = timer_delay
            pan.fixup[consts.FixupVars.TIM_ENABLED] = '1'
            # Set a var to tell the instance whether it needs this logic.
            pan.fixup['$advanced'] = adv_timer
        else:
            pan.fixup[consts.FixupVars.TIM_DELAY] = '99999999999'
            pan.fixup[consts.FixupVars.TIM_ENABLED] = '0'

        for output, delay, input_cmds in conn_pairs:
            for cmd in input_cmds:
                item.add_io_command(
                    output,
                    conditions.local_name(
                        pan,
                        item.inst.fixup.substitute(cmd.target),
                    ) or pan,
                    item.inst.fixup.substitute(cmd.input),
                    panel_fixup.substitute(cmd.params, allow_invert=True),
                    delay=delay + cmd.delay,
                    inst_in=cmd.inst_in,
                    times=cmd.times,
                )

    if needs_toggle:
        toggle = item.inst.map.create_ent(
            classname='env_texturetoggle',
            origin=Vec.from_str(item.inst['origin']) + (0, 0, 16),
            targetname='toggle_' + item.name,
            target=ant_name,
        )
        # Don't use the configurable inputs - if they want that, use custAntline.
        item.add_io_command(
            item.output_deact(),
            toggle,
            'SetTextureIndex',
            '0',
        )
        item.add_io_command(
            item.output_act(),
            toggle,
            'SetTextureIndex',
            '1',
        )
