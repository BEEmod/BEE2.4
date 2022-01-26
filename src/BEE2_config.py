"""Settings related logic for the application.

Functions can be registered with a name, which will be called to save/load
settings.

This also contains a version of ConfigParser that can be easily resaved.

It only saves if the values are modified.
Most functions are also altered to allow defaults instead of erroring.
"""
from configparser import ConfigParser, NoOptionError, SectionProxy, ParsingError
from pathlib import Path
from typing import (
    ClassVar, List, NewType, Tuple, TypeVar, Generic, Protocol, Any, Optional, Callable, Type,
    Awaitable, Iterator, Dict, Mapping, cast,
)
from threading import Lock, Event

import attr
import trio
from atomicwrites import atomic_write

from srctools import Property, KeyValError
from srctools.dmx import Element

import utils
import srctools.logger


LOGGER = srctools.logger.get_logger(__name__)


def read_settings() -> None:
    """Read and apply the settings from disk."""
    path = utils.conf_location('config/config.vdf')
    try:
        file = path.open(encoding='utf8')
    except FileNotFoundError:
        return
    try:
        with file:
            props = Property.parse(file)
    except KeyValError:
        LOGGER.warning('Cannot parse config.vdf!', exc_info=True)
        # Try and move to a backup name, if not don't worry about it.
        try:
            path.replace(path.with_suffix('.err.vdf'))
        except IOError:
            pass

    conf = parse_conf(props)
    _CUR_CONFIG.clear()
    for info, obj_map in conf.items():
        _CUR_CONFIG[info] = obj_map


def write_settings() -> None:
    """Write the settings to disk."""
    if not any(_CUR_CONFIG.values()):
        # We don't have any data saved, abort!
        # This could happen while parsing, for example.
        return

    props = Property.root()
    props.extend(build_conf(_CUR_CONFIG))
    with atomic_write(
        utils.conf_location('config/config.vdf'),
        encoding='utf8',
        overwrite=True,
    ) as file:
        for prop in props:
            for line in prop.export():
                file.write(line)


DataT = TypeVar('DataT', bound='Data')


class Data(Protocol):
    """Data which can be saved to the config. These should be immutable."""
    @classmethod
    def parse_legacy(cls: Type[DataT], conf: Property) -> Dict[str, DataT]:
        """Parse from the old legacy config. The user has to handle the uses_id style."""
        raise NotImplementedError

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
        raise NotImplementedError

    def export_dmx(self) -> Element:
        """Generate DMX for saving the configuration."""
        raise NotImplementedError


@attr.define(eq=False)
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
    callback: Dict[str, Callable[[DataT], Awaitable]] = attr.ib(factory=dict, repr=False)


_NAME_TO_TYPE: Dict[str, ConfType] = {}
_TYPE_TO_TYPE: Dict[Type[Data], ConfType] = {}
# The current data loaded from the config file. This maps an ID to each value, or
# is {'': data} if no key is used.
Config = NewType('Config', Dict[ConfType, Dict[str, Data]])
_CUR_CONFIG: Config = Config({})


def get_info_by_name(name: str) -> ConfType:
    """Lookup the data type for this class."""
    return _NAME_TO_TYPE[name.casefold()]


def get_info_by_type(data: Type[DataT]) -> ConfType[DataT]:
    """Lookup the data type for this class."""
    return _TYPE_TO_TYPE[data]


def register(
    name: str, *,
    version: int = 1,
    palette_stores: bool = True,
    uses_id: bool = False,
) -> Callable[[Type[DataT]], Type[DataT]]:
    """Register a config data type. The name must be unique.

    The version is the latest version of this config, and should increment each time it changes
    in a backwards-incompatible way.
    """
    def deco(cls: Type[DataT]) -> Type[DataT]:
        """Register the class."""
        info = ConfType(cls, name, version, palette_stores, uses_id)
        assert name.casefold() not in _NAME_TO_TYPE, info
        assert cls not in _TYPE_TO_TYPE, info
        _NAME_TO_TYPE[name.casefold()] = _TYPE_TO_TYPE[cls] = info
        return cls
    return deco


async def set_and_run_ui_callback(typ: Type[DataT], func: Callable[[DataT], Awaitable], data_id: str='') -> None:
    """Set the callback used to apply this config type to the UI.

    If the configs have been loaded, it will immediately be called. Whenever new configs
    are loaded, it will be re-applied regardless.
    """
    info: ConfType[DataT] = _TYPE_TO_TYPE[typ]
    if data_id and not info.uses_id:
        raise ValueError(f'Data type "{info.name}" does not support IDs!')
    if data_id in info.callback:
        raise ValueError(f'Cannot set callback for {info.name}[{data_id}] twice!')
    info.callback[data_id] = func
    data_map = _CUR_CONFIG.setdefault(info, {})
    if data_id in data_map:
        await func(cast(DataT, data_map[data_id]))


async def apply_conf(info: ConfType[DataT], data_id: str='') -> None:
    """Apply the current settings for this config type and ID.

    If the data_id is not passed, all settings will be applied.
    """
    if data_id:
        if not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        try:
            data = _CUR_CONFIG[info][data_id]
            cb = info.callback[data_id]
        except KeyError:
            LOGGER.warning('{}[{}] has no UI callback!', info.name, data_id)
        else:
            assert isinstance(data, info.cls), info
            await cb(data)
    else:
        async with trio.open_nursery() as nursery:
            for dat_id, data in _CUR_CONFIG[info].items():
                try:
                    cb = info.callback[dat_id]
                except KeyError:
                    LOGGER.warning('{}[{}] has no UI callback!', info.name, data_id)
                else:
                    nursery.start_soon(cb, data)


def get_cur_conf(cls: Type[DataT], data_id: str='', default: Optional[DataT] = None) -> DataT:
    """Fetch the currently active config for this ID."""
    info: ConfType[DataT] = _TYPE_TO_TYPE[cls]
    if data_id and not info.uses_id:
        raise ValueError(f'Data type "{info.name}" does not support IDs!')
    try:
        data = _CUR_CONFIG[info][data_id]
    except KeyError:
        # Return a default value.
        if default is not None:
            return default
        else:
            raise
    assert isinstance(data, info.cls), info
    return data


def store_conf(data: DataT, data_id: str='') -> None:
    """Update the current data for this ID. """
    info: ConfType[DataT] = _TYPE_TO_TYPE[type(data)]
    if data_id and not info.uses_id:
        raise ValueError(f'Data type "{info.name}" does not support IDs!')
    LOGGER.debug('Storing conf {}[{}] = {!r}', info.name, data_id, data)
    _CUR_CONFIG.setdefault(info, {})[data_id] = data


def parse_conf(props: Property) -> Config:
    """Parse a configuration file into individual data.

    The data is in the form {conf_type: {id: data}}.
    """
    if 'version' not in props:  # New conf format
        return parse_conf_legacy(props)

    version = props.int('version')
    if version != 1:
        raise ValueError(f'Unknown config version {version}!')

    conf = Config({})
    for child in props:
        try:
            info = _NAME_TO_TYPE[child.name]
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
    return conf


def parse_conf_legacy(props: Property) -> Config:
    """Parse the old config format."""
    conf = Config({})
    # Convert legacy configs.
    for info in _NAME_TO_TYPE.values():
        if hasattr(info.cls, 'parse_legacy'):
            conf[info] = new = info.cls.parse_legacy(props)
            LOGGER.info('Converted legacy {} to {}', info.name, new)
        else:
            LOGGER.warning('No legacy conf for "{}"!', info.name)
            conf[info] = {}
    return conf


def build_conf(conf: Config) -> Iterator[Property]:
    """Build out a configuration file from some data.

    The data is in the form {conf_type: {id: data}}.
    """
    yield Property('version', '1')
    for info, data_map in conf.items():
        if not data_map:
            # Blank, don't save.
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


def build_conf_dmx(conf: Config) -> Element:
    """Build out a configuration file from some data.

    The data is in the form {conf_type: {id: data}}.
    """
    info: ConfType
    root = Element('BEE2Config', 'DMElement')
    for info, data_map in conf.items():
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
                nursery.start_soon(apply_conf, info)


@register('LastSelected', uses_id=True)
@attr.frozen
class LastSelected(Data):
    """Used for several general items, specifies the last selected one for restoration."""
    id: Optional[str] = None
    # For legacy parsing, old to new save IDs.
    legacy: ClassVar[List[Tuple[str, str]]] = {
        ('Style', 'styles'),
        ('Skybox', 'skyboxes'),
        ('Voice', 'voicelines'),
        ('Elevator', 'elevators'),
        ('Music_Base', 'music_base'),
        ('Music_Tbeam', 'music_tbeam'),
        ('Music_Bounce', 'music_bounce'),
        ('Music_Speed', 'music_speed'),
    }

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, 'LastSelected']:
        """Parse legacy config data."""
        result = {}
        last_sel = conf.find_key('LastSelected', or_blank=True)
        for old, new in cls.legacy:
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


def get_package_locs() -> Iterator[Path]:
    """Return all the package search locations from the config."""
    section = GEN_OPTS['Directories']
    yield Path(section['package'])
    i = 1
    while True:
        try:
            val = section[f'package{i}']
        except KeyError:
            return
        yield Path(val)
        i += 1


class ConfigFile(ConfigParser):
    """A version of ConfigParser which can easily save itself.

    The config will track whether any values change, and only resave
    if modified.
    get_val, get_bool, and get_int are modified to return defaults instead
    of erroring.
    """
    filename: Optional[Path]

    def __init__(
        self,
        filename: Optional[str],
        *,
        in_conf_folder: bool=True,
        auto_load: bool=True,
    ) -> None:
        """Initialise the config file.

        `filename` is the name of the config file, in the `root` directory.
        If `auto_load` is true, this file will immediately be read and parsed.
        If in_conf_folder is set, The folder is relative to the 'config/'
        folder in the BEE2 folder.
        """
        super().__init__()

        self.has_changed = Event()
        self._file_lock = Lock()

        if filename is not None:
            if in_conf_folder:
                self.filename = utils.conf_location('config') / filename
            else:
                self.filename = Path(filename)
            if auto_load:
                self.load()
        else:
            self.filename = None

    def load(self) -> None:
        """Load config options from disk."""
        if self.filename is None:
            return

        try:
            with self._file_lock, open(self.filename, 'r', encoding='utf8') as conf:
                self.read_file(conf)
                # We're not different to the file on disk..
                self.has_changed.clear()
        # If missing, just use default values.
        except FileNotFoundError:
            LOGGER.warning(
                'Config "{}" not found! Using defaults...',
                self.filename,
            )
        # But if we fail to read entirely, fall back to defaults.
        except (IOError, ParsingError, UnicodeDecodeError):
            LOGGER.warning(
                'Config "{}" cannot be read! Using defaults...',
                self.filename,
                exc_info=True,
            )
            # Try and preserve the bad file with this name,
            # but if it doesn't work don't worry about it.
            try:
                self.filename.replace(self.filename.with_suffix('.err.cfg'))
            except IOError:
                pass

    def save(self) -> None:
        """Write our values out to disk."""
        with self._file_lock:
            LOGGER.info('Saving changes in config "{}"!', self.filename)
            if self.filename is None:
                raise ValueError('No filename provided!')

            # Create the parent if it hasn't already.
            self.filename.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write(self.filename, overwrite=True, encoding='utf8') as conf:
                self.write(conf)
            self.has_changed.clear()

    def save_check(self) -> None:
        """Check to see if we have different values, and save if needed."""
        if self.has_changed.is_set():
            self.save()

    def set_defaults(self, def_settings: Mapping[str, Mapping[str, Any]]) -> None:
        """Set the default values if the settings file has no values defined."""
        for sect, values in def_settings.items():
            if sect not in self:
                self[sect] = {}
            for key, default in values.items():
                if key not in self[sect]:
                    self[sect][key] = str(default)
        self.save_check()

    def get_val(self, section: str, value: str, default: str) -> str:
        """Get the value in the specifed section.

        If either does not exist, set to the default and return it.
        """
        if section not in self:
            self[section] = {}
        if value in self[section]:
            return self[section][value]
        else:
            self.has_changed.set()
            self[section][value] = default
            return default

    def __getitem__(self, section: str) -> SectionProxy:
        """Allows setting/getting config[section][value]."""
        try:
            return super().__getitem__(section)
        except KeyError:
            self[section] = {}
            return super().__getitem__(section)

    def getboolean(self, section: str, value: str, default: bool=False, **kwargs) -> bool:
        """Get the value in the specified section, coercing to a Boolean.

            If either does not exist, set to the default and return it.
            """
        if section not in self:
            self[section] = {}
        try:
            return super().getboolean(section, value, **kwargs)
        except (ValueError, NoOptionError):
            #  Invalid boolean, or not found
            self.has_changed.set()
            self[section][value] = str(int(default))
            return default

    get_bool = getboolean

    def getint(self, section: str, value: str, default: int=0, **kwargs) -> int:
        """Get the value in the specified section, coercing to a Integer.

            If either does not exist, set to the default and return it.
            """
        if section not in self:
            self[section] = {}
        try:
            return super().getint(section, value, **kwargs)
        except (ValueError, NoOptionError):
            self.has_changed.set()
            self[section][value] = str(int(default))
            return default

    get_int = getint

    def add_section(self, section: str) -> None:
        """Add a file section."""
        self.has_changed.set()
        super().add_section(section)

    def remove_section(self, section: str) -> bool:
        """Remove a file section."""
        self.has_changed.set()
        return super().remove_section(section)

    def set(self, section: str, option: str, value: Any=None) -> None:
        """Set an option, marking the file dirty if this changed it."""
        orig_val = self.get(section, option, fallback=None)
        value = str(value)
        if orig_val is None or orig_val != value:
            self.has_changed.set()
            super().set(section, option, value)


# Define this here so app modules can easily access the config
# Don't load it though, since this is imported by VBSP too.
GEN_OPTS = ConfigFile('config.cfg', auto_load=False)
