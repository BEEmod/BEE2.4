from __future__ import annotations

from typing import Self, override
from collections.abc import Mapping

from srctools import EmptyMapping, Keyvalues, conv_bool, bool_as_int, logger
from srctools.dmx import Element, ValueType as DMXValue
import attrs

from corridor import Direction, GameMode, Option, Orient
import config
import utils


LOGGER = logger.get_logger(__name__)
__all__ = [
    'Direction', 'GameMode', 'Orient',  # Re-export
    'Config', 'Options', 'UIState',
]


@config.PALETTE.register
@config.APP.register
@attrs.frozen
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
            raise config.UnknownVersion(version, '1 or 2')

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
            raise config.UnknownVersion(version, '1 or 2')

        return Config(enabled)

    @override
    def export_dmx(self) -> Element:
        """Serialise to DMX configs."""
        elem = Element('Corridor', 'DMEConfig')
        for inst, enabled in self.enabled.items():
            elem[inst] = enabled

        return elem


@config.COMPILER.register
@config.PALETTE.register
@config.APP.register
@attrs.frozen
class Options(config.Data, conf_name='CorridorOptions', uses_id=True, version=1):
    """Configuration defined for a specific corridor group."""
    options: Mapping[utils.ObjectID, utils.SpecialID] = EmptyMapping

    @staticmethod
    def get_id(
        style: str,
        mode: GameMode,
        direction: Direction,
    ) -> str:
        """Given the style and kind of corridor, return the ID for config lookup.

        Orientation is not included.
        """
        return f'{style.casefold()}:{mode.value}_{direction.value}'

    @classmethod
    @override
    def parse_kv1(cls, data: Keyvalues, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        options = {}
        for child in data:
            opt_id = utils.obj_id(child.real_name, 'corridor option ID')
            value = utils.special_id(child.value, 'corridor option value')
            if utils.not_special_id(value) or value == utils.ID_RANDOM:
                options[opt_id] = value
            else:
                raise ValueError(f'Invalid option value "{child.value}" for option "{opt_id}"!')
        return cls(options)

    @override
    def export_kv1(self) -> Keyvalues:
        return Keyvalues('', [
            Keyvalues(opt_id, value)
            for opt_id, value in self.options.items()
        ])

    @classmethod
    @override
    def parse_dmx(cls, data: Element, version: int) -> Self:
        if version != 1:
            raise config.UnknownVersion(version, '1')
        options = {}
        for child in data.values():
            if child.name == 'name':
                continue
            opt_id = utils.obj_id(child.name, 'corridor option ID')
            value = utils.special_id(child.val_string, 'corridor option value')
            if utils.not_special_id(value) or value == utils.ID_RANDOM:
                options[opt_id] = value
            else:
                raise ValueError(f'Invalid option value "{value}" for option "{opt_id}"!')

        return cls(options)

    @override
    def export_dmx(self) -> Element:
        elem = Element('CorridorOptions', 'DMConfig')
        for opt_id, value in self.options.items():
            elem[opt_id] = value
        return elem

    def value_for(self, option: Option) -> utils.SpecialID:
        """Return the currently selected value for the specified option."""
        try:
            opt_id = self.options[option.id]
        except KeyError:
            return option.default
        if opt_id == utils.ID_RANDOM:
            return opt_id
        for value in option.values:
            if opt_id == value.id:
                return opt_id
        LOGGER.warning(
            'Configured ID "{}" is not valid for option "{}"',
            opt_id, option.id,
        )
        return option.default


@config.APP.register
@attrs.frozen(slots=False)
class UIState(config.Data, conf_name='CorridorUIState'):
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
        if version != 1:
            raise config.UnknownVersion(version, '1')
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
        if version != 1:
            raise config.UnknownVersion(version, '1')
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
