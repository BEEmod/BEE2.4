"""Manages PeTI item connections."""
from enum import Enum
from collections import defaultdict, namedtuple

from srctools import VMF, Entity, Output, Property
import comp_consts as const
import instanceLocs
import instance_traits
import utils

from typing import Optional, Iterable, Dict, List, Set, Tuple


LOGGER = utils.getLogger(__name__)

ITEM_TYPES = {}  # type: Dict[str, ItemType]

# The original input/output connection values defined for each item.
# Each is a tuple of (inst_name, command) values, ready to be passed to
# VLib.Output().
# If the command is '', no in/output is present.
ItemConnections = namedtuple('ItemConnections', [
    'in_act', 'in_deact', 'out_act', 'out_deact',
])
CONNECTIONS = {}

# The special tbeam polarity input from ITEM_TBEAM. Works like above.
TBEAM_CONN_ACT = TBEAM_CONN_DEACT = (None, '')


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

    AND = 'and'  # AND input for an item.
    OR = 'or'    # OR input for an item.

    OR_LOGIC = 'or_logic'  # Treat as an invisible OR gate, no instance.
    AND_LOGIC = 'and_logic'  # Treat as an invisible AND gate, no instance.

    # An item 'chained' to the next. Inputs should be moved to the output
    # item in addition to our own output.
    DAISYCHAIN = 'daisychain'


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


# Targetname -> item
ITEMS = {}  # type: Dict[str, Item]


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

    __slots__ = [
        'id', 'default_dual',
        'invert_var', 'enable_cmd', 'disable_cmd',
        'sec_invert_var', 'sec_enable_cmd', 'sec_disable_cmd',
        'output_type', 'output_act', 'output_deact',
    ]

    def __init__(
        self,
        id: str,
        default_dual: ConnType,

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
        self.output_act = output_act
        self.output_deact = output_deact

    @staticmethod
    def parse(conf: Property):
        """Read the item type info from the given config."""
        item_id = conf.real_name

        def get_outputs(prop_name):
            """Parse all the outputs with this name."""
            return [
                Output.parse(prop)
                for prop in
                conf.find_all(prop_name)
            ]

        enable_cmd = get_outputs('enable_cmd')
        disable_cmd = get_outputs('disable_cmd')

        has_sec = 'sec_enable_cmd' in conf or 'sec_disable_cmd' in conf

        invert_var = conf['invertVar', '0']

        if has_sec:
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
                item_id, conf['default_dual'],
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
            item_id, default_dual,
            invert_var, enable_cmd, disable_cmd,
            sec_invert_var, sec_enable_cmd, sec_disable_cmd,
            output_type, out_act, out_deact,
        )


class Item:
    """Represents one item/instance with IO."""
    __slots__ = [
        'inst',
        'ind_panels', 'ind_toggle',
        'antlines', 'shape_signs',
        'timer',
        'inputs', 'outputs',
        'item_type',
    ]

    def __init__(
        self,
        inst: Entity,
        item_type: ItemType,
        toggle: Entity = None,
        panels: Iterable[Entity]=(),
        antlines: Iterable[Entity]=(),
        shape_signs: Iterable[ShapeSignage]=(),
        timer_count: int=None,
    ):
        self.inst = inst
        self.item_type = item_type

        # Associated indicator panels
        self.ind_panels = set(panels)  # type: Set[Entity]
        self.ind_toggle = toggle
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
        self._from.inputs.add(self)
        self._to.outputs.add(self)

    def remove(self):
        """Remove this from the directories."""
        self._from.inputs.discard(self)
        self._to.outputs.discard(self)

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


def read_configs(conf: Property):
    """Build our connection configuration from the config files."""
    for prop in conf.find_children('Items'):
        if prop.name in ITEM_TYPES:
            raise ValueError('Duplicate item type "{}"'.format(prop.real_name))
        ITEM_TYPES[prop.name] = ItemType.parse(prop)


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

    tbeam_polarity = {
        TBEAM_CONN_ACT,
        TBEAM_CONN_DEACT,
    }
    tbeam_io = {
        CONNECTIONS['item_tbeam'].in_act,
        CONNECTIONS['item_tbeam'].in_deact
    }

    for inst in vmf.by_class['func_instance']:
        inst_name = inst['targetname']
        if not inst_name:
            continue

        traits = instance_traits.get(inst)

        if 'indicator_toggle' in traits:
            toggles[inst['targetname']] = inst
        elif 'indicator_panel' in traits:
            panels[inst['targetname']] = inst
        else:
            # Normal item.
            try:
                item_type = ITEM_TYPES[instance_traits.get_item_id(inst).casefold()]
            except KeyError:
                raise ValueError(
                    'No connections for item "{}", '
                    'but connections in the map!'.format(
                        instance_traits.get_item_id(inst)
                    ))
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

        for out in item.inst.outputs:
            inputs[out.target].append(out)
        # inst.outputs.clear()

        for out_name in inputs:
            # Fizzler base -> model/brush outputs, skip and readd.
            if out_name.endswith(('_modelStart', '_modelEnd', '_brush')):
                # item.inst.add_out(*inputs[out_name])
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
                    input_items.append(ITEMS[out_name])
                except KeyError:
                    raise ValueError('"{}" is not a known instance!'.format(out_name))

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
                    input_tuple = (out.inst_in, out.input)
                    if input_tuple in tbeam_polarity:
                        conn_type = ConnType.TBEAM_DIR
                        break
                    elif input_tuple in tbeam_io:
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
