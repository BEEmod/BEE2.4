"""Deals with storing, saving and loading configuration.

Other modules define an immutable state class, then register it with this.
They can then fetch the current state and store new state.
"""
from __future__ import annotations

from typing import ClassVar, Self, cast, override
from collections.abc import Generator, ItemsView, Iterator, KeysView
from pathlib import Path
import abc
import contextlib
import os

from srctools import AtomicWriter, KeyValError, Keyvalues, logger
from srctools.dmx import Element, ValueType as DMXTypes
import attrs
import trio

import utils


LOGGER = logger.get_logger(__name__)
if not os.environ.get('BEE_LOG_CONFIG'):  # Debug messages are spammy.
    LOGGER.setLevel('INFO')


# Name and version to use for DMX files.
DMX_NAME = 'BEEConfig'
DMX_VERSION = 1


@attrs.define
class UnknownVersion(Exception):
    """Raised for unknown versions during parsing."""
    version: int
    allowed: str

    def __str__(self) -> str:
        """Format nicely."""
        return f'Invalid version {self.version}! Valid versions: {self.allowed}'


@attrs.define(eq=False)
class ConfInfo[DataT: 'Data']:
    """Holds information about a type of configuration data."""
    name: str
    version: int
    uses_id: bool  # If we manage individual configs for each of these IDs.
    default: DataT | None  # If non-None, the class can be called with no args, so a default is present.


class Data(abc.ABC):
    """Data which can be saved to the config. These should be immutable."""
    __info: ClassVar[ConfInfo]
    __slots__ = ()  # No members itself.

    @override
    def __init_subclass__(
        cls, *,
        conf_name: str = '',
        version: int = 1,
        uses_id: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if hasattr(cls, '_Data__info'):
            # Attrs __slots__ classes remakes the class, but it'll already have the info included.
            # Just keep the existing info, no kwargs are given here.
            return

        if not conf_name:
            raise ValueError('Config name must be specified!')
        if conf_name.casefold() in {'version', 'name'}:
            raise ValueError(f'Illegal name: "{conf_name}"')
        # Default must be created during the register call, after attrs decorator runs.
        cls.__info = ConfInfo(conf_name, version, uses_id, None)

    @classmethod
    def get_conf_info(cls) -> ConfInfo[Self]:
        """Return the ConfInfo for this class."""
        return cls.__info

    @classmethod
    def parse_legacy(cls, conf: Keyvalues, /) -> dict[str, Self]:
        """Parse from the old legacy config. The user has to handle the uses_id style."""
        return {}

    @classmethod
    @abc.abstractmethod
    def parse_kv1(cls, data: Keyvalues, /, version: int) -> Self:
        """Parse keyvalues config values."""
        raise NotImplementedError

    @abc.abstractmethod
    def export_kv1(self, /) -> Keyvalues:
        """Generate keyvalues for saving configuration."""
        raise NotImplementedError

    @classmethod
    def parse_dmx(cls, data: Element, /, version: int) -> Self:
        """Parse DMX config values."""
        return cls.parse_kv1(data.to_kv1(), version)

    def export_dmx(self, /) -> Element:
        """Generate DMX for saving the configuration."""
        return Element.from_kv1(self.export_kv1())


@attrs.define(repr=False)
class Config:
    """The current data loaded from the config file.

    This maps an ID to each value, or is {'': data} if no key is used.
    """
    _data: dict[type[Data], dict[str, Data]] = attrs.Factory(dict)

    def __repr__(self) -> str:
        vals = ', '.join([
            f'{len(data_map)}x {cls.get_conf_info().name}'
            for cls, data_map in self._data.items()
        ])
        return f'<Config: {vals}>'

    def copy(self) -> Config:
        """Copy the config, assuming values are immutable."""
        return Config({
            cls: data_map.copy()
            for cls, data_map in self._data.items()
        })

    def is_blank(self) -> bool:
        """Check if we have any values assigned."""
        return not any(self._data.values())

    def get[D: Data](
        self,
        cls: type[D],
        data_id: str = '',
    ) -> D:
        """Fetch the value defined for a specific ID."""
        info = cls.get_conf_info()
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        data_map = cast('dict[str, D]', self._data[cls])
        return data_map[data_id]

    def with_value(self, data: Data, data_id: str = '') -> Config:
        """Return a copy of the config with the data stored under the specified ID."""
        cls = type(data)
        info = cls.get_conf_info()

        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        LOGGER.debug('Storing conf {}[{}] = {!r}', info.name, data_id, data)
        self.get_or_blank(cls)[data_id] = data
        return self.copy()

    def overwrite[D: Data](self, cls: type[D], data_map: dict[str, D]) -> None:
        """Overwrite the map for a type."""
        self._data[cls] = data_map  # type: ignore

    def get_or_blank[D: Data](self, cls: type[D]) -> dict[str, D]:
        """Return the map for a single type, setting it to empty if not found."""
        res: dict[str, Data]
        try:
            res = self._data[cls]
        except KeyError:
            self._data[cls] = res = {}
        return res  # type: ignore

    def discard[D: Data](self, cls: type[D], data_id: str) -> tuple[Config, D | None]:
        """Remove the specified data ID, returning the value or None if not present."""
        try:
            # If cls or data_id is not present, raises.
            data_map = self._data[cls].copy()
            popped = cast(D, data_map.pop(data_id))
        except KeyError:
            return self, None

        copy = self._data.copy()
        if data_map:
            # This data map is missing just the specified ID.
            copy[cls] = data_map
        else:
            # Last ID for this class, remove entirely.
            del copy[cls]
        return Config(copy), popped

    def classes(self) -> KeysView[type[Data]]:
        """Return a view over the types present in the config."""
        return self._data.keys()

    def items(self) -> ItemsView[type[Data], dict[str, Data]]:
        """Return a view over the types and associated items."""
        return self._data.items()

    def items_cls[D: Data](self, cls: type[D]) -> ItemsView[str, D]:
        """Return a view over the items for a specific class."""
        data_map = cast('dict[str, D]', self._data[cls])
        return data_map.items()


@attrs.define(eq=False)
class ConfigSpec:
    """A config spec represents the set of data types in a particlar config file."""
    _name_to_type: dict[str, type[Data]] = attrs.Factory(dict)
    _registered: set[type[Data]] = attrs.Factory(set)

    # After the relevant UI is initialised, this is set to a channel which
    # applies the data to the UI. This way we know it can be done safely now.
    # If data was loaded from the config, it gets sent into the channel.
    # One is provided independently for each ID, so it can be sent to the right object.
    _apply_channel: dict[
        tuple[type[Data], str],
        list[trio.MemorySendChannel[Data]],
    ] = attrs.field(factory=dict, repr=False)

    _current: Config = attrs.Factory(lambda: Config({}))

    def datatype_for_name(self, name: str) -> type[Data]:
        """Lookup the data type for a specific name."""
        return self._name_to_type[name.casefold()]

    def register[DataT: Data](self, cls: type[DataT]) -> type[DataT]:
        """Register a config data type. The name must be unique."""
        info = cls.get_conf_info()
        folded_name = info.name.casefold()
        if folded_name in self._name_to_type:
            raise ValueError(f'"{info.name}" is already registered!')
        self._name_to_type[info.name.casefold()] = cls
        self._registered.add(cls)

        if info.default is None:
            try:
                info.default = cls()
            except TypeError:
                pass
        return cls

    @contextlib.contextmanager
    def get_ui_channel[DataT: Data](
        self,
        typ: type[DataT],
        data_id: str = '',
    ) -> Generator[trio.MemoryReceiveChannel[DataT], None, None]:
        """Associate a channel which will be sent the config value whenever it changes.

        If the configs have been loaded, it will immediately be set. Whenever new configs
        are loaded, it will be re-applied regardless.

        This is a context manager, which closes and removes the channel when exited.
        """
        if typ not in self._registered:
            raise ValueError(f'Unregistered data type {typ!r}')
        info = typ.get_conf_info()
        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')

        # Invalid to drop DataT -> Data.
        chan_list = cast(
            list[trio.MemorySendChannel[DataT]],
            self._apply_channel.setdefault((typ, data_id), [])
        )

        send: trio.MemorySendChannel[DataT]
        rec: trio.MemoryReceiveChannel[DataT]
        send, rec = trio.open_memory_channel(1)

        try:
            current = self._current.get(typ, data_id)
        except KeyError:
            pass
        else:
            # Can't possibly block, we just created this.
            send.send_nowait(current)
        chan_list.append(send)
        try:
            yield rec
        finally:
            rec.close()
            chan_list.remove(send)

    async def apply_conf[D: Data](self, typ: type[D], *, data_id: str = '') -> None:
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
                data = self._current.get(typ, data_id)
                channel_list = self._apply_channel[typ, data_id]
            except KeyError:
                LOGGER.warning('{}[{!r}] has no UI channel!', info.name, data_id)
            else:
                assert isinstance(data, typ), info
                async with trio.open_nursery() as nursery:
                    for channel in channel_list:
                        nursery.start_soon(channel.send, data)
        else:
            try:
                data_map = self._current.items_cls(typ)
            except KeyError:
                LOGGER.warning('{}[:] has no UI channel!', info.name)
                return
            async with trio.open_nursery() as nursery:
                for dat_id, data in data_map:
                    try:
                        channel_list = self._apply_channel[typ, dat_id]
                    except KeyError:
                        LOGGER.warning('{}[{!r}] has no UI channel!', info.name, dat_id)
                    else:
                        for channel in channel_list:
                            nursery.start_soon(channel.send, data)

    def get_full_conf(self, filter_to: ConfigSpec | None = None) -> Config:
        """Get the config stored by this spec, filtering to another if requested."""
        if filter_to is None:
            filter_to = self

        # Fully copy the Config structure so these don't interact with each other.
        return Config({
            cls: conf_map.copy()
            for cls, conf_map in self._current.items()
            if cls in filter_to._registered
        })

    def merge_conf(self, config: Config) -> None:
        """Re-store values in the specified config.

        Config types not registered with us are ignored.
        For per-ID types all values are replaced.
        """
        for cls, opt_map in config.items():
            if cls not in self._registered:
                continue
            self._current.overwrite(cls, opt_map.copy())

    async def apply_multi(self, config: Config) -> None:
        """Merge the values into our config, then apply the changed types.

        Application is done concurrently, but all are stored atomically.
        Config types not registered with us are ignored.
        """
        self.merge_conf(config)
        async with trio.open_nursery() as nursery:
            for cls in config.classes():
                if cls in self._registered:
                    nursery.start_soon(self.apply_conf, cls)

    def get_cur_conf[DataT: Data](
        self,
        cls: type[DataT],
        data_id: str = '',
        default: DataT | type[Exception] | None = None,
        legacy_id: str = '',
    ) -> DataT:
        """Fetch the currently active config for this ID.

        If legacy_id is defined, this will be checked if the original does not exist, and if so
        moved to the actual ID.
        Default can be set to an exception type to force an exception. Otherwise, if the class can
        be constructed without args that will be returned by default.
        """
        if cls not in self._registered:
            raise ValueError(f'Unregistered data type {cls!r}')
        info = cls.get_conf_info()
        data: DataT | None = None
        try:
            return self._current.get(cls, data_id)
        except KeyError:
            if legacy_id:
                try:
                    conf, data = self._current.discard(cls, legacy_id)
                    if data is not None:
                        self._current = conf.with_value(data, data_id)
                except KeyError:
                    pass

        if data is None:
            # Return a default value.
            if isinstance(default, type) and issubclass(default, Exception):
                raise default(data_id)
            elif default is not None:
                return default
            elif info.default is not None:
                return info.default
            else:
                raise KeyError(data_id)

        assert isinstance(data, cls), info
        return data

    def store_conf(self, data: Data, data_id: str = '') -> None:
        """Update the current data for this ID. """
        if type(data) not in self._registered:
            raise ValueError(f'Unregistered data type {type(data)!r}')
        self._current = self._current.with_value(data, data_id)

    def discard_conf(self, cls: type[Data], data_id: str = '') -> None:
        """Remove the specified ID."""
        if cls not in self._registered:
            raise ValueError(f'Unregistered data type {cls!r}')
        info = cls.get_conf_info()

        if data_id and not info.uses_id:
            raise ValueError(f'Data type "{info.name}" does not support IDs!')
        new_conf, popped = self._current.discard(cls, data_id)
        if self._current.discard(cls, data_id) is not None:
            LOGGER.debug('Discarding conf {}[{}]', info.name, data_id)
            self._current = new_conf

    def parse_kv1(self, kv: Keyvalues) -> tuple[Config, bool]:
        """Parse a configuration file into individual data.

        The data is in the form {conf_type: {id: data}}, and a bool indicating if it was upgraded
        and so should be resaved.
        """
        if 'version' not in kv:  # New conf format
            return self._parse_legacy(kv), True

        version = kv.int('version')
        if version != 1:
            raise ValueError(f'Unknown config version {version}!')

        conf = Config()
        upgraded = False
        for child in kv:
            if child.name == 'version':
                continue
            try:
                cls = self._name_to_type[child.name]
            except KeyError:
                LOGGER.warning('Unknown config section type "{}"!', child.real_name)
                continue
            info = cls.get_conf_info()
            version = child.int('_version', 1)
            try:
                del child['_version']
            except LookupError:
                pass
            if version > info.version:
                LOGGER.warning(
                    'Config section "{}" has version {}, '
                    'which is higher than the supported version ({})!',
                    info.name, version, info.version
                )
                # Don't try to parse, it'll be invalid.
                continue
            elif version != info.version:
                LOGGER.warning(
                    'Upgrading config section "{}" from {} -> {}',
                    info.name, version, info.version,
                )
                upgraded = True
            data_map = conf.get_or_blank(cls)
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

    def _parse_legacy(self, kv: Keyvalues) -> Config:
        """Parse the old config format."""
        conf = Config({})
        # Convert legacy configs.
        for cls in self._name_to_type.values():
            info = cls.get_conf_info()
            if hasattr(cls, 'parse_legacy'):
                new = cls.parse_legacy(kv)
                conf.overwrite(cls, new)
                LOGGER.info('Converted legacy {} to {}', info.name, new)
            else:
                LOGGER.warning('No legacy conf for "{}"!', info.name)
                conf.overwrite(cls, {})
        return conf

    def parse_dmx(self, dmx: Element, fmt_name: str, fmt_version: int) -> tuple[Config, bool]:
        """Parse a configuration file in the DMX format into individual data.

        * The format name and version parsed from the DMX file should also be supplied.
        * The new config is returned, alongside a bool indicating if it was upgraded
        and so should be resaved.
        """
        if fmt_name != DMX_NAME or fmt_version not in [1]:
            raise ValueError(f'Unknown config {fmt_name} v{fmt_version}!')

        conf = Config()
        upgraded = False
        for attr in dmx.values():
            if attr.name == 'name' or attr.type is not DMXTypes.ELEMENT:
                continue
            try:
                cls = self._name_to_type[attr.name.casefold()]
            except KeyError:
                LOGGER.warning('Unknown config section type "{}"!', attr.name)
                continue
            info = cls.get_conf_info()
            child = attr.val_elem
            try:
                if not child.type.startswith('Conf_v'):
                    raise ValueError
                version = int(child.type.removeprefix('Conf_v'))
            except ValueError:
                LOGGER.warning('Invalid config section version "{}"', child.type)
                continue
            if version > info.version:
                LOGGER.warning(
                    'Config section "{}" has version {}, '
                    'which is higher than the supported version ({})!',
                    info.name, version, info.version
                )
                # Don't try to parse, it'll be invalid.
                continue
            elif version != info.version:
                LOGGER.warning(
                    'Upgrading config section "{}" from {} -> {}',
                    info.name, version, info.version,
                )
                upgraded = True
            data_map = conf.get_or_blank(cls)
            if info.uses_id:
                for data_attr in child.values():
                    if data_attr.name == 'name' or data_attr.type is not DMXTypes.ELEMENT:
                        continue
                    data = data_attr.val_elem
                    if data.type != 'SubConf':
                        LOGGER.warning(
                            'Invalid sub-config type "{}" for section {}',
                            data.type, info.name,
                        )
                        continue
                    try:
                        data_map[data_attr.name] = cls.parse_dmx(data, version)
                    except Exception:
                        LOGGER.warning(
                            'Failed to parse config {}[{}]:',
                            info.name, data.name,
                            exc_info=True,
                        )
            else:
                try:
                    data_map[''] = cls.parse_dmx(child, version)
                except Exception:
                    LOGGER.warning(
                        'Failed to parse config {}:',
                        info.name,
                        exc_info=True,
                    )
        return conf, upgraded

    def build_kv1(self, conf: Config) -> Iterator[Keyvalues]:
        """Build out a configuration file from some data.

        The data is in the form {conf_type: {id: data}}.
        """
        yield Keyvalues('version', '1')
        for cls, data_map in conf.items():
            if not data_map or cls not in self._registered:
                # Blank or not in our definition, don't save.
                continue
            info = cls.get_conf_info()
            kv = Keyvalues(info.name, [
                Keyvalues('_version', str(info.version)),
            ])
            if info.uses_id:
                for data_id, data in data_map.items():
                    sub_prop = data.export_kv1()
                    sub_prop.name = data_id
                    kv.append(sub_prop)
            else:
                # Must be a single '' key.
                if list(data_map.keys()) != ['']:
                    raise ValueError(
                        f'Must have a single "" key for non-id type '
                        f'"{info.name}", got:\n{data_map}'
                    )
                [data] = data_map.values()
                kv.extend(data.export_kv1())
            yield kv

    def build_dmx(self, conf: Config) -> Element:
        """Build out a configuration file from some data.

        The data is in the form {conf_type: {id: data}}.
        """
        root = Element('BEE2Config', 'DMElement')
        cls: type[Data]
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

    def read_file(self, filename: Path) -> None:
        """Read and apply the settings from disk."""
        try:
            file = filename.open(encoding='utf8')
        except FileNotFoundError:
            return
        try:
            with file:
                kv = Keyvalues.parse(file)
        except KeyValError:
            LOGGER.warning('Cannot parse {}!', filename.name, exc_info=True)
            # Try and move to a backup name, if not don't worry about it.
            try:
                filename.replace(filename.with_suffix('.err.vdf'))
            except OSError:
                pass
            return

        conf, _ = self.parse_kv1(kv)
        self._current._data = conf._data

    def write_file(self, filename: Path) -> None:
        """Write the settings to disk."""
        if self._current.is_blank():
            # We don't have any data saved, abort!
            # This could happen while parsing, for example.
            return

        kv = Keyvalues.root()
        kv.extend(self.build_kv1(self._current))
        with AtomicWriter(filename) as file:
            kv.serialise(file)


# The configuration files we use.
APP_LOC = utils.conf_location('config/config.vdf')
APP: ConfigSpec = ConfigSpec()
PALETTE: ConfigSpec = ConfigSpec()
COMPILER: ConfigSpec = ConfigSpec()


# Import submodules, so they're registered.
from config import (  # noqa: E402
    compile_pane, corridors, filters, gen_opts, item_defaults,  last_sel, palette,   # noqa: F401
    signage,  stylevar, widgets, windows,  # noqa: F401
)
