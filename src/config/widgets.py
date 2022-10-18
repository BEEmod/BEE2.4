from typing import Dict, Mapping, Union

import attrs
from srctools import EmptyMapping, Property, logger
from srctools.dmx import Element

import config


LOGGER = logger.get_logger(__name__, 'conf.widgets')


@config.APP.register
@attrs.frozen(slots=False)
class WidgetConfig(config.Data, conf_name='ItemVar', uses_id=True):
    """Saved values for package-customisable widgets in the Item/Style Properties Pane."""
    # A single non-timer value with "" as key, or timer name -> value.
    values: Union[str, Mapping[str, str]] = EmptyMapping

    @classmethod
    def parse_legacy(cls, props: Property) -> Dict[str, 'WidgetConfig']:
        """Parse from the old legacy config."""
        data = {}
        for group in props.find_children('ItemVar'):
            if not group.has_children():
                LOGGER.warning('Illegal leaf keyvalue "{}" in ItemVar conf', group.name)
            for widget in group:
                data[f'{group.real_name}:{widget.real_name}'] = WidgetConfig.parse_kv1(widget, 1)
        return data

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'WidgetConfig':
        """Parse Keyvalues config values."""
        assert version == 1
        if data.has_children():
            return WidgetConfig({
                prop.name: prop.value
                for prop in data
            })
        else:
            return WidgetConfig(data.value)

    def export_kv1(self) -> Property:
        """Generate keyvalues for saving configuration."""
        if isinstance(self.values, str):
            return Property('', self.values)
        else:
            return Property('', [
                Property(tim, value)
                for tim, value in self.values.items()
            ])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'WidgetConfig':
        """Parse DMX format configuration."""
        assert version == 1
        if 'value' in data:
            return WidgetConfig(data['value'].val_string)
        else:
            return WidgetConfig({
                attr.name[4:]: attr.val_string
                for attr in data.values()
                if attr.name.startswith('tim_')
            })

    def export_dmx(self) -> Element:
        """Generate DMX format configuration."""
        elem = Element('ItemVar', 'DMElement')
        if isinstance(self.values, str):
            elem['value'] = self.values
        else:
            for tim, value in self.values.items():
                elem[f'tim_{tim}'] = value
        return elem
