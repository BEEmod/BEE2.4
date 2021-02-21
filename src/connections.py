"""The classes and enums representing item connection configuration.

This controls how I/O is generated for each item.
"""
import sys
from enum import Enum
from typing import Dict, Optional, Tuple, Iterable, List

import consts
from srctools import Output, Vec, Property


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


class FeatureMode(Enum):
    """When to apply a feature."""
    DYNAMIC = 'dynamic'  # Only if dynamic (inputs)
    ALWAYS = 'always'
    NEVER = 'never'

    def valid(self, has_inputs: bool) -> bool:
        """Check if this is valid for the item."""
        if self.value == 'dynamic':
            return has_inputs
        else:
            return self.value == 'always'


class OutNames(str, Enum):
    """Fake input/outputs used in generation of the real ones."""
    # Needs to match gameMan.Game.build_instance_data().
    IN_ACT = 'ACTIVATE'
    IN_DEACT = 'DEACTIVATE'

    IN_SEC_ACT = 'ACTIVATE_SECONDARY'
    IN_SEC_DEACT = 'DEACTIVATE_SECONDARY'

    OUT_ACT = 'ON_ACTIVATED'
    OUT_DEACT = 'ON_DEACTIVATED'


def _intern_out(out: Optional[Tuple[Optional[str], str]]) -> Optional[Tuple[Optional[str], str]]:
    if out is None:
        return None
    out_name, output = out
    if out_name is not None:
        out_name = sys.intern(out_name)
    return out_name, output


class Config:
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

        return Config(
            item_id, default_dual, input_type, spawn_fire,
            invert_var, enable_cmd, disable_cmd,
            sec_invert_var, sec_enable_cmd, sec_disable_cmd,
            output_type, out_act, out_deact,
            lock_cmd, unlock_cmd, out_lock, out_unlock, inf_lock_only,
            timer_sound_pos, timer_done_cmd, force_timer_sound,
            timer_start, timer_stop,
        )

    def __getstate__(self) -> tuple:
        if self.timer_start is None:
            timer_start = None
        else:
            timer_start = list(map(_intern_out, self.timer_start))
        if self.timer_stop is None:
            timer_stop = None
        else:
            timer_stop = list(map(_intern_out, self.timer_stop))

        return (
            self.id,
            self.input_type,
            sys.intern(self.invert_var),
            self.spawn_fire,
            self.enable_cmd,
            self.disable_cmd,
            self.default_dual,
            sys.intern(self.sec_invert_var),
            self.sec_enable_cmd,
            self.sec_disable_cmd,
            self.output_type,
            _intern_out(self.output_act),
            _intern_out(self.output_deact),
            self.timer_sound_pos,
            self.timer_done_cmd,
            self.force_timer_sound,
            timer_start,
            timer_stop,
            self.lock_cmd,
            self.unlock_cmd,
            self.inf_lock_only,
            _intern_out(self.output_lock),
            _intern_out(self.output_unlock),
        )

    def __setstate__(self, state: tuple) -> None:
        (
            self.id,
            self.input_type,
            self.invert_var,
            self.spawn_fire,
            self.enable_cmd,
            self.disable_cmd,
            self.default_dual,
            self.sec_invert_var,
            self.sec_enable_cmd,
            self.sec_disable_cmd,
            self.output_type,
            self.output_act,
            self.output_deact,
            self.timer_sound_pos,
            self.timer_done_cmd,
            self.force_timer_sound,
            self.timer_start,
            self.timer_stop,
            self.lock_cmd,
            self.unlock_cmd,
            self.inf_lock_only,
            self.output_lock,
            self.output_unlock,
        ) = state
