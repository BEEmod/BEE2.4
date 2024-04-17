from typing import Dict, List, Mapping, NewType, Union, cast
from typing_extensions import override

from srctools import EmptyMapping, Keyvalues, logger
from srctools.dmx import Element
import attrs

import config


LOGGER = logger.get_logger(__name__, 'conf.widgets')


# To prevent mixups, a newtype for 1-30 timer strings + 'INF'.
TimerNum = NewType('TimerNum', str)
TIMER_NUM: List[TimerNum] = cast(List[TimerNum], list(map(str, range(3, 31))))
TIMER_STR_INF: TimerNum = cast(TimerNum, 'inf')
TIMER_NUM_INF: List[TimerNum] = [TIMER_STR_INF, *TIMER_NUM]
VALID_NUMS = set(TIMER_NUM)


def parse_timer(value: str) -> TimerNum:
    """Validate this is a timer value."""
    if value in VALID_NUMS:
        return cast(TimerNum, value)
    raise ValueError('Invalid timer value!')


@config.PALETTE.register
@config.APP.register
@attrs.frozen
class WidgetConfig(config.Data, conf_name='ItemVar', uses_id=True):
    """Saved values for package-customisable widgets in the Item/Style Properties Pane."""
    # A single non-timer value, or timer name -> value.
    values: Union[str, Mapping[TimerNum, str]] = EmptyMapping

    @classmethod
    @override
    def parse_legacy(cls, config: Keyvalues) -> Dict[str, 'WidgetConfig']:
        """Parse from the old legacy config."""
        data = {}
        for group in config:
            if not group.has_children():
                LOGGER.warning('Illegal leaf keyvalue "{}" in ItemVar conf', group.name)
            for widget in group:
                data[f'{group.real_name}:{widget.real_name}'] = WidgetConfig.parse_kv1(widget, 1)
        return data

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> 'WidgetConfig':
        """Parse Keyvalues config values."""
        assert version == 1
        if data.has_children():
            result: Dict[TimerNum, str] = {}
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
            return Keyvalues('ItemVar', [
                Keyvalues(tim, value)
                for tim, value in self.values.items()
            ])

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> 'WidgetConfig':
        """Parse DMX format configuration."""
        assert version == 1
        if 'value' in data:
            return WidgetConfig(data['value'].val_string)
        else:
            result: Dict[TimerNum, str] = {}
            for attr in data.values():
                if attr.name.startswith('tim_'):
                    try:
                        result[parse_timer(attr.name[4:])] = attr.val_string
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
