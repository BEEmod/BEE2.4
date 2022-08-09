"""Deals with storing, saving and loading configuration.

Other modules define an immutable state class, then register it with this.
They can then fetch the current state and store new state.
"""
from enum import Enum
from pathlib import Path
from typing import (
    Any, ClassVar, Optional, Set, TypeVar, Callable, Generic, NewType, Union, cast,
    Type, Dict, Awaitable, Iterator, Tuple,
)
import os

import attrs
import trio
from atomicwrites import atomic_write
from srctools import KeyValError, Property, logger
from srctools.dmx import Element

import utils
from BEE2_config import GEN_OPTS as LEGACY_CONF


LOGGER = logger.get_logger(__name__)
if not os.environ.get('BEE_LOG_CONFIG'):  # Debug messages are spammy.
    LOGGER.setLevel('INFO')


DataT = TypeVar('DataT', bound='Data')


class Data:
    """Data which can be saved to the config. These should be immutable."""
    __info: ClassVar['ConfType']

    def __init_subclass__(
        cls, *,
        name: str = '',
        version: int = 1,
        palette_stores: bool = True,  # TODO remove
        uses_id: bool = False,
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if not name:
            raise ValueError('Config name must be specified!')
        if name.casefold() in {'version', 'name'}:
            raise ValueError(f'Illegal name: "{name}"')
        cls.__info = ConfType(cls, name, version, palette_stores, uses_id)

    @classmethod
    def get_conf_info(cls: Type[DataT]) -> 'ConfType[DataT]':
        """Return the ConfType for this class."""
        return cls.__info

    @classmethod
    def parse_legacy(cls: Type[DataT], conf: Property) -> Dict[str, DataT]:
        """Parse from the old legacy config. The user has to handle the uses_id style."""
        return {}

    @classmethod
    def parse_kv1(cls: Type[DataT], data: Property, version: int) -> DataT:
        """Parse keyvalues config values."""
        raise NotImplementedError

    def export_kv1(self) -> Property:
        """Generate keyvalues for saving configuration."""
        raise NotImplementedError

    @classmethod
    def parse_dmx(cls: Type[DataT], data: Element, version: int) -> DataT:
        """Parse DMX config values."""
        return cls.parse_kv1(data.to_kv1(), version)

    def export_dmx(self) -> Element:
        """Generate DMX for saving the configuration."""
        return Element.from_kv1(self.export_kv1())


@attrs.define(eq=False)
class ConfType(Generic[DataT]):
    """Holds information about a type of configuration data."""
    cls: Type[DataT]
    name: str
    version: int
    palette_stores: bool  # If this is save/loaded by palettes.
    uses_id: bool  # If we manage individual configs for each of these IDs.
    # After the relevant UI is initialised, this is set to an async func which
    # applies the data to the UI. This way we know it can be done safely now.
    # If data was loaded from the config, the callback is immediately awaited.
    # One is provided independently for each ID, so it can be sent to the right object.
    callback: Dict[str, Callable[[DataT], Awaitable]] = attrs.field(factory=dict, repr=False)


# The current data loaded from the config file. This maps an ID to each value, or
# is {'': data} if no key is used.
Config = NewType('Config', Dict[ConfType, Dict[str, Data]])
_CUR_CONFIG: Config = Config({})


@attrs.define(eq=False)
class ConfigSpec:
    """ConfTypes are registered with a spec, to define what sections are present."""
    filename: Optional[Path]
    _name_to_type: Dict[str, ConfType] = attrs.Factory(dict)
    _class_to_type: Dict[Type[Data], ConfType] = attrs.Factory(dict)
    _registered: Set[Type[Data]] = attrs.Factory(set)
    # _current: Config = attrs.Factory(lambda: Config({}))
    @property
    def _current(self) -> Config:
        """TODO: Redirect all _CUR_CONFIG uses to here."""
        return _CUR_CONFIG

    @_current.setter
    def _current(self, value: Config) -> None:
        global _CUR_CONFIG
        _CUR_CONFIG = value

    def info_by_name(self, name: str) -> ConfType:
        """Lookup the data type for a specific name."""
        return self._name_to_type[name.casefold()]

    def info_by_class(self, data: Type[DataT]) -> ConfType[DataT]:
        """Lookup the data type for this class."""
        return self._class_to_type[data]

    def register(self, cls: Type[DataT]) -> Type[DataT]:
        """Register a config data type. The name must be unique."""
        info = cls.get_conf_info()
        self._name_to_type[info.name.casefold()] = info
        self._class_to_type[cls] = info
        self._registered.add(cls)
        return cls

    async def set_and_run_ui_callback(
        self,
        typ: Type[DataT],
        func: Callable[[DataT], Awaitable],
        data_id: str='',
    ) -> None:
        """Set the callback used to apply this config type to the UI.

        If the configs have been loaded, it will immediately be called. Whenever new configs
        are loaded, it will be re-applied regardless.
        """
        info: ConfType[DataT] = self._class_to_type[typ]
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        if data_id in info.callback:
            raise ValueError(f'Cannot set callback for {info.name}[{data_id}] twice!')
        info.callback[data_id] = func
        data_map = self._current.setdefault(info, {})
        if data_id in data_map:
            await func(cast(DataT, data_map[data_id]))

    async def apply_conf(
        self,
        info_or_type: Union[ConfType[DataT], Type[DataT]],
        *,
        data_id: str= '',
    ) -> None:
        """Apply the current settings for this config type and ID.

        If the data_id is not passed, all settings will be applied.
        """
        info: ConfType[DataT]
        if isinstance(info_or_type, ConfType):
            info = info_or_type
        else:
            info = self._class_to_type[info_or_type]

        if data_id:
            if not info.uses_id:
                raise ValueError(f'Data type "{info.name}" does not support IDs!')
            try:
                data = self._current[info][data_id]
                cb = info.callback[data_id]
            except KeyError:
                LOGGER.warning('{}[{}] has no UI callback!', info.name, data_id)
            else:
                assert isinstance(data, info.cls), info
                await cb(data)
        else:
            try:
                data_map = self._current[info]
            except KeyError:
                LOGGER.warning('{}[:] has no UI callback!', info.name)
                return
            async with trio.open_nursery() as nursery:
                for dat_id, data in data_map.items():
                    try:
                        cb = info.callback[dat_id]
                    except KeyError:
                        LOGGER.warning('{}[{}] has no UI callback!', info.name, data_id)
                    else:
                        nursery.start_soon(cb, data)

    def get_cur_conf(
        self,
        cls: Type[DataT],
        data_id: str='',
        default: Union[DataT, None] = None,
        legacy_id: str='',
    ) -> DataT:
        """Fetch the currently active config for this ID.

        If legacy_id is defined, this will be checked if the original does not exist, and if so
        moved to the actual ID.
        """
        info: ConfType[DataT] = self._class_to_type[cls]
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        data: object = None
        try:
            data = self._current[info][data_id]
        except KeyError:
            if legacy_id:
                try:
                    conf_map = self._current[info]
                    data = conf_map[data_id] = conf_map.pop(legacy_id)
                except KeyError:
                    pass
        if data is None:
            # Return a default value.
            if default is not None:
                return default
            else:
                raise KeyError(data_id)

        assert isinstance(data, info.cls), info
        return data

    def store_conf(self, data: DataT, data_id: str='') -> None:
        """Update the current data for this ID. """
        info: ConfType[DataT] = self._class_to_type[type(data)]
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        LOGGER.debug('Storing conf {}[{}] = {!r}', info.name, data_id, data)
        try:
            self._current[info][data_id] = data
        except KeyError:
            self._current[info] = {data_id: data}

    def parse_kv1(self, props: Property) -> Tuple[Config, bool]:
        """Parse a configuration file into individual data.

        The data is in the form {conf_type: {id: data}}, and a bool indicating if it was upgraded
        and so should be resaved.
        """
        if 'version' not in props:  # New conf format
            return self._parse_legacy(props), True

        version = props.int('version')
        if version != 1:
            raise ValueError(f'Unknown config version {version}!')

        conf = Config({})
        upgraded = False
        for child in props:
            if child.name == 'version':
                continue
            try:
                info = self._name_to_type[child.name]
            except KeyError:
                LOGGER.warning('Unknown config option "{}"!', child.real_name)
                continue
            version = child.int('_version', 1)
            try:
                del child['_version']
            except LookupError:
                pass
            if version > info.version:
                LOGGER.warning(
                    'Config option "{}" has version {}, '
                    'which is higher than the supported version ({})!',
                    info.name, version, info.version
                )
                # Don't try to parse, it'll be invalid.
                continue
            elif version != info.version:
                upgraded = True
            data_map: Dict[str, Data] = {}
            conf[info] = data_map
            if info.uses_id:
                for data_prop in child:
                    try:
                        data_map[data_prop.real_name] = info.cls.parse_kv1(data_prop, version)
                    except Exception:
                        LOGGER.warning(
                            'Failed to parse config {}[{}]:',
                            info.name, data_prop.real_name,
                            exc_info=True,
                        )
            else:
                try:
                    data_map[''] = info.cls.parse_kv1(child, version)
                except Exception:
                    LOGGER.warning(
                        'Failed to parse config {}:',
                        info.name,
                        exc_info=True,
                    )
        return conf, upgraded

    def _parse_legacy(self, props: Property) -> Config:
        """Parse the old config format."""
        conf = Config({})
        # Convert legacy configs.
        for info in self._name_to_type.values():
            if hasattr(info.cls, 'parse_legacy'):
                conf[info] = new = info.cls.parse_legacy(props)
                LOGGER.info('Converted legacy {} to {}', info.name, new)
            else:
                LOGGER.warning('No legacy conf for "{}"!', info.name)
                conf[info] = {}
        return conf

    def build_kv1(self, conf: Config) -> Iterator[Property]:
        """Build out a configuration file from some data.

        The data is in the form {conf_type: {id: data}}.
        """
        yield Property('version', '1')
        info: ConfType
        for info, data_map in conf.items():
            if not data_map or info.cls not in self._class_to_type:
                # Blank or not in our definition, don't save.
                continue
            prop = Property(info.name, [
                Property('_version', str(info.version)),
            ])
            if info.uses_id:
                for data_id, data in data_map.items():
                    sub_prop = data.export_kv1()
                    sub_prop.name = data_id
                    prop.append(sub_prop)
            else:
                # Must be a single '' key.
                if list(data_map.keys()) != ['']:
                    raise ValueError(
                        f'Must have a single \'\' key for non-id type "{info.name}", got:\n{data_map}'
                    )
                [data] = data_map.values()
                prop.extend(data.export_kv1())
            yield prop

    def build_dmx(self, conf: Config) -> Element:
        """Build out a configuration file from some data.

        The data is in the form {conf_type: {id: data}}.
        """
        info: ConfType
        root = Element('BEE2Config', 'DMElement')
        for info, data_map in conf.items():
            if info.cls not in self._class_to_type:
                continue
            if not hasattr(info.cls, 'export_dmx'):
                LOGGER.warning('No DMX export for {}!', info.name)
                continue
            if info.uses_id:
                elem = Element(info.name, f'Conf_v{info.version}')
                for data_id, data in data_map.items():
                    sub_elem = data.export_dmx()
                    sub_elem.name = data_id
                    sub_elem.type = 'SubConf'
                    elem[data_id] = sub_elem
            else:
                # Must be a single '' key.
                if list(data_map.keys()) != ['']:
                    raise ValueError(
                        f'Must have a single \'\' key for non-id type "{info.name}", got:\n{data_map}'
                    )
                [data] = data_map.values()
                elem = data.export_dmx()
                elem.name = info.name
                elem.type = f'Conf_v{info.version}'
            root[info.name] = elem
        return root

    def read_file(self) -> None:
        """Read and apply the settings from disk."""
        if self.filename is None:
            raise ValueError('No filename specified for this ConfigSpec!')

        try:
            file = self.filename.open(encoding='utf8')
        except FileNotFoundError:
            return
        try:
            with file:
                props = Property.parse(file)
        except KeyValError:
            LOGGER.warning('Cannot parse {}!', self.filename.name, exc_info=True)
            # Try and move to a backup name, if not don't worry about it.
            try:
                self.filename.replace(self.filename.with_suffix('.err.vdf'))
            except IOError:
                pass

        conf, _ = self.parse_kv1(props)
        self._current.clear()
        for info, obj_map in conf.items():
            self._current[info] = obj_map

    def write_file(self) -> None:
        """Write the settings to disk."""
        if self.filename is None:
            raise ValueError('No filename specified for this ConfigSpec!')

        if not any(self._current.values()):
            # We don't have any data saved, abort!
            # This could happen while parsing, for example.
            return

        props = Property.root()
        props.extend(self.build_kv1(self._current))
        with atomic_write(self.filename, encoding='utf8', overwrite=True) as file:
            for prop in props:
                for line in prop.export():
                    file.write(line)


def get_pal_conf() -> Config:
    """Return a copy of the current settings for the palette."""
    return Config({
        info: opt_map.copy()
        for info, opt_map in _CUR_CONFIG.items()
        if info.palette_stores
    })


async def apply_pal_conf(conf: Config) -> None:
    """Apply a config provided from the palette."""
    # First replace all the configs to be atomic, then apply.
    for info, opt_map in conf.items():
        if info.palette_stores:  # Double-check, in case it's added to the file.
            _CUR_CONFIG[info] = opt_map.copy()
    async with trio.open_nursery() as nursery:
        for info in conf:
            if info.palette_stores:
                nursery.start_soon(APP.apply_conf, info)


# Main application configs.
APP = ConfigSpec(utils.conf_location('config/config.vdf'))


@APP.register
@attrs.frozen(slots=False)
class LastSelected(Data, name='LastSelected', uses_id=True):
    """Used for several general items, specifies the last selected one for restoration."""
    id: Union[str, None] = None

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, 'LastSelected']:
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
                result[new] = cls(last_sel[old])
            except LookupError:
                pass
        return result

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'LastSelected':
        """Parse Keyvalues data."""
        assert version == 1
        if data.has_children():
            raise ValueError(f'LastSelected cannot be a block: {data!r}')
        if data.value.casefold() == '<none>':
            return cls(None)
        return cls(data.value)

    def export_kv1(self) -> Property:
        """Export to a property block."""
        return Property('', '<NONE>' if self.id is None else self.id)

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'LastSelected':
        """Parse DMX elements."""
        assert version == 1
        if 'selected_none' in data and data['selected_none'].val_bool:
            return cls(None)
        else:
            return cls(data['selected'].val_str)

    def export_dmx(self) -> Element:
        """Export to a DMX element."""
        elem = Element('LastSelected', 'DMElement')
        if self.id is None:
            elem['selected_none'] = True
        else:
            elem['selected'] = self.id
        return elem


class AfterExport(Enum):
    """Specifies what happens after exporting."""
    NORMAL = 0  # Stay visible
    MINIMISE = 1  # Minimise to tray
    QUIT = 2  # Quit the app.


@APP.register
@attrs.frozen(slots=False)
class GenOptions(Data, name='Options', palette_stores=False):
    """General app config options, mainly booleans. These are all changed in the options window."""
    # The boolean values are handled the same way, using the metadata to record the old legacy names.
    # If the name has a :, the first is the section and the second is the name.
    # Otherwise, it's just the section name and the attr name is the same as the option name.

    after_export: AfterExport = AfterExport.NORMAL
    launch_after_export: bool = attrs.field(default=True, metadata={'legacy': 'General:launch_game'})

    play_sounds: bool = attrs.field(default=True, metadata={'legacy': 'General'})
    keep_win_inside: bool = attrs.field(default=True, metadata={'legacy': 'General'})
    force_load_ontop: bool = attrs.field(default=True, metadata={'legacy': 'General:splash_stay_ontop'})
    compact_splash: bool = attrs.field(default=True, metadata={'legacy': 'General'})
    music_collapsed: bool = attrs.field(default=True, metadata={'legacy': 'Last_Selected'})

    # Log window.
    show_log_win: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_win_level: str = 'INFO'

    # Stuff mainly for devs.
    preserve_resources: bool = attrs.field(default=False, metadata={'legacy': 'General:preserve_bee2_resource_dir'})
    dev_mode: bool = attrs.field(default=False, metadata={'legacy': 'Debug:development_mode'})
    log_missing_ent_count: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_missing_styles: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    log_item_fallbacks: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})
    visualise_inheritance: bool = False
    force_all_editor_models: bool = attrs.field(default=False, metadata={'legacy': 'Debug'})

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, 'GenOptions']:
        """Parse from the GEN_OPTS config file."""
        log_win_level = LEGACY_CONF['Debug']['window_log_level']
        try:
            after_export = AfterExport(LEGACY_CONF.get_int(
                'General', 'after_export_action',
                0,
            ))
        except ValueError:
            after_export = AfterExport.NORMAL

        res = {}
        for field in gen_opts_bool:
            try:
                section: str = field.metadata['legacy']
            except KeyError:
                # New field.
                res[field.name] = field.default
                continue
            try:
                section, name = section.split(':')
            except ValueError:
                name = field.name
            res[field.name] = LEGACY_CONF.get_bool(section, name, field.default)

        return {'': GenOptions(
            after_export=after_export,
            log_win_level=log_win_level,
            **res,
        )}

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'GenOptions':
        """Parse KV1 values."""
        assert version == 1
        try:
            after_export = AfterExport(data.int('after_export', 0))
        except ValueError:
            after_export = AfterExport.NORMAL

        return GenOptions(
            after_export=after_export,
            log_win_level=data['log_win_level', 'INFO'],
            **{
                field.name: data.bool(field.name, field.default)
                for field in gen_opts_bool
            },
        )

    def export_kv1(self) -> Property:
        """Produce KV1 values."""
        prop = Property('', [
            Property('after_export', str(self.after_export.value)),
            Property('log_win_level', self.log_win_level),
        ])
        for field in gen_opts_bool:
            prop[field.name] = '1' if getattr(self, field.name) else '0'
        return prop

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'GenOptions':
        """Parse DMX configuration."""
        assert version == 1
        res: dict[str, Any] = {}
        try:
            res['after_export'] = AfterExport(data['after_export'].val_int)
        except (KeyError, ValueError):
            res['after_export'] = AfterExport.NORMAL
        for field in gen_opts_bool:
            try:
                res[field.name] = data[field.name].val_bool
            except KeyError:
                res[field.name] = field.default
        return GenOptions(**res)

    def export_dmx(self) -> Element:
        """Produce DMX configuration."""
        elem = Element('Options', 'DMElement')
        elem['after_export'] = self.after_export.value
        for field in gen_opts_bool:
            elem[field.name] = getattr(self, field.name)
        return elem


gen_opts_bool = [
    field
    for field in attrs.fields(GenOptions)
    if field.default in (True, False)
]


@APP.register
@attrs.frozen(slots=False)
class WindowState(Data, name='PaneState', uses_id=True, palette_stores=False):
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
