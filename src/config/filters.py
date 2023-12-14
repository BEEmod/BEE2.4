"""Configuration for the filter section, to restore after reopening the app."""
import attrs
from srctools.dmx import Element
from typing_extensions import Self

from srctools import Keyvalues

import config


@config.APP.register
@attrs.frozen(kw_only=True)
class FilterConf(config.Data, conf_name='ItemFilter', palette_stores=False, uses_id=False, version=1):
    """Filter configuration."""
    compress: bool = False

    @classmethod
    def parse_kv1(cls, data: Keyvalues, version: int) -> Self:
        if version != 1:
            raise AssertionError(version)
        return cls(
            compress=data.bool('compress'),
        )

    def export_kv1(self) -> Keyvalues:
        return Keyvalues('', [
            Keyvalues('compress', '1' if self.compress else '0')
        ])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> Self:
        if version != 1:
            raise AssertionError(version)
        try:
            compress = data['compress'].val_bool
        except KeyError:
            compress = False

        return cls(
            compress=compress,
        )

    def export_dmx(self) -> Element:
        elem = Element('ItemFilter', 'DMConfig')
        elem['compress'] = self.compress
        return elem
