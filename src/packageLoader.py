"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
from zipfile import ZipFile
from collections import defaultdict, namedtuple
import logging
import os
import os.path
import shutil

from property_parser import Property, NoKeyError
from FakeZip import FakeZip, zip_names
from selectorWin import SelitemData
from loadScreen import main_loader as loader
from packageMan import PACK_CONFIG
import vmfLib as VLib
import extract_packages
import utils

from typing import (
    Union, Optional,
    List, Dict, Tuple,
)

LOGGER = utils.getLogger(__name__)

all_obj = {}
obj_override = {}
packages = {}  # type: Dict[str, Package]
OBJ_TYPES = {}

data = {}

res_count = -1

TEMPLATE_FILE = VLib.VMF()

ObjData = namedtuple('ObjData', 'zip_file, info_block, pak_id, disp_name')
ParseData = namedtuple('ParseData', 'zip_file, id, info, pak_id')
ObjType = namedtuple('ObjType', 'cls, allow_mult, has_img')

# This package contains necessary components, and must be available.
CLEAN_PACKAGE = 'BEE2_CLEAN_STYLE'

# Check to see if the zip contains the resources referred to by the packfile.
CHECK_PACKFILE_CORRECTNESS = False


def pak_object(name, allow_mult=False, has_img=True):
    """Decorator to add a class to the list of objects.

    Each object class needs two methods:
    parse() gets called with a ParseData object, to read from info.txt.
    The return value gets saved.

    For override items, they are parsed normally. The original item then
    gets the add_over(override) method called for each override to add values.

    If allow_mult is true, duplicate items will be treated as overrides,
    with one randomly chosen to be the 'parent'.
    """
    def x(cls):
        OBJ_TYPES[name] = ObjType(cls, allow_mult, has_img)
        return cls
    return x


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


def find_packages(pak_dir, zips, zip_name_lst):
    """Search a folder for packages, recursing if necessary."""
    found_pak = False
    for name in os.listdir(pak_dir):  # Both files and dirs
        name = os.path.join(pak_dir, name)
        is_dir = os.path.isdir(name)
        if name.endswith('.zip') and os.path.isfile(name):
            zip_file = ZipFile(name)
        elif is_dir:
            zip_file = FakeZip(name)
        else:
            LOGGER.info('Extra file: {}', name)
            continue

        if 'info.txt' in zip_file.namelist():  # Is it valid?
            zips.append(zip_file)
            zip_name_lst.append(os.path.abspath(name))
            LOGGER.debug('Reading package "' + name + '"')
            with zip_file.open('info.txt') as info_file:
                info = Property.parse(info_file, name + ':info.txt')
            pak_id = info['ID']
            packages[pak_id] = Package(
                pak_id,
                zip_file,
                info,
                name,
            )
            found_pak = True
        else:
            if is_dir:
                # This isn't a package, so check the subfolders too...
                LOGGER.debug('Checking subdir "{}" for packages...', name)
                find_packages(name, zips, zip_name_lst)
            else:
                zip_file.close()
                LOGGER.warning('ERROR: Bad package "{}"!', name)
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

    LOG_ENT_COUNT = log_missing_ent_count
    CHECK_PACKFILE_CORRECTNESS = log_incorrect_packfile
    zips = []
    data['zips'] = []
    try:
        find_packages(pak_dir, zips, data['zips'])

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

        cache_folder = os.path.abspath('../cache/')

        shutil.rmtree(cache_folder, ignore_errors=True)
        img_loc = os.path.join('resources', 'bee2')
        for zip_file in zips:
            for path in zip_names(zip_file):
                loc = os.path.normcase(path).casefold()
                if loc.startswith(img_loc):
                    loader.step("IMG_EX")
                    zip_file.extract(path, path=cache_folder)

        shutil.rmtree('../images/cache', ignore_errors=True)
        if os.path.isdir("../cache/resources/bee2"):
            shutil.move("../cache/resources/bee2", "../images/cache")
        shutil.rmtree('../cache/', ignore_errors=True)

    finally:
        # close them all, we've already read the contents.
        for z in zips:
            z.close()

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
                ParseData(pack.zip, obj_id, obj, pack.id)
            )

        for obj in pack.info.find_all(comp_type):
            obj_id = obj['id']
            if obj_id in all_obj[comp_type]:
                if allow_dupes:
                    # Pretend this is an override
                    obj_override[comp_type][obj_id].append(
                        ParseData(pack.zip, obj_id, obj, pack.id)
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
                    continue  # We already have a definition
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


def parse_item_folder(folders, zip_file, pak_id):
    for fold in folders:
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
            'desc':     list(desc_parse(props)),
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

        PACK_CONFIG[self.id]['Enabled'] = utils.bool_as_int(value)
    enabled = enabled.setter(set_enabled)


@pak_object('Style')
class Style:
    def __init__(
            self,
            style_id,
            selitem_data: 'SelitemData',
            editor,
            config=None,
            base_style=None,
            suggested=None,
            has_video=True,
            corridor_names=utils.EmptyMapping,
            ):
        self.id = style_id
        self.selitem_data = selitem_data
        self.editor = editor
        self.base_style = base_style
        self.bases = []  # Set by setup_style_tree()
        self.suggested = suggested or {}
        self.has_video = has_video
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
        has_video = utils.conv_bool(info['has_video', '1'])

        sugg = info.find_key('suggested', [])
        sugg = (
            sugg['quote', '<NONE>'],
            sugg['music', '<NONE>'],
            sugg['skybox', 'SKY_BLACK'],
            sugg['goo', 'GOO_NORM'],
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
        folder = 'styles/' + info['folder']
        config = folder + '/vbsp_config.cfg'
        with data.zip_file.open(folder + '/items.txt', 'r') as item_data:
            items = Property.parse(
                item_data,
                data.pak_id+':'+folder+'/items.txt'
            )

        try:
            with data.zip_file.open(config, 'r') as vbsp_config:
                vbsp = Property.parse(
                    vbsp_config,
                    data.pak_id+':'+config,
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
            )

    def add_over(self, override: 'Style'):
        """Add the additional commands to ourselves."""
        self.editor.extend(override.editor)
        self.config.extend(override.config)
        self.selitem_data.auth.extend(override.selitem_data.auth)

    def __repr__(self):
        return '<Style:' + self.id + '>'


@pak_object('Item')
class Item:
    def __init__(
            self,
            item_id,
            versions,
            def_version,
            needs_unlock=False,
            all_conf=None,
            unstyled=False,
            glob_desc=(),
            desc_last=False
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
    def parse(cls, data):
        """Parse an item definition."""
        versions = {}
        def_version = None
        folders = {}
        unstyled = utils.conv_bool(data.info['unstyled', '0'])

        glob_desc = list(desc_parse(data.info))
        desc_last = utils.conv_bool(data.info['AllDescLast', '0'])

        all_config = get_config(
            data.info,
            data.zip_file,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )

        needs_unlock = utils.conv_bool(data.info['needsUnlock', '0'])

        for ver in data.info.find_all('version'):
            vals = {
                'name':    ver['name', 'Regular'],
                'id':      ver['ID', 'VER_DEFAULT'],
                'is_wip': utils.conv_bool(ver['wip', '0']),
                'is_dep':  utils.conv_bool(ver['deprecated', '0']),
                'styles':  {},
                'def_style': None,
                }
            for sty_list in ver.find_all('styles'):
                for sty in sty_list:
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
                        # definitions
                        our_style = our_ver[sty_id]

                        our_style['auth'].extend(style['auth'])
                        our_style['desc'].extend(style['desc'])
                        our_style['tags'].extend(style['tags'])
                        our_style['vbsp'] += style['vbsp']

    def __repr__(self):
        return '<Item:' + self.id + '>'


@pak_object('QuotePack')
class QuotePack:
    def __init__(
            self,
            quote_id,
            selitem_data: 'SelitemData',
            config,
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
        port_skin = utils.conv_int(data.info['caveSkin', None], None)

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


@pak_object('Skybox')
class Skybox:
    def __init__(
            self,
            sky_id,
            selitem_data: 'SelitemData',
            config,
            mat,
            ):
        self.id = sky_id
        self.selitem_data = selitem_data
        self.material = mat
        self.config = config

    @classmethod
    def parse(cls, data):
        """Parse a skybox definition."""
        selitem_data = get_selitem_data(data.info)
        mat = data.info['material', 'sky_black']
        config = get_config(
            data.info,
            data.zip_file,
            'skybox',
            pak_id=data.pak_id,
        )
        return cls(
            data.id,
            selitem_data,
            config,
            mat,
        )

    def add_over(self, override: 'Skybox'):
        """Add the additional vbsp_config commands to ourselves."""
        self.selitem_data.auth.extend(override.selitem_data.auth)
        self.config.extend(override.config)

    def __repr__(self):
        return '<Skybox ' + self.id + '>'


@pak_object('Music')
class Music:
    def __init__(
            self,
            music_id,
            selitem_data: 'SelitemData',
            config=None,
            inst=None,
            sound=None,
            pack=(),
            ):
        self.id = music_id
        self.config = config or Property(None, [])
        self.inst = inst
        self.sound = sound
        self.packfiles = list(pack)

        self.selitem_data = selitem_data

    @classmethod
    def parse(cls, data):
        """Parse a music definition."""
        selitem_data = get_selitem_data(data.info)
        inst = data.info['instance', None]
        sound = data.info['soundscript', None]

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
            config=config,
            pack=packfiles,
            )

    def add_over(self, override: 'Music'):
        """Add the additional vbsp_config commands to ourselves."""
        self.config.extend(override.config)
        self.selitem_data.auth.extend(override.selitem_data.auth)

    def __repr__(self):
        return '<Music ' + self.id + '>'


@pak_object('StyleVar', allow_mult=True, has_img=False)
class StyleVar:
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
        self.desc = desc
        if unstyled:
            self.styles = None
        else:
            self.styles = styles

    @classmethod
    def parse(cls, data):
        name = data.info['name']
        unstyled = utils.conv_bool(data.info['unstyled', '0'])
        default = utils.conv_bool(data.info['enabled', '0'])
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
            base in self.styles
            for base in
            style.bases
        )


@pak_object('Elevator')
class ElevatorVid:
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

    def add_over(self, override):
        pass

    def __repr__(self):
        return '<ElevatorVid ' + self.id + '>'


@pak_object('PackList', allow_mult=True, has_img=False)
class PackList:
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
                        line = utils.clean_line(line)
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
                self.file.append(item)

        for item in override.trigger_mats:
            if item not in self.trigger_mats:
                self.trigger_mats.append(item)


@pak_object('EditorSound', has_img=False)
class EditorSound:
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


@pak_object('BrushTemplate', has_img=False)
class BrushTemplate:
    """A template brush which will be copied into the map, then retextured.

    This allows the sides of the brush to swap between wall/floor textures
    based on orientation.
    All world and detail brushes from the given VMF will be copied.
    """
    def __init__(self, temp_id, vmf_file: VLib.VMF):
        self.id = temp_id
        # We don't actually store the solids here - put them in
        # the TEMPLATE_FILE VMF. That way the VMF object can vanish.

        # If we have overlays, we need to ensure the IDs crossover correctly
        id_mapping = {}

        if vmf_file.brushes:
            self.temp_world = TEMPLATE_FILE.create_ent(
                classname='bee2_template_world',
                template_id=self.id,
            )
            self.temp_world.solids = [
                solid.copy(map=TEMPLATE_FILE, side_mapping=id_mapping)
                for solid in
                vmf_file.brushes
            ]
        else:
            self.temp_world = None

        # Add detail brushes
        if any(e.is_brush() for e in vmf_file.by_class['func_detail']):
            self.temp_detail = TEMPLATE_FILE.create_ent(
                classname='bee2_template_detail',
                template_id=self.id,
            )
            for ent in vmf_file.by_class['func_detail']:
                self.temp_detail.solids.extend(
                    solid.copy(map=TEMPLATE_FILE, side_mapping=id_mapping)
                    for solid in
                    ent.solids
                )
        else:
            self.temp_detail = None

        self.temp_overlays = []

        # Look for overlays, and translate their IDS.
        for overlay in vmf_file.by_class['info_overlay']:  # type: VLib.Entity
            new_overlay = overlay.copy(
                map=TEMPLATE_FILE,
            )
            new_overlay['template_id'] = self.id
            new_overlay['classname'] = 'bee2_template_overlay'
            sides = overlay['sides'].split()
            new_overlay['sides'] = ' '.join(
                id_mapping[side]
                for side in sides
                if side in id_mapping
            )
            TEMPLATE_FILE.add_ent(new_overlay)

            self.temp_overlays.append(new_overlay)

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
        file = VLib.VMF.parse(file)
        return cls(
            data.id,
            file,
        )


def desc_parse(info):
    """Parse the description blocks, to create data which matches richTextBox.

    """
    for prop in info.find_all("description"):
        if prop.has_children():
            for line in prop:
                yield (line.name, line.value)
        else:
            yield ("line", prop.value)


def get_selitem_data(info):
    """Return the common data for all item types - name, author, description.

    """
    auth = sep_values(info['authors', ''])
    desc = list(desc_parse(info))
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', '_blank']
    group = info['group', '']
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