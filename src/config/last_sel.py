from __future__ import annotations
from typing_extensions import override

from srctools import Keyvalues
from srctools.dmx import Element
import attrs

import config


@config.PALETTE.register
@config.APP.register
@attrs.frozen
class LastSelected(config.Data, conf_name='LastSelected', uses_id=True):
    """Used for several general items, specifies the last selected one for restoration."""
    id: str | None = None

    @classmethod
    def parse_legacy(cls, conf: Keyvalues) -> dict[str, LastSelected]:
        """Parse legacy config data."""
        result = {}
        last_sel = conf.find_key('LastSelected', or_blank=True)
        # Old -> new save IDs
        for old, new in [
            ('Game', 'game'),
            ('Style', 'styles'),
            ('Skybox', 'skyboxes'),
            ('Voice', 'voicelines'),
            ('Elevator', 'elevators'),
            ('Music_Base', 'music_base'),
            ('Music_Tbeam', 'music_tbeam'),
            ('Music_Bounce', 'music_bounce'),
            ('Music_Speed', 'music_speed'),
        ]:
            try:
                value = last_sel[old]
            except LookupError:
                continue

            if value.casefold() == '<none>':
                result[new] = cls(None)
            else:
                result[new] = cls(value)
        return result

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> LastSelected:
        """Parse Keyvalues data."""
        assert version == 1, version
        if data.has_children():
            raise ValueError(f'LastSelected cannot be a block: {data!r}')
        if data.value.casefold() == '<none>':
            return cls(None)
        return cls(data.value)

    @override
    def export_kv1(self) -> Keyvalues:
        """Export to a property block."""
        return Keyvalues('', '<NONE>' if self.id is None else self.id)

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> LastSelected:
        """Parse DMX elements."""
        assert version == 1, version
        if 'selected_none' in data and data['selected_none'].val_bool:
            return cls(None)
        else:
            return cls(data['selected'].val_str)

    @override
    def export_dmx(self) -> Element:
        """Export to a DMX element."""
        elem = Element('LastSelected', 'DMElement')
        if self.id is None:
            elem['selected_none'] = True
        else:
            elem['selected'] = self.id
        return elem
