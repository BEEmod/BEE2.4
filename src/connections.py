"""Manages PeTI item connections.

This allows checking which items are connected to what, and also regenerates
the outputs with optimisations and custom settings.
"""
from enum import Enum
from collections import defaultdict

from srctools import VMF, Entity, Output, Property, conv_bool, Vec
import comp_consts as const
import instanceLocs
import conditions
import instance_traits
import utils
import vbsp_options

from typing import Optional, Iterable, Dict, List, Set, Tuple


LOGGER = utils.getLogger(__name__)

ITEM_TYPES = {}  # type: Dict[str, ItemType]

# Targetname -> item
ITEMS = {}  # type: Dict[str, Item]

# Outputs we need to use to make a math_counter act like
# the specified logic gate.
COUNTER_AND_ON = 'OnHitMax'
COUNTER_AND_OFF = 'OnChangedFromMax'

COUNTER_OR_ON = 'OnChangedFromMin'
COUNTER_OR_OFF = 'OnHitMin'


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 'default'  # Normal / unconfigured input
    # Becomes one of the others based on item preference.

    PRIMARY = TBEAM_IO = 'primary'  # A Type, 'normal'
    SECONDARY = TBEAM_DIR = 'secondary'  # B Type, 'alt'

    BOTH = 'both'  # Trigger both simultaneously.


class InputType(Enum):
    """Indicates the kind of input behaviour to use."""
    # Normal PeTI, pass activate/deactivate via proxy.
    # For this the IO command is the original counter style.
    DEFAULT = 'default'

    # Have A and B inputs - acts like AND for both.
    DUAL = 'dual'

    AND = 'and'  # AND input for an item.
    OR = 'or'    # OR input for an item.

    OR_LOGIC = 'or_logic'  # Treat as an invisible OR gate, no instance.
    AND_LOGIC = 'and_logic'  # Treat as an invisible AND gate, no instance.

    # An item 'chained' to the next. Inputs should be moved to the output
    # item in addition to our own output.
    DAISYCHAIN = 'daisychain'

    @property
    def is_logic(self):
        """Is this a logic gate?"""
        return self.value in ('and_logic', 'or_logic')


class PanelSwitchingStyle(Enum):
    """How the panel instance does its switching."""
    CUSTOM = 'custom'      # Some logic, we don't do anything.
    EXTERNAL = 'external'  # Provide a toggle to the instance.
    INTERNAL = 'internal'  # The inst has a toggle or panel, so we can reuse it.


class OutNames(str, Enum):
    """Fake input/outputs used in generation of the real ones."""
    # Needs to match gameMan.Game.build_instance_data().
    IN_ACT = 'ACTIVATE'
    IN_DEACT = 'DEACTIVATE'

    IN_SEC_ACT = 'ACTIVATE_SECONDARY'
    IN_SEC_DEACT = 'DEACTIVATE_SECONDARY'

    OUT_ACT = 'ON_ACTIVATED'
    OUT_DEACT = 'ON_DEACTIVATED'


CONN_NAMES = {
    ConnType.DEFAULT: '',
    ConnType.PRIMARY: 'A',
    ConnType.SECONDARY: 'B',
    ConnType.BOTH: 'A+B',
}

# The order signs are used in maps.
SIGN_ORDER = [
    const.Signage.SHAPE_DOT,
    const.Signage.SHAPE_MOON,
    const.Signage.SHAPE_TRIANGLE,
    const.Signage.SHAPE_CROSS,
    const.Signage.SHAPE_SQUARE,
    const.Signage.SHAPE_CIRCLE,
    const.Signage.SHAPE_SINE,
    const.Signage.SHAPE_SLASH,
    const.Signage.SHAPE_STAR,
    const.Signage.SHAPE_WAVY
]

SIGN_ORDER_LOOKUP = {
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

    def __iter__(self):
        return iter(self.overlays)

    def __lt__(self, other: 'ShapeSignage'):
        """Allow sorting in a consistent order."""
        return self.name < other.name

    def __gt__(self, other: 'ShapeSignage'):
        """Allow sorting in a consistent order."""
        return self.name > other.name


class ItemType:
    """Represents an item, with inputs and outputs."""

    def __init__(
        self,
        id: str,
        default_dual: ConnType,
        input_type: InputType,

        invert_var: str,
        enable_cmd: List[Output],
        disable_cmd: List[Output],

        sec_invert_var: str,
        sec_enable_cmd: List[Output],
        sec_disable_cmd: List[Output],

        output_type: ConnType,
        output_act: Optional[Tuple[Optional[str], str]],
        output_deact: Optional[Tuple[Optional[str], str]],
    ):
        self.id = id

        # How this item uses their inputs.
        self.input_type = input_type

        # True/False for always, $var, !$var for lookup.
        self.invert_var = invert_var

        # IO commands for enabling/disabling the item.
        self.enable_cmd = enable_cmd
        self.disable_cmd = disable_cmd

        # If no A/B type is set on the input, use this type.
        # Set to None to indicate no secondary is present.
        self.default_dual = default_dual

        # Same for secondary items.
        self.sec_invert_var = sec_invert_var
        self.sec_enable_cmd = sec_enable_cmd
        self.sec_disable_cmd = sec_disable_cmd

        # Sets the affinity used for outputs from this item - makes the
        # Input A/B converter items work.
        # If DEFAULT, we use the value on the target item.
        self.output_type = output_type

        # inst_name, output commands for outputs.
        # If they are None, it's not used.

        # Logic items have preset ones of these from the counter.
        if input_type is InputType.AND_LOGIC:
            self.output_act = (None, COUNTER_AND_ON)
            self.output_deact = (None, COUNTER_AND_OFF)
        elif input_type is InputType.OR_LOGIC:
            self.output_act = (None, COUNTER_OR_ON)
            self.output_deact = (None, COUNTER_OR_OFF)
        else:
            self.output_act = output_act
            self.output_deact = output_deact

    @staticmethod
    def parse(item_id: str, conf: Property):
        """Read the item type info from the given config."""

        def get_outputs(prop_name):
            """Parse all the outputs with this name."""
            return [
                Output.parse(prop)
                for prop in
                conf.find_all(prop_name)
            ]

        enable_cmd = get_outputs('enable_cmd')
        disable_cmd = get_outputs('disable_cmd')

        try:
            input_type = InputType(
                conf['Type', 'default'].casefold()
            )
        except ValueError:
            raise ValueError('Invalid input type "{}": {}'.format(
                item_id, conf['type'],
            )) from None

        invert_var = conf['invertVar', '0']

        if input_type is InputType.DUAL:
            sec_enable_cmd = get_outputs('sec_enable_cmd')
            sec_disable_cmd = get_outputs('sec_disable_cmd')

            try:
                default_dual = ConnType(
                    conf['default_dual', 'default'].casefold()
                )
            except ValueError:
                raise ValueError('Invalid default type for "{}": {}'.format(
                    item_id, conf['default_dual'],
                )) from None

            sec_invert_var = conf['sec_invertVar', '0']
        else:
            sec_enable_cmd = []
            sec_disable_cmd = []
            default_dual = sec_invert_var = None

        try:
            output_type = ConnType(
                conf['DualType', 'default'].casefold()
            )
        except ValueError:
            raise ValueError('Invalid output affinity for "{}": {}'.format(
                item_id, conf['DualType'],
            )) from None

        try:
            out_act = Output.parse_name(conf['out_activate'])
        except IndexError:
            out_act = None

        try:
            out_deact = Output.parse_name(conf['out_deactivate'])
        except IndexError:
            out_deact = None

        return ItemType(
            item_id, default_dual, input_type,
            invert_var, enable_cmd, disable_cmd,
            sec_invert_var, sec_enable_cmd, sec_disable_cmd,
            output_type, out_act, out_deact,
        )


class Item:
    """Represents one item/instance with IO."""
    __slots__ = [
        'inst',
        'ind_panels',
        'antlines', 'shape_signs',
        'timer',
        'inputs', 'outputs',
        'item_type', 'io_outputs',
    ]

    def __init__(
        self,
        inst: Entity,
        item_type: ItemType,
        panels: Iterable[Entity]=(),
        antlines: Iterable[Entity]=(),
        shape_signs: Iterable[ShapeSignage]=(),
        timer_count: int=None,
    ):
        self.inst = inst
        self.item_type = item_type

        # Associated indicator panels
        self.ind_panels = set(panels)  # type: Set[Entity]

        # Overlays
        self.antlines = set(antlines)  # type: Set[Entity]
        self.shape_signs = list(shape_signs)

        # None = Infinite/normal.
        self.timer = timer_count

        # From this item
        self.outputs = set()  # type: Set[Connection]
        # To this item
        self.inputs = set()  # type: Set[Connection]

        assert self.name, 'Blank name!'

    def __repr__(self):
        return '<Item {}: "{}">'.format(self.item_type.id, self.name)

    @property
    def traits(self):
        """Return the set of instance traits for the item."""
        return instance_traits.get(self.inst)

    @property
    def name(self) -> str:
        """Return the targetname of the item."""
        return self.inst['targetname']

    @name.setter
    def name(self, name: str):
        """Set the targetname of the item."""
        self.inst['targetname'] = name


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
    ):
        self._to = to_item
        self._from = from_item
        self.type = conn_type
        self.outputs = list(outputs)

    def __repr__(self):
        return '<Connection {} {} -> {}>'.format(
            CONN_NAMES[self.type],
            self._from.name,
            self._to.name,
        )

    def add(self):
        """Add this to the directories."""
        self._from.outputs.add(self)
        self._to.inputs.add(self)

    def remove(self):
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
    def from_item(self, item: Item):
        self._from.outputs.discard(self)
        self._from = item
        item.outputs.add(self)


def collapse_item(item: Item):
    """Remove an item with a single input, transferring all IO."""
    try:
        [input_conn] = item.inputs  # type: Connection
        input_item = input_conn.from_item  # type: Item
    except ValueError:
        raise ValueError('Too many inputs for "{}"!'.format(item.name))

    input_conn.remove()

    input_item.antlines |= item.antlines
    input_item.ind_panels |= item.ind_panels

    item.antlines.clear()
    item.ind_panels.clear()

    for conn in list(item.outputs):
        conn.from_item = input_item

    del ITEMS[item.name]
    item.inst.remove()


def read_configs(conf: Property):
    """Build our connection configuration from the config files."""
    for prop in conf.find_children('Connections'):
        if prop.name in ITEM_TYPES:
            raise ValueError('Duplicate item type "{}"'.format(prop.real_name))
        ITEM_TYPES[prop.name] = ItemType.parse(prop.real_name, prop)

    if 'item_indicator_panel' not in ITEM_TYPES:
        raise ValueError('No checkmark panel item type!')

    if 'item_indicator_panel_timer' not in ITEM_TYPES:
        raise ValueError('No timer panel item type!')


def calc_connections(
    vmf: VMF,
    shape_frame_tex: List[str],
    enable_shape_frame: bool,
):
    """Compute item connections from the map file.

    This also fixes cases where items have incorrect checkmark/timer signs.
    Instance Traits must have been calculated.
    It also applies frames to shape signage to distinguish repeats.
    """
    # First we want to match targetnames to item types.
    toggles = {}  # type: Dict[str, Entity]
    overlays = defaultdict(set)  # type: Dict[str, Set[Entity]]

    # Accumulate all the signs into groups, so the list should be 2-long:
    # sign_shapes[name, material][0/1]
    sign_shape_overlays = defaultdict(list)  # type: Dict[Tuple[str, str], List[Entity]]

    # Indicator panels
    panels = {}  # type: Dict[str, Entity]

    panel_timer = instanceLocs.resolve_one('[indPanTimer]', error=True)
    panel_check = instanceLocs.resolve_one('[indPanCheck]', error=True)

    # We only need to pay attention for TBeams, other items we can
    # just detect any output.
    tbeam_polarity = {OutNames.IN_SEC_ACT, OutNames.IN_SEC_DEACT}
    # Also applies to other items, but not needed for this analysis.
    tbeam_io = {OutNames.IN_ACT, OutNames.IN_DEACT}

    for inst in vmf.by_class['func_instance']:
        inst_name = inst['targetname']
        # No connections, so nothing to worry about.
        if not inst_name:
            continue

        traits = instance_traits.get(inst)

        if 'indicator_toggle' in traits:
            toggles[inst['targetname']] = inst
            # We do not use toggle instances.
            inst.remove()
        elif 'indicator_panel' in traits:
            panels[inst['targetname']] = inst
        else:
            # Normal item.
            try:
                item_type = ITEM_TYPES[instance_traits.get_item_id(inst).casefold()]
            except KeyError:
                # These aren't made for non-io items. If it has outputs,
                # that'll be a problem later.
                item_type = None
            ITEMS[inst_name] = Item(inst, item_type)

    for over in vmf.by_class['info_overlay']:
        name = over['targetname']
        mat = over['material']
        if mat in SIGN_ORDER_LOOKUP:
            sign_shape_overlays[name, mat.casefold()].append(over)
        else:
            # Antlines
            overlays[name].add(over)

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
        input_items = []  # Instances we trigger
        inputs = defaultdict(list)  # type: Dict[str, List[Output]]

        if item.inst.outputs and item.item_type is None:
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

        for out_name in inputs:
            # Fizzler base -> model/brush outputs, ignore these (discard).
            # fizzler.py will regenerate as needed.
            if out_name.endswith(('_modelStart', '_modelEnd', '_brush')):
                continue

            if out_name in toggles:
                inst_toggle = toggles[out_name]
                item.antlines |= overlays[inst_toggle.fixup['indicator_name']]
            elif out_name in panels:
                pan = panels[out_name]
                item.ind_panels.add(pan)
                if pan.fixup.bool(const.FixupVars.TIM_ENABLED):
                    item.timer = tim = pan.fixup.int(const.FixupVars.TIM_DELAY)
                    if not (1 <= tim <= 30):
                        # These would be infinite.
                        item.timer = None
                else:
                    item.timer = None
            else:
                try:
                    inp_item = ITEMS[out_name]
                except KeyError:
                    raise ValueError('"{}" is not a known instance!'.format(out_name))
                else:
                    input_items.append(inp_item)
                    if inp_item.item_type is None:
                        raise ValueError(
                            'No connections for item "{}", '
                            'but inputs in the map!'.format(
                                instance_traits.get_item_id(inp_item.inst)
                            )
                        )

        desired_panel_inst = panel_check if item.timer is None else panel_timer

        # Check/cross instances sometimes don't match the kind of timer delay.
        for pan in item.ind_panels:
            pan['file'] = desired_panel_inst
            pan.fixup[const.FixupVars.TIM_ENABLED] = item.timer is not None

        for inp_item in input_items:  # type: Item
            # Default A/B type.
            conn_type = ConnType.DEFAULT
            in_outputs = inputs[inp_item.name]

            if inp_item.item_type.id == 'ITEM_TBEAM':
                # It's a funnel - we need to figure out if this is polarity,
                # or normal on/off.
                for out in in_outputs:
                    if out.input in tbeam_polarity:
                        conn_type = ConnType.TBEAM_DIR
                        break
                    elif out.input in tbeam_io:
                        conn_type = ConnType.TBEAM_IO
                        break
                else:
                    raise ValueError(
                        'Excursion Funnel "{}" has inputs, '
                        'but no valid types!'.format(inp_item.name)
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


@conditions.make_result_setup('ChangeIOType')
def res_change_io_type_parse(props: Property):
    """Pre-parse all item types into an anonymous block."""
    return ItemType.parse('<ChangeIOType: {:X}>'.format(id(props)), props)


@conditions.make_result('ChangeIOType')
def res_change_io_type(inst: Entity, res: Property):
    """Switch an item to use different inputs or outputs.

    Must be done before priority level -250.
    The contents are the same as that allowed in the input BEE2 block in
    editoritems.
    """
    try:
        item = ITEMS[inst['targetname']]
    except KeyError:
        raise ValueError('No item with name "{}"!'.format(inst['targetname']))

    item.item_type = res.value


def do_item_optimisation(vmf: VMF):
    """Optimise redundant logic items."""
    needs_global_toggle = False

    for item in list(ITEMS.values()):
        # We can't remove items that have functionality, or don't have IO.
        if item.item_type is None or not item.item_type.input_type.is_logic:
            continue

        prim_inverted = conv_bool(conditions.resolve_value(
            item.inst,
            item.item_type.invert_var,
        ))

        sec_inverted = conv_bool(conditions.resolve_value(
            item.inst,
            item.item_type.sec_invert_var,
        ))

        # Don't optimise if inverted.
        if prim_inverted or sec_inverted:
            continue
        inp_count = len(item.inputs)
        if inp_count == 0:
            # Totally useless, remove.
            # We just leave the panel entities, and tie all the antlines
            # to the same toggle.
            needs_global_toggle = True
            for ent in item.antlines:
                ent['targetname'] = '_static_ind'

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
            origin=vbsp_options.get(Vec, 'global_ents_loc'),
            targetname='_static_ind_tog',
            target='_static_ind',
        )


@conditions.meta_cond(-250, only_once=True)
def gen_item_outputs(vmf: VMF):
    """Create outputs for all items with connections.

    This performs an optimization pass over items with outputs to remove
    redundancy, then applies all the outputs to the instances. Before this,
    connection count and inversion values are not valid. After this point,
    items may not have connections altered.
    """
    pan_switching_check = vbsp_options.get(PanelSwitchingStyle, 'ind_pan_check_switching')
    pan_switching_timer = vbsp_options.get(PanelSwitchingStyle, 'ind_pan_timer_switching')

    pan_check_type = ITEM_TYPES['item_indicator_panel']
    pan_timer_type = ITEM_TYPES['item_indicator_panel_timer']

    do_item_optimisation(vmf)

    # We go 'backwards', creating all the inputs for each item.
    # That way we can change behaviour based on item counts.
    for item in ITEMS.values():
        if item.item_type is None:
            continue

        # Add outputs for antlines.
        if item.antlines or item.ind_panels:
            if item.timer is None:
                add_item_indicators(item, pan_switching_check, pan_check_type)
            else:
                add_item_indicators(item, pan_switching_timer, pan_timer_type)

        if not item.inputs:
            continue

        if item.item_type.input_type is InputType.DUAL:

            prim_inputs = [
                conn
                for conn in item.inputs
                if conn.type is ConnType.PRIMARY
                or conn.type is ConnType.DEFAULT
            ]
            sec_inputs = [
                conn
                for conn in item.inputs
                if conn.type is ConnType.SECONDARY
                or conn.type is ConnType.DEFAULT
            ]
            add_item_inputs(
                item,
                InputType.AND,
                prim_inputs,
                const.FixupVars.BEE_CONN_COUNT_A,
                item.item_type.enable_cmd,
                item.item_type.disable_cmd,
                item.item_type.invert_var,
            )
            add_item_inputs(
                item,
                InputType.AND,
                sec_inputs,
                const.FixupVars.BEE_CONN_COUNT_B,
                item.item_type.sec_enable_cmd,
                item.item_type.sec_disable_cmd,
                item.item_type.sec_invert_var,
            )
        else:
            add_item_inputs(
                item,
                item.item_type.input_type,
                list(item.inputs),
                const.FixupVars.CONN_COUNT,
                item.item_type.enable_cmd,
                item.item_type.disable_cmd,
                item.item_type.invert_var,
            )


def add_item_inputs(
    item: Item,
    logic_type: InputType,
    inputs: List[Connection],
    count_var: str,
    enable_cmd: List[Output],
    disable_cmd: List[Output],
    invert_var: str,
):
    """Handle either the primary or secondary inputs to an item."""
    item.inst.fixup[count_var] = len(inputs)

    if logic_type is InputType.DEFAULT:
        # 'Original' PeTI proxies.
        for conn in inputs:
            inp_item = conn.from_item
            for output, input_cmds in [
                (inp_item.item_type.output_act, enable_cmd),
                (inp_item.item_type.output_deact, disable_cmd)
            ]:
                if not output or not input_cmds:
                    continue

                out_name, out_cmd = output
                for cmd in input_cmds:
                    inp_item.inst.add_out(
                        Output(
                            out_cmd,
                            item.inst,
                            cmd.input,
                            inst_out=out_name,
                            inst_in=cmd.inst_in,
                        )
                    )
        return

    is_inverted = conv_bool(conditions.resolve_value(
        item.inst,
        invert_var,
    ))

    if is_inverted:
        enable_cmd, disable_cmd = disable_cmd, enable_cmd

    if logic_type is InputType.DAISYCHAIN:
        needs_counter = True
    else:
        needs_counter = len(inputs) > 1

    if logic_type.is_logic:
        origin = item.inst['origin']
        name = item.name

        counter = item.inst
        counter.clear_keys()

        counter['origin'] = origin
        counter['targetname'] = name
        counter['classname'] = 'math_counter'

        if not needs_counter:
            LOGGER.warning('Item "{}" was not optimised out!', name)
            # Force counter so it still works.
            needs_counter = True
    elif needs_counter:
        counter = item.inst.map.create_ent(
            classname='math_counter',
            targetname=conditions.local_name(item.inst, 'counter'),
            origin=item.inst['origin'],
        )
    else:
        counter = None

    if needs_counter:
        counter['min'] = counter['startvalue'] = counter['StartDisabled'] = 0
        counter['max'] = len(inputs)

        for conn in inputs:
            inp_item = conn.from_item
            for output, input_name in [
                (inp_item.item_type.output_act, 'Add'),
                (inp_item.item_type.output_deact, 'Subtract')
            ]:
                if not output:
                    continue

                out_name, out_cmd = output
                inp_item.inst.add_out(
                    Output(
                        out_cmd,
                        counter,
                        input_name,
                        '1',
                        inst_out=out_name,
                    )
                )

        if logic_type is InputType.AND:
            count_on = COUNTER_AND_ON
            count_off = COUNTER_AND_OFF
        elif logic_type is InputType.OR:
            count_on = COUNTER_OR_ON
            count_off = COUNTER_OR_OFF
        elif logic_type.is_logic:
            # We don't add outputs here, the outputted items do that.
            # counter is item.inst, so those are added to that.
            LOGGER.info('LOGIC counter: {}', counter['targetname'])
            return
        elif logic_type.DAISYCHAIN:
            # Todo
            return
        else:
            # Should never happen, not other types.
            raise ValueError('Unknown counter logic type: ' + repr(logic_type))

        for output_name, input_cmds in [
            (count_on, enable_cmd),
            (count_off, disable_cmd)
        ]:
            if not input_cmds:
                continue
            for cmd in input_cmds:
                counter.add_out(
                    Output(
                        output_name,
                        conditions.local_name(item.inst, cmd.target) or item.inst,
                        cmd.input,
                        cmd.params,
                        times=cmd.times,
                    )
                )

    else:  # No counter - fire directly.
        for conn in inputs:
            inp_item = conn.from_item
            for output, input_cmds in [
                (inp_item.item_type.output_act, enable_cmd),
                (inp_item.item_type.output_deact, disable_cmd)
            ]:
                if not output or not input_cmds:
                    continue

                out_name, out_cmd = output
                for cmd in input_cmds:
                    inp_item.inst.add_out(
                        Output(
                            out_cmd,
                            conditions.local_name(item.inst, cmd.target) or item.inst,
                            cmd.input,
                            cmd.params,
                            inst_out=out_name,
                            times=cmd.times,
                        )
                    )


def add_item_indicators(
    item: Item,
    inst_type: PanelSwitchingStyle,
    pan_item: ItemType,
):
    """Generate the commands for antlines."""
    ant_name = '@{}_overlay'.format(item.name)
    has_ant = len(item.antlines) > 0
    has_sign = len(item.ind_panels) > 0

    for ind in item.antlines:
        ind['targetname'] = ant_name

    if inst_type is PanelSwitchingStyle.CUSTOM:
        needs_toggle = has_ant
    elif inst_type is PanelSwitchingStyle.EXTERNAL:
        needs_toggle = has_ant or has_sign
    elif inst_type is PanelSwitchingStyle.INTERNAL:
        needs_toggle = has_ant and not has_sign
    else:
        raise ValueError('Bad switch style ' + repr(inst_type))

    first_inst = True

    for pan in item.ind_panels:
        if inst_type is PanelSwitchingStyle.EXTERNAL:
            pan.fixup[const.FixupVars.TOGGLE_OVERLAY] = ant_name
        # Ensure only one gets the indicator name.
        elif first_inst and inst_type is PanelSwitchingStyle.INTERNAL:
            pan.fixup[const.FixupVars.TOGGLE_OVERLAY] = ant_name
            first_inst = False
        else:
            pan.fixup[const.FixupVars.TOGGLE_OVERLAY] = ' '

        for output, input_cmds in [
            (item.item_type.output_act, pan_item.enable_cmd),
            (item.item_type.output_deact, pan_item.disable_cmd)
        ]:
            if not output:
                continue
            out_name, out = output
            for cmd in input_cmds:
                item.inst.add_out(
                    Output(
                        out,
                        conditions.local_name(pan, cmd.target) or pan,
                        cmd.input,
                        cmd.params,
                        inst_out=out_name,
                        times=cmd.times,
                    )
                )

    if needs_toggle:
        toggle = item.inst.map.create_ent(
            classname='env_texturetoggle',
            origin=Vec.from_str(item.inst['origin']) + (0, 0, 16),
            targetname='toggle_' + item.name,
            target=ant_name,
        )
        for output, skin in [
            (item.item_type.output_act, 1),
            (item.item_type.output_deact, 0)
        ]:
            if not output:
                continue
            out_name, out = output
            item.inst.add_out(
                Output(
                    out,
                    toggle,
                    'SetTextureIndex',
                    skin,
                    inst_out=out_name,
                )
            )
