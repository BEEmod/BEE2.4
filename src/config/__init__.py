"""Deals with storing, saving and loading configuration.

Other modules define an immutable state class, then register it with this.
They can then fetch the current state and store new state.
"""
import abc
from pathlib import Path
from typing import (
    ClassVar, Optional, Set, TypeVar, Callable, NewType, Union, cast,
    Type, Dict, Awaitable, Iterator, Tuple,
)
import os

import attrs
import trio
from srctools import KeyValError, AtomicWriter, Property, logger
from srctools.dmx import Element

import utils


LOGGER = logger.get_logger(__name__)
if not os.environ.get('BEE_LOG_CONFIG'):  # Debug messages are spammy.
    LOGGER.setLevel('INFO')


DataT = TypeVar('DataT', bound='Data')


@attrs.define(eq=False)
class ConfInfo:
    """Holds information about a type of configuration data."""
    name: str
    version: int
    palette_stores: bool  # If this is saved/loaded by palettes.
    uses_id: bool  # If we manage individual configs for each of these IDs.


class Data(abc.ABC):
    """Data which can be saved to the config. These should be immutable."""
    __info: ClassVar[ConfInfo]
    __slots__ = ()  # No members itself.

    def __init_subclass__(
        cls, *,
        conf_name: str = '',
        version: int = 1,
        palette_stores: bool = True,  # TODO remove
        uses_id: bool = False,
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if not conf_name:
            raise ValueError('Config name must be specified!')
        if conf_name.casefold() in {'version', 'name'}:
            raise ValueError(f'Illegal name: "{conf_name}"')
        cls.__info = ConfInfo(conf_name, version, palette_stores, uses_id)

    @classmethod
    def get_conf_info(cls) -> ConfInfo:
        """Return the ConfInfo for this class."""
        return cls.__info

    @classmethod
    def parse_legacy(cls: Type[DataT], conf: Property) -> Dict[str, DataT]:
        """Parse from the old legacy config. The user has to handle the uses_id style."""
        return {}

    @classmethod
    @abc.abstractmethod
    def parse_kv1(cls: Type[DataT], data: Property, version: int) -> DataT:
        """Parse keyvalues config values."""
        raise NotImplementedError

    @abc.abstractmethod
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


# The current data loaded from the config file. This maps an ID to each value, or
# is {'': data} if no key is used.
Config = NewType('Config', Dict[Type[Data], Dict[str, Data]])


@attrs.define(eq=False)
class ConfigSpec:
    """A config spec represents the set of data types in a particlar config file."""
    filename: Optional[Path]
    _name_to_type: Dict[str, Type[Data]] = attrs.Factory(dict)
    _registered: Set[Type[Data]] = attrs.Factory(set)

    # After the relevant UI is initialised, this is set to an async func which
    # applies the data to the UI. This way we know it can be done safely now.
    # If data was loaded from the config, the callback is immediately awaited.
    # One is provided independently for each ID, so it can be sent to the right object.
    callback: Dict[Tuple[Type[Data], str], Callable[[Data], Awaitable]] = attrs.field(factory=dict, repr=False)

    _current: Config = attrs.Factory(lambda: Config({}))

    def datatype_for_name(self, name: str) -> Type[Data]:
        """Lookup the data type for a specific name."""
        return self._name_to_type[name.casefold()]

    def register(self, cls: Type[DataT]) -> Type[DataT]:
        """Register a config data type. The name must be unique."""
        info = cls.get_conf_info()
        folded_name = info.name.casefold()
        if folded_name in self._name_to_type:
            raise ValueError(f'"{info.name}" is already registered!')
        self._name_to_type[info.name.casefold()] = cls
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
        if typ not in self._registered:
            raise ValueError(f'Unregistered data type {typ!r}')
        info = typ.get_conf_info()
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        if (typ, data_id) in self.callback:
            raise ValueError(f'Cannot set callback for {info.name}[{data_id}] twice!')
        self.callback[typ, data_id] = func  # type: ignore
        data_map = self._current.setdefault(typ, {})
        if data_id in data_map:
            await func(cast(DataT, data_map[data_id]))

    async def apply_conf(self, typ: Type[Data], *, data_id: str= '') -> None:
        """Apply the current settings for this config type and ID.

        If the data_id is not passed, all settings will be applied.
        """
        if typ not in self._registered:
            raise ValueError(f'Unregistered data type {typ!r}')
        info = typ.get_conf_info()

        if data_id:
            if not info.uses_id:
                raise ValueError(f'Data type "{info.name}" does not support IDs!')
            try:
                data = self._current[typ][data_id]
                cb = self.callback[typ, data_id]
            except KeyError:
                LOGGER.warning('{}[{!r}] has no UI callback!', info.name, data_id)
            else:
                assert isinstance(data, typ), info
                await cb(data)
        else:
            try:
                data_map = self._current[typ]
            except KeyError:
                LOGGER.warning('{}[:] has no UI callback!', info.name)
                return
            async with trio.open_nursery() as nursery:
                for dat_id, data in data_map.items():
                    try:
                        cb = self.callback[typ, dat_id]
                    except KeyError:
                        LOGGER.warning('{}[{!r}] has no UI callback!', info.name, dat_id)
                    else:
                        nursery.start_soon(cb, data)

    def merge_conf(self, config: Config) -> None:
        """Re-store values in the specified config.

        Config types not registered with us are ignored.
        For per-ID types all values are replaced.
        """
        for cls, opt_map in config.items():
            if cls not in self._registered:
                continue
            self._current[cls] = opt_map.copy()

    async def apply_multi(self, config: Config) -> None:
        """Merge the values into our config, then apply the changed types.

        Application is done concurrently, but all are stored atomically.
        Config types not registered with us are ignored.
        """
        self.merge_conf(config)
        async with trio.open_nursery() as nursery:
            for cls in config:
                if cls in self._registered:
                    nursery.start_soon(self.apply_conf, cls)

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
        if cls not in self._registered:
            raise ValueError(f'Unregistered data type {cls!r}')
        info = cls.get_conf_info()
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        data: object = None
        try:
            data = self._current[cls][data_id]
        except KeyError:
            if legacy_id:
                try:
                    conf_map = self._current[cls]
                    data = conf_map[data_id] = conf_map.pop(legacy_id)
                except KeyError:
                    pass
        if data is None:
            # Return a default value.
            if default is not None:
                return default
            else:
                raise KeyError(data_id)

        assert isinstance(data, cls), info
        return data

    def store_conf(self, data: DataT, data_id: str='') -> None:
        """Update the current data for this ID. """
        if type(data) not in self._registered:
            raise ValueError(f'Unregistered data type {type(data)!r}')
        cls = type(data)
        info = cls.get_conf_info()

        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        LOGGER.debug('Storing conf {}[{}] = {!r}', info.name, data_id, data)
        try:
            self._current[cls][data_id] = data
        except KeyError:
            self._current[cls] = {data_id: data}

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
                cls = self._name_to_type[child.name]
            except KeyError:
                LOGGER.warning('Unknown config option "{}"!', child.real_name)
                continue
            info = cls.get_conf_info()
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
            conf[cls] = data_map
            if info.uses_id:
                for data_prop in child:
                    try:
                        data_map[data_prop.real_name] = cls.parse_kv1(data_prop, version)
                    except Exception:
                        LOGGER.warning(
                            'Failed to parse config {}[{}]:',
                            info.name, data_prop.real_name,
                            exc_info=True,
                        )
            else:
                try:
                    data_map[''] = cls.parse_kv1(child, version)
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
        for cls in self._name_to_type.values():
            info = cls.get_conf_info()
            if hasattr(cls, 'parse_legacy'):
                conf[cls] = new = cls.parse_legacy(props)
                LOGGER.info('Converted legacy {} to {}', info.name, new)
            else:
                LOGGER.warning('No legacy conf for "{}"!', info.name)
                conf[cls] = {}
        return conf

    def build_kv1(self, conf: Config) -> Iterator[Property]:
        """Build out a configuration file from some data.

        The data is in the form {conf_type: {id: data}}.
        """
        yield Property('version', '1')
        for cls, data_map in conf.items():
            if not data_map or cls not in self._registered:
                # Blank or not in our definition, don't save.
                continue
            info = cls.get_conf_info()
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
                        f'Must have a single "" key for non-id type '
                        f'"{info.name}", got:\n{data_map}'
                    )
                [data] = data_map.values()
                prop.extend(data.export_kv1())
            yield prop

    def build_dmx(self, conf: Config) -> Element:
        """Build out a configuration file from some data.

        The data is in the form {conf_type: {id: data}}.
        """
        root = Element('BEE2Config', 'DMElement')
        cls: Type[Data]
        for cls, data_map in conf.items():
            if cls not in self._registered:
                continue
            info = cls.get_conf_info()
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
        self._current.update(conf)

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
        with AtomicWriter(self.filename) as file:
            for prop in props:
                for line in prop.export():
                    file.write(line)


def get_pal_conf() -> Config:
    """Return a copy of the current settings for the palette."""
    return Config({
        cls: opt_map.copy()
        for cls, opt_map in APP._current.items()
        if cls.get_conf_info().palette_stores
    })


async def apply_pal_conf(conf: Config) -> None:
    """Apply a config provided from the palette."""
    # First replace all the configs to be atomic, then apply.
    for cls, opt_map in conf.items():
        if cls.get_conf_info().palette_stores:  # Double-check, in case it's added to the file.
            APP._current[cls] = opt_map.copy()
    async with trio.open_nursery() as nursery:
        for cls in conf:
            if cls.get_conf_info().palette_stores:
                nursery.start_soon(APP.apply_conf, cls)


# Main application configs.
APP: ConfigSpec = ConfigSpec(utils.conf_location('config/config.vdf'))
PALETTE: ConfigSpec = ConfigSpec(None)


# Import submodules, so they're registered.
from config import (
    compile_pane, corridors, gen_opts,
    last_sel, palette, signage,
    stylevar, widgets, windows,
)
