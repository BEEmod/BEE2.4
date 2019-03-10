"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
import operator
import os
import shutil
import math
import re
from collections import defaultdict
from enum import Enum

import srctools
import tkMarkdown
import utils
from packageMan import PACK_CONFIG
from srctools import (
    Property, NoKeyError,
    Vec, EmptyMapping,
    VMF, Entity, Solid,
    VPK,
)
from srctools.filesys import FileSystem, get_filesystem, RawFileSystem
import srctools.logger

from typing import (
    Union, Optional, Any, TYPE_CHECKING,
    Iterator, Iterable, Type,
    Dict, List, Tuple, NamedTuple,
    Match,
    TypeVar,
    Callable,
)


# noinspection PyUnresolvedReferences
if TYPE_CHECKING:
    from gameMan import Game
    from selectorWin import SelitemData
    from loadScreen import BaseLoadScreen


LOGGER = srctools.logger.get_logger(__name__)

all_obj = {}
obj_override = {}
packages = {}  # type: Dict[str, Package]
OBJ_TYPES = {}

# Maps a package ID to the matching filesystem for reading files easily.
PACKAGE_SYS = {}  # type: Dict[str, FileSystem]


# Don't change face IDs when copying to here.
# This allows users to refer to the stuff in templates specifically.
# The combined VMF isn't to be compiled or edited outside of us, so it's fine
# to have overlapping IDs between templates.
TEMPLATE_FILE = VMF(preserve_ids=True)

# Various namedtuples to allow passing blocks of data around
# (especially to functions that only use parts.)

# Temporary data stored when parsing info.txt, but before .parse() is called.
# This allows us to parse all packages before loading objects.
ObjData = NamedTuple('ObjData', [
    ('fsys', FileSystem),
    ('info_block', Property),
    ('pak_id', str),
    ('disp_name', str),
])
# The arguments for pak_object.parse().
ParseData = NamedTuple('ParseData', [
    ('fsys', FileSystem),
    ('id', str),
    ('info', Property),
    ('pak_id', str),
    ('is_override', bool),
])
# The values stored for OBJ_TYPES
ObjType = NamedTuple('ObjType', [
    ('cls', Type['PakObject']),
    ('allow_mult', bool),
    ('has_img', bool),
])
# The arguments to pak_object.export().
ExportData = NamedTuple('ExportData', [
    ('selected', Any),  # Usually str, but some items pass other things.
    ('selected_style', 'Style'),  # Some items need to know which style is selected
    ('editoritems', Property),
    ('vbsp_conf', Property),
    ('game', 'Game'),
])

# The desired variant for an item, before we've figured out the dependencies.
UnParsedItemVariant = NamedTuple('UnParsedItemVariant', [
    ('filesys', FileSystem),  # The original filesystem.
    ('folder', Optional[str]),  # If set, use the given folder from our package.
    ('style', Optional[str]),  # Inherit from a specific style (implies folder is None)
    ('config', Optional[Property]),  # Config for editing
])

# Name, description and icon for each corridor in a style.
CorrDesc = NamedTuple('CorrDesc', [
    ('name', str),
    ('icon', str),
    ('desc', str),
])

# Corridor type to size.
CORRIDOR_COUNTS = {
    'sp_entry': 7,
    'sp_exit': 4,
    'coop': 4,
}

# Finds names surrounded by %s
RE_PERCENT_VAR = re.compile(r'%(\w*)%')

# This package contains necessary components, and must be available.
CLEAN_PACKAGE = 'BEE2_CLEAN_STYLE'

# Check to see if the zip contains the resources referred to by the packfile.
CHECK_PACKFILE_CORRECTNESS = False

VPK_OVERRIDE_README = """\
Files in this folder will be written to the VPK during every BEE2 export.
Use to override resources as you please.
"""

# The name given to standard connections - regular input/outputs in editoritems.
CONN_NORM = 'CONNECTION_STANDARD'
CONN_FUNNEL = 'CONNECTION_TBEAM_POLARITY'


# The folder we want to copy our VPKs to.
VPK_FOLDER = {
    # The last DLC released by Valve - this is the one that we
    # overwrite with a VPK file.
    utils.STEAM_IDS['PORTAL2']: 'portal2_dlc3',
    utils.STEAM_IDS['DEST_AP']: 'portal2_dlc3',

    # This doesn't have VPK files, and is higher priority.
    utils.STEAM_IDS['APERTURE TAG']: 'portal2',
}


class MusicChannel(Enum):
    """Categories that can have music."""
    BASE = 'base'  # Main track
    TBEAM = 'tbeam'  # Funnel audio
    BOUNCE = 'BounceGel'  # Jumping on repulsion gel.
    SPEED = 'SpeedGel'  # Moving fast horizontally


class NoVPKExport(Exception):
    """Raised to indicate that VPK files weren't copied."""

T = TypeVar('T')


class _PakObjectMeta(type):
    def __new__(mcs, name, bases, namespace, allow_mult=False, has_img=True):
        """Adds a PakObject to the list of objects.

        Making a metaclass allows us to hook into the creation of all subclasses.
        """
        # Defer to type to create the class..
        cls = type.__new__(mcs, name, bases, namespace)  # type: Type[PakObject]

        # Only register subclasses of PakObject - those with a parent class.
        # PakObject isn't created yet so we can't directly check that.
        if bases:
            OBJ_TYPES[name] = ObjType(cls, allow_mult, has_img)

        # Maps object IDs to the object.
        cls._id_to_obj = {}

        return cls

    def __init__(cls, name, bases, namespace, **kwargs):
        # We have to strip kwargs from the type() calls to prevent errors.
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
    def all(cls: Type[T]) -> Iterable[T]:
        """Get the list of objects parsed."""
        return cls._id_to_obj.values()

    @classmethod
    def by_id(cls: Type[T], object_id: str) -> T:
        """Return the object with a given ID."""
        return cls._id_to_obj[object_id.casefold()]


def reraise_keyerror(err, obj_id):
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


def set_cond_source(props: Property, source: str):
    """Set metadata for Conditions in the given config blocks.

    This generates '__src__' keyvalues in Condition blocks with info like
    the source object ID and originating file, so errors can be traced back
    to the config file creating it.
    """
    for cond in props.find_all('Conditions', 'Condition'):
        cond['__src__'] = source


def find_packages(pak_dir):
    """Search a folder for packages, recursing if necessary."""
    found_pak = False
    for name in os.listdir(pak_dir):  # Both files and dirs
        name = os.path.join(pak_dir, name)
        if name.endswith('.vpk') and not name.endswith('_dir.vpk'):
            # _000.vpk files, useless without the directory
            continue

        try:
            filesys = get_filesystem(name)
        except ValueError:
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
                LOGGER.warning('ERROR: Bad package "{}"!', name)
            # Don't continue to parse this "package"
            continue
        try:
            pak_id = info['ID']
        except IndexError:
            # Close the ref we've gotten, since it's not in the dict
            # it won't be done by load_packages().
            filesys.close_ref()
            raise

        PACKAGE_SYS[pak_id] = filesys

        packages[pak_id] = Package(
            pak_id,
            filesys,
            info,
            name,
        )
        found_pak = True

    if not found_pak:
        LOGGER.debug('No packages in folder!')


def close_filesystems():
    """Close the package's filesystems.

    This means future access needs to reopen the file handle.
    """
    for sys in PACKAGE_SYS.values():
        sys.close_ref()


def no_packages_err(pak_dir, msg):
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
        loader: 'BaseLoadScreen',
        log_item_fallbacks=False,
        log_missing_styles=False,
        log_missing_ent_count=False,
        log_incorrect_packfile=False,
        has_mel_music=False,
        has_tag_music=False,
        ) -> Tuple[dict, Iterable[FileSystem]]:
    """Scan and read in all packages."""
    global LOG_ENT_COUNT, CHECK_PACKFILE_CORRECTNESS
    pak_dir = os.path.abspath(pak_dir)

    if not os.path.isdir(pak_dir):
        no_packages_err(pak_dir, 'The given packages directory is not present!')

    LOG_ENT_COUNT = log_missing_ent_count
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

        data = {}  # type: Dict[str, List[PakObject]]

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
            parse_package(pack, has_tag_music, has_mel_music)
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
                obj_class = OBJ_TYPES[obj_type].cls  # type: Type[PakObject]
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

                if not hasattr(object_, 'id'):
                    raise ValueError(
                        '"{}" object {} has no ID!'.format(obj_type, object_)
                    )

                # Store in this database so we can find all objects for each type.
                obj_class._id_to_obj[object_.id.casefold()] = object_

                object_.pak_id = obj_data.pak_id
                object_.pak_name = obj_data.disp_name
                for override_data in obj_override[obj_type].get(obj_id, []):
                    override = OBJ_TYPES[obj_type].cls.parse(
                        override_data
                    )
                    object_.add_over(override)
                data[obj_type].append(object_)
                loader.step("OBJ")

        should_close_filesystems = False
    finally:
        if should_close_filesystems:
            close_filesystems()

    LOGGER.info('Object counts:\n{}\n', '\n'.join(
        '{:<15}: {}'.format(name, len(objs))
        for name, objs in
        data.items()
    ))

    LOGGER.info('Checking music objects...')
    Music.check_objects()

    LOGGER.info('Allocating styled items...')
    setup_style_tree(
        Item.all(),
        Style.all(),
        log_item_fallbacks,
        log_missing_styles,
    )
    return data, PACKAGE_SYS.values()


def parse_package(pack: 'Package', has_tag=False, has_mel=False):
    """Parse through the given package to find all the components."""
    for pre in Property.find_key(pack.info, 'Prerequisites', []):
        # Special case - disable these packages when the music isn't copied.
        if pre.value == '<TAG_MUSIC>':
            if not has_tag:
                return 0
        elif pre.value == '<MEL_MUSIC>':
            if not has_mel:
                return 0
        elif pre.value not in packages:
            LOGGER.warning(
                'Package "{pre}" required for "{id}" - '
                'ignoring package!',
                pre=pre.value,
                id=pack.id,
            )
            return 0

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
    all_styles = {}  # type: Dict[str, Style]

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
        all_ver = list(item.versions.values())  # type: List[Dict[str, Union[Dict[str, Style], str]]]
        # Move default version to the beginning, so it's read first.
        # that ensures it's got all styles set if we need to fallback.
        all_ver.remove(item.def_ver)
        all_ver.insert(0, item.def_ver)

        for vers in all_ver:
            # We need to repeatedly loop to handle the chains of
            # dependencies. This is a list of (style_id, UnParsed).
            to_change = []  # type: List[Tuple[str, UnParsedItemVariant]]
            styles = vers['styles']  # type:  Dict[str, Union[UnParsedItemVariant, ItemVariant]]
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


def parse_item_folder(
    folders: Dict[str, Union['ItemVariant', UnParsedItemVariant]],
    filesystem: FileSystem,
    pak_id: str,
):
    """Parse through the data in item/ folders.

    folders is a dict, with the keys set to the folder names we want.
    The values will be filled in with itemVariant values
    """
    for fold in folders:
        prop_path = 'items/' + fold + '/properties.txt'
        editor_path = 'items/' + fold + '/editoritems.txt'
        config_path = 'items/' + fold + '/vbsp_config.cfg'
        try:
            with filesystem:
                props = filesystem.read_prop(prop_path).find_key('Properties')
                editor = filesystem.read_prop(editor_path)
        except FileNotFoundError as err:
            raise IOError(
                '"' + pak_id + ':items/' + fold + '" not valid!'
                'Folder likely missing! '
            ) from err

        try:
            editoritems, *editor_extra = Property.find_all(editor, 'Item')
        except ValueError:
            raise ValueError(
                '"{}:items/{}/editoritems.txt has no '
                '"Item" block!'.format(pak_id, fold)
            )

        # editor_extra is any extra blocks (offset catchers, extent items).
        # These must not have a palette section - it'll override any the user
        # chooses.
        for item_block in editor_extra:  # type: Property
            for subtype in item_block.find_all('Editor', 'SubType'):
                while 'palette' in subtype:
                    LOGGER.warning(
                        '"{}:items/{}/editoritems.txt has palette set for extra'
                        ' item blocks. Deleting.'.format(pak_id, fold)
                    )
                    del subtype['palette']

        folders[fold] = ItemVariant(
            editoritems=editoritems,
            editor_extra=editor_extra,

            # Add the folder the item definition comes from,
            # so we can trace it later for debug messages.
            source='<{}>/items/{}'.format(pak_id, fold),
            vbsp_config=Property(None, []),

            authors=sep_values(props['authors', '']),
            tags=sep_values(props['tags', '']),
            desc=desc_parse(props, pak_id + ':' + prop_path),
            ent_count=props['ent_count', ''],
            url=props['infoURL', None],
            icons={
                p.name: p.value
                for p in
                props['icon', []]
            },
            all_name=props['all_name', None],
            all_icon=props['all_icon', None],
        )

        if LOG_ENT_COUNT and not folders[fold].ent_count:
            LOGGER.warning(
                '"{id}:{path}" has missing entity count!',
                id=pak_id,
                path=prop_path,
            )

        # If we have at least 1, but not all of the grouping icon
        # definitions then notify the author.
        num_group_parts = (
            (folders[fold].all_name is not None)
            + (folders[fold].all_icon is not None)
            + ('all' in folders[fold].icons)
        )
        if 0 < num_group_parts < 3:
            LOGGER.warning(
                'Warning: "{id}:{path}" has incomplete grouping icon '
                'definition!',
                id=pak_id,
                path=prop_path,
            )
        try:
            with filesystem:
                folders[fold].vbsp_config = conf = filesystem.read_prop(
                    config_path,
                )
        except FileNotFoundError:
            folders[fold].vbsp_config = conf = Property(None, [])

        set_cond_source(conf, folders[fold].source)


def apply_replacements(conf: Property) -> Property:
    """Apply a set of replacement values to a config file, returning a new copy.

    The replacements are found in a 'Replacements' block in the property.
    These replace %values% starting and ending with percents. A double-percent
    allows literal percents. Unassigned values are an error.
    """
    replace = {}
    new_conf = Property(conf.real_name, [])

    # Strip the replacement blocks from the config, and save the values.
    for prop in conf:
        if prop.name == 'replacements':
            for rep_prop in prop:
                replace[rep_prop.name.strip('%')] = rep_prop.value
        else:
            new_conf.append(prop)

    def rep_func(match: Match):
        """Does the replacement."""
        var = match.group(1)
        if not var:  # %% becomes %.
            return '%'
        try:
            return replace[var.casefold()]
        except KeyError:
            raise ValueError('Unresolved variable: {!r}\n{}'.format(var, replace))

    for prop in new_conf.iter_tree(blocks=True):
        prop.name = RE_PERCENT_VAR.sub(rep_func, prop.real_name)
        if not prop.has_children():
            prop.value = RE_PERCENT_VAR.sub(rep_func, prop.value)

    return new_conf


class ItemVariant:
    """Data required for an item in a particular style."""

    def __init__(
        self,
        editoritems: Property,
        vbsp_config: Property,
        editor_extra: Iterable[Property],
        authors: List[str],
        tags: List[str],
        desc: tkMarkdown.MarkdownData,
        icons: Dict[str, str],
        ent_count: str='',
        url: str = None,
        all_name: str=None,
        all_icon: str=None,
        source: str='',
    ):
        self.editor = editoritems
        self.editor_extra = Property(None, list(editor_extra))
        self.vbsp_config = vbsp_config
        self.source = source  # Original location of configs

        self.authors = authors
        self.tags = tags
        self.desc = desc
        self.icons = icons
        self.ent_count = ent_count
        self.url = url

        # The name and VTF for grouped items
        self.all_name = all_name
        self.all_icon = all_icon

    def copy(self) -> 'ItemVariant':
        """Make a copy of all the data."""
        return ItemVariant(
            self.editor.copy(),
            self.vbsp_config.copy(),
            self.editor_extra.copy(),
            self.authors.copy(),
            self.tags.copy(),
            self.desc.copy(),
            self.icons.copy(),
            self.ent_count,
            self.url,
            self.all_name,
            self.all_icon,
            self.source,
        )

    def can_group(self) -> bool:
        """Does this variant have the data needed to group?"""
        return (
            self.all_icon is not None and
            self.all_name is not None
        )

    def override_from_folder(self, other: 'ItemVariant') -> None:
        """Perform the override from another item folder."""
        self.authors.extend(other.authors)
        self.tags.extend(self.tags)
        self.vbsp_config += other.vbsp_config
        self.desc = tkMarkdown.join(self.desc, other.desc)

    def modify(self, fsys: FileSystem, props: Property, source: str) -> 'ItemVariant':
        """Apply a config to this item variant.

        This produces a copy with various modifications - switching
        out palette or instance values, changing the config, etc.
        """
        if 'config' in props:
            # Item.parse() has resolved this to the actual config.
            vbsp_config = get_config(
                props,
                fsys,
                'items',
                pak_id=fsys.path,
            )
        else:
            vbsp_config = self.vbsp_config.copy()

        if 'replace' in props:
            # Replace property values in the config via regex.
            replace_vals = [
                (re.compile(prop.real_name, re.IGNORECASE), prop.value)
                for prop in
                props.find_children('Replace')
            ]
            for prop in vbsp_config.iter_tree():
                for regex, sub in replace_vals:
                    prop.name = regex.sub(sub, prop.real_name)
                    prop.value = regex.sub(sub, prop.value)

        vbsp_config += list(get_config(
            props,
            fsys,
            'items',
            prop_name='append',
            pak_id=fsys.path,
        ))

        if 'description' in props:
            desc = desc_parse(props, source)
        else:
            desc = self.desc.copy()

        if 'appenddesc' in props:
            desc = tkMarkdown.join(
                desc,
                desc_parse(props, source, prop_name='appenddesc'),
            )

        if 'authors' in props:
            authors = sep_values(props['authors', ''])
        else:
            authors = self.authors

        if 'tags' in props:
            tags = sep_values(props['tags', ''])
        else:
            tags = self.tags.copy()

        variant = ItemVariant(
            self.editor.copy(),
            vbsp_config,
            self.editor_extra.copy(),
            authors=authors,
            tags=tags,
            desc=desc,
            icons=self.icons.copy(),
            ent_count=props['ent_count', self.ent_count],
            url=props['url', self.url],
            all_name=self.all_name,
            all_icon=self.all_icon,
            source='{} from {}'.format(source, self.source),
        )
        variant._modify_editoritems(props, Property('', [variant.editor]), source)
        if 'Item' in variant.editor_extra and 'extra' in props:
            variant._modify_editoritems(
                props.find_key('extra'),
                variant.editor_extra,
                source,
            )

        return variant

    def _modify_editoritems(
        self,
        props: Property,
        editor: Property,
        source: str,
    ) -> None:
        """Modify either the base or extra editoritems block."""
        is_extra = editor is self.editor_extra

        subtypes = list(editor.find_all('Item', 'Editor', 'SubType'))

        # Implement overriding palette items
        for item in props.find_children('Palette'):
            pal_icon = item['icon', None]
            pal_name = item['pal_name', None]  # Name for the palette icon
            bee2_icon = item['bee2', None]

            if item.name == 'all':
                if is_extra:
                    raise Exception(
                        'Cannot specify "all" for hidden '
                        'editoritems blocks in {}!'.format(source)
                    )
                else:
                    if pal_icon:
                        self.all_icon = pal_icon
                    if pal_name:
                        self.all_name = pal_name
                    if bee2_icon:
                        self.icons['all'] = bee2_icon
                continue

            try:
                subtype = subtypes[int(item.name)]
            except (IndexError, ValueError, TypeError):
                raise Exception(
                    'Invalid index "{}" when modifying '
                    'editoritems for {}'.format(item.name, source)
                )

            # Overriding model data.
            models = []
            for prop in item:
                if prop.name in ('models', 'model'):
                    if prop.has_children():
                        models.extend([subprop.value for subprop in prop])
                    else:
                        models.append(prop.value)
            if models:
                while 'model' in subtype:
                    del subtype['model']
                for model in models:
                    subtype.append(Property('Model', [
                        Property('ModelName', model),
                    ]))

            if item['name', None]:
                subtype['name'] = item['name']  # Name for the subtype

            if bee2_icon:
                if is_extra:
                    raise Exception(
                        'Cannot specify BEE2 icons for hidden '
                        'editoritems blocks in {}!'.format(source)
                    )
                else:
                    self.icons[item.name] = bee2_icon

            if pal_name or pal_icon:
                palette = subtype.ensure_exists('Palette')
                if pal_name:
                    palette['Tooltip'] = pal_name
                if pal_icon:
                    palette['Image'] = pal_icon

        # Allow overriding the instance blocks, only for the first in extras.
        exporting = editor.find_key('Item').ensure_exists('Exporting')

        instances = exporting.ensure_exists('Instances')
        inst_children = {
            self._inst_block_key(prop): prop
            for prop in
            instances
        }
        instances.clear()

        for inst in props.find_children('Instances'):
            try:
                del inst_children[self._inst_block_key(inst)]
            except KeyError:
                pass
            if inst.has_children():
                inst_children[self._inst_block_key(inst)] = inst.copy()
            else:
                # Shortcut to just create the property
                inst_children[self._inst_block_key(inst)] = Property(
                    inst.real_name,
                    [Property('Name', inst.value)],
                )
        for key, prop in sorted(inst_children.items(), key=operator.itemgetter(0)):
            instances.append(prop)

        # Override IO commands.
        if 'IOConf' in props:
            for io_block in exporting:
                if io_block.name not in ('outputs', 'inputs'):
                    continue
                while 'bee2' in io_block:
                    del io_block['bee2']

            io_conf = props.find_key('IOConf')
            io_conf.name = 'BEE2'
            exporting.ensure_exists('Inputs').append(io_conf)

    @staticmethod
    def _inst_block_key(prop: Property):
        """Sort function for the instance blocks.
        
        String values come first, then all numeric ones in order.
        """
        if prop.real_name.isdecimal():
            return 0, int(prop.real_name)
        else:
            return 1, prop.real_name


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
    def enabled(self):
        """Should this package be loaded?"""
        if self.id == CLEAN_PACKAGE:
            # The clean style package is special!
            # It must be present.
            return True

        return PACK_CONFIG.get_bool(self.id, 'Enabled', default=True)

    def set_enabled(self, value: bool):
        """Enable or disable the package."""
        if self.id == CLEAN_PACKAGE:
            raise ValueError('The Clean Style package cannot be disabled!')

        PACK_CONFIG[self.id]['Enabled'] = srctools.bool_as_int(value)
    enabled = enabled.setter(set_enabled)

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
        style_id,
        selitem_data: 'SelitemData',
        editor,
        config=None,
        base_style=None,
        suggested=None,
        has_video=True,
        vpk_name='',
        corridors: Dict[Tuple[str, int], CorrDesc]=None,
    ):
        self.id = style_id
        self.selitem_data = selitem_data
        self.editor = editor
        self.base_style = base_style
        # Set by setup_style_tree() after all objects are read..
        # this is a list of this style, plus parents in order.
        self.bases = []  # type: List[Style]
        self.suggested = suggested or {}
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

    def __repr__(self):
        return '<Style:' + self.id + '>'

    def export(self):
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


class Item(PakObject):
    """An item in the editor..."""
    def __init__(
            self,
            item_id,
            versions,
            def_version,
            needs_unlock=False,
            all_conf=None,
            unstyled=False,
            isolate_versions=False,
            glob_desc=(),
            desc_last=False,
            folders: Dict[Tuple[FileSystem, str], ItemVariant]=EmptyMapping,
            ):
        self.id = item_id
        self.versions = versions
        self.def_ver = def_version
        self.def_data = def_version['def_style']
        self.needs_unlock = needs_unlock
        self.all_conf = all_conf or Property(None, [])
        # If set or set on a version, don't look at the first version
        # for unstyled items.
        self.isolate_versions = isolate_versions
        self.unstyled = unstyled
        self.glob_desc = glob_desc
        self.glob_desc_last = desc_last
        # Dict of folders we need to have decoded.
        self.folders = folders

    @classmethod
    def parse(cls, data: ParseData):
        """Parse an item definition."""
        versions = {}
        def_version = None
        # The folders we parse for this - we don't want to parse the same
        # one twice. First they're set to True if we need to read them,
        # then parse_item_folder() replaces that with the actual values
        folders = {}  # type: Dict[str, Optional[ItemVariant]]
        unstyled = data.info.bool('unstyled')

        glob_desc = desc_parse(data.info, 'global:' + data.id)
        desc_last = data.info.bool('AllDescLast')

        all_config = get_config(
            data.info,
            data.fsys,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )
        set_cond_source(all_config, '<Item {} all_conf>'.format(
            data.id,
        ))

        for ver in data.info.find_all('version'):
            vals = {
                'name':    ver['name', 'Regular'],
                'id':      ver['ID', 'VER_DEFAULT'],
                'styles':  {},
                'isolate': ver.bool('isolated'),
                'def_style': None,
                }
            for style in ver.find_children('styles'):
                if style.has_children():
                    folder = UnParsedItemVariant(
                        data.fsys,
                        folder=style['folder', None],
                        style=style['Base', ''],
                        config=style,
                    )

                elif style.value.startswith('<') and style.value.endswith('>'):
                    # Reusing another style unaltered using <>.
                    folder = UnParsedItemVariant(
                        data.fsys,
                        style=style.value[1:-1],
                        folder=None,
                        config=None,
                    )
                else:
                    # Reference to the actual folder...
                    folder = UnParsedItemVariant(
                        data.fsys,
                        folder=style.value,
                        style=None,
                        config=None,
                    )
                # We need to parse the folder now if set.
                if folder.folder:
                    folders[folder.folder] = True

                # The first style is considered the 'default', and is used
                # if not otherwise present.
                # We set it to the name, then lookup later in setup_style_tree()
                if vals['def_style'] is None:
                    vals['def_style'] = style.real_name
                vals['styles'][style.real_name] = folder

                if style.real_name == folder.style:
                    raise ValueError(
                        'Item "{}"\'s "{}" style '
                        'can\'t inherit from itself!'.format(
                            data.id,
                            style.real_name,
                        ))
            versions[vals['id']] = vals

            # The first version is the 'default',
            # so non-isolated versions will fallback to it.
            # But the default is isolated itself.
            if def_version is None:
                def_version = vals
                vals['isolate'] = True

        # Fill out the folders dict with the actual data
        parse_item_folder(folders, data.fsys, data.pak_id)

        # Then copy over to the styles values
        for ver in versions.values():
            if ver['def_style'] in folders:
                ver['def_style'] = folders[ver['def_style']]
            for sty, fold in ver['styles'].items():
                if isinstance(fold, str):
                    ver['styles'][sty] = folders[fold]

        if not versions:
            raise ValueError('Item "' + data.id + '" has no versions!')

        return cls(
            data.id,
            versions=versions,
            def_version=def_version,
            needs_unlock=data.info.bool('needsUnlock'),
            isolate_versions=data.info.bool('isolate_versions'),
            all_conf=all_config,
            unstyled=unstyled,
            glob_desc=glob_desc,
            desc_last=desc_last,
            # Add filesystem to individualise this to the package.
            folders={
                (data.fsys, folder): item_variant
                for folder, item_variant in
                folders.items()
            }
        )

    def add_over(self, override: 'Item'):
        """Add the other item data to ourselves."""
        # Copy over all_conf always.
        self.all_conf += override.all_conf

        self.folders.update(override.folders)

        for ver_id, version in override.versions.items():
            if ver_id not in self.versions:
                # We don't have that version!
                self.versions[ver_id] = version
            else:
                our_ver = self.versions[ver_id]['styles']
                for sty_id, style in version['styles'].items():
                    if sty_id not in our_ver:
                        # We don't have that style!
                        our_ver[sty_id] = style
                    else:
                        raise ValueError(
                            'Two definitions for item folder {}.{}.{}',
                            self.id,
                            ver_id,
                            sty_id,
                        )
                        # our_style.override_from_folder(style)

    def __repr__(self):
        return '<Item:' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export all items into the configs.

        For the selected attribute, this takes a tuple of values:
        (pal_list, versions, prop_conf)
        Pal_list is a list of (item, subitem) tuples representing the palette.
        Versions is a {item:version_id} dictionary.
        prop_conf is a {item_id: {prop_name: value}} nested dictionary for
         overridden property names. Empty dicts can be passed instead.
        """
        editoritems = exp_data.editoritems
        vbsp_config = exp_data.vbsp_conf
        pal_list, versions, prop_conf = exp_data.selected

        style_id = exp_data.selected_style.id

        aux_item_configs = {
            conf.id: conf
            for conf in ItemConfig.all()
        }

        for item in sorted(Item.all(), key=operator.attrgetter('id')):  # type: Item
            ver_id = versions.get(item.id, 'VER_DEFAULT')

            (
                item_block,
                editor_parts,
                config_part
            ) = item._get_export_data(
                pal_list, ver_id, style_id, prop_conf,
            )
            editoritems += apply_replacements(item_block)
            editoritems += apply_replacements(editor_parts)
            vbsp_config += apply_replacements(config_part)

            # Add auxiliary configs as well.
            try:
                aux_conf = aux_item_configs[item.id]  # type: ItemConfig
            except KeyError:
                pass
            else:
                vbsp_config += apply_replacements(aux_conf.all_conf)
                try:
                    version_data = aux_conf.versions[ver_id]
                except KeyError:
                    pass  # No override.
                else:
                    # Find the first style definition for the selected one
                    # that's defined for this config
                    for poss_style in exp_data.selected_style.bases:
                        if poss_style.id in version_data:
                            vbsp_config += apply_replacements(
                                version_data[poss_style.id]
                            )
                            break

    def _get_export_data(
        self,
        pal_list,
        ver_id,
        style_id,
        prop_conf: Dict[str, Dict[str, str]],
    ) -> Tuple[Property, Property, Property]:
        """Get the data for an exported item."""

        # Build a dictionary of this item's palette positions,
        # if any exist.
        palette_items = {
            subitem: index
            for index, (item, subitem) in
            enumerate(pal_list)
            if item == self.id
        }

        item_data = self.versions[ver_id]['styles'][style_id]  # type: ItemVariant

        new_editor = item_data.editor.copy()

        new_editor['type'] = self.id  # Set the item ID to match our item
        # This allows the folders to be reused for different items if needed.

        for index, editor_section in enumerate(
                new_editor.find_all("Editor", "Subtype")):

            # For each subtype, see if it's on the palette
            for editor_sec_index, pal_section in enumerate(
                    editor_section):
                # We need to manually loop so we get the index of the palette
                # property block in the section
                if pal_section.name != "palette":
                    # Skip non-palette blocks in "SubType"
                    # (animations, sounds, model)
                    continue

                if index in palette_items:
                    icon = pal_section['Image']

                    if len(palette_items) == 1:
                        # Switch to the 'Grouped' icon and name
                        if item_data.all_name is not None:
                            pal_section['Tooltip'] = item_data.all_name

                        if item_data.all_icon is not None:
                            icon = item_data.all_icon

                    # Bug in Portal 2 - palette icons must end with '.png',
                    # so force that to be the case for all icons.
                    if icon.casefold().endswith('.vtf'):
                        icon = icon[:-3] + 'png'
                    pal_section['Image'] = icon

                    pal_section['Position'] = "{x} {y} 0".format(
                        x=palette_items[index] % 4,
                        y=palette_items[index] // 4,
                    )
                else:
                    # This subtype isn't on the palette, delete the entire
                    # "Palette" block.
                    del editor_section[editor_sec_index]
                    break

        # Apply configured default values to this item
        prop_overrides = prop_conf.get(self.id, {})
        for prop_section in new_editor.find_all("Editor", "Properties"):
            for item_prop in prop_section:
                if item_prop.bool('BEE2_ignore'):
                    continue

                if item_prop.name.casefold() in prop_overrides:
                    item_prop['DefaultValue'] = prop_overrides[item_prop.name.casefold()]
        return (
            new_editor,
            item_data.editor_extra.copy(),
            # Add all_conf first so it's conditions run first by default
            self.all_conf + item_data.vbsp_config,
        )

    @staticmethod
    def convert_item_io(
        comm_block: Property,
        item: Property,
        conv_peti_input: Callable[[Property, str, str], None]=lambda a, b, c: None,
    ):
        """Convert editoritems configs with the new BEE2 connections format.

        This produces (conf,  has_input, has_output, has_secondary):
        The config block for instances.cfg, and if inputs, outputs, and the
        secondary input are present.
        """
        item_id = comm_block.name
        # Look in the Inputs and Outputs blocks to find the io definitions.
        # Copy them to property names like 'Input_Activate'.
        has_input = False
        has_secondary = False
        has_output = False
        try:
            [input_conf] = item.find_all('Exporting', 'Inputs', 'BEE2')
        except ValueError:
            pass
        else:
            input_conf = input_conf.copy()
            input_conf.name = None
            comm_block += input_conf
        try:
            [output_conf] = item.find_all('Exporting', 'Outputs', 'BEE2')
            output_conf.name = None
        except ValueError:
            pass
        else:
            output_conf = output_conf.copy()
            output_conf.name = None
            comm_block += output_conf
        for block in item.find_all('Exporting', 'Inputs', CONN_NORM):
            has_input = True
            conv_peti_input(block, 'enable_cmd', 'activate')
            conv_peti_input(block, 'disable_cmd', 'deactivate')
        for block in item.find_all('Exporting', 'Outputs', CONN_NORM):
            has_output = True
            for io_prop in block:
                comm_block['out_' + io_prop.name] = io_prop.value
        # The funnel item type is special, having the additional input type.
        # Handle that specially.
        if item_id == 'item_tbeam':
            for block in item.find_all('Exporting', 'Inputs', CONN_FUNNEL):
                has_secondary = True
                conv_peti_input(block, 'sec_enable_cmd', 'activate')
                conv_peti_input(block, 'sec_disable_cmd', 'deactivate')

        # For special situations, allow forcing that we have these.
        force_io = ''
        while 'force' in comm_block:
            force_io = comm_block['force', ''].casefold()
            del comm_block['force']
        if 'in' in force_io:
            has_input = True
        if 'out' in force_io:
            has_output = True

        if 'enable_cmd' in comm_block or 'disable_cmd' in comm_block:
            has_input = True
        inp_type = comm_block['type', ''].casefold()
        if inp_type == 'dual':
            has_secondary = True
        elif inp_type == 'daisychain':
            # We specify this.
            if 'enable_cmd' in comm_block or 'disable_cmd' in comm_block:
                LOGGER.warning(
                    'DAISYCHAIN items cannot have inputs specified.'
                )
            # The item has an input, but the instance never gets it.
            has_input = True
            if not has_output:
                LOGGER.warning(
                    'DAISYCHAIN items need an output to make sense!'
                )
        elif inp_type.endswith('_logic'):
            if 'out_activate' in comm_block or 'out_deactivate' in comm_block:
                LOGGER.warning(
                    'AND_LOGIC or OR_LOGIC items cannot '
                    'have outputs specified.'
                )
            if 'enable_cmd' in comm_block or 'disable_cmd' in comm_block:
                LOGGER.warning(
                    'AND_LOGIC or OR_LOGIC items cannot '
                    'have inputs specified.'
                )
            # These logically always have both.
            has_input = has_output = True
        elif 'out_activate' in comm_block or 'out_deactivate' in comm_block:
            has_output = True
        if item_id in (
            'item_indicator_panel',
            'item_indicator_panel_timer',
            'item_indicator_toggle',
        ):
            # Force the antline instances to have inputs, so we can specify
            # the real instance doesn't. We need the fake ones to match
            # instances to items.
            has_input = True

        # Remove all the IO blocks from editoritems, and replace with
        # dummy ones.
        # Then remove the config blocks.
        for io_type in ('Inputs', 'Outputs'):
            for block in item.find_all('Exporting', io_type):
                while CONN_NORM in block:
                    del block[CONN_NORM]
                while 'BEE2' in block:
                    del block['BEE2']
        if has_input:
            item.ensure_exists('Exporting').ensure_exists('Inputs').append(
                Property(CONN_NORM, [
                    Property('Activate', 'ACTIVATE'),
                    Property('Deactivate', 'DEACTIVATE'),
                ])
            )
        # Add the secondary for funnels only.
        if item_id.casefold() == 'item_tbeam':
            if not has_secondary:
                LOGGER.warning(
                    "No dual input for TBeam, these won't function."
                )
            item.ensure_exists('Exporting').ensure_exists('Inputs').append(
                Property(CONN_FUNNEL, [
                    Property('Activate', 'ACTIVATE_SECONDARY'),
                    Property('Deactivate', 'DEACTIVATE_SECONDARY'),
                ])
            )
        # Fizzlers don't work correctly with outputs - we don't
        # want it in editoritems.
        if has_output and item['ItemClass', ''].casefold() != 'itembarrierhazard':
            item.ensure_exists('Exporting').ensure_exists('Outputs').append(
                Property(CONN_NORM, [
                    Property('Activate', 'ON_ACTIVATED'),
                    Property('Deactivate', 'ON_DEACTIVATED'),
                ])
            )
        return has_input, has_output, has_secondary


class ItemConfig(PakObject, allow_mult=True, has_img=False):
    """Allows adding additional configuration for items.

    The ID should match an item ID.
    """
    def __init__(self, it_id, all_conf, version_conf):
        self.id = it_id
        self.versions = version_conf
        self.all_conf = all_conf

    @classmethod
    def parse(cls, data: ParseData):
        """Parse from config files."""
        filesystem = data.fsys  # type: FileSystem
        vers = {}

        all_config = get_config(
            data.info,
            data.fsys,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )
        set_cond_source(all_config, '<ItemConfig {}:{} all_conf>'.format(
            data.pak_id, data.id,
        ))

        with filesystem:
            for ver in data.info.find_all('Version'):  # type: Property
                ver_id = ver['ID', 'VER_DEFAULT']
                vers[ver_id] = styles = {}
                for sty_block in ver.find_all('Styles'):
                    for style in sty_block:
                        styles[style.real_name] = conf = filesystem.read_prop(
                            'items/' + style.value + '.cfg'
                        )

                        set_cond_source(conf, "<ItemConfig {}:{} in '{}'>".format(
                            data.pak_id, data.id, style.real_name,
                        ))

        return cls(
            data.id,
            all_config,
            vers,
        )

    def add_over(self, override: 'ItemConfig'):
        """Add additional style configs to the original config."""
        self.all_conf += override.all_conf.copy()

        for vers_id, styles in override.versions.items():
            our_styles = self.versions.setdefault(vers_id, {})
            for sty_id, style in styles.items():
                if sty_id not in our_styles:
                    our_styles[sty_id] = style.copy()
                else:
                    our_styles[sty_id] += style.copy()

    @staticmethod
    def export(exp_data: ExportData):
        """This export is done in Item.export().

        Here we don't know the version set for each item.
        """
        pass


class QuotePack(PakObject):
    """Adds lists of voice lines which are automatically chosen."""
    def __init__(
            self,
            quote_id,
            selitem_data: 'SelitemData',
            config: Property,
            chars=None,
            skin=None,
            studio: str=None,
            studio_actor='',
            cam_loc: Vec=None,
            turret_hate=False,
            interrupt=0.0,
            cam_pitch=0.0,
            cam_yaw=0.0,
            ):
        self.id = quote_id
        self.selitem_data = selitem_data
        self.cave_skin = skin
        self.config = config
        set_cond_source(config, 'QuotePack <{}>'.format(quote_id))
        self.chars = chars or ['??']
        self.studio = studio
        self.studio_actor = studio_actor
        self.cam_loc = cam_loc
        self.inter_chance = interrupt
        self.cam_pitch = cam_pitch
        self.cam_yaw = cam_yaw
        self.turret_hate = turret_hate

    @classmethod
    def parse(cls, data):
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

        monitor_data = data.info.find_key('monitor', None)

        if monitor_data.value is not None:
            mon_studio = monitor_data['studio']
            mon_studio_actor = monitor_data['studio_actor', '']
            mon_interrupt = monitor_data.float('interrupt_chance', 0)
            mon_cam_loc = monitor_data.vec('Cam_loc')
            mon_cam_pitch, mon_cam_yaw, _ = monitor_data.vec('Cam_angles')
            turret_hate = monitor_data.bool('TurretShoot')
        else:
            mon_studio = mon_cam_loc = None
            mon_interrupt = mon_cam_pitch = mon_cam_yaw = 0
            mon_studio_actor = ''
            turret_hate = False

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

    def __repr__(self):
        return '<Voice:' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
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
            path = os.path.join(
                os.getcwd(),
                '..',
                'config',
                'voice',
                prefix.upper() + voice.id + '.cfg',
            )
            LOGGER.info(path)
            if os.path.isfile(path):
                shutil.copy(
                    path,
                    exp_data.game.abs_path(
                        'bin/bee2/{}voice.cfg'.format(prefix)
                    )
                )
                LOGGER.info('Written "{}voice.cfg"', prefix)
            else:
                LOGGER.info('No {} voice config!', pretty)

    @staticmethod
    def strip_quote_data(prop: Property, _depth=0):
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


class Skybox(PakObject):
    def __init__(
            self,
            sky_id,
            selitem_data: 'SelitemData',
            config: Property,
            fog_opts: Property,
            mat,
            ):
        self.id = sky_id
        self.selitem_data = selitem_data
        self.material = mat
        self.config = config
        set_cond_source(config, 'Skybox <{}>'.format(sky_id))
        self.fog_opts = fog_opts

        # Extract this for selector windows to easily display
        self.fog_color = Vec.from_str(
            fog_opts['primarycolor' ''],
            255, 255, 255
        )

    @classmethod
    def parse(cls, data: ParseData):
        """Parse a skybox definition."""
        selitem_data = get_selitem_data(data.info)
        mat = data.info['material', 'sky_black']
        config = get_config(
            data.info,
            data.fsys,
            'skybox',
            pak_id=data.pak_id,
        )

        fog_opts = data.info.find_key("Fog", [])

        return cls(
            data.id,
            selitem_data,
            config,
            fog_opts,
            mat,
        )

    def add_over(self, override: 'Skybox'):
        """Add the additional vbsp_config commands to ourselves."""
        self.selitem_data = join_selitem_data(
            self.selitem_data,
            override.selitem_data
        )
        self.config += override.config
        self.fog_opts += override.fog_opts.copy()

    def __repr__(self):
        return '<Skybox ' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export the selected skybox."""
        if exp_data.selected is None:
            return  # No skybox..

        try:
            skybox = Skybox.by_id(exp_data.selected)  # type: Skybox
        except KeyError:
            raise Exception(
                "Selected skybox ({}) doesn't exist?".format(exp_data.selected)
            )

        exp_data.vbsp_conf.set_key(
            ('Options', 'Skybox'),
            skybox.material,
        )

        exp_data.vbsp_conf.append(skybox.config.copy())

        # Styles or other items shouldn't be able to set fog settings..
        if 'fog' in exp_data.vbsp_conf:
            del exp_data.vbsp_conf['fog']

        fog_opts = skybox.fog_opts.copy()
        fog_opts.name = 'Fog'

        exp_data.vbsp_conf.append(fog_opts)


class Music(PakObject):
    """Allows specifying background music for the map."""

    has_base = False
    has_tbeam = False
    has_bouncegel = False
    has_speedgel = False

    def __init__(
        self,
        music_id,
        selitem_data: 'SelitemData',
        sound: Dict[MusicChannel, List[str]],
        children: Dict[MusicChannel, str],
        config: Property=None,
        inst=None,
        sample: Dict[MusicChannel, Optional[str]]=None,
        pack=(),
        loop_len=0,
        synch_tbeam=False,
    ):
        self.id = music_id
        self.config = config or Property(None, [])
        self.children = children
        set_cond_source(config, 'Music <{}>'.format(music_id))
        self.inst = inst
        self.sound = sound
        self.packfiles = list(pack)
        self.len = loop_len
        self.sample = sample

        self.selitem_data = selitem_data

        self.has_synced_tbeam = synch_tbeam

    @classmethod
    def parse(cls, data: ParseData):
        """Parse a music definition."""
        selitem_data = get_selitem_data(data.info)
        inst = data.info['instance', None]
        sound = data.info.find_key('soundscript', [])  # type: Property

        if sound.has_children():
            sounds = {}
            for channel in MusicChannel:
                sounds[channel] = channel_snd = []
                for prop in sound.find_all(channel.value):
                    if prop.has_children():
                        channel_snd += [
                            subprop.value
                            for subprop in
                            prop
                        ]
                    else:
                        channel_snd.append(prop.value)

            synch_tbeam = sound.bool('sync_funnel')
        else:
            # Only base.
            sounds = {
                channel: []
                for channel in
                MusicChannel
            }
            sounds[MusicChannel.BASE] = [sound.value]
            synch_tbeam = False

        # The sample music file to play, if found.
        sample_block = data.info.find_key('sample', '')  # type: Property
        if sample_block.has_children():
            sample = {}  # type: Dict[MusicChannel, Optional[str]]
            for channel in MusicChannel:
                chan_sample = sample[channel] = sample_block[channel.value, '']
                if chan_sample:
                    zip_sample = (
                        'resources/music_samp/' +
                        chan_sample
                    )
                    if zip_sample not in data.fsys:
                        LOGGER.warning(
                            'Music sample for <{}>{} does not exist in zip: "{}"',
                            data.id,
                            ('' if
                             channel is MusicChannel.BASE
                             else f' ({channel.value})'),
                            zip_sample,
                        )
                else:
                    sample[channel] = None
        else:
            # Single value, fill it into all channels we define.
            sample = {
                channel: sample_block.value if sounds[channel] else None
                for channel in MusicChannel
            }

        snd_length = data.info['loop_len', '0']
        if ':' in snd_length:
            # Allow specifying lengths as min:sec.
            minute, second = snd_length.split(':')
            snd_length = 60 * srctools.conv_int(minute) + srctools.conv_int(second)
        else:
            snd_length = srctools.conv_int(snd_length)

        packfiles = [
            prop.value
            for prop in
            data.info.find_all('pack')
        ]

        children_prop = data.info.find_key('children', [])
        children = {
            channel: children_prop[channel.value, '']
            for channel in MusicChannel
            if channel is not MusicChannel.BASE
        }

        config = get_config(
            data.info,
            data.fsys,
            'music',
            pak_id=data.pak_id,
        )
        return cls(
            data.id,
            selitem_data,
            sounds,
            children,
            inst=inst,
            sample=sample,
            config=config,
            pack=packfiles,
            loop_len=snd_length,
            synch_tbeam=synch_tbeam,
        )

    def add_over(self, override: 'Music'):
        """Add the additional vbsp_config commands to ourselves."""
        self.config.append(override.config)
        self.selitem_data = join_selitem_data(
            self.selitem_data,
            override.selitem_data
        )

    def __repr__(self):
        return '<Music ' + self.id + '>'

    def provides_channel(self, channel: MusicChannel):
        """Check if this music has this channel."""
        if self.sound[channel]:
            return True
        if channel is MusicChannel.BASE and self.inst:
            # The instance provides the base track.
            return True
        return False

    def has_channel(self, channel: MusicChannel):
        """Check if this track or its children has a channel."""
        if self.sound[channel]:
             return True
        if channel is MusicChannel.BASE and self.inst:
            # The instance provides the base track.
            return True
        try:
            children = Music.by_id(self.children[channel])
        except KeyError:
            return False
        return children.sound[channel]

    def get_attrs(self) -> Dict[str, bool]:
        """Generate attributes for SelectorWin."""
        attrs = {
            channel.name: self.has_channel(channel)
            for channel in MusicChannel
            if channel is not MusicChannel.BASE
        }
        attrs['TBEAM_SYNC'] = self.has_synced_tbeam
        return attrs

    def get_suggestion(self, channel: MusicChannel):
        """Get the ID we want to suggest for a channel."""
        try:
            child = Music.by_id(self.children[channel])
        except KeyError:
            child = self
        if child.sound[channel]:
            return child.id
        return None

    def get_sample(self, channel: MusicChannel) -> Optional[str]:
        """Get the path to the sample file, if present."""
        if self.sample[channel]:
            return self.sample[channel]
        try:
            children = Music.by_id(self.children[channel])
        except KeyError:
            return None
        return children.sample[channel]

    @staticmethod
    def export(exp_data: ExportData):
        """Export the selected music."""
        selected = exp_data.selected  # type: Dict[MusicChannel, Optional[Music]]

        base_music = selected[MusicChannel.BASE]

        vbsp_config = exp_data.vbsp_conf

        if base_music is not None:
            vbsp_config += base_music.config.copy()

        music_conf = Property('MusicScript', [])
        vbsp_config.append(music_conf)
        to_pack = set()

        for channel, music in selected.items():
            if music is None:
                continue

            sounds = music.sound[channel]
            if len(sounds) == 1:
                music_conf.append(Property(channel.value, sounds[0]))
            else:
                music_conf.append(Property(channel.value, [
                    Property('snd', snd)
                    for snd in sounds
                ]))

            to_pack.update(music.packfiles)

        if base_music is not None:
            vbsp_config.set_key(
                ('Options', 'music_looplen'),
                str(base_music.len),
            )

            vbsp_config.set_key(
                ('Options', 'music_sync_tbeam'),
                srctools.bool_as_int(base_music.has_synced_tbeam),
            )
            vbsp_config.set_key(
                ('Options', 'music_instance'),
                base_music.inst or '',
            )

        # If we need to pack, add the files to be unconditionally
        # packed.
        if to_pack:
            vbsp_config.set_key(
                ('PackTriggers', 'Forced'),
                [
                    Property('File', file)
                    for file in to_pack
                ],
            )

    @classmethod
    def check_objects(cls):
        """Check children of each music item actually exist.

        This must be done after they all were parsed.
        """
        sounds = {}  # type: Dict[str, str]
        for music in cls.all():
            for channel in MusicChannel:
                # Base isn't present in this.
                child_id = music.children.get(channel, '')
                if child_id:
                    try:
                        child = cls.by_id(child_id)
                    except KeyError:
                        LOGGER.warning(
                            'Music "{}" refers to nonexistent'
                            ' "{}" for {} channel!',
                            music.id,
                            child_id,
                            channel.value,
                        )
                # Look for tracks used in two items, indicates
                # they should be children of one...
                for sound in music.sound[channel]:
                    sound = sound.casefold()
                    try:
                        other_id = sounds[sound]
                    except KeyError:
                        sounds[sound] = music.id
                    else:
                        if music.id != other_id:
                            LOGGER.warning(
                                'Sound "{}" was reused in "{}" <> "{}".',
                                sound,
                                music.id,
                                other_id
                            )


class StyleVar(PakObject, allow_mult=True, has_img=False):
    def __init__(
        self,
        var_id: str,
        name: str,
        styles: List[str],
        unstyled: bool=False,
        default: bool=False,
        desc: str='',
    ):
        self.id = var_id
        self.name = name
        self.default = default
        self.enabled = default
        self.desc = desc
        if unstyled:
            self.styles = None
        else:
            self.styles = styles

    @classmethod
    def parse(cls, data: 'ParseData') -> 'StyleVar':
        """Parse StyleVars from configs."""
        name = data.info['name', '']

        unstyled = srctools.conv_bool(data.info['unstyled', '0'])
        default = srctools.conv_bool(data.info['enabled', '0'])
        styles = [
            prop.value
            for prop in
            data.info.find_all('Style')
        ]
        desc = '\n'.join(
            prop.value
            for prop in
            data.info.find_all('description')
        )
        return cls(
            data.id,
            name,
            styles,
            unstyled=unstyled,
            default=default,
            desc=desc,
        )

    def add_over(self, override: 'StyleVar') -> None:
        """Override a stylevar to add more compatible styles."""
        # Setting it to be unstyled overrides any other values!
        if self.styles is None:
            return
        elif override.styles is None:
            self.styles = None
        else:
            self.styles.extend(override.styles)

        if not self.name:
            self.name = override.name

        # If they both have descriptions, add them together.
        # Don't do it if they're both identical though.
        # bool(strip()) = has a non-whitespace character
        stripped_over = override.desc.strip()
        if stripped_over and stripped_over not in self.desc:
            if self.desc.strip():
                self.desc += '\n\n' + override.desc
            else:
                self.desc = override.desc

    def __repr__(self) -> str:
        return '<Stylevar "{}", name="{}", default={}, styles={}>:\n{}'.format(
            self.id,
            self.name,
            self.default,
            self.styles,
            self.desc,
        )

    def applies_to_style(self, style: Style) -> bool:
        """Check to see if this will apply for the given style.

        """
        if self.styles is None:
            return True  # Unstyled stylevar

        if style.id in self.styles:
            return True

        return any(
            base.id in self.styles
            for base in
            style.bases
        )

    def applies_to_all(self) -> bool:
        """Check if this applies to all styles."""
        if self.styles is None:
            return True

        for style in Style.all():
            if not self.applies_to_style(style):
                return False
        return True

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export style var selections into the config.

        The .selected attribute is a dict mapping ids to the boolean value.
        """
        # Add the StyleVars block, containing each style_var.

        exp_data.vbsp_conf.append(Property('StyleVars', [
            Property(key, srctools.bool_as_int(val))
            for key, val in
            exp_data.selected.items()
        ]))


class StyleVPK(PakObject, has_img=False):
    """A set of VPK files used for styles.

    These are copied into _dlc3, allowing changing the in-editor wall
    textures.
    """
    def __init__(self, vpk_id, filesys: FileSystem, directory: str) -> None:
        """Initialise a StyleVPK object."""
        self.id = vpk_id
        self.fsys = filesys
        self.dir = directory

    @classmethod
    def parse(cls, data: ParseData):
        """Read the VPK file from the package."""
        vpk_name = data.info['filename']

        source_folder = os.path.normpath('vpk/' + vpk_name)

        # At least one exists?
        if not any(data.fsys.walk_folder(source_folder)):
            raise Exception(
                'VPK object "{}" has no associated files!'.format(data.id)
            )

        return cls(data.id, data.fsys, source_folder)

    @staticmethod
    def export(exp_data: ExportData):
        """Generate the VPK file in the game folder."""
        sel_vpk = exp_data.selected_style.vpk_name

        if sel_vpk:
            for vpk in StyleVPK.all():
                if vpk.id.casefold() == sel_vpk:
                    sel_vpk = vpk
                    break
            else:
                sel_vpk = None
        else:
            sel_vpk = None

        try:
            dest_folder = StyleVPK.clear_vpk_files(exp_data.game)
        except PermissionError:
            raise NoVPKExport()  # We can't edit the VPK files - P2 is open..

        if exp_data.game.steamID == utils.STEAM_IDS['PORTAL2']:
            # In Portal 2, we make a dlc3 folder - this changes priorities,
            # so the soundcache will be regenerated. Just copy the old one over.
            sound_cache = os.path.join(
                dest_folder, 'maps', 'soundcache', '_master.cache'
            )
            LOGGER.info('Sound cache: {}', sound_cache)
            if not os.path.isfile(sound_cache):
                LOGGER.info('Copying over soundcache file for DLC3..')
                os.makedirs(os.path.dirname(sound_cache), exist_ok=True)
                try:
                    shutil.copy(
                        exp_data.game.abs_path(
                            'portal2_dlc2/maps/soundcache/_master.cache',
                        ),
                        sound_cache,
                    )
                except FileNotFoundError:
                    # It's fine, this will be regenerated automatically
                    pass

        # Generate the VPK.
        vpk_file = VPK(os.path.join(dest_folder, 'pak01_dir.vpk'), mode='w')
        with vpk_file:
            if sel_vpk is not None:
                for file in sel_vpk.fsys.walk_folder(sel_vpk.dir):
                    with file.open_bin() as open_file:
                        vpk_file.add_file(
                            file.path,
                            open_file.read(),
                            sel_vpk.dir,
                        )

            # Additionally, pack in game/vpk_override/ into the vpk - this allows
            # users to easily override resources in general.

            override_folder = exp_data.game.abs_path('vpk_override')
            os.makedirs(override_folder, exist_ok=True)

            # Also write a file to explain what it's for..
            with open(os.path.join(override_folder, 'BEE2_README.txt'), 'w') as f:
                f.write(VPK_OVERRIDE_README)

            vpk_file.add_folder(override_folder)
            del vpk_file['BEE2_README.txt']  # Don't add this to the VPK though..

        LOGGER.info('Written {} files to VPK!', len(vpk_file))

    @staticmethod
    def iter_vpk_names():
        """Iterate over VPK filename suffixes.

        The first is '_dir.vpk', then '_000.vpk' with increasing
        numbers.
        """
        yield '_dir.vpk'
        for i in range(999):
            yield '_{:03}.vpk'.format(i)

    @staticmethod
    def clear_vpk_files(game) -> str:
        """Remove existing VPKs files from a game.

         We want to leave other files - otherwise users will end up
         regenerating the sound cache every time they export.

        This returns the path to the game folder.
        """
        dest_folder = game.abs_path(VPK_FOLDER.get(
            game.steamID,
            'portal2_dlc3',
        ))

        os.makedirs(dest_folder, exist_ok=True)
        try:
            for file in os.listdir(dest_folder):
                if file[:6] == 'pak01_':
                    os.remove(os.path.join(dest_folder, file))
        except PermissionError:
            # The player might have Portal 2 open. Abort changing the VPK.
            LOGGER.warning("Couldn't replace VPK files. Is Portal 2 "
                           "or Hammer open?")
            raise

        return dest_folder


class Elevator(PakObject):
    """An elevator video definition.

    This is mainly defined just for Valve's items - you can't pack BIKs.
    """
    def __init__(
        self,
        elev_id,
        selitem_data: 'SelitemData',
        video,
        vert_video=None,
    ) -> None:
        self.id = elev_id

        self.selitem_data = selitem_data

        if vert_video is None:
            self.has_orient = False
            self.horiz_video = video
            self.vert_video = video
        else:
            self.has_orient = True
            self.horiz_video = video
            self.vert_video = vert_video

    @classmethod
    def parse(cls, data: ParseData) -> 'Elevator':
        """Read elevator videos from the package."""
        info = data.info
        selitem_data = get_selitem_data(info)

        if 'vert_video' in info:
            video = info['horiz_video']
            vert_video = info['vert_video']
        else:
            video = info['video']
            vert_video = None

        return cls(
            data.id,
            selitem_data,
            video,
            vert_video,
        )

    def __repr__(self) -> str:
        return '<Elevator ' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export the chosen video into the configs."""
        style = exp_data.selected_style  # type: Style
        vbsp_config = exp_data.vbsp_conf  # type: Property

        if exp_data.selected is None:
            elevator = None
        else:
            try:
                elevator = Elevator.by_id(exp_data.selected)  # type: Elevator
            except KeyError:
                raise Exception(
                    "Selected elevator ({}) "
                    "doesn't exist?".format(exp_data.selected)
                ) from None

        if style.has_video:
            if elevator is None:
                # Use a randomised video
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'RAND',
                )
            elif elevator.id == 'VALVE_BLUESCREEN':
                # This video gets a special script and handling
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'BSOD',
                )
            else:
                # Use the particular selected video
                vbsp_config.set_key(
                    ('Elevator', 'type'),
                    'FORCE',
                )
                vbsp_config.set_key(
                    ('Elevator', 'horiz'),
                    elevator.horiz_video,
                )
                vbsp_config.set_key(
                    ('Elevator', 'vert'),
                    elevator.vert_video,
                )
        else:  # No elevator video for this style
            vbsp_config.set_key(
                ('Elevator', 'type'),
                'NONE',
            )


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


class EditorSound(PakObject, has_img=False):
    """Add sounds that are usable in the editor.

    The editor only reads in game_sounds_editor, so custom sounds must be
    added here.
    The ID is the name of the sound, prefixed with 'BEE2_Editor.'.
    The values in 'keys' will form the soundscript body.
    """
    def __init__(self, snd_name: str, data: Property) -> None:
        self.id = 'BEE2_Editor.' + snd_name
        self.data = data
        data.name = self.id

    @classmethod
    def parse(cls, data: ParseData) -> 'EditorSound':
        """Parse editor sounds from the package."""
        return cls(
            snd_name=data.id,
            data=data.info.find_key('keys', [])
        )

    @staticmethod
    def export(exp_data: ExportData):
        """Export EditorSound objects."""
        # Just command the game to do the writing.
        exp_data.game.add_editor_sounds(
            EditorSound.all()
        )


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

    def __init__(self, temp_id: str, vmf_file: VMF, force=None, keep_brushes=True):
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
            LOGGER.warning('Template "{}" has no config!', temp_id)

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
                if force_is_detail is not None:
                    export_detail = force_is_detail
                else:
                    export_detail = is_detail
                if len(vis_ids) > 1:
                    raise ValueError(
                        'Template "{}" has brush with two '
                        'visgroups!'.format(temp_id)
                    )
                visgroups = [
                    visgroup_names[vis_id]
                    for vis_id in
                    vis_ids
                ]
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

        # Transfer this configuration ent over.
        for color_picker in vmf_file.by_class['bee2_template_colorpicker']:
            new_ent = color_picker.copy(vmf_file=TEMPLATE_FILE, keep_vis=False)
            new_ent['template_id'] = temp_id
            TEMPLATE_FILE.add_ent(new_ent)

        for overlay in vmf_file.by_class['info_overlay']:  # type: Entity
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

        if self.temp_detail is None and self.temp_world is None:
            if not self.temp_overlays and not is_scaling:
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
    def export(exp_data: ExportData):
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


def get_selitem_data(info):
    """Return the common data for all item types - name, author, description.
    """
    from selectorWin import SelitemData

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


def join_selitem_data(our_data: 'SelitemData', over_data: 'SelitemData'):
    """Join together two sets of selitem data.

    This uses the over_data values if defined, using our_data if not.
    Authors and descriptions will be joined to each other.
    """
    from selectorWin import SelitemData
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

