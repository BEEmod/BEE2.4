"""The classes and enums representing item connection configuration.

This controls how I/O is generated for each item.
"""
from __future__ import annotations
from typing import Dict, Final, Iterable
from typing_extensions import Self
from enum import Enum
import sys

from srctools import Keyvalues, Output, Vec, conv_bool
import attrs

import utils


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 'default'  # Normal / un-configured input
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
VALID_CONN_TYPE_NAMES = ', '.join([f'"{x}"' for x in sorted(CONN_TYPE_NAMES)])


@utils.freeze_enum_props
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
    def is_logic(self) -> bool:
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


class OutNames(Enum):
    """Fake input/outputs used in generation of the real ones."""
    # Needs to match gameMan.Game.build_instance_data().
    IN_ACT = 'ACTIVATE'
    IN_DEACT = 'DEACTIVATE'

    IN_SEC_ACT = 'ACTIVATE_SECONDARY'
    IN_SEC_DEACT = 'DEACTIVATE_SECONDARY'

    OUT_ACT = 'ON_ACTIVATED'
    OUT_DEACT = 'ON_DEACTIVATED'


# Item IDs used for the checkmark/timer panels.
INDICATOR_CHECK_ID: Final = utils.obj_id('ITEM_INDICATOR_PANEL')
INDICATOR_TIMER_ID: Final = utils.obj_id('ITEM_INDICATOR_PANEL_TIMER')


def _intern_out(out: tuple[str | None, str] | None) -> tuple[str | None, str] | None:
    if out is None:
        return None
    out_name, output = out
    if out_name is not None:
        out_name = sys.intern(out_name)
    return out_name, output


def format_output_name(out_tup: tuple[str | None, str]) -> str:
    """Convert the output tuple into a nice string."""
    inst, out = out_tup
    if inst is not None:
        return f'{inst} -> {out}'
    else:
        return out


def format_delay(offset: float, add_timer_delay: bool) -> str:
    """Format a number which may have $timer_delay added to it."""
    if add_timer_delay:
        if offset == 0.0:
            return '$timer_delay'
        else:
            return f'$timer_delay{offset:+}'
    else:
        if offset == 0.0:
            return ''
        else:
            return str(offset)

OUT_NAME_DESC = (
    'This should be either an instance output name like '
    '"instance:ent_name;OnSomeOutput", or a simple output name like "OnStartTouch" '
    'if the instance is being replaced by a single entity.'
)


def get_input(kv_name: str, desc: str, inp_str: str) -> tuple[str | None, str] | None:
    """Parse an input command."""
    if not inp_str:
        return None
    try:
        return Output.parse_name(inp_str)
    except ValueError:
        raise ValueError(
            f'Could not parse output name for {desc}: {kv_name}="{inp_str}"\n{OUT_NAME_DESC}'
        ) from None


def get_outputs(conf: Keyvalues,  desc: str, kv_name: str) -> list[Output]:
    """Parse all the outputs with this name."""
    outputs = []
    for kv in conf.find_all(kv_name):
        if kv.value != '':
            try:
                out = Output.parse(kv)
            except ValueError:
                raise ValueError(
                    f'Could not parse output value for {desc}: {kv_name}="{kv.value}"\n'
                    'A value similar to AddOutput in the form '
                    '"target_ent,input,parameters,delay,times_to_fire" is expected.\n'
                ) from None
            out.output = ''  # Clear this, it's unused.
            outputs.append(out)
    return outputs


@utils.freeze_enum_props
class TimerModes(Enum):
    """Modes for timer indicator panel commands."""
    COUNT_UP = 'countup'  # Go from empty to full.
    COUNT_DOWN = 'countdown'  # Go from full to empty.
    RESET_FULL = 'resetfull'  # Reset back to full, over about 0.25 seconds.
    RESET_EMPTY = 'resetempty'  # Reset back to empty, over about 0.25 seconds.

    @property
    def is_count(self) -> bool:
        """Return whether this is a gradual count."""
        return self.name.startswith('COUNT')

    @property
    def is_reset(self) -> bool:
        """Return whether this resets the timer."""
        return self.name.startswith('RESET')


@attrs.frozen
class TimerCommand:
    """Outputs to generate to control timer indicator panels."""
    output: tuple[str | None, str]  # Output to use plus the name.
    mode: TimerModes  # Basically the input.
    delay: float  = attrs.field(kw_only=True, default=0.0)  # Output delay.
    delay_add_timer: bool = attrs.field(kw_only=True)  # If set, add $timer_delay to delay.
    fadetime: float = attrs.field(kw_only=True, default=0.0)  # The time taken to do the fade.
    fadetime_add_timer: bool = attrs.field(kw_only=True)  # If set, add $timer_delay to fade-time.

    @classmethod
    def parse(cls, kv: Keyvalues, desc: str) -> Self:
        """Parse a command from keyvalues."""
        output = get_input('output', desc, kv['output', ''])
        if output is None:
            raise ValueError(f'Timer command in {desc} must have an output name provided!\n{OUT_NAME_DESC}')

        mode_str = kv['mode', 'countdown'].casefold()
        try:
            mode = TimerModes(mode_str)
        except ValueError:
            raise ValueError(
                f'Timer command uses invalid mode "{mode_str}"! The mode must be one of '
                f'"CountUp", "CountDown", "ResetFull" or "ResetEmpty".'
            ) from None

        return cls(
            output,
            mode,
            delay=kv.float('delay'),
            delay_add_timer=kv.bool('delay_add_timer'),
            fadetime=kv.float('fadetime'),
            fadetime_add_timer=kv.bool('fadetime_add_timer'),
        )


class Config:
    """Represents a type of item, with inputs and outputs.

    This is shared by all items of the same type.
    """
    output_act: tuple[str | None, str] | None
    output_deact: tuple[str | None, str] | None

    def __init__(
        self,
        item_id: str,
        default_dual: ConnType=ConnType.DEFAULT,
        input_type: InputType=InputType.DEFAULT,

        spawn_fire: FeatureMode=FeatureMode.NEVER,
        invert_var: str = '0',
        enable_cmd: Iterable[Output]=(),
        disable_cmd: Iterable[Output]=(),

        sec_spawn_fire: FeatureMode=FeatureMode.NEVER,
        sec_invert_var: str='0',
        sec_enable_cmd: Iterable[Output]=(),
        sec_disable_cmd: Iterable[Output]=(),

        output_type: ConnType=ConnType.DEFAULT,
        output_act: tuple[str | None, str] | None=None,
        output_deact: tuple[str | None, str] | None=None,

        lock_cmd: Iterable[Output]=(),
        unlock_cmd: Iterable[Output]=(),
        output_lock: tuple[str | None, str] | None=None,
        output_unlock: tuple[str | None, str] | None=None,
        inf_lock_only: bool=False,

        timer_sound_pos: Vec | None=None,
        timer_done_cmd: Iterable[Output]=(),
        force_timer_sound: bool=False,
        timer_outputs: Iterable[TimerCommand]=(),
    ) -> None:
        self.id = item_id

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
        # Set to Default to indicate no secondary is present.
        self.default_dual = default_dual

        # Same for secondary items.
        self.sec_invert_var = sec_invert_var
        self.sec_spawn_fire = sec_spawn_fire
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

        # If set, connections for controlling timer indicator panels. If empty, we use the normal
        # outputs for countdown.
        self.timer_outputs = list(timer_outputs)

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
    def parse(item_id: str, conf: Keyvalues) -> Config:
        """Read the item type info from the given config."""
        desc = f'item "{item_id}"'

        enable_cmd = get_outputs(conf, desc, 'enable_cmd')
        disable_cmd = get_outputs(conf, desc, 'disable_cmd')
        lock_cmd = get_outputs(conf, desc, 'lock_cmd')
        unlock_cmd = get_outputs(conf, desc, 'unlock_cmd')

        inf_lock_only = conf.bool('inf_lock_only')

        timer_done_cmd = get_outputs(conf, desc, 'timer_done_cmd')
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
            raise ValueError('Invalid input type for "{}": {}'.format(
                item_id, conf['type'],
            )) from None

        invert_var = conf['invertVar', '0']

        spawn_fire_str = conf['spawnfire', 'never']
        try:
            spawn_fire = FeatureMode(spawn_fire_str.casefold())
        except ValueError:
            # Older config option - it was a bool for always/never.
            spawn_fire_bool = conv_bool('spawnfire', None)
            if spawn_fire_bool is None:
                # Not a bool or the expected value, complain.
                raise ValueError(
                    f'Invalid spawnfire option for item "{item_id}: "{spawn_fire_str}"\n'
                    'Valid options: "always", "dynamic", "never"'
                ) from None

            spawn_fire = FeatureMode.ALWAYS if spawn_fire_bool else FeatureMode.NEVER

        try:
            sec_spawn_fire = FeatureMode(conf['sec_spawnfire', 'never'].casefold())
        except ValueError:  # Default to primary value.
            raise ValueError(
                f'Invalid secondary spawnfire option for item "{item_id}: "{conf["sec_spawnfire"]}"\n'
                'Valid options: "always", "dynamic", "never"'
            ) from None

        if input_type is InputType.DUAL:
            sec_enable_cmd = get_outputs(conf, desc, 'sec_enable_cmd')
            sec_disable_cmd = get_outputs(conf, desc, 'sec_disable_cmd')

            try:
                default_dual = CONN_TYPE_NAMES[
                    conf['Default_Dual', 'primary'].casefold()
                ]
            except KeyError:
                raise ValueError(
                    f'Invalid default type for "{item_id}": {conf["Default_Dual"]}\n'
                    f'Valid values: {VALID_CONN_TYPE_NAMES}'
                ) from None

            # We need an affinity to use when nothing else specifies it.
            if default_dual is ConnType.DEFAULT:
                raise ValueError(
                    f'Must specify a "default_dual" type for "{item_id}" when using type=dual!'
                ) from None

            sec_invert_var = conf['sec_invertVar', '0']
        else:
            # No dual type, set to default values.
            sec_enable_cmd = []
            sec_disable_cmd = []
            default_dual = ConnType.DEFAULT
            sec_invert_var = ''

        try:
            output_type = CONN_TYPE_NAMES[
                conf['DualType', 'default'].casefold()
            ]
        except KeyError:
            raise ValueError(
                f'Invalid output affinity for "{item_id}": {conf["DualType"]}\n'
                f'Valid values: {VALID_CONN_TYPE_NAMES}'
            ) from None

        out_act = get_input('out_activate', desc, conf['out_activate', ''])
        out_deact = get_input('out_deactivate', desc, conf['out_deactivate', ''])
        out_lock = get_input('out_lock', desc, conf['out_lock', ''])
        out_unlock = get_input('out_unlock', desc, conf['out_unlock', ''])

        timer_outputs = [
            TimerCommand.parse(cmd, desc)
            for cmd in conf.find_all('TimerCommand')
        ]
        if not timer_outputs:
            # The original deprecated commands, which control the regular style timer.
            for kv in conf:
                if kv.name == 'out_timer_start':
                    output = get_input(kv.real_name, desc, kv.value)
                    if output is not None:
                        timer_outputs.append(TimerCommand(
                            output,
                            mode=TimerModes.COUNT_DOWN,
                            delay_add_timer=False,
                            fadetime_add_timer=True,
                        ))
                elif kv.name == 'out_timer_stop':
                    output = get_input(kv.real_name, desc, kv.value)
                    if output is not None:
                        timer_outputs.append(TimerCommand(
                            output,
                            mode=TimerModes.RESET_FULL,
                            delay_add_timer=False,
                            fadetime_add_timer=False,
                        ))

        return Config(
            item_id, default_dual, input_type,
            spawn_fire, invert_var, enable_cmd, disable_cmd,
            sec_spawn_fire, sec_invert_var, sec_enable_cmd, sec_disable_cmd,
            output_type, out_act, out_deact,
            lock_cmd, unlock_cmd, out_lock, out_unlock, inf_lock_only,
            timer_sound_pos, timer_done_cmd, force_timer_sound, timer_outputs,
        )

    def __getstate__(self) -> tuple:

        return (
            self.id,
            self.input_type,
            sys.intern(self.invert_var),
            self.spawn_fire,
            self.enable_cmd,
            self.disable_cmd,
            self.default_dual,
            sys.intern(self.sec_invert_var),
            self.sec_spawn_fire,
            self.sec_enable_cmd,
            self.sec_disable_cmd,
            self.output_type,
            _intern_out(self.output_act),
            _intern_out(self.output_deact),
            self.timer_sound_pos,
            self.timer_done_cmd,
            self.force_timer_sound,
            self.timer_outputs,
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
            self.sec_spawn_fire,
            self.sec_enable_cmd,
            self.sec_disable_cmd,
            self.output_type,
            self.output_act,
            self.output_deact,
            self.timer_sound_pos,
            self.timer_done_cmd,
            self.force_timer_sound,
            self.timer_outputs,
            self.lock_cmd,
            self.unlock_cmd,
            self.inf_lock_only,
            self.output_lock,
            self.output_unlock,
        ) = state

    def get_input_blurb(self) -> str:
        """For development, summarise all input-related configuration."""
        text = [
            f'Input type: {self.input_type.value}',
        ]
        if self.input_type is InputType.DUAL:
            text += [
                f'Default (without A/B item): {self.default_dual.value.title()}',
                f'Primary Invert: {self.invert_var}',
                f'Primary Spawn Fire: {self.spawn_fire.value.title()}',
                f'Secondary Invert: {self.sec_invert_var}',
                f'Secondary Spawn Fire: {self.sec_spawn_fire.value.title()}',
            ]
            primary = 'Primary '
        else:
            text += [
                f'Invert: {self.invert_var}',
                f'Spawn Fire: {self.spawn_fire.value.title()}',
            ]
            primary = ''

        for out in self.enable_cmd:
            # Slice to strip the beginning "<Output> ".
            text.append(f'{primary}Enable {str(out)[9:]}')
        for out in self.disable_cmd:
            text.append(f'{primary}Disable {str(out)[9:]}')
        for out in self.sec_enable_cmd:
            text.append(f'Secondary Enable {str(out)[9:]}')
        for out in self.sec_disable_cmd:
            text.append(f'Secondary Disable {str(out)[9:]}')

        # Output, but it goes backwards towards the input item.
        if self.output_lock is not None:
            text.append('Button Lock: ' + format_output_name(self.output_lock))
        if self.output_unlock is not None:
            text.append('Button Unlock: ' + format_output_name(self.output_unlock))

        return '\n'.join(text)

    def get_output_blurb(self) -> str:
        """For development, summarise all output-related configuration."""
        text: list[str] = []

        if self.output_type is not ConnType.DEFAULT:
            text.append(f'Affinity: {self.output_type.value.title()}')

        if self.output_act is not None:
            text.append('Activation: ' + format_output_name(self.output_act))
        if self.output_deact is not None:
            text.append('Deactivation: ' + format_output_name(self.output_deact))

        for cmd in self.timer_outputs:
            text.append(
                f'Timer Cmd: {format_output_name(cmd.output)} => {cmd.mode.value}('
                f'{format_delay(cmd.delay, cmd.delay_add_timer)}'
                f') @ {format_delay(cmd.delay, cmd.delay_add_timer)} sec'
            )

        if self.timer_sound_pos is not None:
            text += [
                f'Timer Sound Offset: ({self.timer_sound_pos})',
                f'Always play ticktock: {self.force_timer_sound}',
                f'Only lock infinite buttons: {self.inf_lock_only}',
            ]

        for output in self.timer_done_cmd:
            text.append(f'Timer Complete: {str(output)[9:]}')

        if self.lock_cmd and self.unlock_cmd:
            for output in self.lock_cmd:
                text.append(f'Button Lock {str(output)[9:]}')
            for output in self.unlock_cmd:
                text.append(f'Button Unlock {str(output)[9:]}')

        return '\n'.join(text)
