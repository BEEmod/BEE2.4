"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
import operator
import os
import os.path
import shutil
from collections import defaultdict, namedtuple
from contextlib import ExitStack
from zipfile import ZipFile

import extract_packages
import srctools
import tkMarkdown
import utils
from FakeZip import FakeZip, zip_names, zip_open_bin
from loadScreen import main_loader as loader
from packageMan import PACK_CONFIG
from selectorWin import SelitemData
from srctools import (
    Property, NoKeyError,
    Vec, EmptyMapping,
    VMF, Entity,
)

from typing import (
    Dict,
)

LOGGER = utils.getLogger(__name__)

all_obj = {}
obj_override = {}
packages = {}  # type: Dict[str, Package]
OBJ_TYPES = {}

data = {}

res_count = -1

TEMPLATE_FILE = VMF()

# Various namedtuples to allow passing blocks of data around
# (especially to functions that only use parts.)

# Tempory data stored when parsing info.txt, but before .parse() is called.
# This allows us to parse all packages before loading objects.
ObjData = namedtuple('ObjData', 'zip_file, info_block, pak_id, disp_name')
# The arguments for pak_object.parse().
ParseData = namedtuple('ParseData', 'zip_file, id, info, pak_id, is_override')
# The values stored for OBJ_TYPES
ObjType = namedtuple('ObjType', 'cls, allow_mult, has_img')
# The arguments to pak_object.export().
ExportData = namedtuple('ExportData', [
    'selected',
    'selected_style',  # Some items need to know which style is selected
    'editoritems',
    'vbsp_conf',
    'game',
])

# This package contains necessary components, and must be available.
CLEAN_PACKAGE = 'BEE2_CLEAN_STYLE'

# Check to see if the zip contains the resources referred to by the packfile.
CHECK_PACKFILE_CORRECTNESS = False

# The binary data comprising a blank VPK file.
EMPTY_VPK = bytes([
    52, 18, 170, 85,  # VPK identifier
    1,  # Version 1
    0,  # 0 bytes of directory info
    0, 0, 1, 0, 0, 0, 0,
])

# The folder we want to copy our VPKs to.
VPK_FOLDER = {
    # The last DLC released by Valve - this is the one that we
    # overwrite with a VPK file.
    utils.STEAM_IDS['PORTAL2']: 'portal2_dlc3',

    # This doesn't have VPK files, and is higher priority.
    utils.STEAM_IDS['APERTURE TAG']: 'portal2',
}


class _PakObjectMeta(type):
    def __new__(mcs, name, bases, namespace, allow_mult=False, has_img=True):
        """Adds a PakObject to the list of objects.

        Making a metaclass allows us to hook into the creation of all subclasses.
        """
        # Defer to type to create the class..
        cls = type.__new__(mcs, name, bases, namespace)

        # Only register subclasses of PakObject - those with a parent class.
        # PakObject isn't created yet so we can't directly check that.
        if bases:
            OBJ_TYPES[name] = ObjType(cls, allow_mult, has_img)

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
    @classmethod
    def parse(cls, data: ParseData) -> 'PakObject':
        """Parse the package object from the info.txt block.

        ParseData is a namedtuple containing relevant info:
        - zip_file, the package's ZipFile or FakeZip
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
    def get_objects(cls):
        """Get the list of objects parsed."""
        return OBJ_TYPES[cls.__name__]


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
        prop_block,
        zip_file,
        folder,
        pak_id='',
        prop_name='config',
        extension='.cfg',
        ):
    """Extract a config file refered to by the given property block.

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

    # Zips must use '/' for the seperator, even on Windows!
    path = folder + '/' + prop_block.value
    if len(path) < 3 or path[-4] != '.':
        # Add extension
        path += extension
    try:
        with zip_file.open(path) as f:
            return Property.parse(
                f,
                pak_id + ':' + path,
            )
    except KeyError:
        LOGGER.warning('"{id}:{path}" not in zip!', id=pak_id, path=path)
        return Property(None, [])
    except UnicodeDecodeError:
        LOGGER.exception('Unable to read "{id}:{path}"', id=pak_id, path=path)
        raise


def find_packages(pak_dir, zips, zip_stack: ExitStack, zip_name_lst):
    """Search a folder for packages, recursing if necessary."""
    found_pak = False
    for name in os.listdir(pak_dir):  # Both files and dirs
        name = os.path.join(pak_dir, name)
        is_dir = os.path.isdir(name)
        if name.endswith('.zip') and os.path.isfile(name):
            zip_file = ZipFile(name)
            # Ensure we quit close this zipfile..
            zip_stack.enter_context(zip_file)
        elif is_dir:
            zip_file = FakeZip(name)
            # FakeZips don't actually hold a file handle, we don't need to
            # close them.
        else:
            LOGGER.info('Extra file: {}', name)
            continue

        LOGGER.debug('Reading package "' + name + '"')

        try:
            # Valid packages must have an info.txt file!
            info_file = zip_file.open('info.txt')
        except KeyError:
            if is_dir:
                # This isn't a package, so check the subfolders too...
                LOGGER.debug('Checking subdir "{}" for packages...', name)
                find_packages(name, zips, zip_stack, zip_name_lst)
            else:
                # Invalid, explicitly close this zipfile handle..
                zip_file.close()
                LOGGER.warning('ERROR: Bad package "{}"!', name)
        else:
            with info_file:
                info = Property.parse(info_file, name + ':info.txt')

            # Add the zipfile to the list, it's valid
            zips.append(zip_file)
            zip_name_lst.append(os.path.abspath(name))

            pak_id = info['ID']
            packages[pak_id] = Package(
                pak_id,
                zip_file,
                info,
                name,
            )
            found_pak = True

    if not found_pak:
        LOGGER.debug('No packages in folder!')


def load_packages(
        pak_dir,
        log_item_fallbacks=False,
        log_missing_styles=False,
        log_missing_ent_count=False,
        log_incorrect_packfile=False,
        ):
    """Scan and read in all packages in the specified directory."""
    global LOG_ENT_COUNT, CHECK_PACKFILE_CORRECTNESS
    pak_dir = os.path.abspath(os.path.join(os.getcwd(), '..', pak_dir))

    if not os.path.isdir(pak_dir):
        from tkinter import messagebox
        import sys
        # We don't have a packages directory!
        messagebox.showerror(
            master=loader,
            title='BEE2 - Invalid Packages Directory!',
            message='The given packages directory is not present!\n'
                    'Get the packages from '
                    '"http://github.com/TeamSpen210/BEE2-items" '
                    'and place them in "' + pak_dir +
                    os.path.sep + '".',
                    # Add slash to the end to indicate it's a folder.
        )
        sys.exit('No Packages Directory!')

    shutil.rmtree('../vpk_cache/', ignore_errors=True)

    LOG_ENT_COUNT = log_missing_ent_count
    CHECK_PACKFILE_CORRECTNESS = log_incorrect_packfile
    zips = []
    data['zips'] = []

    # Use ExitStack to dynamically manage the zipfiles we find and open.
    with ExitStack() as zip_stack:
        find_packages(pak_dir, zips, zip_stack, data['zips'])

        pack_count = len(packages)
        loader.set_length("PAK", pack_count)

        for obj_type in OBJ_TYPES:
            all_obj[obj_type] = {}
            obj_override[obj_type] = defaultdict(list)
            data[obj_type] = []

        images = 0
        for pak_id, pack in packages.items():
            if not pack.enabled:
                LOGGER.info('Package {id} disabled!', id=pak_id)
                pack_count -= 1
                loader.set_length("PAK", pack_count)
                continue

            LOGGER.info('Reading objects from "{id}"...', id=pak_id)
            img_count = parse_package(pack)
            images += img_count
            loader.step("PAK")

        # If new packages were added, update the config!
        PACK_CONFIG.save_check()

        loader.set_length("OBJ", sum(
            len(obj_type)
            for obj_type in
            all_obj.values()
        ))
        loader.set_length("IMG_EX", images)

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
                LOGGER.debug('Loading {type} "{id}"!', type=obj_type, id=obj_id)
                # parse through the object and return the resultant class
                try:
                    object_ = OBJ_TYPES[obj_type].cls.parse(
                        ParseData(
                            obj_data.zip_file,
                            obj_id,
                            obj_data.info_block,
                            obj_data.pak_id,
                            False,
                        )
                    )
                except (NoKeyError, IndexError) as e:
                    reraise_keyerror(e, obj_id)

                object_.pak_id = obj_data.pak_id
                object_.pak_name = obj_data.disp_name
                for override_data in obj_override[obj_type].get(obj_id, []):
                    override = OBJ_TYPES[obj_type].cls.parse(
                        override_data
                    )
                    object_.add_over(override)
                data[obj_type].append(object_)
                loader.step("OBJ")

        # Extract all resources/BEE2/ images.

        img_dest = '../images/cache'

        shutil.rmtree(img_dest, ignore_errors=True)
        img_loc = os.path.join('resources', 'bee2')
        for zip_file in zips:
            for path in zip_names(zip_file):
                loc = os.path.normcase(path).casefold()
                if not loc.startswith(img_loc):
                    continue
                # Strip resources/BEE2/ from the path and move to the
                # cache folder.
                dest_loc = os.path.join(
                    img_dest,
                    os.path.relpath(loc, img_loc)
                )
                # Make the destination directory and copy over the image
                os.makedirs(os.path.dirname(dest_loc), exist_ok=True)
                with zip_open_bin(zip_file, path) as src:
                    with open(dest_loc, mode='wb') as dest:
                        shutil.copyfileobj(src, dest)
                loader.step("IMG_EX")

    LOGGER.info('Allocating styled items...')
    setup_style_tree(
        data['Item'],
        data['Style'],
        log_item_fallbacks,
        log_missing_styles,
    )
    return data


def parse_package(pack: 'Package'):
    """Parse through the given package to find all the components."""
    for pre in Property.find_key(pack.info, 'Prerequisites', []):
        if pre.value not in packages:
            LOGGER.warning(
                'Package "{pre}" required for "{id}" - '
                'ignoring package!',
                pre=pre.value,
                id=pack.id,
            )
            return False
    # First read through all the components we have, so we can match
    # overrides to the originals
    for comp_type in OBJ_TYPES:
        allow_dupes = OBJ_TYPES[comp_type].allow_mult
        # Look for overrides
        for obj in pack.info.find_all("Overrides", comp_type):
            obj_id = obj['id']
            obj_override[comp_type][obj_id].append(
                ParseData(pack.zip, obj_id, obj, pack.id, True)
            )

        for obj in pack.info.find_all(comp_type):
            obj_id = obj['id']
            if obj_id in all_obj[comp_type]:
                if allow_dupes:
                    # Pretend this is an override
                    obj_override[comp_type][obj_id].append(
                        ParseData(pack.zip, obj_id, obj, pack.id, True)
                    )
                else:
                    raise Exception('ERROR! "' + obj_id + '" defined twice!')
            all_obj[comp_type][obj_id] = ObjData(
                pack.zip,
                obj,
                pack.id,
                pack.disp_name,
            )

    img_count = 0
    img_loc = os.path.join('resources', 'bee2')
    for item in zip_names(pack.zip):
        item = os.path.normcase(item).casefold()
        if item.startswith("resources"):
            extract_packages.res_count += 1
            if item.startswith(img_loc):
                img_count += 1
    return img_count


def setup_style_tree(item_data, style_data, log_fallbacks, log_missing_styles):
    """Modify all items so item inheritance is properly handled.

    This will guarantee that all items have a definition for each
    combination of item and version.
    The priority is:
    - Exact Match
    - Parent style
    - Grandparent (etc) style
    - First version's style
    - First style of first version
    """
    all_styles = {}

    for style in style_data:
        all_styles[style.id] = style

    for style in all_styles.values():
        base = []
        b_style = style
        while b_style is not None:
            # Recursively find all the base styles for this one
            base.append(b_style)
            b_style = all_styles.get(b_style.base_style, None)
            # Just append the style.base_style to the list,
            # until the style with that ID isn't found anymore.
        style.bases = base

    # All styles now have a .bases attribute, which is a list of the
    # parent styles that exist.

    # To do inheritance, we simply copy the data to ensure all items
    # have data defined for every used style.
    for item in item_data:
        all_ver = list(item.versions.values())
        # Move default version to the beginning, so it's read first
        all_ver.remove(item.def_ver)
        all_ver.insert(0, item.def_ver)
        for vers in all_ver:
            for sty_id, style in all_styles.items():
                if sty_id in vers['styles']:
                    continue  # We already have a definition, or a reference
                for base_style in style.bases:
                    if base_style.id in vers['styles']:
                        # Copy the values for the parent to the child style
                        vers['styles'][sty_id] = vers['styles'][base_style.id]
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
                    # For the base version, use the first style if
                    # a styled version is not present
                    if vers['id'] == item.def_ver['id']:
                        vers['styles'][sty_id] = vers['def_style']
                        if log_missing_styles and not item.unstyled:
                            LOGGER.warning(
                                'Item "{item}" using '
                                'inappropriate style for "{style}"!',
                                item=item.id,
                                style=sty_id,
                            )
                    else:
                        # For versions other than the first, use
                        # the base version's definition
                        vers['styles'][sty_id] = item.def_ver['styles'][sty_id]

            # Evaluate style references.
            for sty_id, value in vers['styles'].items():
                if not isinstance(value, str):
                    continue  # Normal value
                # It's a reference to another style.
                try:
                    vers['styles'][sty_id] = vers['styles'][value[1:-1]]
                except KeyError:
                    raise Exception(
                        'Invalid style reference '
                        '("{}") for "{}", in "{}" style.'.format(
                            value, item.id, sty_id,
                        )
                    )

            if isinstance(vers['def_style'], str):
                # The default style is a value reference, fix it up.
                # If it's an invalid value the above loop will catch it.
                vers['def_style'] = vers['styles'][vers['def_style'][1:-1]]


def parse_item_folder(folders, zip_file, pak_id):
    for fold in folders:
        if fold.startswith('<') and fold.endswith('>'):
            # A reference for another style - skip it now, we'll copy the
            # real value in setup_style_tree()
            folders[fold] = fold
            continue

        prop_path = 'items/' + fold + '/properties.txt'
        editor_path = 'items/' + fold + '/editoritems.txt'
        config_path = 'items/' + fold + '/vbsp_config.cfg'
        try:
            with zip_file.open(prop_path, 'r') as prop_file:
                props = Property.parse(
                    prop_file, pak_id + ':' + prop_path,
                ).find_key('Properties')
            with zip_file.open(editor_path, 'r') as editor_file:
                editor = Property.parse(
                    editor_file, pak_id + ':' + editor_path
                )
        except KeyError as err:
            # Opening the files failed!
            raise IOError(
                '"' + pak_id + ':items/' + fold + '" not valid!'
                'Folder likely missing! '
            ) from err

        editor_iter = Property.find_all(editor, 'Item')
        folders[fold] = {
            'auth':     sep_values(props['authors', '']),
            'tags':     sep_values(props['tags', '']),
            'desc':     desc_parse(props, pak_id + ':' + prop_path),
            'ent':      props['ent_count', '??'],
            'url':      props['infoURL', None],
            'icons':    {p.name: p.value for p in props['icon', []]},
            'all_name': props['all_name', None],
            'all_icon': props['all_icon', None],
            'vbsp':     Property(None, []),

            # The first Item block found
            'editor': next(editor_iter),
            # Any extra blocks (offset catchers, extent items)
            'editor_extra': list(editor_iter),
        }

        if LOG_ENT_COUNT and folders[fold]['ent'] == '??':
            LOGGER.warning('"{id}:{path}" has missing entity count!',
                id=pak_id,
                path=prop_path,
            )

        # If we have at least 1, but not all of the grouping icon
        # definitions then notify the author.
        num_group_parts = (
            (folders[fold]['all_name'] is not None)
            + (folders[fold]['all_icon'] is not None)
            + ('all' in folders[fold]['icons'])
        )
        if 0 < num_group_parts < 3:
            LOGGER.warning(
                'Warning: "{id}:{path}" has incomplete grouping icon '
                'definition!',
                id=pak_id,
                path=prop_path,
            )
        try:
            with zip_file.open(config_path, 'r') as vbsp_config:
                folders[fold]['vbsp'] = Property.parse(
                    vbsp_config,
                    pak_id + ':' + config_path,
                )
        except KeyError:
            folders[fold]['vbsp'] = Property(None, [])


class Package:
    """Represents a package."""
    def __init__(
            self,
            pak_id: str,
            zip_file: ZipFile,
            info: Property,
            name: str,
            ):
        disp_name = info['Name', None]
        if disp_name is None:
            LOGGER.warning('Warning: {id} has no display name!', id=pak_id)
            disp_name = pak_id.lower()

        self.id = pak_id
        self.zip = zip_file
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
        if self.id == CLEAN_PACKAGE:
            raise ValueError('The Clean Style package cannot be disabled!')

        PACK_CONFIG[self.id]['Enabled'] = srctools.bool_as_int(value)
    enabled = enabled.setter(set_enabled)

    def is_stale(self):
        """Check to see if this package has been modified since the last run."""
        if isinstance(self.zip, FakeZip):
            # unzipped packages are for development, so always extract.
            LOGGER.info('Extracting resources - {} is unzipped!', self.id)
            return True
        last_modtime = PACK_CONFIG.get_int(self.id, 'ModTime', 0)
        zip_modtime = int(os.stat(self.name).st_mtime)

        if zip_modtime != last_modtime:
            LOGGER.info('Package {} is stale! Extracting resources...', self.id)
            return True
        return False

    def set_modtime(self):
        """After the cache has been extracted, set the modification dates
         in the config."""
        if isinstance(self.zip, FakeZip):
            # No modification time
            PACK_CONFIG[self.id]['ModTime'] = '0'
        else:
            PACK_CONFIG[self.id]['ModTime'] = str(int(
                os.stat(self.name).st_mtime
            ))


class Style(PakObject):
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
            corridor_names=EmptyMapping,
        ):
        self.id = style_id
        self.selitem_data = selitem_data
        self.editor = editor
        self.base_style = base_style
        self.bases = []  # Set by setup_style_tree()
        self.suggested = suggested or {}
        self.has_video = has_video
        self.vpk_name = vpk_name
        self.corridor_names = {
            'sp_entry': corridor_names.get('sp_entry', Property('', [])),
            'sp_exit':  corridor_names.get('sp_exit', Property('', [])),
            'coop':     corridor_names.get('coop', Property('', [])),
        }
        if config is None:
            self.config = Property(None, [])
        else:
            self.config = config

    @classmethod
    def parse(cls, data):
        """Parse a style definition."""
        info = data.info
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

        corridors = info.find_key('corridors', [])
        corridors = {
            'sp_entry': corridors.find_key('sp_entry', []),
            'sp_exit':  corridors.find_key('sp_exit', []),
            'coop':     corridors.find_key('coop', []),
        }

        if base == '':
            base = None
        try:
            folder = 'styles/' + info['folder']
        except IndexError:
            if data.is_override:
                items = Property(None, [])
                vbsp = None
            else:
                raise ValueError('Style missing configuration!')
        else:
            with data.zip_file.open(folder + '/items.txt', 'r') as item_data:
                items = Property.parse(
                    item_data,
                    data.pak_id + ':' + folder + '/items.txt'
                )

            config = folder + '/vbsp_config.cfg'
            try:
                with data.zip_file.open(config, 'r') as vbsp_config:
                    vbsp = Property.parse(
                        vbsp_config,
                        data.pak_id + ':' + config,
                    )
            except KeyError:
                vbsp = None

        return cls(
            style_id=data.id,
            selitem_data=selitem_data,
            editor=items,
            config=vbsp,
            base_style=base,
            suggested=sugg,
            has_video=has_video,
            corridor_names=corridors,
            vpk_name=vpk_name
        )

    def add_over(self, override: 'Style'):
        """Add the additional commands to ourselves."""
        self.editor.append(override.editor)
        self.config.append(override.config)
        self.selitem_data.auth.extend(override.selitem_data.auth)

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
        editoritems += self.editor.find_all("Item")
        vbsp_config += self.config

        return editoritems, vbsp_config


class Item(PakObject):
    def __init__(
            self,
            item_id,
            versions,
            def_version,
            needs_unlock=False,
            all_conf=None,
            unstyled=False,
            glob_desc=(),
            desc_last=False,
            ):
        self.id = item_id
        self.versions = versions
        self.def_ver = def_version
        self.def_data = def_version['def_style']
        self.needs_unlock = needs_unlock
        self.all_conf = all_conf or Property(None, [])
        self.unstyled = unstyled
        self.glob_desc = glob_desc
        self.glob_desc_last = desc_last

    @classmethod
    def parse(cls, data: ParseData):
        """Parse an item definition."""
        versions = {}
        def_version = None
        folders = {}
        unstyled = srctools.conv_bool(data.info['unstyled', '0'])

        glob_desc = desc_parse(data.info, 'global:' + data.id)
        desc_last = srctools.conv_bool(data.info['AllDescLast', '0'])

        all_config = get_config(
            data.info,
            data.zip_file,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )

        needs_unlock = srctools.conv_bool(data.info['needsUnlock', '0'])

        for ver in data.info.find_all('version'):
            vals = {
                'name':    ver['name', 'Regular'],
                'id':      ver['ID', 'VER_DEFAULT'],
                'is_wip': srctools.conv_bool(ver['wip', '0']),
                'is_dep':  srctools.conv_bool(ver['deprecated', '0']),
                'styles':  {},
                'def_style': None,
                }
            for sty_list in ver.find_all('styles'):
                for sty in sty_list:
                    # The first style is considered the 'default', and is used
                    # if not otherwise present.
                    if vals['def_style'] is None:
                        vals['def_style'] = sty.value
                    vals['styles'][sty.real_name] = sty.value
                    folders[sty.value] = True
            versions[vals['id']] = vals
            if def_version is None:
                def_version = vals

        parse_item_folder(folders, data.zip_file, data.pak_id)

        for ver in versions.values():
            if ver['def_style'] in folders:
                ver['def_style'] = folders[ver['def_style']]
            for sty, fold in ver['styles'].items():
                ver['styles'][sty] = folders[fold]

        if not versions:
            raise ValueError('Item "' + data.id + '" has no versions!')

        return cls(
            data.id,
            versions=versions,
            def_version=def_version,
            needs_unlock=needs_unlock,
            all_conf=all_config,
            unstyled=unstyled,
            glob_desc=glob_desc,
            desc_last=desc_last,
        )

    def add_over(self, override):
        """Add the other item data to ourselves."""
        # Copy over all_conf always.
        self.all_conf += override.all_conf

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
                        # We both have a matching folder, merge the
                        # definitions. We don't override editoritems!
                        our_style = our_ver[sty_id]

                        our_style['auth'].extend(style['auth'])
                        our_style['desc'].extend(style['desc'])
                        our_style['tags'].extend(style['tags'])
                        our_style['vbsp'] += style['vbsp']

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
         overriden property names. Empty dicts can be passed instead.
        """
        editoritems = exp_data.editoritems
        vbsp_config = exp_data.vbsp_conf
        pal_list, versions, prop_conf = exp_data.selected

        style_id = exp_data.selected_style.id

        aux_item_configs = {
            conf.id: conf
            for conf in data['ItemConfig']
        }

        for item in sorted(data['Item'], key=operator.attrgetter('id')):  # type: Item
            ver_id = versions.get(item.id, 'VER_DEFAULT')

            (
                item_block,
                editor_parts,
                config_part
            ) = item._get_export_data(
                pal_list, ver_id, style_id, prop_conf,
            )
            editoritems += item_block
            editoritems += editor_parts
            vbsp_config += config_part

            try:
                aux_conf = aux_item_configs[item.id]  # type: ItemConfig
            except KeyError:
                pass
            else:
                vbsp_config += aux_conf.all_conf
                try:
                    vbsp_config += aux_conf.versions[ver_id][style_id]
                except KeyError:
                    pass  # No override.

    def _get_export_data(self, pal_list, ver_id, style_id, prop_conf: Dict[str, Dict[str, str]]):
        """Get the data for an exported item."""

        # Build a dictionary of this item's palette positions,
        # if any exist.
        palette_items = {
            subitem: index
            for index, (item, subitem) in
            enumerate(pal_list)
            if item == self.id
        }

        item_data = self.versions[ver_id]['styles'][style_id]

        new_editor = item_data['editor'].copy()

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
                    if len(palette_items) == 1:
                        # Switch to the 'Grouped' icon and name
                        if item_data['all_name'] is not None:
                            pal_section['Tooltip'] = item_data['all_name']
                        if item_data['all_icon'] is not None:
                            pal_section['Image'] = item_data['all_icon']

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
                if item_prop.name.casefold() in prop_overrides:
                    item_prop['DefaultValue'] = prop_overrides[item_prop.name.casefold()]

        return (
            new_editor,
            item_data['editor_extra'],
            # Add all_conf first so it's conditions run first by default
            self.all_conf + item_data['vbsp'],
        )


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
        vers = {}

        all_config = get_config(
            data.info,
            data.zip_file,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )

        for ver in data.info.find_all('Version'):  # type: Property
            ver_id = ver['ID', 'VER_DEFAULT']
            vers[ver_id] = styles = {}
            for sty_block in ver.find_all('Styles'):
                for style in sty_block:  # type: Property
                    file_loc = 'items/' + style.value + '.cfg'
                    LOGGER.info(locals())
                    with data.zip_file.open(file_loc) as f:
                        styles[style.real_name] = Property.parse(
                            f,
                            data.pak_id + ':' + file_loc,
                        )

        return cls(
            data.id,
            all_config,
            vers,
        )

    def add_over(self, override: 'ItemConfig'):
        self.all_conf += override.all_conf

        for vers_id, styles in override.versions.items():
            our_styles = self.versions.setdefault(vers_id, {})
            for sty_id, style in styles.items():
                if sty_id not in our_styles:
                    our_styles[sty_id] = style
                else:
                    our_styles[sty_id] += style

    @staticmethod
    def export(exp_data: ExportData):
        """This export is done in Item.export().

        Here we don't know the version set for each item.
        """
        pass


class QuotePack(PakObject):
    def __init__(
            self,
            quote_id,
            selitem_data: 'SelitemData',
            config: Property,
            chars=None,
            skin=None,
            ):
        self.id = quote_id
        self.selitem_data = selitem_data
        self.cave_skin = skin
        self.config = config
        self.chars = chars or ['??']

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

        config = get_config(
            data.info,
            data.zip_file,
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
            )

    def add_over(self, override: 'QuotePack'):
        """Add the additional lines to ourselves."""
        self.selitem_data.auth += override.selitem_data.auth
        self.config += override.config
        self.config.merge_children(
            'quotes_sp',
            'quotes_coop',
        )
        if self.cave_skin is None:
            self.cave_skin = override.cave_skin

    def __repr__(self):
        return '<Voice:' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export the quotepack."""
        if exp_data.selected is None:
            return  # No quote pack!

        for voice in data['QuotePack']:  # type: QuotePack
            if voice.id == exp_data.selected:
                break
        else:
            raise Exception(
                "Selected voice ({}) doesn't exist?".format(exp_data.selected)
            )

        vbsp_config = exp_data.vbsp_conf  # type: Property

        # We want to strip 'trans' sections from the voice pack, since
        # they're not useful.
        for prop in voice.config:
            if prop.name == 'quotes':
                vbsp_config.append(QuotePack.strip_quote_data(prop))
            else:
                vbsp_config.append(prop)

        # Set values in vbsp_config, so flags can determine which voiceline
        # is selected.
        vbsp_config.set_key(
            ('Options', 'voice_pack'),
            voice.id,
        )
        vbsp_config.set_key(
            ('Options', 'voice_char'),
            ','.join(voice.chars)
        )

        if voice.cave_skin is not None:
            vbsp_config.set_key(
                ('Options', 'cave_port_skin'),
                str(voice.cave_skin),
            )

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
            data.zip_file,
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
        self.selitem_data.auth.extend(override.selitem_data.auth)
        self.config += override.config
        self.fog_opts += override.fog_opts

    def __repr__(self):
        return '<Skybox ' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export the selected skybox."""
        if exp_data.selected is None:
            return  # No skybox..

        for skybox in data['Skybox']:  # type: Skybox
            if skybox.id == exp_data.selected:
                break
        else:
            raise Exception(
                "Selected skybox ({}) doesn't exist?".format(exp_data.selected)
            )

        exp_data.vbsp_conf.set_key(
            ('Textures', 'Special', 'Sky'),
            skybox.material,
        )

        exp_data.vbsp_conf.append(skybox.config)

        # Styles or other items shouldn't be able to set fog settings..
        if 'fog' in exp_data.vbsp_conf:
            del exp_data.vbsp_conf['fog']

        fog_opts = skybox.fog_opts.copy()
        fog_opts.name = 'Fog'

        exp_data.vbsp_conf.append(fog_opts)


class Music(PakObject):

    def __init__(
            self,
            music_id,
            selitem_data: 'SelitemData',
            config: Property=None,
            inst=None,
            sound=None,
            sample=None,
            pack=(),
            loop_len=0,
            ):
        self.id = music_id
        self.config = config or Property(None, [])
        self.inst = inst
        self.sound = sound
        self.packfiles = list(pack)
        self.len = loop_len
        self.sample = sample

        self.selitem_data = selitem_data

        # Set attributes on this so UI.load_packages() can easily check for
        # which are present...
        sound_channels = ('base', 'speedgel', 'bouncegel', 'tbeam',)
        if isinstance(sound, Property):
            for chan in sound_channels:
                setattr(self, 'has_' + chan, bool(sound[chan, '']))
        else:
            for chan in sound_channels:
                setattr(self, 'has_' + chan, False)

    @classmethod
    def parse(cls, data: ParseData):
        """Parse a music definition."""
        selitem_data = get_selitem_data(data.info)
        inst = data.info['instance', None]
        sound = data.info.find_key('soundscript', '')  # type: Property

        # The sample music file to play, if found.
        rel_sample = data.info['sample', '']
        if rel_sample:
            sample = os.path.abspath('../sounds/music_samp/' + rel_sample)
            zip_sample = 'resources/music_samp/' + rel_sample
            try:
                with zip_open_bin(data.zip_file, zip_sample):
                    pass
            except KeyError:
                LOGGER.warning(
                    'Music sample for <{}> does not exist in zip: "{}"',
                    data.id,
                    zip_sample,
                )
        else:
            sample = None

        snd_length = data.info['loop_len', '0']
        if ':' in snd_length:
            # Allow specifying lengths as min:sec.
            minute, second = snd_length.split(':')
            snd_length = 60 * srctools.conv_int(minute) + srctools.conv_int(second)
        else:
            snd_length = srctools.conv_int(snd_length)

        if not sound.has_children():
            sound = sound.value

        packfiles = [
            prop.value
            for prop in
            data.info.find_all('pack')
        ]

        config = get_config(
            data.info,
            data.zip_file,
            'music',
            pak_id=data.pak_id,
        )
        return cls(
            data.id,
            selitem_data,
            inst=inst,
            sound=sound,
            sample=sample,
            config=config,
            pack=packfiles,
            loop_len=snd_length,
        )

    def add_over(self, override: 'Music'):
        """Add the additional vbsp_config commands to ourselves."""
        self.config.append(override.config)
        self.selitem_data.auth.extend(override.selitem_data.auth)

    def __repr__(self):
        return '<Music ' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export the selected music."""
        if exp_data.selected is None:
            return  # No music..

        for music in data['Music']:  # type: Music
            if music.id == exp_data.selected:
                break
        else:
            raise Exception(
                "Selected music ({}) doesn't exist?".format(exp_data.selected)
            )

        vbsp_config = exp_data.vbsp_conf

        if isinstance(music.sound, Property):
            # We want to generate the soundscript - copy over the configs.
            vbsp_config.append(Property('MusicScript', music.sound.value))
            script = 'music.BEE2'
        else:
            script = music.sound

        # Set the instance/ambient_generic file that should be used.
        if script is not None:
            vbsp_config.set_key(
                ('Options', 'music_SoundScript'),
                script,
            )
        if music.inst is not None:
            vbsp_config.set_key(
                ('Options', 'music_instance'),
                music.inst,
            )
        vbsp_config.set_key(
            ('Options', 'music_looplen'),
            str(music.len),
        )

        # If we need to pack, add the files to be unconditionally packed.
        if music.packfiles:
            vbsp_config.set_key(
                ('PackTriggers', 'Forced'),
                [
                    Property('File', file)
                    for file in
                    music.packfiles
                ],
            )

        # Allow flags to detect the music that's used
        vbsp_config.set_key(('Options', 'music_ID'), music.id)
        vbsp_config += music.config


class StyleVar(PakObject, allow_mult=True, has_img=False):
    def __init__(
            self,
            var_id,
            name,
            styles,
            unstyled=False,
            default=False,
            desc='',
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
    def parse(cls, data):
        name = data.info['name']
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

    def add_over(self, override):
        """Override a stylevar to add more compatible styles."""
        # Setting it to be unstyled overrides any other values!
        if self.styles is None:
            return
        elif override.styles is None:
            self.styles = None
        else:
            self.styles.extend(override.styles)
        # If they both have descriptions, add them together.
        # Don't do it if they're both identical though.
        if override.desc and override.desc not in self.desc:
            if self.desc:
                self.desc += '\n\n' + override.desc
            else:
                self.desc = override.desc

    def __repr__(self):
        return '<StyleVar ' + self.id + '>'

    def applies_to_style(self, style):
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

    @staticmethod
    def export(exp_data: ExportData):
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
    def __init__(self, vpk_id, file_count=0):
        """Initialise a StyleVPK object.

        The file_count is the number of VPK files - 0 = just pak01_dir.
        """
        self.id = vpk_id
        self.file_count = file_count

    @classmethod
    def parse(cls, data: ParseData):
        vpk_name = data.info['filename']
        dest_folder = os.path.join('../vpk_cache', data.id.casefold())

        os.makedirs(dest_folder, exist_ok=True)

        zip_file = data.zip_file  # type: ZipFile

        has_files = False
        file_count = 0

        for file_count, name in enumerate(cls.iter_vpk_names()):
            src = 'vpk/' + vpk_name + name
            dest = os.path.join(dest_folder, 'pak01' + name)
            try:
                src_file = zip_open_bin(zip_file, src)
            except KeyError:
                # This VPK filename isn't present, we've found them all..
                break
            else:
                with src_file, open(dest, 'wb') as dest_file:
                    shutil.copyfileobj(src_file, dest_file)
                has_files = True

        if not has_files:
            raise Exception(
                'VPK object "{}" has no associated VPK files!'.format(data.id)
            )

        return cls(data.id, file_count)

    @staticmethod
    def export(exp_data: ExportData):
        sel_vpk = exp_data.selected_style.vpk_name  # type: Style

        if sel_vpk:
            for vpk in data['StyleVPK']:  # type: StyleVPK
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
            return  # We can't edit the VPK files - P2 is open..

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
                shutil.copy(
                    exp_data.game.abs_path(
                        'portal2_dlc2/maps/soundcache/_master.cache',
                    ),
                    sound_cache,
                )

        if sel_vpk is None:
            # Write a blank VPK file.
            with open(os.path.join(dest_folder, 'pak01_dir.vpk'), 'wb') as f:
                f.write(EMPTY_VPK)
            LOGGER.info('Written empty VPK to "{}"', dest_folder)
        else:
            src_folder = os.path.join('../vpk_cache', sel_vpk.id.casefold())
            for index, suffix in zip(
                    range(sel_vpk.file_count),  # Limit to the number of files
                    sel_vpk.iter_vpk_names()):
                shutil.copy(
                    os.path.join(src_folder, 'pak01' + suffix),
                    os.path.join(dest_folder, 'pak01' + suffix),
                )
            LOGGER.info(
                'Written {} VPK{} to "{}"',
                sel_vpk.file_count,
                '' if sel_vpk.file_count == 1 else 's',
                dest_folder,
            )

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
            ):
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
    def parse(cls, data):
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

    def __repr__(self):
        return '<Elevator ' + self.id + '>'

    @staticmethod
    def export(exp_data: ExportData):
        """Export the chosen video into the configs."""
        style = exp_data.selected_style  # type: Style
        vbsp_config = exp_data.vbsp_conf  # type: Property

        if exp_data.selected is None:
            elevator = None
        else:
            for elevator in data['Elevator']:
                if elevator.id == exp_data.selected:
                    break
            else:
                raise Exception(
                    "Selected elevator ({}) "
                    "doesn't exist?".format(exp_data.selected)
                )

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
    def __init__(self, pak_id, files, mats):
        self.id = pak_id
        self.files = files
        self.trigger_mats = mats

    @classmethod
    def parse(cls, data):
        conf = data.info.find_key('Config', '')
        mats = [
            prop.value
            for prop in
            data.info.find_all('AddIfMat')
        ]
        if conf.has_children():
            # Allow having a child block to define packlists inline
            files = [
                prop.value
                for prop in conf
            ]
        else:
            path = 'pack/' + conf.value + '.cfg'
            try:
                with data.zip_file.open(path) as f:
                    # Each line is a file to pack.
                    # Skip blank lines, strip whitespace, and
                    # alow // comments.
                    files = []
                    for line in f:
                        line = srctools.clean_line(line)
                        if line:
                            files.append(line)
            except KeyError as ex:
                raise FileNotFoundError(
                    '"{}:{}" not in zip!'.format(
                        data.id,
                        path,
                    )
                ) from ex
        if CHECK_PACKFILE_CORRECTNESS:
            # Use normpath so sep differences are ignored, plus case.
            zip_files = {
                os.path.normpath(file).casefold()
                for file in
                zip_names(data.zip_file)
                if file.startswith('resources')
            }
            for file in files:
                #  Check to make sure the files exist...
                file = os.path.join('resources', os.path.normpath(file)).casefold()
                if file not in zip_files:
                    LOGGER.warning('Warning: "{file}" not in zip! ({pak_id})',
                        file=file,
                        pak_id=data.pak_id,
                    )

        return cls(
            data.id,
            files,
            mats,
        )

    def add_over(self, override):
        """Override items just append to the list of files."""
        # Dont copy over if it's already present
        for item in override.files:
            if item not in self.files:
                self.files.append(item)

        for item in override.trigger_mats:
            if item not in self.trigger_mats:
                self.trigger_mats.append(item)

    @staticmethod
    def export(exp_data: ExportData):
        """Export all the packlists."""

        pack_block = Property('PackList', [])

        # A list of materials which will casue a specific packlist to be used.
        pack_triggers = Property('PackTriggers', [])

        for pack in data['PackList']:  # type: PackList
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

            for trigger_mat in pack.trigger_mats:
                pack_triggers.append(
                    Property('Material', [
                        Property('Texture', trigger_mat),
                        Property('PackList', pack.id),
                    ])
                )

        # Only add packtriggers if there's actually a value
        if pack_triggers.value:
            exp_data.vbsp_conf.append(pack_triggers)

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
    def __init__(self, snd_name, data):
        self.id = 'BEE2_Editor.' + snd_name
        self.data = data
        data.name = self.id

    @classmethod
    def parse(cls, data):
        return cls(
            snd_name=data.id,
            data=data.info.find_key('keys', [])
        )

    @staticmethod
    def export(exp_data: ExportData):
        """Export EditorSound objects."""
        # Just command the game to do the writing.
        exp_data.game.add_editor_sounds(
            data['EditorSound']
        )


class BrushTemplate(PakObject, has_img=False):
    """A template brush which will be copied into the map, then retextured.

    This allows the sides of the brush to swap between wall/floor textures
    based on orientation.
    All world and detail brushes from the given VMF will be copied.
    """
    def __init__(self, temp_id, vmf_file: VMF, force=None, keep_brushes=True):
        """Import in a BrushTemplate object.

        This copies the solids out of vmf_file and into TEMPLATE_FILE.
        If force is set to 'world' or 'detail', the other type will be converted.
        If keep_brushes is false brushes will be skipped (for TemplateOverlay).
        """
        self.id = temp_id
        # We don't actually store the solids here - put them in
        # the TEMPLATE_FILE VMF. That way the original VMF object can vanish.

        # If we have overlays, we need to ensure the IDs crossover correctly
        id_mapping = {}

        self.temp_world = TEMPLATE_FILE.create_ent(
            classname='bee2_template_world',
            template_id=temp_id,
        )
        self.temp_detail = TEMPLATE_FILE.create_ent(
            classname='bee2_template_detail',
            template_id=temp_id,
        )

        # Check to see if any func_details have associated solids..
        has_detail = any(
            e.is_brush()
            for e in
            vmf_file.by_class['func_detail']
        )

        # Copy world brushes
        if keep_brushes and vmf_file.brushes:
            self.temp_world.solids = [
                solid.copy(map=TEMPLATE_FILE, side_mapping=id_mapping)
                for solid in
                vmf_file.brushes
            ]

        # Copy detail brushes
        if keep_brushes and has_detail:
            for ent in vmf_file.by_class['func_detail']:
                self.temp_detail.solids.extend(
                    solid.copy(map=TEMPLATE_FILE, side_mapping=id_mapping)
                    for solid in
                    ent.solids
                )

        # Allow switching world brushes to detail or vice-versa.
        if force.casefold == 'world':
            self.temp_world.solids.extend(self.temp_detail.solids)
            del self.temp_detail.solids[:]

        if force.casefold == 'detail':
            self.temp_detail.solids.extend(self.temp_world.solids)
            del self.temp_world.solids[:]

        # Destroy the entity object if it's unused.
        if not self.temp_detail.solids:
            self.temp_detail.remove()
            self.temp_detail = None
        if not self.temp_world.solids:
            self.temp_world.remove()
            self.temp_world = None

        self.temp_overlays = []

        # Look for overlays, and translate their IDS.
        for overlay in vmf_file.by_class['info_overlay']:  # type: Entity
            new_overlay = overlay.copy(
                map=TEMPLATE_FILE,
            )
            new_overlay['template_id'] = temp_id
            new_overlay['classname'] = 'bee2_template_overlay'
            sides = overlay['sides'].split()
            new_overlay['sides'] = ' '.join(
                id_mapping[side]
                for side in sides
                if side in id_mapping
            )
            TEMPLATE_FILE.add_ent(new_overlay)

            self.temp_overlays.append(new_overlay)

        if self.temp_detail is None and self.temp_world is None:
            if not self.temp_overlays:
                LOGGER.warning('BrushTemplate "{}" has no data!', temp_id)

    @classmethod
    def parse(cls, data: ParseData):
        file = get_config(
            prop_block=data.info,
            zip_file=data.zip_file,
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
        path = exp_data.game.abs_path('bin/bee2/templates.vmf')
        with open(path, 'w') as temp_file:
            TEMPLATE_FILE.export(temp_file)


def desc_parse(info, id=''):
    """Parse the description blocks, to create data which matches richTextBox.

    """
    has_warning = False
    lines = []
    for prop in info.find_all("description"):
        if prop.has_children():
            for line in prop:
                if line.name and not has_warning:
                    LOGGER.warning('Old desc format: {}', id)
                    has_warning = True
                lines.append(line.value)
        else:
            lines.append(prop.value)

    return tkMarkdown.convert('\n'.join(lines))



def get_selitem_data(info):
    """Return the common data for all item types - name, author, description.

    """
    auth = sep_values(info['authors', ''])
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', '_blank']
    group = info['group', '']
    sort_key = info['sort_key', '']
    desc = desc_parse(info, id=info['id'])
    if not group:
        group = None
    if not short_name:
        short_name = name

    return SelitemData(
        name,
        short_name,
        auth,
        icon,
        desc,
        group,
        sort_key,
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

if __name__ == '__main__':
    load_packages('packages//', False)