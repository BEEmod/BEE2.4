"""Customizable configuration for specific items or groups of them."""
from __future__ import annotations

from typing import Any, Protocol, Self
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, aclosing
import itertools

from srctools import EmptyMapping, Keyvalues, Vec, logger

from trio_util import AsyncValue, wait_any
import attrs
import trio

from app.mdown import MarkdownData
from config.widgets import (
    TIMER_NUM as TIMER_NUM, TIMER_NUM_INF as TIMER_NUM_INF,
    TimerNum as TimerNum, WidgetConfig,
)
from transtoken import TransToken, TransTokenSource
import config
import BEE2_config
import packages


class ConfigProto(Protocol):
    """Protocol widget configuration classes must match."""
    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues, /) -> Self:
        """Parse keyvalues into a widget config."""


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


@attrs.define
class SingleWidget(Widget):
    """Represents a single widget with no timer value."""
    holder: AsyncValue[str]

    async def load_conf_task(
        self, cm: AbstractContextManager[trio.MemoryReceiveChannel[WidgetConfig]],
    ) -> None:
        """Apply the configuration to the UI."""
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
        data_id = f'{self.group_id}:{self.id}'
        async with aclosing(self.holder.eventual_values()) as agen:
            async for value in agen:
                config.APP.store_conf(WidgetConfig(value), data_id)


@attrs.define
class MultiWidget(Widget):
    """Represents a group of multiple widgets for all the timer values."""
    use_inf: bool  # For timer, is infinite valid?
    holders: dict[TimerNum, AsyncValue[str]]

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
        data_id = f'{self.group_id}:{self.id}'
        while True:
            # Wait for any to change, then store. We don't do them individually, since
            # we don't want a store spam if they get changed all at once.
            await wait_any(*[
                holder.wait_transition
                for holder in self.holders.values()
            ])
            config.APP.store_conf(WidgetConfig({
                num: holder.value
                for num, holder in self.holders.items()
            }), data_id)


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
    async def parse(cls, data: packages.ParseData) -> ConfigGroup:
        """Parse the config group from info.txt."""
        props = data.info

        if data.is_override:
            # Override doesn't need to have a name.
            group_name = TransToken.BLANK
        else:
            group_name = TransToken.parse(data.pak_id, props['Name'])

        desc = packages.desc_parse(props, data.id, data.pak_id)

        widgets: list[SingleWidget] = []
        multi_widgets: list[MultiWidget] = []

        for wid in props.find_all('Widget'):
            await trio.sleep(0)
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
            try:
                name = TransToken.parse(data.pak_id, wid['Label'])
            except LookupError:
                name = TransToken.untranslated(wid_id)
            tooltip = TransToken.parse(data.pak_id, wid['Tooltip', ''])
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
                    LOGGER.warning('Widget {}:{} had timer defaults, but widget is singular!', data.id, wid_id)
                    cur_value = default_prop.value

                widgets.append(SingleWidget(
                    group_id=data.id,
                    id=wid_id,
                    name=name,
                    tooltip=tooltip,
                    kind=kind,
                    config=wid_conf,
                    holder=AsyncValue(cur_value),
                ))

        return cls(
            data.id,
            group_name,
            desc,
            widgets,
            multi_widgets,
        )

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield translation tokens for this config group."""
        source = f'configgroup/{self.id}'
        yield self.name, f'{source}.name'
        yield from self.desc.iter_tokens(f'{source}.desc')
        for widget in itertools.chain(self.widgets, self.multi_widgets):
            yield widget.name, f'{source}/{widget.id}.name'
            yield widget.tooltip, f'{source}/{widget.id}.tooltip'

    def add_over(self, override: ConfigGroup) -> None:
        """Override a ConfigGroup to add additional widgets."""
        # Make sure they don't double-up.
        conficts = self.widget_ids() & override.widget_ids()
        if conficts:
            raise ValueError('Duplicate IDs in "{}" override - {}', self.id, conficts)

        if self.name is TransToken.BLANK:
            self.name = override.name

        self.widgets.extend(override.widgets)
        self.multi_widgets.extend(override.multi_widgets)
        self.desc += override.desc

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
    item_id: str

    @classmethod
    def parse(cls, data: packages.ParseData, conf: Keyvalues) -> Self:
        """Parse from configs."""
        return cls(conf['ItemID'])


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
KIND_STRING = register_no_conf('string', 'str')
