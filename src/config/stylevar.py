from __future__ import annotations

from typing import Dict

import attrs
from srctools import Property, bool_as_int, conv_bool
from srctools.dmx import Element

import config


@config.APP.register
@attrs.frozen(slots=False)
class State(config.Data, conf_name='StyleVar', uses_id=True):
    """Holds style var state stored in configs."""
    value: bool = False

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, State]:
        """Parse the old StyleVar config."""
        return {
            prop.real_name: cls(conv_bool(prop.value))
            for prop in conf.find_children('StyleVar')
        }

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> State:
        """Parse KV1-formatted stylevar states."""
        assert version == 1, version
        return cls(conv_bool(data.value))

    def export_kv1(self) -> Property:
        """Export the stylevars in KV1 format."""
        return Property('', bool_as_int(self.value))

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> State:
        """Parse DMX config files."""
        try:
            value = data['value'].val_bool
        except KeyError:
            return cls(False)
        else:
            return cls(value)

    def export_dmx(self) -> Element:
        """Export stylevars in DMX format."""
        elem = Element('StyleVar', 'DMElement')
        elem['value'] = self.value
        return elem
