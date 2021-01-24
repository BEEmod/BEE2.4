"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
import os
import shutil
import math
from collections import defaultdict

import srctools
from app import tkMarkdown
import utils
from app.packageMan import PACK_CONFIG
from srctools import (
    Property, NoKeyError, Vec,
    VMF, Entity, Solid,
)
from srctools.filesys import FileSystem, RawFileSystem, ZipFileSystem, VPKFileSystem
import srctools.logger

from typing import (
    Union, Optional, Any, TYPE_CHECKING,
    TypeVar, Type, cast,
    Dict, List, Tuple, Set, NamedTuple, Collection,
    Iterable, Iterator,
)


# noinspection PyUnresolvedReferences
if TYPE_CHECKING:
    from app.gameMan import Game
    from app.selector_win import SelitemData
    from loadScreen import LoadScreen
    from typing import NoReturn


LOGGER = srctools.logger.get_logger(__name__)

all_obj: Dict[str, Dict[str, 'ObjData']] = {}
packages: Dict[str, 'Package'] = {}
OBJ_TYPES: Dict[str, 'ObjType'] = {}

# Maps a package ID to the matching filesystem for reading files easily.
PACKAGE_SYS: Dict[str, FileSystem] = {}

# Don't change face IDs when copying to here.
# This allows users to refer to the stuff in templates specifically.
# The combined VMF isn't to be compiled or edited outside of us, so it's fine
# to have overlapping IDs between templates.
TEMPLATE_FILE = VMF(preserve_ids=True)

# Various namedtuples to allow passing blocks of data around
# (especially to functions that only use parts.)


class ObjData(NamedTuple):
    """Temporary data stored when parsing info.txt, but before .parse() is called.

    This allows us to parse all packages before loading objects.
    """
    fsys: FileSystem
    info_block: Property
    pak_id: str
    disp_name: str


class ParseData(NamedTuple):
    """The arguments for pak_object.parse()."""
    fsys: FileSystem
    id: str
    info: Property
    pak_id: str
    is_override: bool


class ObjType(NamedTuple):
    """The values stored for OBJ_TYPES"""
    cls: Type['PakObject']
    allow_mult: bool
    has_img: bool


class ExportData(NamedTuple):
    """The arguments to pak_object.export()."""
    # Usually str, but some items pass other things.
    selected: Any
    # Some items need to know which style is selected
    selected_style: 'Style'
    editoritems: Property
    vbsp_conf: Property
    game: 'Game'


class CorrDesc(NamedTuple):
    """Name, description and icon for each corridor in a style."""
    name: str
    icon: str
    desc: str


# Corridor type to size.
CORRIDOR_COUNTS = {
    'sp_entry': 7,
    'sp_exit': 4,
    'coop': 4,
}

# This package contains necessary components, and must be available.
CLEAN_PACKAGE = 'BEE2_CLEAN_STYLE'

# Check to see if the zip contains the resources referred to by the packfile.
CHECK_PACKFILE_CORRECTNESS = False

VPK_OVERRIDE_README = """\
Files in this folder will be written to the VPK during every BEE2 export.
Use to override resources as you please.
"""


# The folder we want to copy our VPKs to.
VPK_FOLDER = {
    # The last DLC released by Valve - this is the one that we
    # overwrite with a VPK file.
    utils.STEAM_IDS['PORTAL2']: 'portal2_dlc3',
    utils.STEAM_IDS['DEST_AP']: 'portal2_dlc3',

    # This doesn't have VPK files, and is higher priority.
    utils.STEAM_IDS['APERTURE TAG']: 'portal2',
}


class SignStyle(NamedTuple):
    """Signage information for a specific style."""
    world: str
    overlay: str
    icon: str
    type: str


class NoVPKExport(Exception):
    """Raised to indicate that VPK files weren't copied."""

T = TypeVar('T')
PakT = TypeVar('PakT', bound='PakObject')


class _PakObjectMeta(type):
    def __new__(
        mcs,
        name: str,
        bases: Tuple[type, ...],
        namespace: Dict[str, Any],
        allow_mult: bool = False,
        has_img: bool = True,
    ) -> 'Type[PakObject]':
        """Adds a PakObject to the list of objects.

        Making a metaclass allows us to hook into the creation of all subclasses.
        """
        # Defer to type to create the class..
        cls = cast('Type[PakObject]', super().__new__(mcs, name, bases, namespace))

        # Only register subclasses of PakObject - those with a parent class.
        # PakObject isn't created yet so we can't directly check that.
        if bases:
            OBJ_TYPES[name] = ObjType(cls, allow_mult, has_img)

        # Maps object IDs to the object.
        cls._id_to_obj = {}

        return cls

    def __init__(
        cls,
        name: str,
        bases: Tuple[type, ...],
        namespace: Dict[str, Any],
        allow_mult: bool = False,
        has_img: bool = True,
    ) -> None:
        """We have to strip kwargs from the type() calls to prevent errors."""
        type.__init__(cls, name, bases, namespace)


class PakObject(metaclass=_PakObjectMeta):
    """PackObject(allow_mult=False, has_img=True): The base class for package objects.

    In the class base list, set 'allow_mult' to True if duplicates are allowed.
    If duplicates occur, they will be treated as overrides.
    Set 'has_img' to control whether the object will count towards the images
    loading bar - this should be stepped in the UI.load_packages() method.
    """
    # ID of the object
    id = ...  # type: str
    # ID of the package.
    pak_id = ...  # type: str
    # Display name of the package.
    pak_name = ...  # type: str

    @classmethod
    def parse(cls, data: ParseData) -> 'PakObject':
        """Parse the package object from the info.txt block.

        ParseData is a namedtuple containing relevant info:
        - fsys, the package's FileSystem
        - id, the ID of the item
        - info, the Property block in info.txt
        - pak_id, the ID of the package
        """
        raise NotImplementedError

    def add_over(self, override: 'PakObject'):
        """Called to override values.
        self is the originally defined item, and override is the override item
        to copy values from.
        """
        pass

    @staticmethod
    def export(exp_data: ExportData):
        """Export the appropriate data into the game.

        ExportData is a namedtuple containing various data:
        - selected: The ID of the selected item (or None)
        - selected_style: The selected style object
        - editoritems: The Property block for editoritems.txt
        - vbsp_conf: The Property block for vbsp_config
        - game: The game we're exporting to.
        """
        raise NotImplementedError

    @classmethod
    def post_parse(cls) -> None:
        """Do processing after all objects have been fully parsed."""
        pass

    @classmethod
    def all(cls: Type[PakT]) -> Collection[PakT]:
        """Get the list of objects parsed."""
        return cls._id_to_obj.values()

    @classmethod
    def by_id(cls: Type[PakT], object_id: str) -> PakT:
        """Return the object with a given ID."""
        return cls._id_to_obj[object_id.casefold()]


def reraise_keyerror(err: BaseException, obj_id: str) -> 'NoReturn':
    """Replace NoKeyErrors with a nicer one, giving the item that failed."""
    if isinstance(err, IndexError):
        if isinstance(err.__cause__, NoKeyError):
            # Property.__getitem__ raises IndexError from
            # NoKeyError, so read from the original
            key_error = err.__cause__
        else:
            # We shouldn't have caught this
            raise err
    else:
        key_error = err
    raise Exception(
        'No "{key}" in {id!s} object!'.format(
            key=key_error.key,
            id=obj_id,
        )
    ) from err


def get_config(
        prop_block: Property,
        fsys: FileSystem,
        folder: str,
        pak_id='',
        prop_name='config',
        extension='.cfg',
        ):
    """Extract a config file referred to by the given property block.

    Looks for the prop_name key in the given prop_block.
    If the keyvalue has a value of "", an empty tree is returned.
    If it has children, a copy of them is returned.
    Otherwise the value is a filename in the zip which will be parsed.
    """
    prop_block = prop_block.find_key(prop_name, "")
    if prop_block.has_children():
        prop = prop_block.copy()
        prop.name = None
        return prop

    if prop_block.value == '':
        return Property(None, [])

    # Zips must use '/' for the separator, even on Windows!
    path = folder + '/' + prop_block.value
    if len(path) < 3 or path[-4] != '.':
        # Add extension
        path += extension
    try:
        return fsys.read_prop(path)
    except FileNotFoundError:
        LOGGER.warning('"{id}:{path}" not in zip!', id=pak_id, path=path)
        return Property(None, [])
    except UnicodeDecodeError:
        LOGGER.exception('Unable to read "{id}:{path}"', id=pak_id, path=path)
        raise


def set_cond_source(props: Property, source: str) -> None:
    """Set metadata for Conditions in the given config blocks.

    This generates '__src__' keyvalues in Condition blocks with info like
    the source object ID and originating file, so errors can be traced back
    to the config file creating it.
    """
    for cond in props.find_all('Conditions', 'Condition'):
        cond['__src__'] = source


def find_packages(pak_dir: str) -> None:
    """Search a folder for packages, recursing if necessary."""
    found_pak = False
    for name in os.listdir(pak_dir):  # Both files and dirs
        name = os.path.join(pak_dir, name)
        folded = name.casefold()
        if folded.endswith('.vpk') and not folded.endswith('_dir.vpk'):
            # _000.vpk files, useless without the directory
            continue

        if os.path.isdir(name):
            filesys = RawFileSystem(name)
        else:
            ext = os.path.splitext(folded)[1]
            if ext in ('.bee_pack', '.zip'):
                filesys = ZipFileSystem(name)
            elif ext == '.vpk':
                filesys = VPKFileSystem(name)
            else:
                LOGGER.info('Extra file: {}', name)
                continue

        LOGGER.debug('Reading package "' + name + '"')

        # Gain a persistent hold on the filesystem's handle.
        # That means we don't need to reopen the zip files constantly.
        filesys.open_ref()

        # Valid packages must have an info.txt file!
        try:
            info = filesys.read_prop('info.txt')
        except FileNotFoundError:
            # Close the ref we've gotten, since it's not in the dict
            # it won't be done by load_packages().
            filesys.close_ref()

            if os.path.isdir(name):
                # This isn't a package, so check the subfolders too...
                LOGGER.debug('Checking subdir "{}" for packages...', name)
                find_packages(name)
            else:
                LOGGER.warning('ERROR: package "{}" has no info.txt!', name)
            # Don't continue to parse this "package"
            continue
        try:
            pak_id = info['ID']
        except IndexError:
            # Close the ref we've gotten, since it's not in the dict
            # it won't be done by load_packages().
            filesys.close_ref()
            raise

        if pak_id in packages:
            raise ValueError(
                f'Duplicate package with id "{pak_id}"!\n'
                'If you just updated the mod, delete any old files in packages/.'
            ) from None

        PACKAGE_SYS[pak_id] = filesys

        packages[pak_id] = Package(
            pak_id,
            filesys,
            info,
            name,
        )
        found_pak = True

    if not found_pak:
        LOGGER.info('No packages in folder {}!', pak_dir)


def no_packages_err(pak_dir: str, msg: str) -> 'NoReturn':
    """Show an error message indicating no packages are present."""
    from tkinter import messagebox
    import sys
    # We don't have a packages directory!
    messagebox.showerror(
        title='BEE2 - Invalid Packages Directory!',
        message=(
            '{}\nGet the packages from '
            '"http://github.com/BEEmod/BEE2-items" '
            'and place them in "{}".').format(msg, pak_dir + os.path.sep),
        # Add slash to the end to indicate it's a folder.
    )
    sys.exit()


def load_packages(
        pak_dir,
        loader: 'LoadScreen',
        log_item_fallbacks=False,
        log_missing_styles=False,
        log_missing_ent_count=False,
        log_incorrect_packfile=False,
        has_mel_music=False,
        has_tag_music=False,
        ) -> Tuple[dict, Collection[FileSystem]]:
    """Scan and read in all packages."""
    global CHECK_PACKFILE_CORRECTNESS
    pak_dir = os.path.abspath(pak_dir)

    if not os.path.isdir(pak_dir):
        no_packages_err(pak_dir, 'The given packages directory is not present!')

    Item.log_ent_count = log_missing_ent_count
    CHECK_PACKFILE_CORRECTNESS = log_incorrect_packfile

    # If we fail we want to clean up our filesystems.
    should_close_filesystems = True
    try:
        find_packages(pak_dir)

        pack_count = len(packages)
        loader.set_length("PAK", pack_count)

        if pack_count == 0:
            no_packages_err(pak_dir, 'No packages found!')

        # We must have the clean style package.
        if CLEAN_PACKAGE not in packages:
            no_packages_err(
                pak_dir,
                'No Clean Style package! This is required for some '
                'essential resources and objects.'
            )

        data: Dict[str, List[PakObject]] = {}
        obj_override: Dict[str, Dict[str, List[ParseData]]] = {}

        for obj_type in OBJ_TYPES:
            all_obj[obj_type] = {}
            obj_override[obj_type] = defaultdict(list)
            data[obj_type] = []

        for pak_id, pack in packages.items():
            if not pack.enabled:
                LOGGER.info('Package {id} disabled!', id=pak_id)
                pack_count -= 1
                loader.set_length("PAK", pack_count)
                continue

            LOGGER.info('Reading objects from "{id}"...', id=pak_id)
            parse_package(pack, obj_override, has_tag_music, has_mel_music)
            loader.step("PAK")

        loader.set_length("OBJ", sum(
            len(obj_type)
            for obj_type in
            all_obj.values()
        ))

        # The number of images we need to load is the number of objects,
        # excluding some types like Stylevars or PackLists.
        loader.set_length(
            "IMG",
            sum(
                len(all_obj[key])
                for key, opts in
                OBJ_TYPES.items()
                if opts.has_img
            )
        )

        for obj_type, objs in all_obj.items():
            for obj_id, obj_data in objs.items():
                obj_class = OBJ_TYPES[obj_type].cls
                # parse through the object and return the resultant class
                try:
                    object_ = obj_class.parse(
                        ParseData(
                            obj_data.fsys,
                            obj_id,
                            obj_data.info_block,
                            obj_data.pak_id,
                            False,
                        )
                    )
                except (NoKeyError, IndexError) as e:
                    reraise_keyerror(e, obj_id)
                    raise

                if not hasattr(object_, 'id'):
                    raise ValueError(
                        '"{}" object {} has no ID!'.format(obj_type, object_)
                    )

                # Store in this database so we can find all objects for each type.
                obj_class._id_to_obj[object_.id.casefold()] = object_

                object_.pak_id = obj_data.pak_id
                object_.pak_name = obj_data.disp_name
                for override_data in obj_override[obj_type].get(obj_id, []):
                    override = OBJ_TYPES[obj_type].cls.parse(override_data)
                    object_.add_over(override)
                data[obj_type].append(object_)
                loader.step("OBJ")

        should_close_filesystems = False
    finally:
        if should_close_filesystems:
            for sys in PACKAGE_SYS.values():
                sys.close_ref()

    LOGGER.info('Object counts:\n{}\n', '\n'.join(
        '{:<15}: {}'.format(name, len(objs))
        for name, objs in
        data.items()
    ))

    for name, obj_type in OBJ_TYPES.items():
        LOGGER.info('Post-process {} objects...', name)
        obj_type.cls.post_parse()

    LOGGER.info('Allocating styled items...')
    setup_style_tree(
        Item.all(),
        Style.all(),
        log_item_fallbacks,
        log_missing_styles,
    )
    return data, PACKAGE_SYS.values()


def parse_package(
    pack: 'Package',
    obj_override: Dict[str, Dict[str, List[ParseData]]],
    has_tag: bool=False,
    has_mel: bool=False,
) -> None:
    """Parse through the given package to find all the components."""
    for pre in Property.find_key(pack.info, 'Prerequisites', []):
        # Special case - disable these packages when the music isn't copied.
        if pre.value == '<TAG_MUSIC>':
            if not has_tag:
                return
        elif pre.value == '<MEL_MUSIC>':
            if not has_mel:
                return
        elif pre.value not in packages:
            LOGGER.warning(
                'Package "{pre}" required for "{id}" - '
                'ignoring package!',
                pre=pre.value,
                id=pack.id,
            )
            return

    # First read through all the components we have, so we can match
    # overrides to the originals
    for comp_type in OBJ_TYPES:
        allow_dupes = OBJ_TYPES[comp_type].allow_mult
        # Look for overrides
        for obj in pack.info.find_all("Overrides", comp_type):
            obj_id = obj['id']
            obj_override[comp_type][obj_id].append(
                ParseData(pack.fsys, obj_id, obj, pack.id, True)
            )

        for obj in pack.info.find_all(comp_type):
            try:
                obj_id = obj['id']
            except IndexError:
                raise ValueError('No ID for "{}" object type in "{}" package!'.format(comp_type, pack.id)) from None
            if obj_id in all_obj[comp_type]:
                if allow_dupes:
                    # Pretend this is an override
                    obj_override[comp_type][obj_id].append(
                        ParseData(pack.fsys, obj_id, obj, pack.id, True)
                    )
                    # Don't continue to parse and overwrite
                    continue
                else:
                    raise Exception('ERROR! "' + obj_id + '" defined twice!')
            all_obj[comp_type][obj_id] = ObjData(
                pack.fsys,
                obj,
                pack.id,
                pack.disp_name,
            )


def setup_style_tree(
    item_data: Iterable['Item'],
    style_data: Iterable['Style'],
    log_fallbacks,
    log_missing_styles,
):
    """Handle inheritance across item folders.

    This will guarantee that all items have a definition for each
    combination of item and version.
    The priority is:
    - Exact Match
    - Parent style
    - Grandparent (etc) style
    - First version's style
    - First style of first version
    """
    all_styles: Dict[str, Style] = {}

    for style in style_data:
        all_styles[style.id] = style

    for style in all_styles.values():
        base = []
        b_style = style
        while b_style is not None:
            # Recursively find all the base styles for this one

            if b_style in base:
                # Already hit this!
                raise Exception('Loop in bases for "{}"!'.format(b_style.id))
            base.append(b_style)
            b_style = all_styles.get(b_style.base_style, None)
            # Just append the style.base_style to the list,
            # until the style with that ID isn't found anymore.
        style.bases = base

    # All styles now have a .bases attribute, which is a list of the
    # parent styles that exist (plus the style).

    # To do inheritance, we simply copy the data to ensure all items
    # have data defined for every used style.
    for item in item_data:
        all_ver: List[Dict[str, Union[
            Dict[str, Union[UnParsedItemVariant, ItemVariant]],
            str
        ]]] = list(item.versions.values())

        # Move default version to the beginning, so it's read first.
        # that ensures it's got all styles set if we need to fallback.
        all_ver.remove(item.def_ver)
        all_ver.insert(0, item.def_ver)

        for vers in all_ver:
            # We need to repeatedly loop to handle the chains of
            # dependencies. This is a list of (style_id, UnParsed).
            to_change: List[Tuple[str, UnParsedItemVariant]] = []
            styles: Dict[str, Union[UnParsedItemVariant, ItemVariant]] = vers['styles']
            for sty_id, conf in styles.items():
                to_change.append((sty_id, conf))
                # Not done yet
                styles[sty_id] = None

            # Evaluate style lookups and modifications
            while to_change:
                # Needs to be done next loop.
                deferred = []
                # filesys = FileSystem  # The original filesystem.
                # folder = str  # If set, use the given folder from our package.
                # style = str  # Inherit from a specific style (implies folder is None)
                # config = Property  # Config for editing
                for sty_id, conf in to_change:
                    if conf.style:
                        try:
                            if ':' in conf.style:
                                ver_id, base_style_id = conf.style.split(':', 1)
                                start_data = item.versions[ver_id]['styles'][base_style_id]
                            else:
                                start_data = styles[conf.style]
                        except KeyError:
                            raise ValueError(
                                'Item {}\'s {} style referenced '
                                'invalid style "{}"'.format(
                                    item.id,
                                    sty_id,
                                    conf.style,
                                ))
                        if start_data is None:
                            # Not done yet!
                            deferred.append((sty_id, conf))
                            continue
                        # Can't have both!
                        if conf.folder:
                            raise ValueError(
                                'Item {}\'s {} style has both folder and'
                                ' style!'.format(
                                    item.id,
                                    sty_id,
                                ))
                    elif conf.folder:
                        # Just a folder ref, we can do it immediately.
                        # We know this dict should be set.
                        try:
                            start_data = item.folders[conf.filesys, conf.folder]
                        except KeyError:
                            LOGGER.info('Folders: {}', item.folders.keys())
                            raise
                    else:
                        # No source for our data!
                        raise ValueError(
                            'Item {}\'s {} style has no data source!'.format(
                                item.id,
                                sty_id,
                            ))

                    if conf.config is None:
                        styles[sty_id] = start_data.copy()
                    else:
                        styles[sty_id] = start_data.modify(
                            conf.filesys,
                            conf.config,
                            '<{}:{}.{}>'.format(item.id, vers['id'], sty_id),
                        )

                # If we defer all the styles, there must be a loop somewhere.
                # We can't resolve that!
                if len(deferred) == len(to_change):
                    raise ValueError(
                        'Loop in style references!\nNot resolved:\n' + '\n'.join(
                            '{} -> {}'.format(conf.style, sty_id)
                            for sty_id, conf in deferred
                        )
                    )
                to_change = deferred

            # Fix this reference to point to the actual value.
            vers['def_style'] = styles[vers['def_style']]

            for sty_id, style in all_styles.items():
                if sty_id in styles:
                    continue  # We already have a definition
                for base_style in style.bases:
                    if base_style.id in styles:
                        # Copy the values for the parent to the child style
                        styles[sty_id] = styles[base_style.id]
                        if log_fallbacks and not item.unstyled:
                            LOGGER.warning(
                                'Item "{item}" using parent '
                                '"{rep}" for "{style}"!',
                                item=item.id,
                                rep=base_style.id,
                                style=sty_id,
                            )
                        break
                else:
                    # No parent matches!
                    if log_missing_styles and not item.unstyled:
                        LOGGER.warning(
                            'Item "{item}" using '
                            'inappropriate style for "{style}"!',
                            item=item.id,
                            style=sty_id,
                        )

                    # If 'isolate versions' is set on the item,
                    # we never consult other versions for matching styles.
                    # There we just use our first style (Clean usually).
                    # The default version is always isolated.
                    # If not isolated, we get the version from the default
                    # version. Note the default one is computed first,
                    # so it's guaranteed to have a value.
                    styles[sty_id] = (
                        vers['def_style'] if
                        item.isolate_versions or vers['isolate']
                        else item.def_ver['styles'][sty_id]
                    )


class Package:
    """Represents a package."""
    def __init__(
            self,
            pak_id: str,
            filesystem: FileSystem,
            info: Property,
            name: str,
            ):
        disp_name = info['Name', None]
        if disp_name is None:
            LOGGER.warning('Warning: {id} has no display name!', id=pak_id)
            disp_name = pak_id.lower()

        self.id = pak_id
        self.fsys = filesystem
        self.info = info
        self.name = name
        self.disp_name = disp_name
        self.desc = info['desc', '']

    @property
    def enabled(self) -> bool:
        """Should this package be loaded?"""
        if self.id == CLEAN_PACKAGE:
            # The clean style package is special!
            # It must be present.
            return True

        return PACK_CONFIG.get_bool(self.id, 'Enabled', default=True)

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable the package."""
        if self.id == CLEAN_PACKAGE:
            raise ValueError('The Clean Style package cannot be disabled!')

        PACK_CONFIG[self.id]['Enabled'] = srctools.bool_as_int(value)

    def is_stale(self, mod_time: int):
        """Check to see if this package has been modified since the last run."""
        if isinstance(self.fsys, RawFileSystem):
            # unzipped packages are for development, so always extract.
            LOGGER.info('Need to extract resources - {} is unzipped!', self.id)
            return True

        zip_modtime = int(os.stat(self.name).st_mtime)

        # If zero, it's never extracted...
        if zip_modtime != mod_time or mod_time == 0:
            LOGGER.info('Need to extract resources - {} is stale!', self.id)
            return True
        return False

    def get_modtime(self):
        """After the cache has been extracted, set the modification dates
         in the config."""
        if isinstance(self.fsys, RawFileSystem):
            # No modification time
            return 0
        else:
            return int(os.stat(self.name).st_mtime)


class Style(PakObject):
    """Represents a style, specifying the era a test was built in."""
    def __init__(
        self,
        style_id: str,
        selitem_data: 'SelitemData',
        editor: Property,
        config=None,
        base_style: Optional[str]=None,
        suggested: Tuple[str, str, str, str]=None,
        has_video: bool=True,
        vpk_name: str='',
        corridors: Dict[Tuple[str, int], CorrDesc]=None,
    ) -> None:
        self.id = style_id
        self.selitem_data = selitem_data
        self.editor = editor
        self.base_style = base_style
        # Set by setup_style_tree() after all objects are read..
        # this is a list of this style, plus parents in order.
        self.bases = []  # type: List[Style]
        self.suggested = suggested or ('<NONE>', '<NONE>', 'SKY_BLACK', '<NONE>')
        self.has_video = has_video
        self.vpk_name = vpk_name
        self.corridors = {}

        for group, length in CORRIDOR_COUNTS.items():
            for i in range(1, length + 1):
                try:
                    self.corridors[group, i] = corridors[group, i]
                except KeyError:
                    self.corridors[group, i] = CorrDesc('', '', '')

        if config is None:
            self.config = Property(None, [])
        else:
            self.config = config

        set_cond_source(self.config, 'Style <{}>'.format(style_id))

    @classmethod
    def parse(cls, data: ParseData):
        """Parse a style definition."""
        info = data.info  # type: Property
        filesystem = data.fsys  # type: FileSystem
        selitem_data = get_selitem_data(info)
        base = info['base', '']
        has_video = srctools.conv_bool(
            info['has_video', ''],
            not data.is_override,  # Assume no video for override
        )
        vpk_name = info['vpk_name', ''].casefold()

        sugg = info.find_key('suggested', [])
        if data.is_override:
            # For overrides, we default to no suggestion..
            sugg = (
                sugg['quote', ''],
                sugg['music', ''],
                sugg['skybox', ''],
                sugg['elev', ''],
            )
        else:
            sugg = (
                sugg['quote', '<NONE>'],
                sugg['music', '<NONE>'],
                sugg['skybox', 'SKY_BLACK'],
                sugg['elev', '<NONE>'],
            )

        corr_conf = info.find_key('corridors', [])
        corridors = {}

        icon_folder = corr_conf['icon_folder', '']

        for group, length in CORRIDOR_COUNTS.items():
            group_prop = corr_conf.find_key(group, [])
            for i in range(1, length + 1):
                prop = group_prop.find_key(str(i), '')  # type: Property

                if icon_folder:
                    icon = '{}/{}/{}.jpg'.format(icon_folder, group, i)
                    # If this doesn't actually exist, don't use this.
                    if 'resources/bee2/corr/' + icon not in data.fsys:
                        LOGGER.debug('No "resources/bee2/{}"!', icon)
                        icon = ''
                else:
                    icon = ''

                if prop.has_children():
                    corridors[group, i] = CorrDesc(
                        name=prop['name', ''],
                        icon=prop['icon', icon],
                        desc=prop['Desc', ''],
                    )
                else:
                    corridors[group, i] = CorrDesc(
                        name=prop.value,
                        icon=icon,
                        desc='',
                    )

        if base == '':
            base = None
        try:
            folder = 'styles/' + info['folder']
        except IndexError:
            # It's OK for override styles to be missing their 'folder'
            # value.
            if data.is_override:
                items = Property(None, [])
                vbsp = None
            else:
                raise ValueError('Style missing configuration!')
        else:
            with filesystem:
                items = filesystem.read_prop(folder + '/items.txt')
                try:
                    vbsp = filesystem.read_prop(folder + '/vbsp_config.cfg')
                except FileNotFoundError:
                    vbsp = None

        return cls(
            style_id=data.id,
            selitem_data=selitem_data,
            editor=items,
            config=vbsp,
            base_style=base,
            suggested=sugg,
            has_video=has_video,
            corridors=corridors,
            vpk_name=vpk_name,
        )

    def add_over(self, override: 'Style') -> None:
        """Add the additional commands to ourselves."""
        self.editor.append(override.editor)
        self.config.append(override.config)
        self.selitem_data = join_selitem_data(
            self.selitem_data,
            override.selitem_data
        )

        self.has_video = self.has_video or override.has_video
        # If overrides have suggested IDs, use those. Unset values = ''.
        self.suggested = tuple(
            over_sugg or self_sugg
            for self_sugg, over_sugg in
            zip(self.suggested, override.suggested)
        )

    def __repr__(self) -> str:
        return f'<Style: {self.id}>'

    def export(self) -> Tuple[Property, Property]:
        """Export this style, returning the vbsp_config and editoritems.

        This is a special case, since styles should go first in the lists.
        """
        vbsp_config = Property(None, [])

        # Editoritems.txt is composed of a "ItemData" block, holding "Item" and
        # "Renderables" sections.

        editoritems = Property("ItemData", [])

        # Only add the actual Item blocks,
        # Renderables is added in gameMan specially.
        # It must come last.
        editoritems += self.editor.copy().find_all("Item")
        vbsp_config += self.config.copy()

        return editoritems, vbsp_config


class QuotePack(PakObject):
    """Adds lists of voice lines which are automatically chosen."""
    def __init__(
        self,
        quote_id,
        selitem_data: 'SelitemData',
        config: Property,
        chars: Optional[Set[str]]=None,
        skin: Optional[int]=None,
        studio: str=None,
        studio_actor: str='',
        cam_loc: Vec=None,
        turret_hate: bool=False,
        interrupt: float=0.0,
        cam_pitch: float=0.0,
        cam_yaw: float=0.0,
    ) -> None:
        self.id = quote_id
        self.selitem_data = selitem_data
        self.cave_skin = skin
        self.config = config
        set_cond_source(config, 'QuotePack <{}>'.format(quote_id))
        self.chars = chars or {'??'}
        self.studio = studio
        self.studio_actor = studio_actor
        self.cam_loc = cam_loc
        self.inter_chance = interrupt
        self.cam_pitch = cam_pitch
        self.cam_yaw = cam_yaw
        self.turret_hate = turret_hate

    @classmethod
    def parse(cls, data: ParseData) -> 'QuotePack':
        """Parse a voice line definition."""
        selitem_data = get_selitem_data(data.info)
        chars = {
            char.strip()
            for char in
            data.info['characters', ''].split(',')
            if char.strip()
        }

        # For Cave Johnson voicelines, this indicates what skin to use on the
        # portrait.
        port_skin = srctools.conv_int(data.info['caveSkin', None], None)

        try:
            monitor_data = data.info.find_key('monitor')
        except NoKeyError:
            mon_studio = mon_cam_loc = None
            mon_interrupt = mon_cam_pitch = mon_cam_yaw = 0
            mon_studio_actor = ''
            turret_hate = False
        else:
            mon_studio = monitor_data['studio']
            mon_studio_actor = monitor_data['studio_actor', '']
            mon_interrupt = monitor_data.float('interrupt_chance', 0)
            mon_cam_loc = monitor_data.vec('Cam_loc')
            mon_cam_pitch, mon_cam_yaw, _ = monitor_data.vec('Cam_angles')
            turret_hate = monitor_data.bool('TurretShoot')

        config = get_config(
            data.info,
            data.fsys,
            'voice',
            pak_id=data.pak_id,
            prop_name='file',
        )

        return cls(
            data.id,
            selitem_data,
            config,
            chars=chars,
            skin=port_skin,
            studio=mon_studio,
            studio_actor=mon_studio_actor,
            interrupt=mon_interrupt,
            cam_loc=mon_cam_loc,
            cam_pitch=mon_cam_pitch,
            cam_yaw=mon_cam_yaw,
            turret_hate=turret_hate,
            )

    def add_over(self, override: 'QuotePack'):
        """Add the additional lines to ourselves."""
        self.selitem_data = join_selitem_data(
            self.selitem_data,
            override.selitem_data
        )
        self.config += override.config
        self.config.merge_children(
            'quotes_sp',
            'quotes_coop',
        )
        if self.cave_skin is None:
            self.cave_skin = override.cave_skin

        if self.studio is None:
            self.studio = override.studio
            self.studio_actor = override.studio_actor
            self.cam_loc = override.cam_loc
            self.inter_chance = override.inter_chance
            self.cam_pitch = override.cam_pitch
            self.cam_yaw = override.cam_yaw
            self.turret_hate = override.turret_hate

    def __repr__(self) -> str:
        return '<Voice:' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export the quotepack."""
        if exp_data.selected is None:
            return  # No quote pack!

        try:
            voice = QuotePack.by_id(exp_data.selected)  # type: QuotePack
        except KeyError:
            raise Exception(
                "Selected voice ({}) doesn't exist?".format(exp_data.selected)
            ) from None

        vbsp_config = exp_data.vbsp_conf  # type: Property

        # We want to strip 'trans' sections from the voice pack, since
        # they're not useful.
        for prop in voice.config:
            if prop.name == 'quotes':
                vbsp_config.append(QuotePack.strip_quote_data(prop))
            else:
                vbsp_config.append(prop.copy())

        # Set values in vbsp_config, so flags can determine which voiceline
        # is selected.
        options = vbsp_config.ensure_exists('Options')

        options['voice_pack'] = voice.id
        options['voice_char'] = ','.join(voice.chars)

        if voice.cave_skin is not None:
            options['cave_port_skin'] = str(voice.cave_skin)

        if voice.studio is not None:
            options['voice_studio_inst'] = voice.studio
            options['voice_studio_actor'] = voice.studio_actor
            options['voice_studio_inter_chance'] = str(voice.inter_chance)
            options['voice_studio_cam_loc'] = voice.cam_loc.join(' ')
            options['voice_studio_cam_pitch'] = str(voice.cam_pitch)
            options['voice_studio_cam_yaw'] = str(voice.cam_yaw)
            options['voice_studio_should_shoot'] = srctools.bool_as_int(voice.turret_hate)

        # Copy the config files for this voiceline..
        for prefix, pretty in [
                ('', 'normal'),
                ('mid_', 'MidChamber'),
                ('resp_', 'Responses')]:
            path = utils.conf_location('config/voice/') / (prefix.upper() + voice.id + '.cfg')
            LOGGER.info('Voice conf path: {}', path)
            if path.is_file():
                shutil.copy(
                    str(path),
                    exp_data.game.abs_path(
                        'bin/bee2/{}voice.cfg'.format(prefix)
                    )
                )
                LOGGER.info('Written "{}voice.cfg"', prefix)
            else:
                LOGGER.info('No {} voice config!', pretty)

    @staticmethod
    def strip_quote_data(prop: Property, _depth=0) -> Property:
        """Strip unused property blocks from the config files.

        This removes data like the captions which the compiler doesn't need.
        The returned property tree is a deep-copy of the original.
        """
        children = []
        for sub_prop in prop:
            # Make sure it's in the right nesting depth - flags might
            # have arbitrary props in lower depths..
            if _depth == 3:  # 'Line' blocks
                if sub_prop.name == 'trans':
                    continue
                elif sub_prop.name == 'name' and 'id' in prop:
                    continue  # The name isn't needed if an ID is available
            elif _depth == 2 and sub_prop.name == 'name':
                # In the "quote" section, the name isn't used in the compiler.
                continue

            if sub_prop.has_children():
                children.append(QuotePack.strip_quote_data(sub_prop, _depth + 1))
            else:
                children.append(Property(sub_prop.real_name, sub_prop.value))
        return Property(prop.real_name, children)

    @classmethod
    def post_parse(cls) -> None:
        """Verify no quote packs have duplicate IDs."""

        def iter_lines(conf: Property) -> Iterator[Property]:
            """Iterate over the varios line blocks."""
            yield from conf.find_all("Quotes", "Group", "Quote", "Line")

            yield from conf.find_all("Quotes", "Midchamber", "Quote", "Line")

            for group in conf.find_children("Quotes", "CoopResponses"):
                if group.has_children():
                    yield from group

        for voice in cls.all():
            used: Set[str] = set()
            for quote in iter_lines(voice.config):
                try:
                    quote_id = quote['id']
                except LookupError:
                    quote_id = quote['name', '']
                    LOGGER.warning(
                        'Quote Pack "{}" has no specific ID for "{}"!',
                        voice.id, quote_id,
                    )
                if quote_id in used:
                    LOGGER.warning(
                        'Quote Pack "{}" has duplicate '
                        'voice ID "{}"!', voice.id, quote_id,
                    )
                used.add(quote_id)


class PackList(PakObject, allow_mult=True, has_img=False):
    """Specifies a group of resources which can be packed together."""
    def __init__(self, pak_id: str, files: List[str]) -> None:
        self.id = pak_id
        self.files = files

    @classmethod
    def parse(cls, data: ParseData) -> 'PackList':
        """Read pack lists from packages."""
        filesystem = data.fsys  # type: FileSystem
        conf = data.info.find_key('Config', '')

        if 'AddIfMat' in data.info:
            LOGGER.warning(
                '{}:{}: AddIfMat is no '
                'longer used.',
                data.pak_id,
                data.id,
            )

        files = []

        if conf.has_children():
            # Allow having a child block to define packlists inline
            files = [
                prop.value
                for prop in conf
            ]
        elif conf.value:
            path = 'pack/' + conf.value + '.cfg'
            with filesystem, filesystem.open_str(path) as f:
                # Each line is a file to pack.
                # Skip blank lines, strip whitespace, and
                # allow // comments.
                for line in f:
                    line = srctools.clean_line(line)
                    if line:
                        files.append(line)

        # Deprecated old option.
        for prop in data.info.find_all('AddIfMat'):
            files.append('materials/' + prop.value + '.vmt')

        if not files:
            raise ValueError('"{}" has no files to pack!'.format(data.id))

        if CHECK_PACKFILE_CORRECTNESS:
            # Use normpath so sep differences are ignored, plus case.
            resources = {
                os.path.normpath(file.path).casefold()
                for file in
                filesystem.walk_folder('resources/')
            }
            for file in files:
                if file.startswith(('-#', 'precache_sound:')):
                    # Used to disable stock soundscripts, and precache sounds
                    # Not to pack - ignore.
                    continue

                file = file.lstrip('#')  # This means to put in soundscript too...

                #  Check to make sure the files exist...
                file = os.path.join('resources', os.path.normpath(file)).casefold()
                if file not in resources:
                    LOGGER.warning(
                        'Warning: "{file}" not in zip! ({pak_id})',
                        file=file,
                        pak_id=data.pak_id,
                    )

        return cls(data.id, files)

    def add_over(self, override: 'PackList') -> None:
        """Override items just append to the list of files."""
        # Don't copy over if it's already present
        for item in override.files:
            if item not in self.files:
                self.files.append(item)

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export all the packlists."""

        pack_block = Property('PackList', [])

        for pack in PackList.all():  # type: PackList
            # Build a
            # "Pack_id"
            # {
            # "File" "filename"
            # "File" "filename"
            # }
            # block for each packlist
            files = [
                Property('File', file)
                for file in
                pack.files
            ]
            pack_block.append(Property(
                pack.id,
                files,
            ))

        LOGGER.info('Writing packing list!')
        with open(exp_data.game.abs_path('bin/bee2/pack_list.cfg'), 'w') as pack_file:
            for line in pack_block.export():
                pack_file.write(line)


class BrushTemplate(PakObject, has_img=False, allow_mult=True):
    """A template brush which will be copied into the map, then retextured.

    This allows the sides of the brush to swap between wall/floor textures
    based on orientation.
    All world and detail brushes from the given VMF will be copied.
    """
    # For scaling templates, maps normals to the prefix to use in the ent.
    NORMAL_TO_NAME = {
        (0, 0, 1): 'up',
        (0, 0, -1): 'dn',
        (0, 1, 0): 'n',
        (0, -1, 0): 's',
        (1, 0, 0): 'e',
        (-1, 0, 0): 'w',
    }

    def __init__(
        self,
        temp_id: str,
        vmf_file: VMF,
        force: str=None,
        keep_brushes: bool=True,
    ) -> None:
        """Import in a BrushTemplate object.

        This copies the solids out of VMF_FILE and into TEMPLATE_FILE.
        If force is set to 'world' or 'detail', the other type will be converted.
        If keep_brushes is false brushes will be skipped (for TemplateOverlay).
        """
        self.id = temp_id
        # We don't actually store the solids here - put them in
        # the TEMPLATE_FILE VMF. That way the original VMF object can vanish.

        self.temp_world = {}
        self.temp_detail = {}

        visgroup_names = {
            vis.id: vis.name
            for vis in
            vmf_file.vis_tree
        }

        # For each template, give them a visgroup to match - that
        # makes it easier to swap between them.
        temp_visgroup_id = TEMPLATE_FILE.create_visgroup(temp_id).id

        if force.casefold() == 'detail':
            force_is_detail = True
        elif force.casefold() == 'world':
            force_is_detail = False
        else:
            force_is_detail = None

        # If we don't have anything warn people.
        has_conf_data = False

        # Parse through a config entity in the template file.
        conf_ents = list(vmf_file.by_class['bee2_template_conf'])
        if len(conf_ents) > 1:
            raise ValueError(
                'Template "{}" has multiple configuration entities!'.format(temp_id)
            )
        elif len(conf_ents) == 1:
            config = conf_ents[0]
            config_id = config['template_id']
            if config_id and temp_id:
                if config['template_id'].casefold() != temp_id.casefold():
                    raise ValueError('VMF and info.txt have different ids:\n conf = {}, info.txt = {}'.format(
                        config['template_id'],
                        temp_id,
                    ))
            # Override passed ID with the one in the VMF.
            elif config_id and not temp_id:
                self.id = temp_id = config_id
            elif not config_id:
                LOGGER.warning('"{}" has no conf ID!', temp_id)
            conf_auto_visgroup = int(srctools.conv_bool(config['detail_auto_visgroup']))
            if srctools.conv_bool(config['discard_brushes']):
                keep_brushes = False
            is_scaling = srctools.conv_bool(config['is_scaling'])
            if config['temp_type'] == 'detail':
                force_is_detail = True
            elif config['temp_type'] == 'world':
                force_is_detail = False
            # Add to the exported map as well.
            export_config = config.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
            # Remove the configs we've parsed
            for key in (
                'temp_type',
                'is_scaling',
                'discard_brushes',
                'template_id',
                'detail_auto_visgroup',
                # Not used, but might be added by Hammer.
                'origin',
                'angles',
            ):
                del export_config[key]
            # Only add if it has useful settings, and we're not a scaling
            # template.
            if export_config.keys and not is_scaling:
                TEMPLATE_FILE.add_ent(export_config)
                export_config['template_id'] = temp_id

        else:
            conf_auto_visgroup = is_scaling = False
            if not temp_id:
                raise ValueError('No template ID passed in!')
            LOGGER.warning('Template "{}" has no config entity! In a future version this will be required.', temp_id)

        if is_scaling:
            # Make a scaling template config.
            scaling_conf = TEMPLATE_FILE.create_ent(
                classname='bee2_template_scaling',
                template_id=temp_id,
            )
            scale_brush = None
            for brushes, is_detail, vis_ids in self.yield_world_detail(vmf_file):
                for brush in brushes:
                    if scale_brush is None:
                        scale_brush = brush
                    else:
                        raise ValueError(
                            'Too many brushes in scaling '
                            'template "{}"!'.format(temp_id),
                        )
            if scale_brush is None:
                raise ValueError(
                    'No brushes in scaling template "{}"!'.format(temp_id)
                )
            has_conf_data = True

            for face in scale_brush:
                try:
                    prefix = BrushTemplate.NORMAL_TO_NAME[face.normal().as_tuple()]
                except KeyError:
                    raise ValueError(
                        'Non Axis-Aligned face in '
                        'scaling template "{}"!'.format(temp_id),
                    )
                scaling_conf[prefix + '_tex'] = face.mat
                scaling_conf[prefix + '_uaxis'] = face.uaxis
                scaling_conf[prefix + '_vaxis'] = face.vaxis
                scaling_conf[prefix + '_rotation'] = face.ham_rot

        elif keep_brushes:
            for brushes, is_detail, vis_ids in self.yield_world_detail(vmf_file):
                has_conf_data = True
                if force_is_detail is not None:
                    export_detail = force_is_detail
                else:
                    export_detail = is_detail
                visgroups = [
                    visgroup_names[vis_id]
                    for vis_id in
                    vis_ids
                ]
                if len(visgroups) > 1:
                    raise ValueError(
                        'Template "{}" has brush with two '
                        'visgroups! ({})'.format(temp_id, ', '.join(visgroups))
                    )
                # No visgroup = ''
                visgroup = visgroups[0] if visgroups else ''

                # Auto-visgroup puts func_detail ents in unique visgroups.
                if is_detail and not visgroup and conf_auto_visgroup:
                    visgroup = '__auto_group_{}__'.format(conf_auto_visgroup)
                    # Reuse as the unique index, >0 are True too..
                    conf_auto_visgroup += 1

                targ_dict = self.temp_detail if export_detail else self.temp_world
                try:
                    ent = targ_dict[temp_id, visgroup, export_detail]
                except KeyError:
                    ent = targ_dict[temp_id, visgroup, export_detail] = TEMPLATE_FILE.create_ent(
                        classname=(
                            'bee2_template_detail' if
                            export_detail
                            else 'bee2_template_world'
                        ),
                        template_id=temp_id,
                        visgroup=visgroup,
                    )
                ent.visgroup_ids.add(temp_visgroup_id)
                for brush in brushes:
                    ent.solids.append(
                        brush.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
                    )

        self.temp_overlays = []

        # Transfer these configuration ents over.
        conf_classes = (
            vmf_file.by_class['bee2_template_colorpicker'] |
            vmf_file.by_class['bee2_template_tilesetter']
        )
        for conf_ent in conf_classes:
            new_ent = conf_ent.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
            new_ent['template_id'] = temp_id
            new_ent['visgroups'] = ' '.join([
                visgroup_names[vis_id]
                for vis_id in
                conf_ent.visgroup_ids
            ])

            TEMPLATE_FILE.add_ent(new_ent)
            has_conf_data = True

        for overlay in vmf_file.by_class['info_overlay']:  # type: Entity
            has_conf_data = True
            visgroups = [
                visgroup_names[vis_id]
                for vis_id in
                overlay.visgroup_ids
                ]
            if len(visgroups) > 1:
                raise ValueError(
                    'Template "{}" has overlay with two '
                    'visgroups!'.format(self.id)
                )
            new_overlay = overlay.copy(
                vmf_file=TEMPLATE_FILE,
                keep_vis=False
            )
            new_overlay.visgroup_ids.add(temp_visgroup_id)
            new_overlay['template_id'] = self.id
            new_overlay['visgroup'] = visgroups[0] if visgroups else ''
            new_overlay['classname'] = 'bee2_template_overlay'
            TEMPLATE_FILE.add_ent(new_overlay)

            self.temp_overlays.append(new_overlay)

        if not has_conf_data:
            LOGGER.warning('BrushTemplate "{}" has no data!', temp_id)

    @classmethod
    def parse(cls, data: ParseData):
        """Read templates from a package."""
        file = get_config(
            prop_block=data.info,
            fsys=data.fsys,
            folder='templates',
            pak_id=data.pak_id,
            prop_name='file',
            extension='.vmf',
        )
        file = VMF.parse(file)
        return cls(
            data.id,
            file,
            force=data.info['force', ''],
            keep_brushes=srctools.conv_bool(data.info['keep_brushes', '1'], True),
        )

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Write the template VMF file."""
        # Sort the visgroup list by name, to make it easier to search through.
        TEMPLATE_FILE.vis_tree.sort(key=lambda vis: vis.name)

        # Place the config entities in a nice grid.
        for conf_class, height in (
            ('bee2_template_conf', 256),
            ('bee2_template_scaling', 256 + 16),
        ):
            conf_ents = list(TEMPLATE_FILE.by_class[conf_class])
            dist = math.floor(math.sqrt(len(conf_ents)))
            half_dist = dist / 2
            for i, ent in enumerate(conf_ents):
                ent['origin'] = Vec(
                    16 * ((i // dist) - half_dist),
                    16 * ((i % dist) - half_dist),
                    height,
                )

        path = exp_data.game.abs_path('bin/bee2/templates.vmf')
        with open(path, 'w') as temp_file:
            TEMPLATE_FILE.export(temp_file, inc_version=False)

    @staticmethod
    def yield_world_detail(vmf: VMF) -> Iterator[Tuple[List[Solid], bool, set]]:
        """Yield all world/detail solids in the map.

        This also indicates if it's a func_detail, and the visgroup IDs.
        (Those are stored in the ent for detail, and the solid for world.)
        """
        for brush in vmf.brushes:
            yield [brush], False, brush.visgroup_ids
        for ent in vmf.by_class['func_detail']:
            yield ent.solids.copy(), True, ent.visgroup_ids


def desc_parse(
    info: Property,
    desc_id: str='',
    *,
    prop_name: str='description',
) -> tkMarkdown.MarkdownData:
    """Parse the description blocks, to create data which matches richTextBox.

    """
    has_warning = False
    lines = []
    for prop in info.find_all(prop_name):
        if prop.has_children():
            for line in prop:
                if line.name and not has_warning:
                    LOGGER.warning('Old desc format: {}', desc_id)
                    has_warning = True
                lines.append(line.value)
        else:
            lines.append(prop.value)

    return tkMarkdown.convert('\n'.join(lines))


def get_selitem_data(info: Property) -> 'SelitemData':
    """Return the common data for all item types - name, author, description.
    """
    from app.selector_win import SelitemData

    auth = sep_values(info['authors', ''])
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', None]
    large_icon = info['iconlarge', None]
    group = info['group', '']
    sort_key = info['sort_key', '']
    desc = desc_parse(info, info['id'])
    if not group:
        group = None
    if not short_name:
        short_name = name

    return SelitemData(
        name,
        short_name,
        auth,
        icon,
        large_icon,
        desc,
        group,
        sort_key,
    )


def join_selitem_data(
    our_data: 'SelitemData',
    over_data: 'SelitemData'
) -> 'SelitemData':
    """Join together two sets of selitem data.

    This uses the over_data values if defined, using our_data if not.
    Authors and descriptions will be joined to each other.
    """
    from app.selector_win import SelitemData
    (
        our_name,
        our_short_name,
        our_auth,
        our_icon,
        our_large_icon,
        our_desc,
        our_group,
        our_sort_key,
    ) = our_data

    (
        over_name,
        over_short_name,
        over_auth,
        over_icon,
        over_large_icon,
        over_desc,
        over_group,
        over_sort_key,
    ) = over_data

    return SelitemData(
        our_name,
        our_short_name,
        our_auth + over_auth,
        over_icon if our_icon is None else our_icon,
        over_large_icon if our_large_icon is None else our_large_icon,
        tkMarkdown.join(our_desc, over_desc),
        over_group or our_group,
        over_sort_key or our_sort_key,
    )


def sep_values(string, delimiters=',;/'):
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

from packages.item import Item, UnParsedItemVariant, ItemVariant, ItemConfig
from packages.stylevar import StyleVar
from packages.elevator import Elevator
from packages.editor_sound import EditorSound
from packages.style_vpk import StyleVPK
from packages.music import Music

