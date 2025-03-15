"""Exported configuration storing the current player model."""
from collections.abc import Mapping
from typing import Self, override

import attrs
from srctools import Keyvalues
from srctools.dmx import Element

import config
from quote_pack import LineCriteria, PLAYER_CRITERIA


@config.APP.register
@attrs.frozen
class AvailablePlayer(config.Data, conf_name='AvailablePlayer', version=1, uses_id=True):
    """The player models available in the last export, for the standalone compile pane."""
    name: str

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, /, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        return cls(data.value)

    @override
    def export_kv1(self) -> Keyvalues:
        """Export the stylevars in KV1 format."""
        return Keyvalues('AvailablePlayer', self.name)

    @classmethod
    @override
    def parse_dmx(cls, data: Element, /, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        try:
            name = data['disp_name'].val_string
        except KeyError:
            return cls('')
        else:
            return cls(name)

    @override
    def export_dmx(self, /) -> Element:
        elem = Element('AvailablePlayer', 'DMElement')
        elem['disp_name'] = self.name
        return elem


@config.COMPILER.register
@attrs.frozen
class ExportPlayer(config.Data, conf_name='PlayerModel', version=1, uses_id=True):
    """Exported player information for the compiler."""
    model: str = ''
    pgun_skin: int = 0

    voice_options: Mapping[LineCriteria, bool] = dict.fromkeys(PLAYER_CRITERIA, False)

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, /, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        model = data['model', '']
        pgun_skin = data.int('pgun_skin')
        options = {
            criteria: data.bool(f'voice_{criteria.name}')
            for criteria in PLAYER_CRITERIA
        }
        return cls(model, pgun_skin, options)

    @override
    def export_kv1(self, /) -> Keyvalues:
        kv = Keyvalues('', [
            Keyvalues('model', self.model),
            Keyvalues('pgun_skin', str(self.pgun_skin)),
        ])
        for criteria in PLAYER_CRITERIA:
            kv[f'voice_{criteria.name.lower()}'] = '1' if self.voice_options.get(criteria) else '0'
        return kv

    @classmethod
    @override
    def parse_dmx(cls, data: Element, /, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        try:
            model = data['model'].val_string
        except KeyError:
            model = ''
        try:
            pgun_skin = data['pgun_skin'].val_int
        except KeyError:
            pgun_skin = 0

        options = {}
        for criteria in PLAYER_CRITERIA:
            try:
                options[criteria] = data[f'voice_{criteria.name}'].val_bool
            except KeyError:
                options[criteria] = False

        return cls(model, pgun_skin, options)

    @override
    def export_dmx(self, /) -> Element:
        elem = Element('PlayerModel', 'DMElement')
        elem['model'] = self.model
        elem['pgun_skin'] = self.pgun_skin
        for criteria in PLAYER_CRITERIA:
            elem[f'voice_{criteria.name.lower()}'] = self.voice_options.get(criteria, False)
        return elem
