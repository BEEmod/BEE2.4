"""Customizable configuration for specific items or groups of them."""
from typing import (
    Any, Awaitable, Callable, Dict, Generic, Iterable, Iterator, List, Optional, Protocol, Set,
    Tuple, Type, TypeVar,
)
from typing_extensions import Self, TypeAlias
import itertools

import attrs
import trio
from srctools import EmptyMapping, Keyvalues, Vec, logger

import BEE2_config
import config
import packages
from app import tkMarkdown

from config.widgets import (
    TIMER_NUM as TIMER_NUM, TIMER_NUM_INF as TIMER_NUM_INF,
    TimerNum as TimerNum, WidgetConfig,
)
from transtoken import TransToken, TransTokenSource


class ConfigProto(Protocol):
    """Protocol widget configuration classes must match."""
    @classmethod
    def parse(cls, conf: Keyvalues, /) -> Self: ...


ConfT = TypeVar('ConfT', bound=ConfigProto)  # Type of the config object for a widget.
OptConfT = TypeVar('OptConfT', bound=Optional[ConfigProto])
LOGGER = logger.get_logger(__name__)


@attrs.frozen
class WidgetType:
    """Information about a type of widget."""
    name: str
    is_wide: bool


@attrs.frozen
class WidgetTypeWithConf(WidgetType, Generic[ConfT]):
    """Information about a type of widget, that requires configuration."""
    conf_type: Type[ConfT]


# Maps widget type names to the type info.
WIDGET_KINDS: Dict[str, WidgetType] = {}
CLS_TO_KIND: Dict[Type[ConfigProto], WidgetTypeWithConf[Any]] = {}
UpdateFunc: TypeAlias = Callable[[str], Awaitable[None]]

CONFIG = BEE2_config.ConfigFile('item_cust_configs.cfg')


def register(*names: str, wide: bool=False) -> Callable[[Type[ConfT]], Type[ConfT]]:
    """Register a widget type that takes config.

    If wide is set, the widget is put into a labelframe, instead of having a label to the side.
    """
    if not names:
        raise TypeError('No name defined!')

    def deco(cls: Type[ConfT]) -> Type[ConfT]:
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


def register_no_conf(*names: str, wide: bool=False) -> WidgetType:
    """Register a widget type which does not need additional configuration.

    Many only need the default values.
    """
    kind = WidgetType(names[0], wide)
    for name in names:
        name = name.casefold()
        assert name not in WIDGET_KINDS, name
        WIDGET_KINDS[name] = kind
    return kind


async def nop_update(__value: str) -> None:
    """Placeholder callback which does nothing."""


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
    value: str
    ui_cback: UpdateFunc = nop_update

    async def apply_conf(self, data: WidgetConfig) -> None:
        """Apply the configuration to the UI."""
        if isinstance(data.values, str):
            if data.values != self.value:
                self.on_changed(data.values)
                # Don't bother scheduling a no-op task.
                if self.ui_cback is not nop_update:
                    await self.ui_cback(self.value)
        else:
            LOGGER.warning('{}:{}: Saved config is timer-based, but widget is singular.', self.group_id, self.id)

    def on_changed(self, value: str) -> None:
        """Recompute state and UI when changed."""
        self.value = value
        config.APP.store_conf(WidgetConfig(value), f'{self.group_id}:{self.id}')


@attrs.define
class MultiWidget(Widget):
    """Represents a group of multiple widgets for all the timer values."""
    use_inf: bool  # For timer, is infinite valid?
    values: Dict[TimerNum, str]
    ui_cbacks: Dict[TimerNum, UpdateFunc] = attrs.Factory(dict)

    async def apply_conf(self, data: WidgetConfig) -> None:
        """Apply the configuration to the UI."""
        old = self.values.copy()
        if isinstance(data.values, str):
            # Single in conf, apply to all.
            self.values = dict.fromkeys(self.values.keys(), data.values)
        else:
            for tim_val in self.values:
                try:
                    self.values[tim_val] = data.values[tim_val]
                except KeyError:
                    continue
        if self.values != old:
            async with trio.open_nursery() as nursery:
                for tim_val, cback in self.ui_cbacks.items():
                    nursery.start_soon(cback, self.values[tim_val])
            config.APP.store_conf(
                WidgetConfig(self.values.copy()),
                f'{self.group_id}:{self.id}',
            )

    def get_on_changed(self, num: TimerNum) -> Callable[[str], object]:
        """Returns a function to recompute state and UI when changed."""
        def on_changed(value: str) -> None:
            """Should be called when this timer has changed."""
            self.values[num] = value
            config.APP.store_conf(
                WidgetConfig(self.values.copy()),
                f'{self.group_id}:{self.id}',
            )
        return on_changed


class ConfigGroup(packages.PakObject, allow_mult=True, needs_foreground=True):
    """A group of configs for an item."""
    def __init__(
        self,
        conf_id: str,
        group_name: TransToken,
        desc: tkMarkdown.MarkdownData,
        widgets: List[SingleWidget],
        multi_widgets: List[MultiWidget],
    ) -> None:
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets
        self.multi_widgets = multi_widgets

    @classmethod
    async def parse(cls, data: packages.ParseData) -> 'ConfigGroup':
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
                default=WidgetConfig(),
            ).values

            # Special case - can't be timer, and no values.
            if kind is KIND_ITEM_VARIANT:
                if is_timer:
                    LOGGER.warning("Item Variants can't be timers! ({}.{})", data.id, wid_id)
                    is_timer = use_inf = False

            if isinstance(kind, WidgetTypeWithConf):
                wid_conf: object = kind.conf_type.parse(wid)
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

                values: dict[TimerNum, str] = {}
                for num in (TIMER_NUM_INF if use_inf else TIMER_NUM):
                    if prev_conf is EmptyMapping:
                        # No new conf, check the old conf.
                        cur_value = CONFIG.get_val(data.id, f'{wid_id}_{num}', defaults[num])
                    elif isinstance(prev_conf, str):
                        cur_value = prev_conf
                    else:
                        cur_value = prev_conf[num]
                    values[num] = cur_value

                multi_widgets.append(MultiWidget(
                    group_id=data.id,
                    id=wid_id,
                    name=name,
                    tooltip=tooltip,
                    config=wid_conf,
                    kind=kind,
                    values=values,
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
                    cur_value = CONFIG.get_val(data.id, wid_id, default_prop.value)
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
                    value=cur_value,
                ))
        # If we are new, write our defaults to config.
        CONFIG.save_check()

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
        yield self.name, source + '.name'
        for widget in itertools.chain(self.widgets, self.multi_widgets):
            yield widget.name, f'{source}/{widget.id}.name'
            yield widget.tooltip, f'{source}/{widget.id}.tooltip'

    def add_over(self, override: 'ConfigGroup') -> None:
        """Override a ConfigGroup to add additional widgets."""
        # Make sure they don't double-up.
        conficts = self.widget_ids() & override.widget_ids()
        if conficts:
            raise ValueError('Duplicate IDs in "{}" override - {}', self.id, conficts)

        if self.name is TransToken.BLANK:
            self.name = override.name

        self.widgets.extend(override.widgets)
        self.multi_widgets.extend(override.multi_widgets)
        self.desc = tkMarkdown.join(self.desc, override.desc)

    def widget_ids(self) -> Set[str]:
        """Return the set of widget IDs used."""
        widgets: List[Iterable[Widget]] = [self.widgets, self.multi_widgets]
        return {wid.id for wid_list in widgets for wid in wid_list}

    @staticmethod
    def export(exp_data: packages.ExportData) -> None:
        """Write all our values to the config."""
        for conf in exp_data.packset.all_obj(ConfigGroup):
            config_section = CONFIG[conf.id]
            for s_wid in conf.widgets:
                if s_wid.has_values:
                    config_section[s_wid.id] = s_wid.value
            for m_wid in conf.multi_widgets:
                for num, value in m_wid.values.items():
                    config_section[f'{m_wid.id}_{num}'] = value
            if not config_section:
                del CONFIG[conf.id]
        CONFIG.save_check()


def parse_color(color: str) -> Tuple[int, int, int]:
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
    def parse(cls, conf: Keyvalues) -> Self:
        """Parse from configs."""
        return cls(conf['ItemID'])


@register('dropdown')
@attrs.define
class DropdownOptions:
    """Options defined for a widget."""
    options: List[str]
    display: List[str]
    key_to_index: Dict[str, int]

    @classmethod
    def parse(cls, conf: Keyvalues) -> Self:
        """Parse configuration."""
        result = cls([], [], {})
        for ind, prop in enumerate(conf.find_children('Options')):
            result.options.append(prop.real_name)
            result.display.append(prop.value)
            result.key_to_index[prop.name] = ind
        return result


@register('range', 'slider', wide=True)
@attrs.frozen
class SliderOptions:
    """Options for a slider widget."""
    min: float
    max: float
    step: float

    @classmethod
    def parse(cls, conf: Keyvalues) -> Self:
        """Parse from keyvalues options."""
        return cls(
            min=conf.float('min', 0),
            max=conf.float('max', 100),
            step=conf.float('step', 1),
        )


@register('Timer', 'MinuteSeconds')
@attrs.frozen
class TimerOptions:
    """Options for minute-second timers."""
    min: int
    max: int

    @classmethod
    def parse(cls, conf: Keyvalues) -> Self:
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
