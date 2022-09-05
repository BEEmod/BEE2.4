from typing import Dict

import attrs
from srctools import Property
from srctools.dmx import Element

from BEE2_config import GEN_OPTS as LEGACY_CONF
import config


@config.APP.register
@attrs.frozen(slots=False)
class WindowState(config.Data, conf_name='PaneState', uses_id=True, palette_stores=False):
    """Holds the position and size of windows."""
    x: int
    y: int
    width: int = -1
    height: int = -1
    visible: bool = True

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, 'WindowState']:
        """Convert old GEN_OPTS configuration."""
        opt_block = LEGACY_CONF['win_state']
        names: set[str] = set()
        for name in opt_block.keys():
            try:
                name, _ = name.rsplit('_', 1)
            except ValueError:
                continue
            names.add(name)
        return {
            name: WindowState(
                x=LEGACY_CONF.getint('win_state', name + '_x', -1),
                y=LEGACY_CONF.getint('win_state', name + '_y', -1),
                width=LEGACY_CONF.getint('win_state', name + '_width', -1),
                height=LEGACY_CONF.getint('win_state', name + '_height', -1),
                visible=LEGACY_CONF.getboolean('win_state', name + '_visible', True)
            )
            for name in names
        }

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'WindowState':
        """Parse keyvalues1 data."""
        return WindowState(
            data.int('x', -1),
            data.int('y', -1),
            data.int('width', -1),
            data.int('height', -1),
            data.bool('visible', True),
        )

    def export_kv1(self) -> Property:
        """Create keyvalues1 data."""
        prop = Property('', [
            Property('visible', '1' if self.visible else '0'),
            Property('x', str(self.x)),
            Property('y', str(self.y)),
        ])
        if self.width >= 0:
            prop['width'] = str(self.width)
        if self.height >= 0:
            prop['height'] = str(self.height)
        return prop

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'WindowState':
        """Parse DMX configuation."""
        pos = data['pos'].val_vec2
        width = data['width'].val_int if 'width' in data else -1
        height = data['height'].val_int if 'height' in data else -1
        return WindowState(
            x=int(pos.x),
            y=int(pos.y),
            width=width,
            height=height,
            visible=data['visible'].val_bool,
        )

    def export_dmx(self) -> Element:
        """Create DMX configuation."""
        elem = Element('', '')
        elem['visible'] = self.visible
        elem['pos'] = (self.x, self.y)
        if self.width >= 0:
            elem['width'] = self.width
        if self.height >= 0:
            elem['height'] = self.height
        return elem
