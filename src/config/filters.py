"""Configuration for the filter section, to restore after reopening the app."""
from typing import Self, override

from srctools.dmx import Element
from srctools import Keyvalues
import attrs

import config


@config.APP.register
@attrs.frozen(kw_only=True)
class FilterConf(config.Data, conf_name='ItemFilter', uses_id=False, version=1):
    """Filter configuration."""
    compress: bool = False

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        return cls(
            compress=data.bool('compress'),
        )

    @override
    def export_kv1(self) -> Keyvalues:
        return Keyvalues('', [
            Keyvalues('compress', '1' if self.compress else '0')
        ])

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        try:
            compress = data['compress'].val_bool
        except KeyError:
            compress = False

        return cls(
            compress=compress,
        )

    @override
    def export_dmx(self) -> Element:
        elem = Element('ItemFilter', 'DMConfig')
        elem['compress'] = self.compress
        return elem
