"""Deals with storing, saving and loading configuration.

Other modules define an immutable state class, then register it with this.
They can then fetch the current state and store new state.
"""
import logging
from enum import Enum
from typing import (
    TypeVar, Callable, ClassVar, Generic, Protocol, NewType, cast,
    List, Optional, Tuple, Type, Dict,
    Awaitable, Iterator,
)

import attr
import trio
from atomicwrites import atomic_write
from srctools import KeyValError, Property, logger
from srctools.dmx import Element

import utils
from BEE2_config import GEN_OPTS


LOGGER = logger.get_logger(__name__)


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
        assert name.casefold() not in {'version', 'name'}, info  # Reserved names
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
        if child.name == 'version':
            continue
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


class AfterExport(Enum):
    """Specifies what happens after exporting."""
    NORMAL = 0  # Stay visible
    MINIMISE = 1  # Minimise to tray
    QUIT = 2  # Quit the app.


@register('Options')
@attr.frozen
class GenOptions(Data):
    """General app config options, mainly booleans. These are all changed in the options window."""
    # What to do after exporting.
    after_export: AfterExport = AfterExport.NORMAL
    launch_after_export: bool = True

    play_sounds: bool = True
    keep_win_inside: bool = True
    force_load_ontop: bool = True
    splash_stay_ontop: bool = True

    # Log window.
    show_log_win: bool = False
    log_win_level: str = 'INFO'

    # Stuff mainly for devs.
    preserve_resources: bool = False
    dev_mode: bool = False
    log_missing_ent_count: bool = False
    log_missing_styles: bool = False
    log_item_fallbacks: bool = False
    log_incorrect_packfile: bool = False
    force_all_editor_models: bool = False

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, 'GenOptions']:
        """Parse from the GEN_OPTS config file."""
        res = {
            'log_win_level': GEN_OPTS['Debug']['window_log_level']
        }
        try:
            res['after_export'] = AfterExport(GEN_OPTS.get_int(
                'General', 'after_export_action',
                0,
            ))
        except ValueError:
            res['after_export'] = AfterExport.NORMAL

        for field in gen_opts_bool:
            old_name = old_gen_opts.get(field.name, field.name)
            res[field.name] = GEN_OPTS.get_bool(
                'Debug' if old_name in old_gen_opts_debug else 'General',
                old_name,
                field.default
            )

        return {'': GenOptions(**res)}

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
        res = {}
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


# We can handle the boolean values uniformly.
old_gen_opts = {
    'launch_after_export': 'launch_game',
    'dev_mode': 'development_mode',
    'preserve_resources': 'preserve_bee2_resource_dir',
}
old_gen_opts_debug = {
    'development_mode',
    'force_all_editor_models',
    'log_incorrect_packfile',
    'log_item_fallbacks',
    'log_missing_ent_count',
    'log_missing_styles',
    'show_log_win',
}
gen_opts_bool = [
    field
    for field in attr.fields_dict(GenOptions).values()
    if field.default in (True, False)
]
