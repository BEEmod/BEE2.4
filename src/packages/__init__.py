"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
from __future__ import annotations
from typing import (
    Iterator, Mapping, NoReturn, ClassVar, Optional, Any, TYPE_CHECKING, TypeVar,
    Type, cast,
)
from typing_extensions import Self

import os
import warnings
from collections.abc import Collection, Iterable
from collections import defaultdict
from pathlib import Path

import attrs
import trio
import srctools

from BEE2_config import ConfigFile
from app import tkMarkdown, img, lazy_conf, background_run
import utils
import consts
from srctools import Keyvalues, NoKeyError
from srctools.tokenizer import TokenSyntaxError
from srctools.filesys import FileSystem, RawFileSystem, ZipFileSystem, VPKFileSystem

from app.dialogs import Dialogs
from editoritems import Item as EditorItem, Renderable, RenderableType
from corridor import CORRIDOR_COUNTS, GameMode, Direction
import srctools.logger

from transtoken import TransToken, TransTokenSource


if TYPE_CHECKING:  # Prevent circular import
    from app.gameMan import Game
    from loadScreen import LoadScreen


__all__ = [
    # Generally global.
    'OBJ_TYPES', 'PACK_CONFIG',
    'SelitemData', 'NoVPKExport',
    'LegacyCorr', 'LEGACY_CORRIDORS',
    'CLEAN_PACKAGE',
    'PakObject', 'PackagesSet', 'get_loaded_packages',
    'find_packages', 'load_packages',

    # Package objects.
    'Style', 'Item', 'StyleVar', 'Elevator', 'EditorSound', 'StyleVPK', 'Signage',
    'Skybox', 'Music', 'QuotePack', 'PackList', 'CorridorGroup', 'ConfigGroup',

    # Mainly intended for package object code.
    'ParseData', 'ExportData',
    'reraise_keyerror', 'get_config', 'set_cond_source',
    'parse_multiline_key', 'desc_parse', 'sep_values',
]

LOGGER = srctools.logger.get_logger(__name__, alias='packages')
OBJ_TYPES: dict[str, Type[PakObject]] = {}
# Maps a package ID to the matching filesystem for reading files easily.
PACKAGE_SYS: dict[str, FileSystem] = {}
PACK_CONFIG = ConfigFile('packages.cfg')


@attrs.define
class SelitemData:
    """Options which are displayed on the selector window."""
    name: TransToken  # Longer full name.
    short_name: TransToken  # Shorter name for the icon.
    auth: set[str]  # List of authors.
    icon: img.Handle | None  # Small square icon.
    large_icon: img.Handle | None  # Larger, landscape icon.
    previews: list[img.Handle]  # Full size images used for previews.
    desc: tkMarkdown.MarkdownData
    group: TransToken
    sort_key: str
    # The packages used to define this, used for debugging.
    packages: frozenset[str] = attrs.Factory(frozenset)

    @classmethod
    def parse(cls, info: Keyvalues, pack_id: str) -> SelitemData:
        """Parse from a keyvalues block."""
        auth = set(sep_values(info['authors', '']))
        name = TransToken.parse(pack_id, info['name'])
        sort_key = info['sort_key', '']
        desc = desc_parse(info, info['id'], pack_id)
        try:
            group = TransToken.parse(pack_id, info['group'])
        except LookupError:
            group = TransToken.BLANK
        try:
            short_name = TransToken.parse(pack_id, info['shortName'])
        except LookupError:
            short_name = name

        try:
            icon = img.Handle.parse(
                info.find_key('icon'),
                pack_id,
                consts.SEL_ICON_SIZE, consts.SEL_ICON_SIZE,
            )
        except LookupError:
            icon = None
        large_key: Keyvalues | None
        try:
            large_key = info.find_key('iconLarge')
        except LookupError:
            large_icon = large_key = None
        else:
            large_icon = img.Handle.parse(
                large_key,
                pack_id,
                *consts.SEL_ICON_SIZE_LRG,
            )
        try:
            preview_block = info.find_block('previews')
        except LookupError:
            # Use the large icon, if present.
            if large_key is not None:
                previews = [img.Handle.parse(
                    large_key,
                    pack_id,
                    0, 0,
                )]
            else:
                previews = []
        else:
            previews = [img.Handle.parse(
                kv,
                pack_id,
                0, 0,
            ) for kv in preview_block]

        return cls(
            name,
            short_name,
            auth,
            icon,
            large_icon,
            previews,
            desc,
            group,
            sort_key,
            frozenset({pack_id}),
        )

    def __add__(self, other: SelitemData) -> SelitemData:
        """Join together two sets of selitem data.

        This uses the over_data values if defined, using our_data if not.
        Authors and descriptions will be joined to each other.
        """
        if not isinstance(other, SelitemData):
            return NotImplemented

        return SelitemData(
            self.name,
            self.short_name,
            self.auth | other.auth,
            other.icon or self.icon,
            other.large_icon or self.large_icon,
            self.previews + other.previews,
            tkMarkdown.join(self.desc, other.desc),
            other.group or self.group,
            other.sort_key or self.sort_key,
            self.packages | other.packages,
        )

    def iter_trans_tokens(self, source: str) -> Iterator[TransTokenSource]:
        """Yield the tokens in this data."""
        yield self.name, f'{source}.long_name'
        yield self.short_name, f'{source}.short_name'
        yield self.group, f'{source}.group'
        yield from tkMarkdown.iter_tokens(self.desc, f'{source}.desc')


@attrs.define
class ObjData:
    """Temporary data stored when parsing info.txt, but before .parse() is called.

    This allows us to parse all packages before loading objects.
    """
    fsys: FileSystem
    info_block: Keyvalues = attrs.field(repr=False)
    pak_id: str
    disp_name: TransToken


@attrs.define
class ParseData:
    """The arguments for pak_object.parse()."""
    fsys: FileSystem
    id: str
    info: Keyvalues = attrs.field(repr=False)
    pak_id: str
    is_override: bool


@attrs.define
class ExportData:
    """The arguments to pak_object.export()."""
    # Usually str, but some items pass other things.
    selected: Any
    # Some items need to know which style is selected
    selected_style: Style
    all_items: list[EditorItem]  # All the items in the map
    renderables: dict[RenderableType, Renderable]  # The error/connection icons
    vbsp_conf: Keyvalues  # vbsp_config.cfg file.
    packset: PackagesSet  # The entire loaded packages set.
    game: Game  # The current game.
    # As objects export, they may fill this to include additional resources
    # to be written to the game folder. This way it can be deferred until
    # after regular resources are copied.
    resources: dict[str, bytes]


@attrs.define
class LegacyCorr:
    """Legacy definitions for each corridor in a style."""
    name: str = ''
    icon: utils.PackagePath = img.PATH_BLANK
    desc: str = ''


# Corridor enums to legacy names
LEGACY_CORRIDORS = {
    (GameMode.SP, Direction.ENTRY): 'sp_entry',
    (GameMode.SP, Direction.EXIT): 'sp_exit',
    (GameMode.COOP, Direction.EXIT): 'coop',
}

# This package contains necessary components, and must be available.
CLEAN_PACKAGE = 'BEE2_CLEAN_STYLE'.casefold()


class NoVPKExport(Exception):
    """Raised to indicate that VPK files weren't copied."""


T = TypeVar('T')
PakT = TypeVar('PakT', bound='PakObject')
style_suggest_keys: dict[str, type[PakObject]] = {}


class PakObject:
    """PackObject(allow_mult=False, has_img=True): The base class for package objects.

    In the class base list, set 'allow_mult' to True if duplicates are allowed.
    If duplicates occur, they will be treated as overrides.
    Set 'has_img' to control whether the object will count towards the images
    loading bar - this should be stepped in the UI.load_packages() method.
    Setting `needs_foreground` indicates that it is unable to load after the main UI.
    If `style_suggest_key` is set, this is the keyvalue in Style definitions containing IDs to suggest.
    `suggest_default` is then the default item to provide if none are specified.
    """
    # ID of the object
    id: str
    # ID of the package.
    pak_id: str
    # Display name of the package.
    pak_name: str
    # TODO: new export system.
    export_priority: int = 0

    _id_to_obj: ClassVar[dict[str, PakObject]]
    allow_mult: ClassVar[bool]
    needs_foreground: ClassVar[bool]
    suggest_default: ClassVar[str]

    def __init_subclass__(
        cls,
        allow_mult: bool = False,
        needs_foreground: bool = False,
        style_suggest_key: str = '',
        suggest_default: str = '<NONE>',
        export_priority: int = 0,
    ) -> None:
        super().__init_subclass__()
        OBJ_TYPES[cls.__name__.casefold()] = cls

        # Maps object IDs to the object.
        cls._id_to_obj = {}
        cls.allow_mult = allow_mult
        cls.needs_foreground = needs_foreground
        cls.export_priority = export_priority
        if style_suggest_key:
            assert style_suggest_key.casefold() not in style_suggest_keys
            style_suggest_keys[style_suggest_key.casefold()] = cls
            cls.suggest_default = suggest_default
        else:
            cls.suggest_default = ''

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Parse the package object from the info.txt block.

        ParseData is a namedtuple containing relevant info:
        - fsys, the package's FileSystem
        - id, the ID of the item
        - info, the Keyvalues block in info.txt
        - pak_id, the ID of the package
        """
        raise NotImplementedError

    def add_over(self, override: Self) -> None:
        """Called to override values.
        self is the originally defined item, and override is the override item
        to copy values from.
        """
        pass

    @staticmethod
    async def export(exp_data: ExportData) -> None:
        """Export the appropriate data into the game.

        ExportData is a namedtuple containing various data:
        - selected: The ID of the selected item (or None)
        - selected_style: The selected style object
        - editoritems: The Keyvalues block for editoritems.txt
        - vbsp_conf: The Keyvalues block for vbsp_config
        - game: The game we're exporting to.
        """
        raise NotImplementedError

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yields translation tokens in this object.

        This is used to regenerate package translation files.
        """
        return iter(())

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Do processing after all objects of this type have been fully parsed (but others may not)."""
        pass


def reraise_keyerror(err: NoKeyError | IndexError, obj_id: str) -> NoReturn:
    """Replace NoKeyErrors with a nicer one, giving the item that failed."""
    key_error: NoKeyError
    if isinstance(err, IndexError):
        if isinstance(err.__cause__, NoKeyError):
            # Keyvalues.__getitem__ raises IndexError from
            # NoKeyError, so read from the original
            key_error = err.__cause__
        else:
            # We shouldn't have caught this
            raise err
    else:
        key_error = err
    raise Exception(f'No "{key_error.key}" in {obj_id!s} object!') from err


def get_config(
    prop_block: Keyvalues,
    folder: str,
    pak_id: str,
    prop_name: str='config',
    extension: str='.cfg',
    source: str='',
) -> lazy_conf.LazyConf:
    """Lazily extract a config file referred to by the given property block.

    Looks for the prop_name key in the given prop_block.
    If the keyvalue has a value of "", an empty tree is returned.
    If it has children, a copy of them will be returned.
    Otherwise, the value is a filename in the zip which will be parsed.

    If source is supplied, set_cond_source() will be run.
    """
    prop_block = prop_block.find_key(prop_name, "")
    if prop_block.has_children():
        prop = prop_block.copy()
        prop.name = ""
        return lazy_conf.raw_prop(prop, source=source)

    if prop_block.value == '':
        return lazy_conf.BLANK

    # Zips must use '/' for the separator, even on Windows!
    path = f'{folder}/{prop_block.value}'
    if len(path) < 3 or path[-4] != '.':
        # Add extension
        path += extension
    return lazy_conf.from_file(utils.PackagePath(pak_id, path), source=f'{pak_id}:{path}')


def set_cond_source(kv: Keyvalues, source: str) -> None:
    """Set metadata for Conditions in the given config blocks.

    This generates '__src__' keyvalues in Condition blocks with info like
    the source object ID and originating file, so errors can be traced back
    to the config file creating it.
    """
    for cond in kv.find_all('Conditions', 'Condition'):
        if '__src__' not in cond:
            cond['__src__'] = source


@attrs.define
class PackagesSet:
    """Holds all the data pared from packages.

    This is swapped out to reload packages.
    """
    packages: dict[str, Package] = attrs.Factory(dict)
    # type -> id -> object
    # The object data before being parsed, and the final result.
    unparsed: dict[Type[PakObject], dict[str, ObjData]] = attrs.field(factory=dict, repr=False)
    objects: dict[Type[PakObject], dict[str, PakObject]] = attrs.Factory(dict)
    # For overrides, a type/ID pair to the list of overrides.
    overrides: dict[tuple[Type[PakObject], str], list[ParseData]] = attrs.Factory(lambda: defaultdict(list))

    # Indicates if an object type has been fully parsed.
    _type_ready: dict[Type[PakObject], trio.Event] = attrs.field(init=False, factory=dict)
    # Internal, indicates if all parse() calls were complete (but maybe not post_parse).
    _parsed: set[Type[PakObject]] = attrs.field(init=False, factory=set)

    # Whether these music files have been detected.
    has_mel_music: bool = False
    has_tag_music: bool = False

    def ready(self, cls: Type[PakObject]) -> trio.Event:
        """Return a Trio Event which is set when a specific object type is fully parsed."""
        try:
            return self._type_ready[cls]
        except KeyError:
            self._type_ready[cls] = evt = trio.Event()
            return evt

    def can_export(self) -> bool:
        """Check if we're currently able to export."""
        try:
            return all(self._type_ready[cls].is_set() for cls in OBJ_TYPES.values())
        except KeyError:
            # ready() was never called on at least one class, so it can't possibly be done yet!
            return False

    def all_obj(self, cls: Type[PakT]) -> Collection[PakT]:
        """Get the list of objects parsed."""
        if cls not in self._parsed:
            raise ValueError(cls.__name__ + ' has not been parsed yet!')
        return cast('dict[str, PakT]', self.objects[cls]).values()

    def obj_by_id(self, cls: Type[PakT], object_id: str) -> PakT:
        """Return the object with a given ID."""
        if cls not in self._parsed:
            raise ValueError(cls.__name__ + ' has not been parsed yet!')
        return cast('dict[str, PakT]', self.objects[cls])[object_id.casefold()]

    def add(self, obj: PakT, pak_id: str, pak_name: str) -> None:
        """Add an object to our dataset later, with the given package name."""
        self.objects[type(obj)][obj.id.casefold()] = obj
        if not hasattr(obj, 'pak_id'):
            obj.pak_id = pak_id
            obj.pak_name = pak_name


def get_loaded_packages() -> PackagesSet:
    """The current set of loaded packages.

    TODO: Try to make this local wherever possible?
    """
    return _LOADED

_LOADED = PackagesSet()


async def find_packages(nursery: trio.Nursery, packset: PackagesSet, pak_dir: Path) -> None:
    """Search a folder for packages, recursing if necessary."""
    found_pak = False
    try:
        contents = list(pak_dir.iterdir())
    except FileNotFoundError:
        LOGGER.warning('Package search location "{}" does not exist!', pak_dir)
        return

    for name in contents:  # Both files and dirs
        folded = name.stem.casefold()
        if folded.endswith('.vpk') and not folded.endswith('_dir.vpk'):
            # _000.vpk files, useless without the directory
            continue

        filesys: FileSystem
        if name.is_dir():
            filesys = RawFileSystem(name)
        else:
            ext = name.suffix.casefold()
            if ext in ('.bee_pack', '.zip'):
                filesys = await trio.to_thread.run_sync(ZipFileSystem, name, abandon_on_cancel=True)
            elif ext == '.vpk':
                filesys = await trio.to_thread.run_sync(VPKFileSystem, name, abandon_on_cancel=True)
            else:
                LOGGER.info('Extra file: {}', name)
                continue

        LOGGER.debug('Reading package "{}"', name)

        # Valid packages must have an info.txt file!
        try:
            info = await trio.to_thread.run_sync(filesys.read_kv1, 'info.txt', abandon_on_cancel=True)
        except FileNotFoundError:
            if name.is_dir():
                # This isn't a package, so check the subfolders too...
                LOGGER.debug('Checking subdir "{}" for packages...', name)
                nursery.start_soon(find_packages, nursery, packset, name)
            else:
                LOGGER.warning('ERROR: package "{}" has no info.txt!', name)
            # Don't continue to parse this "package"
            continue
        try:
            pak_id = info['ID']
        except LookupError:
            raise ValueError('No package ID in {}/info.txt!', filesys.path) from None

        if pak_id.casefold() in packset.packages:
            duplicate = packset.packages[pak_id.casefold()]
            raise ValueError(
                f'Duplicate package with id "{pak_id}"!\n'
                'If you just updated the mod, delete any old files in packages/.\n'
                f'Package 1: {duplicate.fsys.path}\n'
                f'Package 2: {filesys.path}'
            )

        PACKAGE_SYS[pak_id.casefold()] = filesys

        packset.packages[pak_id.casefold()] = Package(
            pak_id,
            filesys,
            info,
            name,
        )
        found_pak = True

    if not found_pak:
        LOGGER.info('No packages in folder {}!', pak_dir)


async def no_packages_err(dialog: Dialogs, pak_dirs: list[Path], msg: TransToken) -> NoReturn:
    """Show an error message indicating no packages are present."""
    import sys
    # We don't have a package directory!
    if len(pak_dirs) == 1:
        trailer = TransToken.untranslated(str((os.getcwd() / pak_dirs[0]).resolve()))
    else:
        trailer = TransToken.ui(
            'one of the following locations:\n{loc}'
        ).format(loc='\n'.join(
            f' - {(os.getcwd() / fold).resolve()}'
            for fold in pak_dirs
        ))
    message = TransToken.ui(
        '{msg}\nGet the packages from "https://github.com/BEEmod/BEE2-items" '
        'and place them in {trailer}'
    ).format(msg=msg, trailer=trailer)

    LOGGER.error(message)
    await dialog.show_info(
        title=TransToken.ui('BEE2 - Invalid Packages Directory!'),
        message=message,
        icon=dialog.ERROR,
    )
    sys.exit()


async def load_packages(
    packset: PackagesSet,
    pak_dirs: list[Path],
    loader: LoadScreen,
    dialog: Dialogs,
) -> None:
    """Scan and read in all packages."""
    async with trio.open_nursery() as find_nurs:
        for pak_dir in pak_dirs:
            find_nurs.start_soon(find_packages, find_nurs, packset, pak_dir)

    pack_count = len(packset.packages)
    loader.set_length("PAK", pack_count)

    if pack_count == 0:
        await no_packages_err(dialog, pak_dirs, TransToken.ui('No packages found!'))

    # We must have the clean style package.
    if CLEAN_PACKAGE not in packset.packages:
        await no_packages_err(dialog, pak_dirs, TransToken.ui(
            'No Clean Style package! This is required for some essential resources and objects.'
        ))

    # Ensure all objects are in the dicts.
    for obj_type in OBJ_TYPES.values():
        packset.unparsed[obj_type] = {}
        packset.objects[obj_type] = {}

    async with trio.open_nursery() as nursery:
        for pack in packset.packages.values():
            if not pack.enabled:
                LOGGER.info('Package {} disabled!', pack.id)
                pack_count -= 1
                loader.set_length("PAK", pack_count)
                continue

            nursery.start_soon(parse_package, nursery, packset, pack, loader)
        LOGGER.debug('Submitted packages.')

    LOGGER.debug('Parsed packages, now parsing objects.')

    loader.set_length("OBJ", sum(
        len(obj_map)
        for obj_type, obj_map in
        packset.unparsed.items()
        if obj_type.needs_foreground
    ))

    LOGGER.info('Object counts:\n{}', '\n'.join(
        f'{obj_type.__name__:<15}: {len(objs)}'
        for obj_type, objs in
        sorted(packset.unparsed.items(), key=lambda t: len(t[1]), reverse=True)
    ))

    # Load either now, or in background.
    async with trio.open_nursery() as nursery:
        for obj_class, objs in packset.unparsed.items():
            if obj_class.needs_foreground:
                nursery.start_soon(
                    parse_type,
                    packset, obj_class, objs, loader,
                )
            else:
                background_run(
                    parse_type,
                    packset, obj_class, objs, None,
                )


async def parse_type(packset: PackagesSet, obj_class: Type[PakT], objs: Iterable[str], loader: Optional[LoadScreen]) -> None:
    """Parse all of a specific object type."""
    async with trio.open_nursery() as nursery:
        for obj_id in objs:
            nursery.start_soon(
                parse_object,
                packset, obj_class, obj_id, loader,
            )
    LOGGER.info('Post-process {} objects...', obj_class.__name__)
    # Tricky, we want to let post_parse() call all_obj() etc, but not let other blocked tasks
    # run until post_parse finishes. So use two flags.
    # noinspection PyProtectedMember
    packset._parsed.add(obj_class)
    await obj_class.post_parse(packset)
    packset.ready(obj_class).set()


async def parse_package(
    nursery: trio.Nursery,
    packset: PackagesSet,
    pack: Package,
    loader: LoadScreen,
) -> None:
    """Parse through the given package to find all the components."""
    from packages import template_brush  # Avoid circular imports
    for pre in pack.info.find_children('Prerequisites'):
        # Special case - disable these packages when the music isn't copied.
        if pre.value == '<TAG_MUSIC>':
            if not packset.has_tag_music:
                return
        elif pre.value == '<MEL_MUSIC>':
            if not packset.has_mel_music:
                return
        elif pre.value.casefold() not in packset.packages:
            LOGGER.warning(
                'Package "{}" required for "{}" - ignoring package!',
                pre.value,  pack.id,
            )
            return

    desc: list[str] = []

    for obj in pack.info:
        await trio.sleep(0)
        if obj.name in ['prerequisites', 'id', 'name']:
            # Not object IDs.
            continue
        if obj.name in ['desc', 'description']:
            desc.extend(obj.as_array())
            continue
        if not obj.has_children():
            LOGGER.warning(
                'Unknown package option "{}" with value "{}"!',
                obj.real_name, obj.value,
            )
            continue

        if obj.name in ('templatebrush', 'brushtemplate'):
            LOGGER.warning(
                'TemplateBrush {} no longer needs to be defined in info.txt',
                obj['id', '<NO ID>'],
            )
        elif obj.name == 'transtoken':
            # Special case for now, since it's package-specific.
            parse_pack_transtoken(pack, obj)
        elif obj.name == 'overrides':
            for over_prop in obj:
                if over_prop.name in ('templatebrush', 'brushtemplate'):
                    LOGGER.warning(
                        'TemplateBrush {} no longer needs to be defined in info.txt',
                        over_prop['id', '<NO ID>'],
                    )
                    continue
                try:
                    obj_type = OBJ_TYPES[over_prop.name]
                except KeyError:
                    LOGGER.warning(
                        'Unknown object type "{}" with ID "{}"!',
                        over_prop.real_name, over_prop['id', '<NO ID>'],
                    )

                    continue
                try:
                    obj_id = over_prop['id']
                except LookupError:
                    raise ValueError(f'No ID for "{obj_type}" object type in "{pack.id}" package!') from None
                packset.overrides[obj_type, obj_id.casefold()].append(
                    ParseData(pack.fsys, obj_id, over_prop, pack.id, True)
                )
        else:
            try:
                obj_type = OBJ_TYPES[obj.name]
            except KeyError:
                LOGGER.warning(
                    'Unknown object type "{}" with ID "{}"!',
                    obj.real_name, obj['id', '<NO ID>'],
                )
                continue
            try:
                obj_id = obj['id']
            except LookupError:
                raise ValueError(f'No ID for "{obj_type}" object type in "{pack.id}" package!') from None
            if obj_id in packset.unparsed[obj_type]:
                if obj_type.allow_mult:
                    # Pretend this is an override, but don't actually set the bool.
                    packset.overrides[obj_type, obj_id.casefold()].append(
                        ParseData(pack.fsys, obj_id, obj, pack.id, False)
                    )
                    # Don't continue to parse and overwrite
                    continue
                else:
                    raise Exception(f'ERROR! "{obj_id}" defined twice!')
            packset.unparsed[obj_type][obj_id] = ObjData(
                pack.fsys,
                obj,
                pack.id,
                pack.disp_name,
            )

    if desc:
        pack.desc = TransToken.parse(pack.id, '\n'.join(desc))

    for template in pack.fsys.walk_folder('templates'):
        await trio.sleep(0)
        if template.path.casefold().endswith('.vmf'):
            nursery.start_soon(template_brush.parse_template, pack.id, template)
    loader.step('PAK', pack.id)


async def parse_object(
    packset: PackagesSet,
    obj_class: Type[PakObject], obj_id: str,
    loader: Optional[LoadScreen],
) -> None:
    """Parse through the object and store the resultant class."""
    obj_data = packset.unparsed[obj_class][obj_id]
    try:
        with srctools.logger.context(f'{obj_data.pak_id}:{obj_id}'):
            object_ = await obj_class.parse(
                ParseData(
                    obj_data.fsys,
                    obj_id,
                    obj_data.info_block,
                    obj_data.pak_id,
                    False,
                )
            )
            await trio.sleep(0)
    except (NoKeyError, IndexError) as e:
        reraise_keyerror(e, obj_id)
    except TokenSyntaxError as e:
        # Add the relevant package to the filename.
        if e.file:
            e.file = f'{obj_data.pak_id}:{e.file}'
        raise
    except Exception as e:
        raise ValueError(
            'Error occured parsing '
            f'{obj_data.pak_id}:{obj_id} item!'
        ) from e

    if not hasattr(object_, 'id'):
        raise ValueError(f'"{obj_class.__name__}" object {object_} has no ID!')
    assert object_.id == obj_id, f'{object_!r} -> {object_.id} != "{obj_id}"!'

    object_.pak_id = obj_data.pak_id
    object_.pak_name = str(obj_data.disp_name)
    for override_data in packset.overrides[obj_class, obj_id.casefold()]:
        await trio.sleep(0)
        try:
            with srctools.logger.context(f'override {override_data.pak_id}:{obj_id}'):
                override = await obj_class.parse(override_data)
        except (NoKeyError, IndexError) as e:
            reraise_keyerror(e, f'{override_data.pak_id}:{obj_id}')
        except TokenSyntaxError as e:
            # Add the relevant package to the filename.
            if e.file:
                e.file = f'{override_data.pak_id}:{e.file}'
            raise
        except Exception as e:
            raise ValueError(
                f'Error occured parsing {obj_id} override '
                f'from package {override_data.pak_id}!'
            ) from e

        await trio.sleep(0)
        object_.add_over(override)
    assert obj_id.casefold() not in packset.objects[obj_class], f'{obj_class}("{obj_id}") = {object_}'
    packset.objects[obj_class][obj_id.casefold()] = object_
    if loader is not None:
        loader.step("OBJ", obj_id)


def parse_pack_transtoken(pack: Package, kv: Keyvalues) -> None:
    """Define an additional translation token in a package."""
    try:
        obj_id = kv['id'].casefold()
    except LookupError:
        raise ValueError('No ID for "TransToken" object type!') from None
    if obj_id in pack.additional_tokens:
        raise ValueError('Duplicate translation token "{}:{}"', pack.id, obj_id)
    with srctools.logger.context(f'{pack.id}:{obj_id}'):
        token = TransToken.parse(pack.id, parse_multiline_key(kv, 'text'))

    pack.additional_tokens[obj_id] = token


class Package:
    """Represents a package."""
    id: str
    fsys: FileSystem
    info: Keyvalues
    path: Path
    disp_name: TransToken
    additional_tokens: dict[str, TransToken]
    desc: TransToken

    def __init__(
        self,
        pak_id: str,
        filesystem: FileSystem,
        info: Keyvalues,
        path: Path,
    ) -> None:
        try:
            disp_name = TransToken.parse(pak_id, info['Name'])
        except LookupError:
            LOGGER.warning('Warning: {} has no display name!', pak_id)
            disp_name = TransToken.untranslated(pak_id.lower())

        self.id = pak_id
        self.fsys = filesystem
        self.info = info
        self.path = path
        self.disp_name = disp_name
        self.additional_tokens = {}
        self.desc = TransToken.ui('No description!')  # Filled in by parse_package().

    @property
    def enabled(self) -> bool:
        """Should this package be loaded?"""
        if self.id.casefold() == CLEAN_PACKAGE:
            # The clean style package is special!
            # It must be present.
            return True

        return PACK_CONFIG.get_bool(self.id, 'Enabled', default=True)

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable the package."""
        if self.id.casefold() == CLEAN_PACKAGE:
            raise ValueError('The Clean Style package cannot be disabled!')

        PACK_CONFIG[self.id]['Enabled'] = srctools.bool_as_int(value)

    def is_stale(self, mod_time: int) -> bool:
        """Check to see if this package has been modified since the last run."""
        if isinstance(self.fsys, RawFileSystem):
            # unzipped packages are for development, so always extract.
            LOGGER.info('Need to extract resources - {} is unzipped!', self.id)
            return True

        if self.enabled:
            zip_modtime = int(self.path.stat().st_mtime)

            # If zero, it's never extracted...
            if zip_modtime != mod_time or mod_time == 0:
                LOGGER.info('Need to extract resources - {} is stale!', self.id)
                return True
        else:
            # For disabled packages, need to refresh if we were extracted.
            if mod_time != 0:
                LOGGER.info('Need to extract resources - {} was previously enabled.', self.id)
                return True
        return False

    def get_modtime(self) -> int:
        """After the cache has been extracted, set the modification dates
         in the config."""
        # Raw filesystems have no mod time. Do the same for disabled ones.
        if isinstance(self.fsys, RawFileSystem) or not self.enabled:
            return 0
        else:
            return int(self.path.stat().st_mtime)


class Style(PakObject, needs_foreground=True):
    """Represents a style, specifying the era a test was built in."""
    def __init__(
        self,
        style_id: str,
        selitem_data: SelitemData,
        items: list[EditorItem],
        renderables: dict[RenderableType, Renderable],
        suggested: dict[type[PakObject], set[str]],
        config: lazy_conf.LazyConf = lazy_conf.BLANK,
        base_style: Optional[str] = None,
        has_video: bool = True,
        vpk_name: str = '',
        legacy_corridors: Mapping[tuple[GameMode, Direction, int], LegacyCorr] = srctools.EmptyMapping,
    ) -> None:
        self.id = style_id
        self.selitem_data = selitem_data
        self.items = items
        self.renderables = renderables
        self.base_style = base_style
        # Set by post_parse() after all objects are read.
        # this is a list of this style, plus parents in order.
        self.bases: list[Style] = []
        self.suggested = suggested
        self.has_video = has_video
        self.vpk_name = vpk_name
        self.legacy_corridors: dict[tuple[GameMode, Direction, int], LegacyCorr] = {}

        for (mode, direction), length in CORRIDOR_COUNTS.items():
            if (mode, direction) not in LEGACY_CORRIDORS:
                continue
            for i in range(1, length + 1):
                try:
                    self.legacy_corridors[mode, direction, i] = legacy_corridors[mode, direction, i]
                except KeyError:
                    self.legacy_corridors[mode, direction, i] = LegacyCorr()

        self.config = config

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Parse a style definition."""
        info = data.info
        selitem_data = SelitemData.parse(info, data.pak_id)
        base = info['base', ''] or None
        has_video = srctools.conv_bool(
            info['has_video', ''],
            not data.is_override,  # Assume no video for override
        )
        vpk_name = info['vpk_name', ''].casefold()
        items: list[EditorItem]
        renderables: dict[RenderableType, Renderable]

        suggested: dict[type[PakObject], set[str]] = {
            pak_type: set()
            for pak_type in style_suggest_keys.values()
        }
        for kv in info.find_children('suggested'):
            try:
                sugg_cls = style_suggest_keys[kv.name]
            except KeyError:
                LOGGER.warning('Unknown suggestion types for style {}: {}', data.id, kv.name)
            else:
                suggested[sugg_cls].add(kv.value)

        corr_conf = info.find_key('corridors', or_blank=True)
        legacy_corridors: dict[tuple[GameMode, Direction, int], LegacyCorr] = {}

        icon_folder = corr_conf['icon_folder', '']

        for (mode, direction), length in CORRIDOR_COUNTS.items():
            try:
                group = LEGACY_CORRIDORS[mode, direction]
            except KeyError:  # Coop entry
                continue
            group_kv = corr_conf.find_key(group, or_blank=True)
            for i in range(1, length + 1):
                kv = group_kv.find_key(str(i), '')

                if icon_folder:
                    icon = utils.PackagePath(data.pak_id, f'corr/{icon_folder}/{group}/{i}.jpg')
                else:
                    icon = img.PATH_BLANK

                if kv.has_children():
                    legacy_corridors[mode, direction, i] = LegacyCorr(
                        name=kv['name', ''],
                        icon=utils.PackagePath.parse(kv['icon', icon], data.pak_id),
                        desc=kv['Desc', ''],
                    )
                else:
                    legacy_corridors[mode, direction, i] = LegacyCorr(
                        name=kv.value,
                        icon=icon,
                        desc='',
                    )
        try:
            folder = 'styles/' + info['folder']
        except LookupError:
            # It's OK for override styles to be missing their 'folder'
            # value.
            if data.is_override:
                items = []
                renderables = {}
                vbsp = lazy_conf.BLANK
            else:
                raise ValueError(f'Style "{data.id}" missing configuration folder!') from None
        else:
            with data.fsys[folder + '/items.txt'].open_str() as f:
                items, renderables = await trio.to_thread.run_sync(EditorItem.parse, f)
            vbsp = lazy_conf.from_file(
                utils.PackagePath(data.pak_id, folder + '/vbsp_config.cfg'),
                missing_ok=True,
                source=f'Style <{data.id}>',
            )

        return cls(
            style_id=data.id,
            selitem_data=selitem_data,
            items=items,
            renderables=renderables,
            config=vbsp,
            base_style=base,
            suggested=suggested,
            has_video=has_video,
            legacy_corridors=legacy_corridors,
            vpk_name=vpk_name,
        )

    def add_over(self, override: Style) -> None:
        """Add the additional commands to ourselves."""
        self.items.extend(override.items)
        self.renderables.update(override.renderables)
        self.config = lazy_conf.concat(self.config, override.config)
        self.selitem_data += override.selitem_data

        self.has_video = self.has_video or override.has_video
        # If overrides have suggested IDs, add those.
        for sugg_cls, sugg in override.suggested.items():
            self.suggested[sugg_cls].update(sugg)

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """Assign the bases lists for all styles, and set default suggested items."""
        for style in packset.all_obj(Style):
            for sugg_cls, sugg_set in style.suggested.items():
                if not sugg_set:
                    sugg_set.add(sugg_cls.suggest_default)

            base = []
            b_style = style
            while b_style is not None:
                # Recursively find all the base styles for this one.
                if b_style in base:
                    # Already hit this!
                    raise Exception(f'Loop in bases for "{b_style.id}"!')
                # Just append the style.base_style to the list,
                # until the style with that ID isn't found any more.
                base.append(b_style)
                if b_style.base_style is not None:
                    try:
                        b_style = packset.obj_by_id(cls, b_style.base_style)
                    except KeyError:
                        LOGGER.warning('Unknown style "{}"!', b_style.base_style)
                        break
                else:
                    # No more.
                    break
            style.bases = base
            LOGGER.debug('Inheritance path for {} = {}', style, style.bases)

    def __repr__(self) -> str:
        return f'<Style: {self.id}>'

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Iterate over translation tokens in the style."""
        return self.selitem_data.iter_trans_tokens('styles/' + self.id)

    @staticmethod
    async def export(exp_data: ExportData) -> None:
        """This isn't used for Styles, we do them specially."""
        pass


def parse_multiline_key(info: Keyvalues, prop_name: str, *, allow_old_format: bool=False) -> str:
    """Allow several methods for entering multi-line keyvalues.

    Any combination of the following is allowed:
    "key" "single line"
    "key" "another line"
    "key"
        {
        "" "blah"
        "" "Blah blah"
        }
    """
    has_warning = False
    lines = []
    for kv in info.find_all(prop_name):
        if kv.has_children():
            for line in kv:
                if line.name and not has_warning:
                    LOGGER.warning('Old desc format found. Keys inside the block should be ""!')
                    has_warning = True
                lines.append(line.value)
        else:
            lines.append(kv.value)
    return '\n'.join(lines)


def desc_parse(
    info: Keyvalues,
    source: str,
    pak_id: str,
    *,
    prop_name: str='description',
) -> tkMarkdown.MarkdownData:
    """Parse the description blocks, to create data which matches richTextBox.

    """
    with srctools.logger.context(source):
        token = TransToken.parse(pak_id, parse_multiline_key(info, prop_name))
    return tkMarkdown.convert(token, pak_id)


def sep_values(string: str, delimiters: Iterable[str] = ',;/') -> list[str]:
    """Split a string by a delimiter, and then strip whitespace.

    Multiple delimiter characters can be passed.
    """
    delim, *extra_del = delimiters
    if string == '':
        return []

    for extra in extra_del:
        string = string.replace(extra, delim)

    vals = string.split(delim)
    return [
        stripped for stripped in
        (val.strip() for val in vals)
        if stripped
    ]


# Load all the package object classes, registering them in the process.
from packages.item import Item
from packages.stylevar import StyleVar
from packages.elevator import Elevator
from packages.editor_sound import EditorSound
from packages.style_vpk import StyleVPK
from packages.signage import Signage
from packages.skybox import Skybox
from packages.music import Music
from packages.quote_pack import QuotePack
from packages.pack_list import PackList
from packages.corridor import CorridorGroup
from packages.widgets import ConfigGroup
