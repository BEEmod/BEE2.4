from __future__ import annotations

from typing import List

import attrs
from srctools import Keyvalues
from srctools.dmx import Attribute as DMAttr, Element, ValueType as DMXValue

import config
from corridor import Direction, GameMode, Orient


@config.APP.register
@attrs.frozen(slots=False)
class Config(config.Data, conf_name='Corridor', uses_id=True, version=1):
    """The current configuration for a corridor."""
    selected: List[str] = attrs.field(factory=list, kw_only=True)
    unselected: List[str] = attrs.field(factory=list, kw_only=True)

    @staticmethod
    def get_id(
        style: str,
        mode: GameMode,
        direction: Direction,
        orient: Orient,
    ) -> str:
        """Given the style and kind of corridor, return the ID for config lookup."""
        return f'{style.casefold()}:{mode.value}_{direction.value}_{orient.value}'

    @classmethod
    def parse_kv1(cls, data: Keyvalues, version: int) -> 'Config':
        """Parse from KeyValues1 configs."""
        assert version == 1, version
        selected = []
        unselected = []
        for child in data.find_children('Corridors'):
            if child.name == 'selected' and not child.has_children():
                selected.append(child.value)
            elif child.name == 'unselected' and not child.has_children():
                unselected.append(child.value)

        return Config(selected=selected, unselected=unselected)

    def export_kv1(self) -> Keyvalues:
        """Serialise to a Keyvalues1 config."""
        kv = Keyvalues('Corridors', [])
        for corr in self.selected:
            kv.append(Keyvalues('selected', corr))
        for corr in self.unselected:
            kv.append(Keyvalues('unselected', corr))

        return Keyvalues('Corridor', [kv])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'Config':
        """Parse from DMX configs."""
        assert version == 1, version
        try:
            selected = list(data['selected'].iter_str())
        except KeyError:
            selected = []
        try:
            unselected = list(data['unselected'].iter_str())
        except KeyError:
            unselected = []

        return Config(selected=selected, unselected=unselected)

    def export_dmx(self) -> Element:
        """Serialise to DMX configs."""
        elem = Element('Corridor', 'DMEConfig')
        elem['selected'] = selected = DMAttr.array('selected', DMXValue.STR)
        selected.extend(self.selected)
        elem['unselected'] = unselected = DMAttr.array('unselected', DMXValue.STR)
        unselected.extend(self.unselected)

        return elem


@config.APP.register
@attrs.frozen(slots=False)
class UIState(config.Data, conf_name='CorridorUIState', palette_stores=False):
    """The current window state for saving and restoring."""
    last_mode: GameMode = GameMode.SP
    last_direction: Direction = Direction.ENTRY
    last_orient: Orient = Orient.HORIZONTAL
    width: int = -1
    height: int = -1

    @classmethod
    def parse_kv1(cls, data: Keyvalues, version: int) -> 'UIState':
        """Parse Keyvalues 1 configuration."""
        assert version == 1, version
        try:
            last_mode = GameMode(data['mode'])
        except (LookupError, ValueError):
            last_mode = GameMode.SP

        try:
            last_direction = Direction(data['direction'])
        except (LookupError, ValueError):
            last_direction = Direction.ENTRY

        try:
            last_orient = Orient(data['orient'])
        except (LookupError, ValueError):
            last_orient = Orient.HORIZONTAL

        return UIState(
            last_mode, last_direction, last_orient,
            data.int('width', -1),
            data.int('height', -1),
        )

    def export_kv1(self) -> Keyvalues:
        """Export Keyvalues 1 configuration."""
        return Keyvalues('', [
            Keyvalues('mode', self.last_mode.value),
            Keyvalues('direction', self.last_direction.value),
            Keyvalues('orient', self.last_orient.value),
            Keyvalues('width', str(self.width)),
            Keyvalues('height', str(self.height)),
        ])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'UIState':
        """Parse Keyvalues 2 configuration."""
        assert version == 1, version
        try:
            last_mode = GameMode(data['mode'].val_string)
        except (LookupError, ValueError):
            last_mode = GameMode.SP

        try:
            last_direction = Direction(data['direction'].val_string)
        except (LookupError, ValueError):
            last_direction = Direction.ENTRY

        try:
            last_orient = Orient(data['orient'].val_string)
        except (LookupError, ValueError):
            last_orient = Orient.HORIZONTAL

        try:
            width = data['width'].val_int
        except KeyError:
            width = -1
        try:
            height = data['height'].val_int
        except KeyError:
            height = -1

        return UIState(
            last_mode, last_direction, last_orient,
            width, height,
        )

    def export_dmx(self) -> Element:
        """Export Keyvalues 2 configuration."""
        element = Element('UIState', 'DMElement')
        element['mode'] = self.last_mode.value
        element['direction'] = self.last_direction.value
        element['orient'] = self.last_orient.value
        element['width'] = self.width
        element['height'] = self.height
        return element
