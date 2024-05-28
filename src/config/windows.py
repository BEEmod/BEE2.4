from __future__ import annotations
from typing_extensions import override
from collections.abc import Mapping

from srctools import Keyvalues, bool_as_int, conv_bool, logger
from srctools.dmx import Attribute, Element, ValueType, Vec2
import attrs

from BEE2_config import GEN_OPTS as LEGACY_CONF
import config


LOGGER = logger.get_logger(__name__, 'conf.win')


@config.APP.register
@attrs.frozen
class WindowState(config.Data, conf_name='PaneState', uses_id=True):
    """Holds the position and size of windows."""
    x: int
    y: int
    width: int = -1
    height: int = -1
    visible: bool = True

    @classmethod
    @override
    def parse_legacy(cls, conf: Keyvalues) -> dict[str, WindowState]:
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
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> WindowState:
        """Parse keyvalues1 data."""
        assert version == 1, version
        return WindowState(
            data.int('x', -1),
            data.int('y', -1),
            data.int('width', -1),
            data.int('height', -1),
            data.bool('visible', True),
        )

    @override
    def export_kv1(self) -> Keyvalues:
        """Create keyvalues1 data."""
        kv = Keyvalues('WindowState', [
            Keyvalues('visible', '1' if self.visible else '0'),
            Keyvalues('x', str(self.x)),
            Keyvalues('y', str(self.y)),
        ])
        if self.width >= 0:
            kv['width'] = str(self.width)
        if self.height >= 0:
            kv['height'] = str(self.height)
        return kv

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> WindowState:
        """Parse DMX configuation."""
        assert version == 1, version
        pos = data['pos'].val_vec2 if 'pos' in data else Vec2(-1, -1)
        return WindowState(
            x=int(pos.x),
            y=int(pos.y),
            width=data['width'].val_int if 'width' in data else -1,
            height=data['height'].val_int if 'height' in data else -1,
            visible=data['visible'].val_bool if 'visible' in data else True,
        )

    @override
    def export_dmx(self) -> Element:
        """Create DMX configuation."""
        elem = Element('', '')
        elem['visible'] = self.visible
        elem['pos'] = Attribute.vec2('pos', (self.x, self.y))
        if self.width >= 0:
            elem['width'] = self.width
        if self.height >= 0:
            elem['height'] = self.height
        return elem


@config.APP.register
@attrs.frozen(slots=False)
class SelectorState(config.Data, conf_name='SelectorWindow', uses_id=True):
    """The state for selector windows for restoration next launch."""
    open_groups: Mapping[str, bool] = attrs.Factory(dict)
    width: int = 0
    height: int = 0

    @classmethod
    @override
    def parse_legacy(cls, conf: Keyvalues) -> dict[str, SelectorState]:
        """Convert the old legacy configuration."""
        result: dict[str, SelectorState] = {}
        for prop in conf.find_children('Selectorwindow'):
            result[prop.name] = cls.parse_kv1(prop, 1)
        return result

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> SelectorState:
        """Parse from keyvalues."""
        assert version == 1
        open_groups = {
            prop.name: conv_bool(prop.value)
            for prop in data.find_children('Groups')
        }
        return cls(
            open_groups,
            data.int('width', -1), data.int('height', -1),
        )

    @override
    def export_kv1(self) -> Keyvalues:
        """Generate keyvalues."""
        kv = Keyvalues('SelectorWindow', [])
        with kv.build() as builder:
            builder.width(str(self.width))
            builder.height(str(self.height))
            with builder.Groups:
                for name, is_open in self.open_groups.items():
                    builder[name](bool_as_int(is_open))
        return kv

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> SelectorState:
        """Parse DMX elements."""
        assert version == 1
        open_groups: dict[str, bool] = {}
        for name in data['closed'].iter_str():
            open_groups[name.casefold()] = False
        for name in data['opened'].iter_str():
            open_groups[name.casefold()] = True

        return cls(open_groups, data['width'].val_int, data['height'].val_int)

    @override
    def export_dmx(self) -> Element:
        """Serialise the state as a DMX element."""
        elem = Element('WindowState', 'DMElement')
        elem['width'] = self.width
        elem['height'] = self.height
        elem['opened'] = opened = Attribute.array('opened', ValueType.STRING)
        elem['closed'] = closed = Attribute.array('closed', ValueType.STRING)
        for name, val in self.open_groups.items():
            (opened if val else closed).append(name)
        return elem
