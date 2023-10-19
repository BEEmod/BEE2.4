from __future__ import annotations

from typing import Mapping
from typing_extensions import override

from srctools import EmptyMapping, Keyvalues, conv_bool, bool_as_int
from srctools.dmx import Element, ValueType as DMXValue
import attrs

from corridor import Direction, GameMode, Orient
import config


__all__ = [
    'Direction', 'GameMode', 'Orient',  # Re-export
    'Config', 'UIState',
]


@config.APP.register
@attrs.frozen(slots=False)
class Config(config.Data, conf_name='Corridor', uses_id=True, version=2):
    """The current configuration for a corridor."""
    enabled: Mapping[str, bool] = EmptyMapping

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
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> Config:
        """Parse from KeyValues1 configs."""
        enabled: dict[str, bool] = {}
        if version == 2:
            for child in data:
                enabled[child.name] = conv_bool(child.value)
        elif version == 1:
            for child in data.find_children('Corridors'):
                if child.name == 'selected' and not child.has_children():
                    enabled[child.value.casefold()] = True
                elif child.name == 'unselected' and not child.has_children():
                    enabled[child.value.casefold()] = False
        else:
            raise ValueError(f'Unknown version {version}!')

        return Config(enabled)

    @override
    def export_kv1(self) -> Keyvalues:
        """Serialise to a Keyvalues1 config."""
        return Keyvalues('Corridor', [
            Keyvalues(corr, bool_as_int(enabled))
            for corr, enabled in self.enabled.items()
        ])

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> Config:
        """Parse from DMX configs."""
        enabled: dict[str, bool] = {}
        if version == 2:
            for key, attr in data.items():
                if attr.type is DMXValue.BOOL:
                    enabled[attr.name.casefold()] = attr.val_bool
        elif version == 1:
            try:
                selected = data['selected']
            except KeyError:
                pass
            else:
                for inst in selected.iter_str():
                    enabled[inst.casefold()] = True
            try:
                unselected = data['unselected']
            except KeyError:
                pass
            else:
                for inst in unselected.iter_str():
                    enabled[inst.casefold()] = False
        else:
            raise ValueError(f'Unknown version {version}!')

        return Config(enabled)

    @override
    def export_dmx(self) -> Element:
        """Serialise to DMX configs."""
        elem = Element('Corridor', 'DMEConfig')
        for inst, enabled in self.enabled.items():
            elem[inst] = enabled

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
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> UIState:
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

    @override
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
    @override
    def parse_dmx(cls, data: Element, version: int) -> UIState:
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

    @override
    def export_dmx(self) -> Element:
        """Export Keyvalues 2 configuration."""
        element = Element('UIState', 'DMElement')
        element['mode'] = self.last_mode.value
        element['direction'] = self.last_direction.value
        element['orient'] = self.last_orient.value
        element['width'] = self.width
        element['height'] = self.height
        return element
