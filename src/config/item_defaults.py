"""Store overridden defaults for items, and also the selected version."""
from typing import Any, Dict, Final
from typing_extensions import override

from srctools import Keyvalues, logger
from srctools.dmx import Element
import attrs

from BEE2_config import ConfigFile
from editoritems_props import PROP_TYPES, ItemPropKind
import config


LOGGER = logger.get_logger(__name__)
DEFAULT_VERSION: Final = 'VER_DEFAULT'
LEGACY = ConfigFile('item_configs.cfg')


@config.PALETTE.register
@config.APP.register
@attrs.frozen
class ItemDefault(config.Data, conf_name='ItemDefault', uses_id=True):
    """Overrides the defaults for item properties."""
    version: str = DEFAULT_VERSION
    defaults: Dict[ItemPropKind[Any], str] = attrs.Factory(dict)

    @classmethod
    @override
    def parse_legacy(cls, conf: Keyvalues) -> Dict[str, 'ItemDefault']:
        """Parse the data in the legacy item_configs.cfg file."""
        result: Dict[str, ItemDefault] = {}
        for item_id, section in LEGACY.items():
            if item_id == LEGACY.default_section:
                continue  # Section for keys before the [] markers? Not useful.
            props: Dict[ItemPropKind[Any], str] = {}
            for prop_name, value in section.items():
                if not prop_name.startswith('prop_'):
                    continue
                prop_name = prop_name[5:]
                try:
                    prop_type = PROP_TYPES[prop_name.casefold()]
                except KeyError:
                    LOGGER.warning('Unknown property "{}" for item "{}"!', prop_name, item_id)
                    prop_type = ItemPropKind.unknown(prop_name)
                props[prop_type] = value
            result[item_id] = cls(section.get('sel_version', DEFAULT_VERSION), props)
        return result

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> 'ItemDefault':
        """Parse keyvalues1 data."""
        if version != 1:
            raise AssertionError(version)
        props: Dict[ItemPropKind[Any], str] = {}
        for kv in data.find_children('properties'):
            try:
                prop_type = PROP_TYPES[kv.name.casefold()]
            except KeyError:
                LOGGER.warning('Unknown property "{}"!', kv.real_name)
                prop_type = ItemPropKind.unknown(kv.real_name)
            props[prop_type] = kv.value
        return cls(data['version', DEFAULT_VERSION], props)

    @override
    def export_kv1(self) -> Keyvalues:
        """Export as keyvalues1 data."""
        return Keyvalues('', [
            Keyvalues('Version', self.version),
            Keyvalues('Properties', [
                Keyvalues(prop.id, value)
                for prop, value in self.defaults.items()
            ])
        ])

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> 'ItemDefault':
        """Parse DMX configuration."""
        if version != 1:
            raise AssertionError(version)
        try:
            item_version = data['version'].val_string
        except KeyError:
            item_version = DEFAULT_VERSION
        props: Dict[ItemPropKind[Any], str] = {}
        for attr in data['properties'].val_elem.values():
            if attr.name == 'name':  # The 'properties' name itself.
                continue
            try:
                prop_type = PROP_TYPES[attr.name.casefold()]
            except KeyError:
                LOGGER.warning('Unknown property "{}"!', attr.name)
                prop_type = ItemPropKind.unknown(attr.name)
            props[prop_type] = attr.val_string

        return cls(item_version, props)

    @override
    def export_dmx(self) -> Element:
        """Export as DMX data."""
        elem = Element('ItemDefault', 'DMElement')
        elem['version'] = self.version
        props = elem['properties'] = Element('Properties', 'DMElement')
        for prop_type, value in self.defaults.items():
            props[prop_type.id] = value
        return elem
