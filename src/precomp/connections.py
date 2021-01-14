"""Manages PeTI item connections.

This allows checking which items are connected to what, and also regenerates
the outputs with optimisations and custom settings.
"""
from enum import Enum
from collections import defaultdict

from srctools import VMF, Entity, Output, Property, conv_bool, Vec
from precomp.antlines import Antline, AntType
from precomp import (
    instance_traits, instanceLocs,
    options,
    packing,
    conditions,
)
import consts
import srctools.logger

from typing import Optional, Iterable, Dict, List, Set, Tuple, Iterator, Union


COND_MOD_NAME = "Item Connections"

LOGGER = srctools.logger.get_logger(__name__)

ITEM_TYPES = {}  # type: Dict[str, ItemType]

# Targetname -> item
ITEMS = {}  # type: Dict[str, Item]

# Outputs we need to use to make a math_counter act like
# the specified logic gate.
COUNTER_AND_ON = 'OnHitMax'
COUNTER_AND_OFF = 'OnChangedFromMax'

COUNTER_OR_ON = 'OnChangedFromMin'
COUNTER_OR_OFF = 'OnHitMin'

# We need different names for each kind of input type, so they don't
# interfere with each other. We use the 'inst_local' pattern not 'inst-local'
# deliberately so the actual item can't affect the IO input.
COUNTER_NAME = {
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


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 'default'  # Normal / unconfigured input
    # Becomes one of the others based on item preference.

    PRIMARY = TBEAM_IO = 'primary'  # A Type, 'normal'
    SECONDARY = TBEAM_DIR = 'secondary'  # B Type, 'alt'

    BOTH = 'both'  # Trigger both simultaneously.


CONN_TYPE_NAMES: Dict[str, ConnType] = {
    'none': ConnType.DEFAULT,
    'a': ConnType.PRIMARY,
    'prim': ConnType.PRIMARY,

    'b': ConnType.SECONDARY,
    'sec': ConnType.SECONDARY,

    'ab': ConnType.BOTH,
    'a+b': ConnType.BOTH,
}

CONN_TYPE_NAMES.update(
    (conn.value.casefold(), conn)
    for conn in ConnType
)


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


class FeatureMode(Enum):
    """When to apply a feature."""
    DYNAMIC = 'dynamic'  # Only if dynamic (inputs)
    ALWAYS = 'always'
    NEVER = 'never'

    def valid(self, item: 'Item') -> bool:
        """Check if this is valid for the item."""
        if self.value == 'dynamic':
            return len(item.inputs) > 0
        else:
            return self.value == 'always'


CONN_NAMES = {
    ConnType.DEFAULT: 'DEF',
    ConnType.PRIMARY: 'A',
    ConnType.SECONDARY: 'B',
    ConnType.BOTH: 'A+B',
}

# The order signs are used in maps.
SIGN_ORDER = [
    consts.Signage.SHAPE_DOT,
    consts.Signage.SHAPE_MOON,
    consts.Signage.SHAPE_TRIANGLE,
    consts.Signage.SHAPE_CROSS,
    consts.Signage.SHAPE_SQUARE,
    consts.Signage.SHAPE_CIRCLE,
    consts.Signage.SHAPE_SINE,
    consts.Signage.SHAPE_SLASH,
    consts.Signage.SHAPE_STAR,
    consts.Signage.SHAPE_WAVY
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


class ItemType:
    """Represents a type of item, with inputs and outputs.

    This is shared by all items of the same type.
    """
    output_act: Optional[Tuple[Optional[str], str]]
    output_deact: Optional[Tuple[Optional[str], str]]

    def __init__(
        self,
        id: str,
        default_dual: ConnType=ConnType.DEFAULT,
        input_type: InputType=InputType.DEFAULT,

        spawn_fire: FeatureMode=FeatureMode.NEVER,

        invert_var: str = '0',
        enable_cmd: Iterable[Output]=(),
        disable_cmd: Iterable[Output]=(),

        sec_invert_var: str='0',
        sec_enable_cmd: Iterable[Output]=(),
        sec_disable_cmd: Iterable[Output]=(),

        output_type: ConnType=ConnType.DEFAULT,
        output_act: Optional[Tuple[Optional[str], str]]=None,
        output_deact: Optional[Tuple[Optional[str], str]]=None,

        lock_cmd: Iterable[Output]=(),
        unlock_cmd: Iterable[Output]=(),
        output_lock: Optional[Tuple[Optional[str], str]]=None,
        output_unlock: Optional[Tuple[Optional[str], str]]=None,
        inf_lock_only: bool=False,

        timer_sound_pos: Optional[Vec]=None,
        timer_done_cmd: Iterable[Output]=(),
        force_timer_sound: bool=False,

        timer_start: Optional[List[Tuple[Optional[str], str]]]=None,
        timer_stop: Optional[List[Tuple[Optional[str], str]]]=None,
    ):
        self.id = id

        # How this item uses their inputs.
        self.input_type = input_type

        # True/False for always, $var, !$var for lookup.
        self.invert_var = invert_var

        # Fire the enable/disable commands after spawning to initialise
        # the entity.
        self.spawn_fire = spawn_fire

        # IO commands for enabling/disabling the item.
        # These are copied to the item, so it can have modified ones.
        # We use tuples so all can reuse the same object.
        self.enable_cmd = tuple(enable_cmd)
        self.disable_cmd = tuple(disable_cmd)

        # If no A/B type is set on the input, use this type.
        # Set to None to indicate no secondary is present.
        self.default_dual = default_dual

        # Same for secondary items.
        self.sec_invert_var = sec_invert_var
        self.sec_enable_cmd = tuple(sec_enable_cmd)
        self.sec_disable_cmd = tuple(sec_disable_cmd)

        # Sets the affinity used for outputs from this item - makes the
        # Input A/B converter items work.
        # If DEFAULT, we use the value on the target item.
        self.output_type = output_type

        # (inst_name, output) commands for outputs.
        # If they are None, it's not used.

        # Logic items have preset ones of these from the counter.
        if input_type is InputType.AND_LOGIC:
            self.output_act = (None, COUNTER_AND_ON)
            self.output_deact = (None, COUNTER_AND_OFF)
        elif input_type is InputType.OR_LOGIC:
            self.output_act = (None, COUNTER_OR_ON)
            self.output_deact = (None, COUNTER_OR_OFF)
        else:  # Other types use the specified ones.
            # Allow passing in an output with a blank command, to indicate
            # no outputs.
            if output_act == (None, ''):
                self.output_act = None
            else:
                self.output_act = output_act

            if output_deact == (None, ''):
                self.output_deact = None
            else:
                self.output_deact = output_deact

        # If set, automatically play tick-tock sounds when output is on.
        self.timer_sound_pos = timer_sound_pos
        # These are fired when the time elapses.
        self.timer_done_cmd = list(timer_done_cmd)
        # If True, always add tick-tock sounds. If false, only when we have
        # a timer dial.
        self.force_timer_sound = force_timer_sound

        # If set, these allow alternate inputs for controlling timers.
        # Multiple can be given. If None, we use the normal output.
        self.timer_start = timer_start
        self.timer_stop = timer_stop

        # For locking buttons, this is the command to reactivate,
        # and force-lock it.
        # If both aren't present, erase both.
        if lock_cmd and unlock_cmd:
            self.lock_cmd = tuple(lock_cmd)
            self.unlock_cmd = tuple(unlock_cmd)
        else:
            self.lock_cmd = self.unlock_cmd = ()

        # If True, the locking button must be infinite to enable the behaviour.
        self.inf_lock_only = inf_lock_only

        # For the target, the commands to lock/unlock the attached button.
        self.output_lock = output_lock
        self.output_unlock = output_unlock

    @staticmethod
    def parse(item_id: str, conf: Property):
        """Read the item type info from the given config."""

        def get_outputs(prop_name):
            """Parse all the outputs with this name."""
            return [
                Output.parse(prop)
                for prop in
                conf.find_all(prop_name)
                # Allow blank to indicate no output.
                if prop.value != ''
            ]

        enable_cmd = get_outputs('enable_cmd')
        disable_cmd = get_outputs('disable_cmd')
        lock_cmd = get_outputs('lock_cmd')
        unlock_cmd = get_outputs('unlock_cmd')

        inf_lock_only = conf.bool('inf_lock_only')

        timer_done_cmd = get_outputs('timer_done_cmd')
        if 'timer_sound_pos' in conf:
            timer_sound_pos = conf.vec('timer_sound_pos')
            force_timer_sound = conf.bool('force_timer_sound')
        else:
            timer_sound_pos = None
            force_timer_sound = False

        try:
            input_type = InputType(
                conf['Type', 'default'].casefold()
            )
        except ValueError:
            raise ValueError('Invalid input type "{}": {}'.format(
                item_id, conf['type'],
            )) from None

        invert_var = conf['invertVar', '0']

        try:
            spawn_fire = FeatureMode(conf['spawnfire', 'never'].casefold())
        except ValueError:
            # Older config option - it was a bool for always/never.
            spawn_fire_bool = conf.bool('spawnfire', None)
            if spawn_fire_bool is None:
                raise  # Nope, not a bool.

            spawn_fire = FeatureMode.ALWAYS if spawn_fire_bool else FeatureMode.NEVER

        if input_type is InputType.DUAL:
            sec_enable_cmd = get_outputs('sec_enable_cmd')
            sec_disable_cmd = get_outputs('sec_disable_cmd')

            try:
                default_dual = CONN_TYPE_NAMES[
                    conf['Default_Dual', 'primary'].casefold()
                ]
            except KeyError:
                raise ValueError('Invalid default type for "{}": {}'.format(
                    item_id, conf['Default_Dual'],
                )) from None

            # We need an affinity to use when nothing else specifies it.
            if default_dual is ConnType.DEFAULT:
                raise ValueError('Must specify a default type for "{}"!'.format(
                    item_id,
                )) from None

            sec_invert_var = conf['sec_invertVar', '0']
        else:
            # No dual type, set to dummy values.
            sec_enable_cmd = []
            sec_disable_cmd = []
            default_dual = ConnType.DEFAULT
            sec_invert_var = ''

        try:
            output_type = CONN_TYPE_NAMES[
                conf['DualType', 'default'].casefold()
            ]
        except KeyError:
            raise ValueError('Invalid output affinity for "{}": {}'.format(
                item_id, conf['DualType'],
            )) from None

        def get_input(prop_name: str):
            """Parse an input command."""
            try:
                return Output.parse_name(conf[prop_name])
            except IndexError:
                return None

        out_act = get_input('out_activate')
        out_deact = get_input('out_deactivate')
        out_lock = get_input('out_lock')
        out_unlock = get_input('out_unlock')

        timer_start = timer_stop = None
        if 'out_timer_start' in conf:
            timer_start = [
                Output.parse_name(prop.value)
                for prop in conf.find_all('out_timer_start')
                if prop.value
            ]
        if 'out_timer_stop' in conf:
            timer_stop = [
                Output.parse_name(prop.value)
                for prop in conf.find_all('out_timer_stop')
                if prop.value
            ]

        return ItemType(
            item_id, default_dual, input_type, spawn_fire,
            invert_var, enable_cmd, disable_cmd,
            sec_invert_var, sec_enable_cmd, sec_disable_cmd,
            output_type, out_act, out_deact,
            lock_cmd, unlock_cmd, out_lock, out_unlock, inf_lock_only,
            timer_sound_pos, timer_done_cmd, force_timer_sound,
            timer_start, timer_stop,
        )


class Item:
    """Represents one item/instance with IO."""
    __slots__ = [
        'inst', 'item_type', '_kv_setters',
        'ind_panels',
        'antlines', 'shape_signs',
        'ant_wall_style', 'ant_floor_style',
        'timer',
        'inputs', 'outputs',
        'enable_cmd', 'disable_cmd',
        'sec_enable_cmd', 'sec_disable_cmd',
        'ant_toggle_var',
    ]

    def __init__(
        self,
        inst: Entity,
        item_type: ItemType,
        ant_floor_style: AntType,
        ant_wall_style: AntType,
        panels: Iterable[Entity]=(),
        antlines: Iterable[Antline]=(),
        shape_signs: Iterable[ShapeSignage]=(),
        timer_count: int=None,
        ant_toggle_var: str='',
    ):
        self.inst = inst
        self.item_type = item_type

        # Associated indicator panels and antlines
        self.ind_panels = set(panels)  # type: Set[Entity]
        self.antlines = set(antlines)
        self.shape_signs = list(shape_signs)

        # And the style to use for the antlines.
        self.ant_floor_style = ant_floor_style
        self.ant_wall_style = ant_wall_style

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

    def __repr__(self) -> str:
        return '<Item {}: "{}">'.format(self.item_type.id, self.name)

    @property
    def traits(self) -> Set[str]:
        """Return the set of instance traits for the item."""
        return instance_traits.get(self.inst)

    @property
    def is_logic(self) -> bool:
        """Check if the input type is a logic type."""
        return self.item_type.input_type.is_logic

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
        if self.item_type.spawn_fire.valid(self) and self.is_logic:
            return None, 'OnUser2'

        if self.item_type.input_type is InputType.DAISYCHAIN:
            if self.inputs:
                return None, COUNTER_AND_ON

        return self.item_type.output_act

    def output_deact(self) -> Optional[Tuple[Optional[str], str]]:
        """Return the output to use when this is deactivated."""
        if self.item_type.spawn_fire.valid(self) and self.is_logic:
            return None, 'OnUser1'

        if self.item_type.input_type is InputType.DAISYCHAIN:
            if self.inputs:
                return None, COUNTER_AND_OFF

        return self.item_type.output_deact

    def timer_output_start(self) -> List[Tuple[Optional[str], str]]:
        """Return the output to use for starting timers."""
        if self.item_type.timer_start is None:
            out = self.output_act()
            return [] if out is None else [out]
        return self.item_type.timer_start

    def timer_output_stop(self) -> List[Tuple[Optional[str], str]]:
        """Return the output to use for stopping timers."""
        if self.item_type.timer_stop is None:
            out = self.output_deact()
            return [] if out is None else [out]
        return self.item_type.timer_stop

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

        if not out_name:
            out_name = ''  # Dump the None.

        out_name = conditions.resolve_value(self.inst, out_name)

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
            conditions.resolve_value(self.inst, out_cmd),
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


def read_configs(conf: Property) -> None:
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
    antlines: Dict[str, List[Antline]],
    shape_frame_tex: List[str],
    enable_shape_frame: bool,
    antline_wall: AntType,
    antline_floor: AntType,
) -> None:
    """Compute item connections from the map file.

    This also fixes cases where items have incorrect checkmark/timer signs.
    Instance Traits must have been calculated.
    It also applies frames to shape signage to distinguish repeats.
    """
    # First we want to match targetnames to item types.
    toggles = {}  # type: Dict[str, Entity]
    # Accumulate all the signs into groups, so the list should be 2-long:
    # sign_shapes[name, material][0/1]
    sign_shape_overlays = defaultdict(list)  # type: Dict[Tuple[str, str], List[Entity]]

    # Indicator panels
    panels = {}  # type: Dict[str, Entity]

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
        elif 'fizzler_model' in traits:
            # Ignore fizzler models - they shouldn't have the connections.
            # Just the base itself.
            pass
        else:
            # Normal item.
            try:
                item_type = ITEM_TYPES[
                    instance_traits.get_item_id(inst).casefold()]
            except (KeyError, AttributeError):
                # KeyError from no item type, AttributeError from None.casefold()
                # These aren't made for non-io items. If it has outputs,
                # that'll be a problem later.
                pass
            else:
                # Pass in the defaults for antline styles.
                ITEMS[inst_name] = Item(
                    inst, item_type,
                    ant_floor_style=antline_floor,
                    ant_wall_style=antline_wall,
                )

                # Strip off the original connection count variables, these are
                # invalid.
                if item_type.input_type is InputType.DUAL:
                    del inst.fixup[consts.FixupVars.CONN_COUNT]
                    del inst.fixup[consts.FixupVars.CONN_COUNT_TBEAM]

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

        # Pre-set the timer value, for items without antlines but with an output.
        if consts.FixupVars.TIM_DELAY in item.inst.fixup:
            if item.item_type.output_act or item.item_type.output_deact:
                item.timer = tim = item.inst.fixup.int(consts.FixupVars.TIM_DELAY)
                if not (1 <= tim <= 30):
                    # These would be infinite.
                    item.timer = None

        for out_name in inputs:
            # Fizzler base -> model/brush outputs, ignore these (discard).
            # fizzler.py will regenerate as needed.
            if out_name.endswith(('_modelStart', '_modelEnd', '_brush')):
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

        for inp_item in input_items:
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
def res_change_io_type(inst: Entity, res: Property) -> None:
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

    # Overwrite these as well.
    item.enable_cmd = res.value.enable_cmd
    item.disable_cmd = res.value.disable_cmd

    item.sec_enable_cmd = res.value.sec_enable_cmd
    item.sec_disable_cmd = res.value.sec_disable_cmd


def do_item_optimisation(vmf: VMF) -> None:
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

    pan_switching_check = options.get(PanelSwitchingStyle, 'ind_pan_check_switching')
    pan_switching_timer = options.get(PanelSwitchingStyle, 'ind_pan_timer_switching')

    pan_check_type = ITEM_TYPES['item_indicator_panel']
    pan_timer_type = ITEM_TYPES['item_indicator_panel_timer']

    auto_logic = []

    # Apply input A/B types to connections.
    # After here, all connections are primary or secondary only.
    for item in ITEMS.values():
        for conn in item.outputs:
            # If not a dual item, it's primary.
            if conn.to_item.item_type.input_type is not InputType.DUAL:
                conn.type = ConnType.PRIMARY
                continue
            # If already set, that is the priority.
            if conn.type is not ConnType.DEFAULT:
                continue
            # Our item set the type of outputs.
            if item.item_type.output_type is not ConnType.DEFAULT:
                conn.type = item.item_type.output_type
            else:
                # Use the affinity of the target.
                conn.type = conn.to_item.item_type.default_dual

    do_item_optimisation(vmf)

    # We go 'backwards', creating all the inputs for each item.
    # That way we can change behaviour based on item counts.
    for item in ITEMS.values():
        if item.item_type is None:
            continue

        # Try to add the locking IO.
        add_locking(item)

        # Check we actually have timers, and that we want the relay.
        if item.timer is not None and (
            item.item_type.timer_sound_pos is not None or
            item.item_type.timer_done_cmd
        ):
            has_sound = item.item_type.force_timer_sound or len(item.ind_panels) > 0
            add_timer_relay(item, has_sound)

        # Add outputs for antlines.
        if item.antlines or item.ind_panels:
            if item.timer is None:
                add_item_indicators(item, pan_switching_check, pan_check_type)
            else:
                add_item_indicators(item, pan_switching_timer, pan_timer_type)

        # Special case - spawnfire items with no inputs need to fire
        # off the outputs. There's no way to control those, so we can just
        # fire it off.
        if not item.inputs and item.item_type.spawn_fire is FeatureMode.ALWAYS:
            if item.is_logic:
                # Logic gates need to trigger their outputs.
                # Make a logic_auto temporarily for this to collect the
                # outputs we need.

                item.inst.clear_keys()
                item.inst['classname'] = 'logic_auto'

                auto_logic.append(item.inst)
            else:
                is_inverted = conv_bool(conditions.resolve_value(
                    item.inst,
                    item.item_type.invert_var,
                ))
                logic_auto = vmf.create_ent(
                    'logic_auto',
                    origin=item.inst['origin'],
                    spawnflags=1,
                )
                for cmd in (item.enable_cmd if is_inverted else item.disable_cmd):
                    logic_auto.add_out(
                        Output(
                            'OnMapSpawn',
                            conditions.local_name(
                                item.inst,
                                conditions.resolve_value(item.inst, cmd.target),
                            ) or item.inst,
                            conditions.resolve_value(item.inst, cmd.input),
                            conditions.resolve_value(item.inst, cmd.params),
                            delay=cmd.delay,
                            only_once=True,
                        )
                    )

        if item.item_type.input_type is InputType.DUAL:
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
                item,
                InputType.AND,
                prim_inputs,
                consts.FixupVars.BEE_CONN_COUNT_A,
                item.enable_cmd,
                item.disable_cmd,
                item.item_type.invert_var,
            )
            add_item_inputs(
                item,
                InputType.AND,
                sec_inputs,
                consts.FixupVars.BEE_CONN_COUNT_B,
                item.sec_enable_cmd,
                item.sec_disable_cmd,
                item.item_type.sec_invert_var,
            )
        else:
            add_item_inputs(
                item,
                item.item_type.input_type,
                list(item.inputs),
                consts.FixupVars.CONN_COUNT,
                item.enable_cmd,
                item.disable_cmd,
                item.item_type.invert_var,
            )

    # Check/cross instances sometimes don't match the kind of timer delay.
    # We also might want to swap them out.

    panel_timer = instanceLocs.resolve_one('[indPanTimer]', error=True)
    panel_check = instanceLocs.resolve_one('[indPanCheck]', error=True)

    for item in ITEMS.values():
        desired_panel_inst = panel_check if item.timer is None else panel_timer

        for pan in item.ind_panels:
            pan['file'] = desired_panel_inst
            pan.fixup[consts.FixupVars.TIM_ENABLED] = item.timer is not None

    logic_auto = vmf.create_ent(
        'logic_auto',
        origin=options.get(Vec, 'global_ents_loc')
    )

    for ent in auto_logic:
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
    if item.item_type.output_lock is None and item.item_type.output_unlock is None:
        return
    if item.item_type.input_type is InputType.DUAL:
        LOGGER.warning(
            'Item type ({}) with locking IO, but dual inputs. '
            'Locking functionality is ignored!',
            item.item_type.id
        )
        return

    # If more than one, it's not logical to lock the button.
    try:
        [lock_conn] = item.inputs
    except ValueError:
        return

    lock_button = lock_conn.from_item

    if item.item_type.inf_lock_only and lock_button.timer is not None:
        return

    # Check the button doesn't also activate other things -
    # we need exclusive control.
    # Also the button actually needs to be lockable.
    if len(lock_button.outputs) != 1 or not lock_button.item_type.lock_cmd:
        return

    instance_traits.get(item.inst).add('locking_targ')
    instance_traits.get(lock_button.inst).add('locking_btn')

    # Force the item to not have a timer.
    for pan in item.ind_panels:
        pan.remove()
    item.ind_panels.clear()

    for output, input_cmds in [
        (item.item_type.output_lock, lock_button.item_type.lock_cmd),
        (item.item_type.output_unlock, lock_button.item_type.unlock_cmd)
    ]:
        if not output:
            continue

        for cmd in input_cmds:
            if cmd.target:
                target = conditions.local_name(lock_button.inst, cmd.target)
            else:
                target = lock_button.inst
            item.add_io_command(
                output,
                target,
                cmd.input,
                cmd.params,
                delay=cmd.delay,
                times=cmd.times,
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

    if item.item_type.timer_sound_pos:
        relay_loc = item.item_type.timer_sound_pos.copy()
        relay_loc.localise(
            Vec.from_str(item.inst['origin']),
            Vec.from_str(item.inst['angles']),
        )
        relay['origin'] = relay_loc
    else:
        relay['origin'] = item.inst['origin']

    for cmd in item.item_type.timer_done_cmd:
        if cmd:
            relay.add_out(Output(
                'OnTrigger',
                conditions.local_name(item.inst, cmd.target) or item.inst,
                conditions.resolve_value(item.inst, cmd.input),
                conditions.resolve_value(item.inst, cmd.params),
                inst_in=cmd.inst_in,
                delay=item.timer + cmd.delay,
                times=cmd.times,
            ))

    if item.item_type.timer_sound_pos is not None and has_sounds:
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

    for outputs, cmd in [
        (item.timer_output_start(), 'Trigger'),
        (item.timer_output_stop(), 'CancelPending')
    ]:
        for output in outputs:
            item.add_io_command(output, rl_name, cmd)


def add_item_inputs(
    item: Item,
    logic_type: InputType,
    inputs: List[Connection],
    count_var: str,
    enable_cmd: Iterable[Output],
    disable_cmd: Iterable[Output],
    invert_var: str,
) -> None:
    """Handle either the primary or secondary inputs to an item."""
    item.inst.fixup[count_var] = len(inputs)

    if len(inputs) == 0:
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
                    inp_item.add_io_command(
                        output,
                        item.inst,
                        conditions.resolve_value(item.inst, cmd.input),
                        conditions.resolve_value(item.inst, cmd.params),
                        inst_in=cmd.inst_in,
                        delay=cmd.delay,
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
                item.item_type.id,
            )

        # Use the item type's output, we've overridden the normal one.
        item.add_io_command(
            item.item_type.output_act,
            counter, 'Add', '1',
        )
        item.add_io_command(
            item.item_type.output_deact,
            counter, 'Subtract', '1',
        )

        for conn in inputs:
            inp_item = conn.from_item
            inp_item.add_io_command(inp_item.output_act(), counter, 'Add', '1')
            inp_item.add_io_command(inp_item.output_deact(), counter, 'Subtract', '1')

        return

    is_inverted = conv_bool(conditions.resolve_value(
        item.inst,
        invert_var,
    ))

    if is_inverted:
        enable_cmd, disable_cmd = disable_cmd, enable_cmd

        # Inverted logic items get a short amount of lag, so loops will propagate
        # over several frames so we don't lock up.
        if item.inputs and item.outputs:
            enable_cmd = [
                Output(
                    '',
                    out.target,
                    out.input,
                    out.params,
                    out.delay + 0.01,
                    times=out.times,
                    inst_in=out.inst_in,
                )
                for out in enable_cmd
            ]
            disable_cmd = [
                Output(
                    '',
                    out.target,
                    out.input,
                    out.params,
                    out.delay + 0.01,
                    times=out.times,
                    inst_in=out.inst_in,
                )
                for out in disable_cmd
            ]

    needs_counter = len(inputs) > 1

    # If this option is enabled, generate additional logic to fire the disable
    # output after spawn (but only if it's not triggered normally.)

    # We just use a relay to do this.
    # User2 is the real enable input, User1 is the real disable input.

    # The relay allows cancelling the 'disable' output that fires shortly after
    # spawning.
    if item.item_type.spawn_fire is not FeatureMode.NEVER:
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
            relay_cmd_name = '@' + item.name + '_inv_rl'
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
                spawn_relay.add_out(
                    Output(
                        output_name,
                        conditions.local_name(
                            item.inst,
                            conditions.resolve_value(item.inst, cmd.target),
                        ) or item.inst,
                        conditions.resolve_value(item.inst, cmd.input),
                        conditions.resolve_value(item.inst, cmd.params),
                        delay=cmd.delay,
                        times=cmd.times,
                    )
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
            count_on = COUNTER_AND_ON
            count_off = COUNTER_AND_OFF
        elif logic_type is InputType.OR:
            count_on = COUNTER_OR_ON
            count_off = COUNTER_OR_OFF
        elif logic_type.is_logic:
            # We don't add outputs here, the outputted items do that.
            # counter is item.inst, so those are added to that.
            return
        else:
            # Should never happen, not other types.
            raise ValueError('Unknown counter logic type: ' + repr(logic_type))

        for output_name, input_cmds in [
            (count_on, enable_cmd),
            (count_off, disable_cmd)
        ]:
            for cmd in input_cmds:
                counter.add_out(
                    Output(
                        output_name,
                        conditions.local_name(
                            item.inst,
                            conditions.resolve_value(item.inst, cmd.target),
                        ) or item.inst,
                        conditions.resolve_value(item.inst, cmd.input),
                        conditions.resolve_value(item.inst, cmd.params),
                        delay=cmd.delay,
                        times=cmd.times,
                    )
                )

    else:  # No counter - fire directly.
        for conn in inputs:
            inp_item = conn.from_item
            for output, input_cmds in [
                (inp_item.output_act(), enable_cmd),
                (inp_item.output_deact(), disable_cmd)
            ]:
                for cmd in input_cmds:
                    inp_item.add_io_command(
                        output,
                        conditions.local_name(
                            item.inst,
                            conditions.resolve_value(item.inst, cmd.target),
                        ) or item.inst,
                        conditions.resolve_value(item.inst, cmd.input),
                        conditions.resolve_value(item.inst, cmd.params),
                        delay=cmd.delay,
                        times=cmd.times,
                    )


def add_item_indicators(
    item: Item,
    inst_type: PanelSwitchingStyle,
    pan_item: ItemType,
) -> None:
    """Generate the commands for antlines and the overlays themselves."""
    ant_name = '@{}_overlay'.format(item.name)
    has_sign = len(item.ind_panels) > 0
    has_ant = len(item.antlines) > 0

    for ant in item.antlines:
        ant.name = ant_name

        ant.export(item.inst.map, wall_conf=item.ant_wall_style, floor_conf=item.ant_floor_style)

    # Special case - the item wants full control over its antlines.
    if has_ant and item.ant_toggle_var:
        item.inst.fixup[item.ant_toggle_var] = ant_name
        # We don't have antlines to control.
        has_ant = False

    if inst_type is PanelSwitchingStyle.CUSTOM:
        needs_toggle = has_ant
    elif inst_type is PanelSwitchingStyle.EXTERNAL:
        needs_toggle = has_ant or has_sign
    elif inst_type is PanelSwitchingStyle.INTERNAL:
        if (
            item.item_type.timer_start is not None or
            item.item_type.timer_stop is not None
        ):
            # The item is doing custom control over the timer, so
            # don't tie antline control to the timer.
            needs_toggle = has_ant
            inst_type = PanelSwitchingStyle.CUSTOM
        else:
            needs_toggle = has_ant and not has_sign
    else:
        raise ValueError('Bad switch style ' + repr(inst_type))

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

        # Overwrite the timer delay value, in case a sign changed ownership.
        if item.timer is not None:
            pan.fixup[consts.FixupVars.TIM_DELAY] = item.timer
            pan.fixup[consts.FixupVars.TIM_ENABLED] = '1'
        else:
            pan.fixup[consts.FixupVars.TIM_DELAY] = '99999999999'
            pan.fixup[consts.FixupVars.TIM_ENABLED] = '0'

        for outputs, input_cmds in [
            (item.timer_output_start(), pan_item.enable_cmd),
            (item.timer_output_stop(), pan_item.disable_cmd)
        ]:
            for output in outputs:
                for cmd in input_cmds:
                    item.add_io_command(
                        output,
                        conditions.local_name(
                            pan,
                            conditions.resolve_value(item.inst, cmd.target),
                        ) or pan,
                        conditions.resolve_value(item.inst, cmd.input),
                        conditions.resolve_value(item.inst, cmd.params),
                        delay=cmd.delay,
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
