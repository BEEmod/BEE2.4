"""Customizable configuration for specific items or groups of them."""
from __future__ import annotations

from typing import Any, Final, Protocol, Self, override
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, aclosing
import itertools

from srctools import EmptyMapping, Keyvalues, Vec, bool_as_int, conv_bool, logger
from trio_util import AsyncValue, wait_any
import attrs
import trio

from app.mdown import MarkdownData
from config.widgets import (
    TIMER_NUM as TIMER_NUM, TIMER_NUM_INF as TIMER_NUM_INF,
    TimerNum as TimerNum, WidgetConfig,
)
from config.stylevar import State as StyleVarState
from transtoken import TransToken, TransTokenSource
import BEE2_config
import config
import packages
import utils


class ConfigProto(Protocol):
    """Protocol widget configuration classes must match."""
    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues, /) -> Self:
        """Parse keyvalues into a widget config."""


# This has to reload items when changed.
UNLOCK_DEFAULT_ID: Final = 'VALVE_MANDATORY:unlockdefault'
LEGACY_CONFIG = BEE2_config.ConfigFile('item_cust_configs.cfg', legacy=True)
LOGGER = logger.get_logger(__name__)


@attrs.frozen
class WidgetType:
    """Information about a type of widget."""
    name: str
    is_wide: bool


@attrs.frozen
class WidgetTypeWithConf[ConfT: ConfigProto](WidgetType):
    """Information about a type of widget, that requires configuration."""
    conf_type: type[ConfT]


# Maps widget type names to the type info.
WIDGET_KINDS: dict[str, WidgetType] = {}
CLS_TO_KIND: dict[type[ConfigProto], WidgetTypeWithConf[Any]] = {}


class RegisterDeco(Protocol):
    """Return type for register()."""
    def __call__[ConfT: ConfigProto](self, cls: type[ConfT], /) -> type[ConfT]:
        ...


def register(*names: str, wide: bool = False) -> RegisterDeco:
    """Register a widget type that takes config.

    If wide is set, the widget is put into a labelframe, instead of having a label to the side.
    """
    if not names:
        raise TypeError('No name defined!')

    def deco[ConfT: ConfigProto](cls: type[ConfT], /) -> type[ConfT]:
        """Do the registration."""
        kind = WidgetTypeWithConf(names[0], wide, cls)
        assert cls not in CLS_TO_KIND, cls
        CLS_TO_KIND[cls] = kind
        for name in names:
            name = name.casefold()
            assert name not in WIDGET_KINDS, name
            WIDGET_KINDS[name] = kind
        return cls
    return deco


def register_no_conf(*names: str, wide: bool = False) -> WidgetType:
    """Register a widget type which does not need additional configuration.

    Many only need the default values.
    """
    kind = WidgetType(names[0], wide)
    for name in names:
        name = name.casefold()
        assert name not in WIDGET_KINDS, name
        WIDGET_KINDS[name] = kind
    return kind


def mandatory_unlocked() -> bool:
    """Check if mandatory items should be shown."""
    option = config.APP.get_cur_conf(WidgetConfig, UNLOCK_DEFAULT_ID).values
    if not isinstance(option, str):
        LOGGER.warning('Unlock Default option is a timer?')
        return False
    return conv_bool(option)


@attrs.define
class Widget:
    """Common logic for both kinds of widget that can appear on a ConfigGroup."""
    group_id: str
    id: str
    name: TransToken
    tooltip: TransToken
    config: object
    kind: WidgetType

    @property
    def has_values(self) -> bool:
        """Item variant widgets don't have configuration, all others do."""
        return self.kind is not KIND_ITEM_VARIANT

    def conf_id(self) -> str:
        """Return the config key used for this widget."""
        return f'{self.group_id}:{self.id}'

    def create_conf(self) -> WidgetConfig:
        """Create a copy of the current configuration."""
        raise NotImplementedError


@attrs.define
class SingleWidget(Widget):
    """Represents a single widget with no timer value."""
    holder: AsyncValue[str]
    # Used for some configs ported from stylevars.
    stylevar_id: str

    def create_conf(self) -> WidgetConfig:
        return WidgetConfig(self.holder.value)

    async def load_conf_task(
        self, cm: AbstractContextManager[trio.MemoryReceiveChannel[WidgetConfig]],
    ) -> None:
        """Apply the configuration to the UI."""
        if not self.has_values:
            return  # No need to load.

        data: WidgetConfig
        with cm as channel:
            async for data in channel:
                if isinstance(data.values, str):
                    self.holder.value = data.values
                else:
                    LOGGER.warning(
                        '{}:{}: Saved config is timer-based, but widget is singular.',
                        self.group_id, self.id,
                    )

    async def state_store_task(self) -> None:
        """Async task which stores the state in configs whenever it changes."""
        if not self.has_values:
            return  # No need to save anything.

        data_id = self.conf_id()
        async with aclosing(self.holder.eventual_values()) as agen:
            async for value in agen:
                # Don't use create_conf(), we already have the current value.
                config.APP.store_conf(WidgetConfig(value), data_id)
                # Make sure the old ID is no longer present whenever saving.
                if self.stylevar_id:
                    config.APP.discard_conf(StyleVarState, self.stylevar_id)


@attrs.define
class MultiWidget(Widget):
    """Represents a group of multiple widgets for all the timer values."""
    use_inf: bool  # For timer, is infinite valid?
    holders: dict[TimerNum, AsyncValue[str]]

    def create_conf(self) -> WidgetConfig:
        return WidgetConfig({
            num: holder.value
            for num, holder in self.holders.items()
        })

    async def load_conf_task(
        self, cm: AbstractContextManager[trio.MemoryReceiveChannel[WidgetConfig]],
    ) -> None:
        """Apply the configuration to the UI."""
        data: WidgetConfig
        with cm as channel:
            async for data in channel:
                if isinstance(data.values, str):
                    # Single in conf, apply to all.
                    for holder in self.holders.values():
                        holder.value = data.values
                else:
                    for num, holder in self.holders.items():
                        try:
                            holder.value = data.values[num]
                        except KeyError:
                            continue

    async def state_store_task(self) -> None:
        """Async task which stores the state in configs whenever it changes."""
        data_id = self.conf_id()
        while True:
            # Wait for any to change, then store. We don't do them individually, since
            # we don't want a store spam if they get changed all at once.
            await wait_any(*[
                holder.wait_transition
                for holder in self.holders.values()
            ])
            config.APP.store_conf(self.create_conf(), data_id)


class ConfigGroup(packages.PakObject, allow_mult=True, needs_foreground=True):
    """A group of configs for an item."""
    def __init__(
        self,
        conf_id: str,
        group_name: TransToken,
        desc: MarkdownData,
        widgets: list[SingleWidget],
        multi_widgets: list[MultiWidget],
    ) -> None:
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets
        self.multi_widgets = multi_widgets

    @classmethod
    @override
    async def parse(cls, data: packages.ParseData) -> ConfigGroup:
        """Parse the config group from info.txt."""
        await trio.lowlevel.checkpoint()
        props = data.info

        if data.is_override:
            # Override doesn't need to have a name.
            group_name = TransToken.BLANK
        else:
            group_name = TransToken.parse(data.pak_id, props['Name'])

        desc = packages.desc_parse(props, data.id, data.pak_id)

        ids: set[str] = set()  # Prevent duplicates inside this definition.
        widgets: list[SingleWidget] = []
        multi_widgets: list[MultiWidget] = []

        for wid in props.find_all('Widget'):
            await trio.lowlevel.checkpoint()
            try:
                kind = WIDGET_KINDS[wid['type'].casefold()]
            except KeyError:
                LOGGER.warning(
                    'Unknown widget type "{}" in <{}:{}>!',
                    wid['type'],
                    data.pak_id,
                    data.id,
                )
                continue

            is_timer = wid.bool('UseTimer')
            use_inf = is_timer and wid.bool('HasInf')
            wid_id = wid['id'].casefold()

            if wid_id in ids:
                # Duplicates inside the definition are nonsensical.
                raise ValueError(f'{data.id} in {data.pak_id} has duplicate widget "{wid_id}"!')
            ids.add(wid_id)

            try:
                name = TransToken.parse(data.pak_id, wid['Label'])
            except LookupError:
                name = TransToken.untranslated(wid_id)
            tooltip = TransToken.parse(data.pak_id, '\n'.join(
                wid.find_key('Tooltip', '').as_array()  # Allow the multiline description style
            ))
            default_prop = wid.find_key('Default', '')

            prev_conf = config.APP.get_cur_conf(
                WidgetConfig,
                f'{data.id}:{wid_id}',
            ).values

            # Special case - can't be timer, and no values.
            if kind is KIND_ITEM_VARIANT:
                if is_timer:
                    LOGGER.warning("Item Variants can't be timers! ({}.{})", data.id, wid_id)
                    is_timer = use_inf = False

            if isinstance(kind, WidgetTypeWithConf):
                wid_conf: object = kind.conf_type.parse(data, wid)
            else:
                wid_conf = None

            if stylevar_id := wid['legacy_stylevar_id', '']:
                if kind is not KIND_CHECKMARK:
                    raise ValueError(
                        f'"{data.id}.{wid_id}": '
                        f'Legacy Stylevars can only be checkmark kinds, not {kind}!'
                    )
                if is_timer:
                    raise ValueError(
                        f'"{data.id}.{wid_id}": Legacy Stylevars can only be singular!'
                    )
                if prev_conf is EmptyMapping:
                    prev_conf = bool_as_int(config.APP.get_cur_conf(
                        StyleVarState, stylevar_id,
                        StyleVarState(conv_bool(default_prop.value)),
                    ).value)
                    LOGGER.debug('Converted legacy stylevar "{}"', stylevar_id)

            if is_timer:
                if default_prop.has_children():
                    defaults = {
                        num: default_prop[num]
                        for num in (TIMER_NUM_INF if use_inf else TIMER_NUM)
                    }
                else:
                    # All the same.
                    defaults = dict.fromkeys(TIMER_NUM_INF if use_inf else TIMER_NUM, default_prop.value)

                holders: dict[TimerNum, AsyncValue[str]] = {}
                for num in (TIMER_NUM_INF if use_inf else TIMER_NUM):
                    if prev_conf is EmptyMapping:
                        # No new conf, check the old conf.
                        cur_value = LEGACY_CONFIG.get_val(data.id, f'{wid_id}_{num}', defaults[num])
                    elif isinstance(prev_conf, str):
                        cur_value = prev_conf
                    else:
                        cur_value = prev_conf[num]
                    holders[num] = AsyncValue(cur_value)

                multi_widgets.append(MultiWidget(
                    group_id=data.id,
                    id=wid_id,
                    name=name,
                    tooltip=tooltip,
                    config=wid_conf,
                    kind=kind,
                    holders=holders,
                    use_inf=use_inf,
                ))
            else:
                # Singular Widget.
                if default_prop.has_children():
                    raise ValueError(
                        f'{data.id}:{wid_id}: Can only have multiple defaults for timer-ed widgets!'
                    )

                if kind is KIND_ITEM_VARIANT:
                    cur_value = ''  # Not used.
                elif prev_conf is EmptyMapping:
                    # No new conf, check the old conf.
                    cur_value = LEGACY_CONFIG.get_val(data.id, wid_id, default_prop.value)
                elif isinstance(prev_conf, str):
                    cur_value = prev_conf
                else:
                    LOGGER.warning(
                        'Widget {}:{} had timer defaults, but widget is singular!',
                        data.id, wid_id,
                    )
                    cur_value = default_prop.value

                widgets.append(SingleWidget(
                    group_id=data.id,
                    id=wid_id,
                    name=name,
                    tooltip=tooltip,
                    kind=kind,
                    config=wid_conf,
                    holder=AsyncValue(cur_value),
                    stylevar_id=stylevar_id,
                ))

        return cls(
            data.id,
            group_name,
            desc,
            widgets,
            multi_widgets,
        )

    @override
    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield translation tokens for this config group."""
        source = f'configgroup/{self.id}'
        yield self.name, f'{source}.name'
        yield from self.desc.iter_tokens(f'{source}.desc')
        for widget in itertools.chain(self.widgets, self.multi_widgets):
            yield widget.name, f'{source}/{widget.id}.name'
            yield widget.tooltip, f'{source}/{widget.id}.tooltip'

    @override
    def add_over(self, override: ConfigGroup) -> None:
        """Override a ConfigGroup to add additional widgets."""
        wid_single = {wid.id: wid for wid in self.widgets}
        wid_multi = {wid.id: wid for wid in self.multi_widgets}
        # Make sure they don't double-up.
        conficts = self.widget_ids() & override.widget_ids()
        if conficts:
            raise ValueError('Duplicate IDs in "{}" override - {}', self.id, conficts)

        if self.name is TransToken.BLANK:
            self.name = override.name
        self.desc += override.desc

        for single_wid in override.widgets:
            try:
                single_existing = wid_single[single_wid.id]
            except KeyError:
                self.widgets.append(single_wid)
                continue
            if (
                single_wid.kind is not single_existing.kind
                or single_wid.config != single_existing.config
                or single_wid.stylevar_id != single_existing.stylevar_id
            ):
                raise ValueError(
                    f'Duplicate widget {self.id}:{single_wid.id}:'
                    f'\n{single_wid}\n{single_existing}'
                )

        for multi_wid in override.multi_widgets:
            try:
                multi_existing = wid_multi[multi_wid.id]
            except KeyError:
                self.multi_widgets.append(multi_wid)
                continue
            if (
                multi_existing.kind is not multi_existing.kind
                or multi_existing.config != multi_existing.config
            ):
                raise ValueError(
                    f'Duplicate widget {self.id}:{multi_existing.id}:'
                    f'\n{multi_wid}\n{multi_existing}'
                )

    @classmethod
    @override
    async def migrate_config(cls, packset: packages.PackagesSet, conf: config.Config) -> config.Config:
        """Update configs to migrate stylevars."""
        await packset.ready(cls).wait()

        for group in packset.all_obj(cls):
            for wid in group.widgets:
                await trio.lowlevel.checkpoint()
                if not wid.stylevar_id:
                    continue
                wid_id = wid.conf_id()
                try:
                    conf.get(WidgetConfig, wid_id)
                    continue  # Already present.
                except KeyError:
                    pass
                conf, stylevar = conf.discard(StyleVarState, wid.stylevar_id)
                if stylevar is not None:
                    conf = conf.with_value(
                        WidgetConfig(bool_as_int(stylevar.value)),
                        wid_id,
                    )
                    LOGGER.info(
                        'Migrate stylevar {} -> widget {}',
                        wid.stylevar_id, wid_id,
                    )
        return conf

    def widget_ids(self) -> set[str]:
        """Return the set of widget IDs used."""
        widgets: list[Iterable[Widget]] = [self.widgets, self.multi_widgets]
        return {wid.id for wid_list in widgets for wid in wid_list}


def parse_color(color: str) -> tuple[int, int, int]:
    """Parse a string into a color."""
    if color.startswith('#'):
        try:
            r = int(color[1:3], base=16)
            g = int(color[3:5], base=16)
            b = int(color[5:], base=16)
        except ValueError:
            LOGGER.warning('Invalid RGB value: "{}"!', color)
            r = g = b = 128
    else:
        r, g, b = map(int, Vec.from_str(color, 128, 128, 128))
    return r, g, b


@register('itemvariant', 'variant')
@attrs.frozen
class ItemVariantConf:
    """Configuration for the special widget."""
    item_ref: packages.PakRef[packages.Item]

    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues) -> Self:
        """Parse from configs."""
        return cls(packages.PakRef(packages.Item, utils.obj_id(conf['ItemID'])))


@register('dropdown')
@attrs.define
class DropdownOptions:
    """Options defined for a widget."""
    options: list[tuple[str, TransToken]]

    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues) -> Self:
        """Parse configuration."""
        return cls([
            (kv.real_name, TransToken.parse(data.pak_id, kv.value))
            for kv in conf.find_children('Options')
        ])


@register('range', 'slider', wide=True)
@attrs.frozen
class SliderOptions:
    """Options for a slider widget."""
    min: float
    max: float
    step: float
    zero_off: bool

    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues) -> Self:
        """Parse from keyvalues options."""
        return cls(
            min=conf.float('min', 0),
            max=conf.float('max', 100),
            step=conf.float('step', 1),
            zero_off=conf.bool('zeroOff', False),
        )


@register('Timer', 'MinuteSeconds')
@attrs.frozen
class TimerOptions:
    """Options for minute-second timers."""
    min: int
    max: int

    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues) -> Self:
        """Parse from config options."""
        max_value = conf.int('max', 60)
        min_value = conf.int('min', 0)
        if min_value > max_value:
            raise ValueError('Bad min and max values!')
        return cls(min_value, max_value)


KIND_ITEM_VARIANT = WIDGET_KINDS['itemvariant']
KIND_CHECKMARK = register_no_conf('boolean', 'bool', 'checkbox')
KIND_COLOR = register_no_conf('color', 'colour', 'rgb')
KIND_STRING = register_no_conf('string', 'str', 'text')
