from __future__ import annotations
from typing import override
from uuid import UUID

from srctools import Keyvalues
from srctools.dmx import Element
import attrs

import config
import utils


@config.PALETTE.register
@config.APP.register
@attrs.frozen
class LastSelected(config.Data, conf_name='LastSelected', uses_id=True):
    """Used for several general items, specifies the last selected one for restoration."""
    id: utils.SpecialID

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

            result[new] = cls(utils.special_id(value))
        return result

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> LastSelected:
        """Parse Keyvalues data."""
        if version != 1:
            raise config.UnknownVersion(version, '1')
        if data.has_children():
            raise ValueError(f'LastSelected cannot be a block: {data!r}')
        return cls(utils.special_id(data.value))

    @override
    def export_kv1(self) -> Keyvalues:
        """Export to a property block."""
        return Keyvalues('', self.id)

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> LastSelected:
        """Parse DMX elements."""
        if version != 1:
            raise config.UnknownVersion(version, '1')
        if 'selected_none' in data and data['selected_none'].val_bool:
            return cls(utils.ID_NONE)
        else:
            return cls(utils.special_id(data['selected'].val_str))

    @override
    def export_dmx(self) -> Element:
        """Export to a DMX element."""
        elem = Element('LastSelected', 'DMElement')
        elem['selected'] = self.id
        return elem


@config.APP.register
@attrs.frozen
class LastGame(config.Data, conf_name='LastGame'):
    """Stores the UUID of the last selected game."""
    uuid: UUID

    @classmethod
    def parse_kv1(cls, data: Keyvalues, /, version: int) -> LastGame:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        return cls(UUID(hex=data['uuid']))

    def export_kv1(self, /) -> Keyvalues:
        return Keyvalues('LastGame', [
            Keyvalues('uuid', self.uuid.hex),
        ])

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> LastGame:
        """Parse DMX elements."""
        if version != 1:
            raise config.UnknownVersion(version, '1')
        return cls(UUID(bytes=data['uuid'].val_bytes))

    @override
    def export_dmx(self) -> Element:
        """Export to a DMX element."""
        elem = Element('LastGame', 'DMElement')
        elem['uuid'] = self.uuid.bytes
        return elem
