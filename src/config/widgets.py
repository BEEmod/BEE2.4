import itertools
from typing import Self, NewType, final, override

from collections.abc import Mapping

from srctools import EmptyMapping, Keyvalues, logger
from srctools.dmx import Element
import attrs

import config


LOGGER = logger.get_logger(__name__, 'conf.widgets')


# To prevent mix-ups, a NewType for 1-30 timer strings + 'INF'.
TimerNum = NewType('TimerNum', str)
TIMER_NUM: list[TimerNum] = [TimerNum(str(n)) for n in range(3, 31)]
TIMER_STR_INF: TimerNum = TimerNum('inf')
TIMER_NUMS_INF: list[TimerNum] = [TIMER_STR_INF, *TIMER_NUM]
VALID_NUMS = set(TIMER_NUMS_INF)


def parse_timer(value: str) -> TimerNum:
    """Validate this is a timer value."""
    if value in VALID_NUMS:
        return TimerNum(value)
    raise ValueError('Invalid timer value!')


@config.COMPILER.register
@config.PALETTE.register
@config.APP.register
@final
@attrs.frozen
class WidgetConfig(config.Data, conf_name='ItemVar', uses_id=True):
    """Saved values for package-customisable widgets in the Item/Style Properties Pane."""
    # A single non-timer value, or timer name -> value.
    values: str | Mapping[TimerNum, str] = EmptyMapping

    @classmethod
    @override
    def parse_legacy(cls, config: Keyvalues) -> dict[str, Self]:
        """Parse from the old legacy config."""
        data = {}
        for group in config.find_children('itemvar'):
            if not group.has_children():
                LOGGER.warning('Illegal leaf keyvalue "{}" in ItemVar conf', group.name)
            for widget in group:
                data[f'{group.real_name}:{widget.real_name}'] = WidgetConfig.parse_kv1(widget, 1)
        return data

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> Self:
        """Parse Keyvalues config values."""
        if version != 1:
            raise config.UnknownVersion(version, '1')
        if data.has_children():
            result: dict[TimerNum, str] = {}
            for prop in data:
                try:
                    result[parse_timer(prop.name)] = prop.value
                except ValueError:
                    LOGGER.warning('Invalid timer value "{}" in ItemVar config', prop.real_name)
            return WidgetConfig(result)
        else:
            return WidgetConfig(data.value)

    @override
    def export_kv1(self) -> Keyvalues:
        """Generate keyvalues for saving configuration."""
        if isinstance(self.values, str):
            return Keyvalues('', self.values)
        else:
            return Keyvalues(
                'ItemVar',
                list(itertools.starmap(Keyvalues, self.values.items())),
            )

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> Self:
        """Parse DMX format configuration."""
        if version != 1:
            raise config.UnknownVersion(version, '1')
        if 'value' in data:
            return WidgetConfig(data['value'].val_string)
        else:
            result: dict[TimerNum, str] = {}
            for attr in data.values():
                if attr.name.startswith('tim_'):
                    try:
                        result[parse_timer(attr.name.removeprefix('tim_'))] = attr.val_string
                    except ValueError:
                        LOGGER.warning('Invalid timer value "{}" in ItemVar config', attr.name)
            return WidgetConfig(result)

    @override
    def export_dmx(self) -> Element:
        """Generate DMX format configuration."""
        elem = Element('ItemVar', 'DMElement')
        if isinstance(self.values, str):
            elem['value'] = self.values
        else:
            for tim, value in self.values.items():
                elem[f'tim_{tim}'] = value
        return elem
