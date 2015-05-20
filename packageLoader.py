"""
Handles scanning through the zip packages to find all items, styles, etc.
"""
import os
import os.path
import shutil
from zipfile import ZipFile
from collections import defaultdict, namedtuple


from property_parser import Property, NoKeyError
from FakeZip import FakeZip
import loadScreen
import utils

__all__ = [
    'load_packages',
    'Style',
    'Item',
    'QuotePack',
    'Skybox',
    'Music',
    'StyleVar',
    ]

all_obj = {}
obj_override = {}
packages = {}

data = {}

res_count = -1

ObjData = namedtuple('ObjData', 'zip_file, info_block, pak_id, disp_name')
ParseData = namedtuple('ParseData', 'zip_file, id, info')
PackageData = namedtuple('package_data', 'zip_file, info, name, disp_name')


def zip_names(zip):
    """For FakeZips, use the generator instead of the zip file.

    """
    if hasattr(zip, 'names'):
        return zip.names()
    else:
        return zip.namelist()


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

def find_packages(pak_dir, zips):
    """Search a folder for packages, recursing if necessary."""
    found_pak = False
    for name in os.listdir(pak_dir): # Both files and dirs
        name = os.path.join(pak_dir, name)
        is_dir = os.path.isdir(name)
        if name.endswith('.zip') and os.path.isfile(name):
            zip_file = ZipFile(name)
        elif is_dir:
            zip_file = FakeZip(name)
        if 'info.txt' in zip_file.namelist():  # Is it valid?
            zips.append(zip_file)
            print('Reading package "' + name + '"')
            with zip_file.open('info.txt') as info_file:
                info = Property.parse(info_file, name + ':info.txt')
            pak_id = info['ID']
            disp_name = info['Name', pak_id]
            packages[pak_id] = PackageData(
                zip_file,
                info,
                name,
                disp_name,
            )
            found_pak = True
        else:
            if is_dir:
                # This isn't a package, so check the subfolders too...
                print('Checking subdir "{}" for packages...'.format(name))
                find_packages(name, zips)
            else:
                zip_file.close()
                print('ERROR: Bad package "{}"!'.format(name))
    if not found_pak:
        print('No packages in folder!')

def load_packages(
        pak_dir,
        load_res,
        log_item_fallbacks=False,
        log_missing_styles=False,
        log_missing_ent_count=False,
        ):
    """Scan and read in all packages in the specified directory."""
    global res_count, LOG_ENT_COUNT
    pak_dir = os.path.join(os.getcwd(), pak_dir)
    if load_res:
        res_count = 0
    else:
        loadScreen.skip_stage("RES")

    LOG_ENT_COUNT = log_missing_ent_count
    print('ENT_COUNT:', LOG_ENT_COUNT)
    zips = []
    try:
        find_packages(pak_dir, zips)

        loadScreen.length("PAK", len(packages))

        for obj_type in obj_types:
            all_obj[obj_type] = {}
            obj_override[obj_type] = defaultdict(list)
            data[obj_type] = []

        objects = 0
        for pak_id, (zip_file, info, name, dispName) in packages.items():
            print(("Reading objects from '" + pak_id + "'...").ljust(50), end='')
            obj_count = parse_package(zip_file, info, pak_id, dispName)
            objects += obj_count
            loadScreen.step("PAK")
            print("Done!")

        loadScreen.length("OBJ", objects)

        # Except for StyleVars, each object will have at least 1 image -
        # in UI.py we step the progress once per object.
        loadScreen.length("IMG", objects - len(all_obj['StyleVar']))

        for obj_type, objs in all_obj.items():
            for obj_id, obj_data in objs.items():
                print("Loading " + obj_type + ' "' + obj_id + '"!')
                # parse through the object and return the resultant class
                try:
                    object_ = obj_types[obj_type].parse(
                        ParseData(
                            obj_data.zip_file,
                            obj_id,
                            obj_data.info_block,
                        )
                    )
                except (NoKeyError, IndexError) as e:
                    reraise_keyerror(e, obj_id)

                object_.pak_id = obj_data.pak_id
                object_.pak_name = obj_data.disp_name
                for zip_file, info_block in \
                        obj_override[obj_type].get(obj_id, []):
                    override = obj_types[obj_type].parse(
                        ParseData(
                            zip_file,
                            obj_id,
                            info_block,
                        )
                    )
                    object_.add_over(override)
                data[obj_type].append(object_)
                loadScreen.step("OBJ")
        if load_res:
            print('Extracting Resources...')
            for zip_file in zips:
                for path in zip_names(zip_file):
                    loc = os.path.normcase(path)
                    if loc.startswith("resources"):
                        loadScreen.step("RES")
                        zip_file.extract(path, path="cache/")

            shutil.rmtree('images/cache', ignore_errors=True)
            shutil.rmtree('inst_cache/', ignore_errors=True)
            shutil.rmtree('source_cache/', ignore_errors=True)

            if os.path.isdir("cache/resources/bee2"):
                shutil.move("cache/resources/bee2", "images/cache")
            if os.path.isdir("cache/resources/instances"):
                shutil.move("cache/resources/instances", "inst_cache/")
            for file_type in ("materials", "models", "sounds", "scripts"):
                if os.path.isdir("cache/resources/" + file_type):
                    shutil.move(
                        "cache/resources/" + file_type,
                        "source_cache/" + file_type,
                    )

            shutil.rmtree('cache/', ignore_errors=True)
            print('Done!')

    finally:
        # close them all, we've already read the contents.
        for z in zips:
            z.close()

    print('Allocating styled items...')
    setup_style_tree(
        data['Item'],
        data['Style'],
        log_item_fallbacks,
        log_missing_styles,
    )
    print('Done!')
    return data


def parse_package(zip_file, info, pak_id, disp_name):
    """Parse through the given package to find all the components."""
    global res_count
    for pre in Property.find_key(info, 'Prerequisites', []).value:
        if pre.value not in packages:
            utils.con_log(
                'Package "' +
                pre.value +
                '" required for "' +
                pak_id +
                '" - ignoring package!'
            )
            return False
    objects = 0
    # First read through all the components we have, so we can match
    # overrides to the originals
    for comp_type in obj_types:
        # Look for overrides
        for obj in info.find_all("Overrides", comp_type):
            obj_id = obj['id']
            obj_override[comp_type][obj_id].append(
                (zip_file, obj)
            )

        for obj in info.find_all(comp_type):
            obj_id = obj['id']
            if obj_id in all_obj[comp_type]:
                raise Exception('ERROR! "' + obj_id + '" defined twice!')
            objects += 1
            all_obj[comp_type][obj_id] = ObjData(
                zip_file,
                obj,
                pak_id,
                disp_name,
            )

    if res_count != -1:
        for item in zip_names(zip_file):
            if item.startswith("resources"):
                res_count += 1
        loadScreen.length("RES", res_count)
    return objects


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
                        if log_fallbacks:
                            print(
                                'Item "{item}" using parent '
                                '"{rep}" for "{style}"!'.format(
                                    item=item.id,
                                    rep=base_style.id,
                                    style=sty_id,
                                )
                            )
                        break
                else:
                    # For the base version, use the first style if
                    # a styled version is not present
                    if vers['id'] == item.def_ver['id']:
                        vers['styles'][sty_id] = vers['def_style']
                        if log_missing_styles:
                            print(
                                'Item "{item}" using '
                                'inappropriate style for "{style}"!'.format(
                                    item=item.id,
                                    style=sty_id,
                                )
                            )
                    else:
                        # For versions other than the first, use
                        # the base version's definition
                        vers['styles'][sty_id] = item.def_ver['styles'][sty_id]


def parse_item_folder(folders, zip_file):
    for fold in folders:
        prop_path = 'items/' + fold + '/properties.txt'
        editor_path = 'items/' + fold + '/editoritems.txt'
        config_path = 'items/' + fold + '/vbsp_config.cfg'
        try:
            with zip_file.open(prop_path, 'r') as prop_file:
                props = Property.parse(
                    prop_file, prop_path,
                ).find_key('Properties')
            with zip_file.open(editor_path, 'r') as editor_file:
                editor = Property.parse(editor_file, editor_path)
        except KeyError as err:
            # Opening the files failed!
            raise IOError(
                '"items/' + fold + '" not valid!'
                'Folder likely missing! '
                ) from err

        editor_iter = Property.find_all(editor, 'Item')
        folders[fold] = {
            'auth':     sep_values(props['authors', ''], ','),
            'tags':     sep_values(props['tags', ''], ';'),
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
            print('Warning: "{}" has missing entity count!'.format(prop_path))

        # If we have at least 1, but not all of the grouping icon
        # definitions then notify the author.
        num_group_parts = (
            (folders[fold]['all_name'] is not None)
            + (folders[fold]['all_icon'] is not None)
            + ('all' in folders[fold]['icons'])
        )
        if 0 < num_group_parts < 3:
            print(
                'Warning: "{}" has incomplete grouping icon definition!'.format(
                    prop_path)
            )

        try:
            with zip_file.open(config_path, 'r') as vbsp_config:
                folders[fold]['vbsp'] = Property.parse(vbsp_config, config_path)
        except KeyError:
            folders[fold]['vbsp'] = Property(None, [])


class Style:
    def __init__(
            self,
            style_id,
            name,
            author,
            desc,
            icon,
            editor,
            config=None,
            base_style=None,
            short_name=None,
            suggested=None,
            has_video=True,
            ):
        self.id = style_id
        self.auth = author
        self.name = name
        self.desc = desc
        self.icon = icon
        self.short_name = name if short_name is None else short_name
        self.editor = editor
        self.base_style = base_style
        self.bases = []  # Set by setup_style_tree()
        self.suggested = suggested or {}
        self.has_video = has_video
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

        short_name = selitem_data.short_name or None
        if base == '':
            base = None
        folder = 'styles/' + info['folder']
        config = folder + '/vbsp_config.cfg'
        with data.zip_file.open(folder + '/items.txt', 'r') as item_data:
            items = Property.parse(item_data, folder+'/items.txt')

        try:
            with data.zip_file.open(config, 'r') as vbsp_config:
                vbsp = Property.parse(vbsp_config, config)
        except KeyError:
            vbsp = None
        return cls(
            style_id=data.id,
            name=selitem_data.name,
            author=selitem_data.auth,
            desc=selitem_data.desc,
            icon=selitem_data.icon,
            editor=items,
            config=vbsp,
            base_style=base,
            short_name=short_name,
            suggested=sugg,
            has_video=has_video,
            )

    def add_over(self, override):
        """Add the additional commands to ourselves."""
        self.editor.extend(override.editor)
        self.config.extend(override.config)
        self.auth.extend(override.auth)

    def __repr__(self):
        return '<Style:' + self.id + '>'


class Item:
    def __init__(self, item_id, versions, def_version, needs_unlock):
        self.id = item_id
        self.versions = versions
        self.def_ver = def_version
        self.def_data = def_version['def_style']
        self.needs_unlock = needs_unlock

    @classmethod
    def parse(cls, data):
        """Parse an item definition."""
        versions = {}
        def_version = None
        folders = {}

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

        parse_item_folder(folders, data.zip_file)

        for ver in versions.values():
            if ver['def_style'] in folders:
                ver['def_style'] = folders[ver['def_style']]
            for sty, fold in ver['styles'].items():
                ver['styles'][sty] = folders[fold]

        if not versions:
            raise ValueError('Item "' + data.id + '" has no versions!')

        return cls(data.id, versions, def_version, needs_unlock)

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


class QuotePack:
    def __init__(
            self,
            quote_id,
            name,
            config,
            icon,
            desc,
            auth=None,
            short_name=None,
            ):
        self.id = quote_id
        self.name = name
        self.icon = icon
        self.short_name = name if short_name is None else short_name
        self.desc = desc
        self.auth = [] if auth is None else auth
        self.config = config

    @classmethod
    def parse(cls, data):
        """Parse a voice line definition."""
        selitem_data = get_selitem_data(data.info)
        path = 'voice/' + data.info['file'] + '.voice'
        with data.zip_file.open(path, 'r') as conf:
            config = Property.parse(conf, path)

        return cls(
            data.id,
            selitem_data.name,
            config,
            selitem_data.icon,
            selitem_data.desc,
            auth=selitem_data.auth,
            short_name=selitem_data.short_name
            )

    def add_over(self, override):
        """Add the additional lines to ourselves."""
        self.auth += override.auth
        self.config += override.config
        self.config.merge_children(
            'quotes_sp',
            'quotes_coop',
        )

    def __repr__(self):
        return '<Voice:' + self.id + '>'


class Skybox:
    def __init__(
            self,
            sky_id,
            name,
            ico,
            config,
            mat,
            auth,
            desc,
            short_name=None,
            ):
        self.id = sky_id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.material = mat
        self.config = config
        self.auth = auth
        self.desc = desc

    @classmethod
    def parse(cls, data):
        """Parse a skybox definition."""
        config_dir = data.info['config', '']
        selitem_data = get_selitem_data(data.info)
        mat = data.info['material', 'sky_black']
        if config_dir == '':  # No config at all
            config = Property(None, [])
        else:
            path = 'skybox/' + config_dir + '.cfg'
            try:
                with data.zip_file.open(path, 'r') as conf:
                    config = Property.parse(conf)
            except KeyError:
                print(config_dir + '.cfg not in zip!')
                config = Property(None, [])
        return cls(
            data.id,
            selitem_data.name,
            selitem_data.icon,
            config,
            mat,
            selitem_data.auth,
            selitem_data.desc,
            selitem_data.short_name,
        )

    def add_over(self, override):
        """Add the additional vbsp_config commands to ourselves."""
        self.auth.extend(override.auth)
        self.config.extend(override.config)

    def __repr__(self):
        return '<Skybox ' + self.id + '>'


class Music:
    def __init__(
            self,
            music_id,
            name,
            ico,
            auth,
            desc,
            short_name=None,
            config=None,
            inst=None,
            sound=None,
            ):
        self.id = music_id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.inst = inst
        self.sound = sound
        self.auth = auth
        self.desc = desc
        self.config = config or Property(None, [])

    @classmethod
    def parse(cls, data):
        """Parse a music definition."""
        selitem_data = get_selitem_data(data.info)
        inst = data.info['instance', None]
        sound = data.info['soundscript', None]

        config_dir = 'music/' + data.info['config', '']
        try:
            with data.zip_file.open(config_dir) as conf:
                config = Property.parse(conf, config_dir)
        except KeyError:
            config = Property(None, [])
        return cls(
            data.id,
            selitem_data.name,
            selitem_data.icon,
            selitem_data.auth,
            selitem_data.desc,
            short_name=selitem_data.short_name,
            inst=inst,
            sound=sound,
            config=config,
            )

    def add_over(self, override):
        """Add the additional vbsp_config commands to ourselves."""
        self.config.extend(override.config)
        self.auth.extend(override.auth)

    def __repr__(self):
        return '<Music ' + self.id + '>'


class StyleVar:
    def __init__(self, var_id, name, styles, default=False):
        self.id = var_id
        self.name = name
        self.styles = styles
        self.default = default

    @classmethod
    def parse(cls, data):
        name = data.info['name']
        styles = [
            prop.value
            for prop in data.info.find_all('Style')
        ]
        default = utils.conv_bool(data.info['enabled', '0'])
        return cls(data.id, name, styles, default)

    def add_over(self, override):
        self.styles.extend(override.styles)

    def __repr__(self):
        return '<StyleVar ' + self.id + '>'

    def applies_to_style(self, style):
        """Check to see if this will apply for the given style.

        """
        if style.id in self.styles:
            return True

        return any(
            base in self.styles
            for base in
            style.bases
        )


class ElevatorVid:
    """An elevator video definition.

    This is mainly defined just for Valve's items.
    """
    def __init__(
            self,
            elev_id,
            ico,
            name,
            auth,
            desc,
            video,
            short_name=None,
            vert_video=None,
            ):
        self.id = elev_id
        self.icon = ico
        self.auth = auth
        self.name = name
        self.short_name = name if short_name is None else short_name
        self.desc = desc
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
            selitem_data.icon,
            selitem_data.name,
            selitem_data.auth,
            selitem_data.desc,
            video,
            selitem_data.short_name,
            vert_video,
        )

    def add_over(self, override):
        pass

    def __repr__(self):
        return '<ElevatorVid ' + self.id + '>'


def desc_parse(info):
    """Parse the description blocks, to create data which matches richTextBox.

    """
    for prop in info.find_all("description"):
        if prop.has_children():
            for line in prop:
                yield (line.name, line.value)
        else:
            yield ("line", prop.value)


SelitemData = namedtuple('SelitemData', 'name, short_name, auth, icon, desc')


def get_selitem_data(info):
    """Return the common data for all item types - name, author, description.

    """
    auth = sep_values(info['authors', ''], ',')
    desc = list(desc_parse(info))
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', '_blank']
    return SelitemData(name, short_name, auth, icon, desc)


def sep_values(string, delimiter):
    """Split a string by a delimiter, and then strip whitespace.

    """
    if string == '':
        return []
    else:
        vals = string.split(delimiter)
        return [
            stripped for stripped in
            (val.strip() for val in vals)
            if stripped
        ]

obj_types = {
    'Style':     Style,
    'Item':      Item,
    'QuotePack': QuotePack,
    'Skybox':    Skybox,
    'Music':     Music,
    'StyleVar':  StyleVar,
    'Elevator':  ElevatorVid,
    }

if __name__ == '__main__':
    load_packages('packages\\', False)