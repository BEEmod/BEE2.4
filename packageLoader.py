'''
Handles scanning through the zip packages to find all items, styles, voice lines, etc.
'''
import os
import os.path
import shutil
from zipfile import ZipFile


from property_parser import Property, NoKeyError
import loadScreen as loader
import utils

__all__ = [
    'load_packages',
    'Style',
    'Item',
    'QuotePack',
    'Skybox',
    'Music',
    'Goo',
    'StyleVar',
    ]

all_obj = {}
obj_override = {}
packages = {}

data = {}

res_count = -1


def reraise_keyerror(err, obj_id):
    '''Replace NoKeyErrors with a nicer one, giving the item that failed.
    '''
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


def load_packages(pak_dir, load_res):
    '''Scan and read in all packages in the specified directory.'''
    global res_count
    pak_dir = os.path.join(os.getcwd(), pak_dir)
    contents = os.listdir(pak_dir)  # this is both files and dirs

    loader.length("PAK", len(contents))

    if load_res:
        res_count = 0
    else:
        loader.skip_stage("RES")

    zips = []
    try:
        for name in contents:
            print('Reading package file "' + name + '"')
            name = os.path.join(pak_dir, name)
            if name.endswith('.zip') and not os.path.isdir(name):
                zip_file = ZipFile(name)
                zips.append(zip_file)
                if 'info.txt' in zip_file.namelist():  # Is it valid?
                    with zip_file.open('info.txt') as info_file:
                        info = Property.parse(info_file, name + ':info.txt')
                    pak_id = info['ID']
                    disp_name = info['Name', pak_id]
                    packages[pak_id] = (pak_id, zip_file, info, name, disp_name)
                else:
                    print("ERROR: Bad package'"+name+"'!")

        for obj_type in obj_types:
            all_obj[obj_type] = {}
            obj_override[obj_type] = {}
            data[obj_type] = []

        objects = 0
        for pak_id, zip_file, info, name, dispName in packages.values():
            print("Scanning package '" + pak_id + "'")
            new_objs = parse_package(zip_file, info, pak_id, dispName)
            objects += new_objs
            loader.step("PAK")
            print("Done!")

        loader.length("OBJ", objects)

        # Except for StyleVars, each object will have at least 1 image -
        # in UI.py we step the progress once per object.
        loader.length("IMG", objects - len(all_obj['StyleVar']))

        print(objects)
        for obj_type, objs in all_obj.items():
            for obj_id, obj_data in objs.items():
                print("Loading " + obj_type + ' "' + obj_id + '"!')
                # parse through the object and return the resultant class
                try:
                    object_ = obj_types[obj_type].parse(
                        obj_data[0],
                        obj_id,
                        obj_data[1],
                        )
                except (NoKeyError, IndexError) as e:
                    reraise_keyerror(e, obj_id)

                object_.pak_id = obj_data[2]
                object_.pak_name = obj_data[3]
                if obj_id in obj_override[obj_type]:
                    for zip_file, info_block in obj_override[obj_type][obj_id]:
                        override = obj_types[obj_type].parse(
                            zip_file,
                            obj_id,
                            info_block,
                            )
                        object_.add_over(override)
                data[obj_type].append(object_)
                loader.step("OBJ")
        if load_res:
            print('Extracting Resources...')
            for zip_file in zips:
                for path in zip_file.namelist():
                    loc = os.path.normcase(path)
                    if loc.startswith("resources"):
                        loader.step("RES")
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
    setup_style_tree(data['Item'], data['Style'])
    return data


def parse_package(zip, info, pak_id, dispName):
    "Parse through the given package to find all the components."
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
        for obj in info.find_all(comp_type):
            obj_id = obj['id']
            is_sub = obj['overrideOrig', '0'] == '1'
            if is_sub:
                if obj_id in obj_override[comp_type]:
                    obj_override[comp_type][obj_id].append((zip, obj))
                else:
                    obj_override[comp_type][obj_id] = [(zip, obj)]
            else:
                if obj_id in all_obj[comp_type]:
                    raise Exception('ERROR! "' + obj_id + '" defined twice!')
                objects += 1
                all_obj[comp_type][obj_id] = (zip, obj, pak_id, dispName)

    if res_count != -1:
        for item in zip.namelist():
            if item.startswith("resources"):
                res_count += 1
        loader.length("RES", res_count)
    return objects


def setup_style_tree(item_data, style_data):
    '''Modify all items so item inheritance is properly handled.

    This will guarantee that all items have a definition for each
    combination of item and version.
    The priority is:
    - Exact Match
    - Parent style
    - Grandparent (etc) style
    - First version's style
    - First style of first version
    '''
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
                        break
                else:
                    # For the base version, use the first style if
                    # a styled version is not present
                    if vers['id'] == item.def_ver['id']:
                        vers['styles'][sty_id] = vers['def_style']
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
        self.suggested = suggested or {}
        self.has_video = has_video
        if config is None:
            self.config = Property(None, [])
        else:
            self.config = config

    @classmethod
    def parse(cls, zip_file, style_id, info):
        '''Parse a style definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        base = info['base', 'NONE']
        has_video = info['has_video', '1'] == '1'

        sugg = info.find_key('suggested', [])
        sugg = (
            sugg['quote', '<NONE>'],
            sugg['music', '<NONE>'],
            sugg['skybox', 'SKY_BLACK'],
            sugg['goo', 'GOO_NORM'],
            sugg['elev', '<NONE>'],
            )

        if short_name == '':
            short_name = None
        if base == 'NONE':
            base = None
        files = zip_file.namelist()
        folder = 'styles/' + info['folder']
        config = folder + '/vbsp_config.cfg'
        with zip_file.open(folder + '/items.txt', 'r') as item_data:
            items = Property.parse(item_data, folder+'/items.txt')
        if config in files:
            with zip_file.open(config, 'r') as vbsp_config:
                vbsp = Property.parse(vbsp_config, config)
        else:
            vbsp = None
        return cls(
            style_id=style_id,
            name=name,
            author=auth,
            desc=desc,
            icon=icon,
            editor=items,
            config=vbsp,
            base_style=base,
            short_name=short_name,
            suggested=sugg,
            has_video=has_video,
            )

    def add_over(self, override):
        '''Add the additional commands to ourselves.'''
        self.editor.extend(override.editor)
        self.config.extend(override.config)
        self.auth.extend(override.auth)

    def __repr__(self):
        return '<Style:' + self.id + '>'


class Item:
    def __init__(self, item_id, versions, def_version):
        self.id = item_id
        self.versions = versions
        self.def_ver = def_version
        self.def_data = def_version['def_style']

    @classmethod
    def parse(cls, zip_file, item_id, info):
        '''Parse an item definition.'''
        versions = {}
        def_version = None
        folders = {}

        for ver in info.find_all('version'):
            vals = {
                'name':     ver['name', 'Regular'],
                'id':       ver['ID', 'VER_DEFAULT'],
                'is_beta':  ver['beta', '0'] == '1',
                'is_dep':   ver['deprecated', '0'] == '1',
                'styles':   {},
                'def_style': None,
                }
            for sty_list in ver.find_all('styles'):
                for sty in sty_list:
                    if vals['def_style'] is None:
                        vals['def_style'] = sty.value
                    vals['styles'][sty.name] = sty.value
                    folders[sty.value] = True
            versions[vals['id']] = vals
            if def_version is None:
                def_version = vals

        parse_item_folder(folders, zip_file)

        for ver in versions.values():
            if ver['def_style'] in folders:
                ver['def_style'] = folders[ver['def_style']]
            for sty, fold in ver['styles'].items():
                ver['styles'][sty] = folders[fold]

        if not versions:
            raise ValueError('Item "' + item_id + '" has no versions!')

        return cls(item_id, versions, def_version)

    def add_over(self, override):
        '''Add the other item data to ourselves.'''
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
    def parse(cls, zip_file, quote_id, info):
        '''Parse a voice line definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        path = 'voice/' + info['file'] + '.voice'
        with zip_file.open(path, 'r') as conf:
            config = Property.parse(conf, path)

        return cls(
            quote_id,
            name,
            config,
            icon,
            desc,
            auth=auth,
            short_name=short_name
            )

    def add_over(self, override):
        '''Add the additional lines to ourselves.'''
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
    def parse(cls, zip_file, item_id, info):
        '''Parse a skybox definition.'''
        config_dir = info['config', '']
        name, short_name, auth, icon, desc = get_selitem_data(info)
        mat = info['material', 'sky_black']
        if config_dir == '':  # No config at all
            config = Property(None, [])
        else:
            path = 'skybox/' + name + '.cfg'
            if path in zip_file.namelist():
                with zip_file.open(name, 'r') as conf:
                    config = Property.parse(conf)
            else:
                print(name + '.cfg not in zip!')
                config = Property(None, [])
        return cls(item_id, name, icon, config, mat, auth, desc, short_name)

    def add_over(self, override):
        '''Add the additional vbsp_config commands to ourselves.'''
        self.auth.extend(override.auth)
        self.config.extend(override.config)

    def __repr__(self):
        return '<Skybox ' + self.id + '>'


class Goo:
    def __init__(
            self,
            goo_id,
            name,
            ico,
            mat,
            mat_cheap,
            auth,
            desc,
            short_name=None,
            config=None,
            ):
        self.id = goo_id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.material = mat
        self.cheap_material = mat_cheap
        self.auth = auth
        self.desc = desc
        self.config = config or Property(None, [])

    @classmethod
    def parse(cls, zip_file, goo_id, info):
        '''Parse a goo definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        mat = info['material', 'nature/toxicslime_a2_bridge_intro']
        mat_cheap = info['material_cheap', mat]

        config_dir = 'goo/' + info['config', '']
        if config_dir in zip_file.namelist():
            with zip_file.open(config_dir, 'r') as conf:
                config = Property.parse(conf, config_dir)
        else:
            config = Property(None, [])

        return cls(
            goo_id,
            name,
            icon,
            mat,
            mat_cheap,
            auth,
            desc,
            short_name,
            config,
        )

    def add_over(self, override):
        '''Add the additional vbsp_config commands to ourselves.'''
        self.config.extend(override.config)
        self.auth.extend(override.auth)

    def __repr__(self):
        return '<Goo ' + self.id + '>'


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
    def parse(cls, zip_file, music_id, info):
        '''Parse a music definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        inst = info['instance', None]
        sound = info['soundscript', None]

        config_dir = 'music/' + info['config', '']
        if config_dir in zip_file.namelist():
            with zip_file.open(config_dir, 'r') as conf:
                config = Property.parse(conf, config_dir)
        else:
            config = Property(None, [])
        return cls(
            music_id,
            name,
            icon,
            auth,
            desc,
            short_name=short_name,
            inst=inst,
            sound=sound,
            config=config,
            )

    def add_over(self, override):
        '''Add the additional vbsp_config commands to ourselves.'''
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
    def parse(cls, _, var_id, info):
        name = info['name']
        styles = [prop.value for prop in info.find_all('Style')]
        default = info['enabled', '0'] == '1'
        return cls(var_id, name, styles, default)

    def add_over(self, override):
        self.styles.extend(override.styles)

    def __repr__(self):
        return '<StyleVar ' + self.id + '>'


class ElevatorVid:
    '''
    An elevator video definition.

    This is mainly defined just for Valve's items.
    '''
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
    def parse(cls, _, elev_id, info):
        name, short_name, auth, icon, desc = get_selitem_data(info)

        if 'vert_video' in info:
            video = info['horiz_video']
            vert_video = info['vert_video']
        else:
            video = info['video']
            vert_video = None

        return cls(
            elev_id,
            icon,
            name,
            auth,
            desc,
            video,
            short_name,
            vert_video
        )

    def add_over(self, override):
        pass

    def __repr__(self):
        return '<ElevatorVid ' + self.id + '>'


def desc_parse(info):
    '''Parse the description blocks, to create data which matches richTextBox.

    '''
    for prop in info.find_all("description"):
        if prop.has_children():
            for line in prop:
                yield (line.name, line.value)
        else:
            yield ("line", prop.value)


def get_selitem_data(info):
    '''Return the common data for all item types - name, author, description.

    '''
    auth = sep_values(info['authors', ''], ',')
    desc = list(desc_parse(info))
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', '_blank']
    return name, short_name, auth, icon, desc


def sep_values(string, delimiter):
    '''Split a string by a delimiter, and then strip whitespace.

    '''
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
    'Goo':       Goo,
    'Music':     Music,
    'StyleVar':  StyleVar,
    'Elevator':  ElevatorVid,
    }

if __name__ == '__main__':
    load_packages('packages\\', False)
