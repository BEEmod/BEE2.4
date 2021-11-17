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
    TypeVar, Generic, Protocol, Any, Optional, Callable, Type,
    Awaitable, Iterable, Iterator, Dict, Mapping,
)
from threading import Lock, Event

import attr
from atomicwrites import atomic_write

from srctools import Property, KeyValError

import utils
import srctools.logger


LOGGER = srctools.logger.get_logger(__name__)

# Functions for saving or loading application settings.
# The palette attribute indicates if this will be persisted in palettes.
OPTION_LOAD: utils.FuncLookup[Callable[[Property], None]] = utils.FuncLookup('LoadHandler', attrs=['from_palette'])
OPTION_SAVE: utils.FuncLookup[Callable[[], Property]] = utils.FuncLookup('SaveHandler', attrs=['to_palette'])


def get_curr_settings(*, is_palette: bool) -> Property:
    """Return a property tree defining the current options."""
    props = Property.root()

    for opt_id, opt_func in OPTION_SAVE.items():
        # Skip if it opts out of being on the palette.
        if is_palette and not getattr(opt_func, 'to_palette', True):
            continue
        opt_prop = opt_func()
        opt_prop.name = opt_id.title()
        props.append(opt_prop)

    return props


def apply_settings(props: Property, *, is_palette: bool) -> None:
    """Given a property tree, apply it to the widgets."""
    for opt_prop in props:
        assert opt_prop.name is not None
        try:
            func = OPTION_LOAD[opt_prop.name]
        except KeyError:
            LOGGER.warning('No handler for option type "{}"!', opt_prop.real_name)
            continue
        # Skip if it opts out of being on the palette.
        if is_palette and not getattr(func, 'from_palette', True):
            continue
        func(opt_prop)


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
    for obj in conf.values():
        info = _TYPE_TO_CONFIG[type(obj)]
        info.data = obj


def write_settings() -> None:
    """Write the settings to disk."""
    props = Property.root()
    props.extend(build_conf(
        info.data
        for info in _NAME_TO_CONFIG.values()
        if info.data is not None
    ))
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
    def parse_kv1(cls: Type[DataT], data: Property, version: int) -> DataT:
        """Parse DMX config values."""
        raise NotImplementedError

    def export_kv1(self) -> Property:
        """Generate keyvalues for saving configuration."""
        raise NotImplementedError


@attr.define
class ConfType(Generic[DataT]):
    """Holds information about a type of configuration data."""
    cls: Type[DataT]
    name: str
    version: int
    palette_stores: bool  # If this is save/loaded by palettes.
    data: Optional[DataT] = None
    callback: Optional[Callable[[DataT], Awaitable]] = None


_NAME_TO_CONFIG: Dict[str, ConfType] = {}
_TYPE_TO_CONFIG: Dict[Type[Data], ConfType] = {}


def register(
    name: str, *,
    version: int = 1,
    palette_stores: bool = True,
) -> Callable[[Type[DataT]], Type[DataT]]:
    """Register a config data type. The name must be unique.

    The version is the latest version of this config, and should increment each time it changes
    in a backwards-incompatible way.
    """
    def deco(cls: Type[DataT]) -> Type[DataT]:
        """Register the class."""
        info = ConfType(cls, name, version, palette_stores)
        assert name.casefold() not in _NAME_TO_CONFIG, info
        assert cls not in _TYPE_TO_CONFIG, info
        _NAME_TO_CONFIG[name.casefold()] = _TYPE_TO_CONFIG[cls] = info
        return cls
    return deco


async def set_callback(typ: Type[DataT], func: Callable[[DataT], Awaitable]) -> None:
    """Set the callback used to apply this config type to the UI.

    If the configs have been loaded, it will immediately be called. Whenever new configs
    are loaded, it will be re-applied regardless.
    """
    info: ConfType[DataT] = _TYPE_TO_CONFIG[typ]
    if info.callback is not None:
        raise ValueError(f'Cannot set callback for {info.cls}="{info.name}" twice!')
    info.callback = func
    if info.data is not None:
        await func(info.data)


async def apply_conf(typ: Type[DataT]) -> None:
    """Apply the current settings for this config type."""
    info: ConfType[DataT] = _TYPE_TO_CONFIG[typ]
    if info.callback is not None and info.data is not None:
        await info.callback(info.data)


def store_conf(data: DataT) -> None:
    """Update this configured data. """
    _TYPE_TO_CONFIG[type(data)].data = data


def parse_conf(props: Property) -> Dict[str, Data]:
    """Parse a configuration file into individual data."""
    conf = {}
    for child in props:
        try:
            info = _NAME_TO_CONFIG[child.name]
        except KeyError:
            LOGGER.warning('Unknown config option "{}"!', child.real_name)
            continue
        version = child.int('_version', 0)
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
        conf[child.name] = info.cls.parse_kv1(child, version)
    return conf


def build_conf(data: Iterable[Data]) -> Iterator[Property]:
    """Build out a configuration file from some data."""
    for obj in data:
        info = _TYPE_TO_CONFIG[type(obj)]
        prop = obj.export_kv1()
        prop[0:0] = [Property('_version', str(info.version))]
        prop.name = info.name
        yield prop


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
