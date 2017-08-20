"""Manages PeTI item connections."""
from enum import Enum
from collections import defaultdict
from srctools import VMF, Entity, Output
import comp_consts as const
import instanceLocs
import conditions
import instance_traits
import utils

from typing import Iterable, Dict, List, Set, Tuple

LOGGER = utils.getLogger(__name__)


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 0  # Normal / unconfigured input
    # Becomes one of the others based on item preference.

    PRIMARY = TBEAM_IO = 1  # A Type, 'normal'
    SECONDARY = TBEAM_DIR = 2  # B Type, 'alt'

    BOTH = 3  # Trigger both simultaneously.

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
    def __init__(self, overlays: List[Entity]):
        super().__init__()
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
        yield from self.overlays


class Item:
    """Represents one item/instance with IO."""
    __slots__ = [
        'inst',
        'ind_panels', 'ind_toggle',
        'antlines', 'shape_signs',
        'timer',
        'inputs', 'outputs',
    ]

    def __init__(
        self,
        inst: Entity,
        toggle: Entity = None,
        panels: Iterable[Entity]=(),
        antlines: Iterable[Entity]=(),
        shape_signs: Iterable[ShapeSignage]=(),
        timer_count: int=None,
    ):
        self.inst = inst

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
        return '<Item "{}">'.format(self.name)

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
    """Represents a connection between two items.

    The item references should not be modified, as this will invalidate
    INPUTS and OUTPUTS.
    """

    __slots__ = [
        'inp', 'out', 'type', 'outputs',
    ]
    def __init__(
        self,
        to_item: Item,   # Item this is triggering
        from_item: Item,  # Item this comes from
        conn_type=ConnType.DEFAULT,
        outputs: Iterable[Output]=(),
    ):
        self.inp = to_item
        self.out = from_item
        self.type = conn_type
        self.outputs = list(outputs)

    def __repr__(self):
        return '<Connection {} {} -> {}>'.format(
            CONN_NAMES[self.type],
            self.out.name,
            self.inp.name,
        )

    def add(self):
        """Add this to the directories."""
        self.inp.inputs.add(self)
        self.out.outputs.add(self)

    def remove(self):
        """Remove this from the directories."""
        self.inp.inputs.discard(self)
        self.out.outputs.discard(self)

    def set_item(self, input=None, output=None):
        """Set the input or output used for this item."""
        self.remove()
        if input is not None:
            self.inp = input
        if output is not None:
            self.out = output
        self.add()


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
    panels = {}  # type: Dict[str, Entity]

    panel_timer = instanceLocs.resolve_one('[indPanTimer]', error=True)
    panel_check = instanceLocs.resolve_one('[indPanCheck]', error=True)

    tbeam_polarity = {
        conditions.TBEAM_CONN_ACT,
        conditions.TBEAM_CONN_DEACT,
    }
    tbeam_io = conditions.CONNECTIONS['item_tbeam']
    tbeam_io = {tbeam_io.in_act, tbeam_io.in_deact}

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
            ITEMS[inst_name] = Item(inst)

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

            if 'tbeam_emitter' in inp_item.traits:
                # It's a funnel - we need to figure out if this is polarity,
                # or normal on/off.
                for out in in_outputs:  # type: Output
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

    for item in ITEMS.values():
        # Copying items can fail to update the connection counts.
        # Make sure they're correct.
        if const.FixupVars.CONN_COUNT in item.inst.fixup:
            # Don't count the polarity outputs...
            item.inst.fixup[const.FixupVars.CONN_COUNT] = sum(
                1 for conn
                in item.inputs
                if conn.type is not ConnType.TBEAM_DIR
            )
        if const.FixupVars.CONN_COUNT_TBEAM in item.inst.fixup:
            # Only count the polarity outputs...
            item.inst.fixup[const.FixupVars.CONN_COUNT_TBEAM] = sum(
                1 for conn
                in item.inputs
                if conn.type is ConnType.TBEAM_DIR
            )

    # Make signage frames
    shape_frame_tex = [mat for mat in shape_frame_tex if mat]
    if shape_frame_tex and enable_shape_frame:
        for shape_mat in sign_shape_by_index.values():
            # Sort by name, so which gets what frame is consistent
            shape_mat.sort(key=lambda shape: shape.name)
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
                    frame['renderorder'] = 1 # On top
