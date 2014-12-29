'''
Handles scanning through the zip packages to find all items, styles, voice lines, etc.
'''
import os
import os.path
import shutil
from zipfile import ZipFile


from property_parser import Property
import loadScreen as loader
import utils

__all__ = ('loadAll', 'Style', 'Item', 'Voice', 'Skybox', 'Music', 'Goo')
obj = {}
obj_override = {}
packages = {}

data = {}

res_count = -1

def loadAll(dir, load_res):
    global res_count
    "Scan and read in all packages in the specified directory."
    dir=os.path.join(os.getcwd(), dir)
    contents=os.listdir(dir) # this is both files and dirs
    
    loader.length("PAK",len(contents))
    if load_res:
        res_count = 0
    else:
        loader.skip_stage("RES")
        
    zips=[]
    try:
        for name in contents:
            print("Reading package file '"+name+"'")
            name=os.path.join(dir,name)
            if name.endswith('.zip') and not os.path.isdir(name):
                zip = ZipFile(name, 'r')
                zips.append(zip)
                if 'info.txt' in zip.namelist(): # Is it valid?
                    with zip.open('info.txt', 'r') as info_file:
                        info=Property.parse(info_file, name + ':info.txt')
                    id = info['ID']
                    dispName = info['Name', id]
                    packages[id] = (id, zip, info, name, dispName)
                else:
                    print("ERROR: Bad package'"+name+"'!")
            
        for type in obj_types:
            obj[type] = {}
            obj_override[type] = {}
            data[type] = []
            
        objects = 0
        for id, zip, info, name, dispName in packages.values():
            print("Scanning package '"+id+"'")
            new_objs=parse_package(zip, info, name, id, dispName)
            objects += new_objs
            loader.step("PAK")
            print("Done!")
            
        loader.length("OBJ", objects)
        
        # Except for StyleVars, each object will have at least 1 image - 
        # in UI.py we step the progress once per object.
        loader.length("IMG", objects - len(obj['StyleVar']))

        print(objects)
        for type, objs in obj.items():
            for id, obj_data in objs.items():
                print("Loading " + type + ' "' + id + '"!')
                over = obj_override[type].get(id, [])
                # parse through the object and return the resultant class
                object = obj_types[type].parse(obj_data[0], id, obj_data[1])
                object.pak_id = obj_data[2]
                object.pak_name = obj_data[3]
                if id in obj_override[type]:
                    for over, zip in obj_override[type][id]:
                        object.add_over(obj_types[type].parse(over[0], id, over[1]), zip)
                data[type].append(object)
                loader.step("OBJ")
        if load_res:
            print('Extracting Resources...')
            for zip in zips:
                for path in zip.namelist():
                    loc=os.path.normcase(path)
                    if loc.startswith("resources"):
                        loader.step("RES")
                        zip.extract(path, path="cache/")
                       
            shutil.rmtree('images/cache', ignore_errors=True)
            shutil.rmtree('inst_cache/', ignore_errors=True)
            
            if os.path.isdir("cache/resources/bee2"):
                shutil.move("cache/resources/bee2", "images/cache")
            if os.path.isdir("cache/resources/instances"):
                shutil.move("cache/resources/instances", "inst_cache/")
                
            shutil.rmtree('cache/', ignore_errors=True)
            print('Done!')
               
    finally:
        for z in zips: #close them all, we've already read the contents.
            z.close()
    setup_style_tree(data)
    return data
        
def parse_package(zip, info, filename, pak_id, dispName):
    "Parse through the given package to find all the components."
    global res_count
    for pre in Property.find_key(info, 'Prerequisites', []).value:
        if pre.value not in packages:
            utils.con_log('Package "' + pre.value + '" required for "' + pak_id + '" - ignoring package!')
            return False
    objects = 0
    # First read through all the components we have, so we can match overrides to the originals
    for comp_type in obj_types:
        for object in info.find_all(comp_type):
            objects += 1
            id = object['id']
            is_sub = object['overrideOrig', '0'] == '1'
            if id in obj[comp_type]:
                if is_sub:
                    if id in obj_override[comp_type]:
                        obj_override[comp_type].append((zip, object))
                    else:
                        obj_override[comp_type] = [(zip,object)]
                else:
                    print('ERROR! "' + id + '" defined twice!')
            else:
                obj[comp_type][id] = (zip, object, pak_id, dispName)
    
    if res_count != -1:
        for item in zip.namelist():
            if item.startswith("resources"):
                res_count += 1
        loader.length("RES", res_count)
    return objects

def setup_style_tree(data):
    '''Modify all items so item inheritance is properly handled.'''
    styles = {}
    
    for style in data['Style']:
        styles[style.id] = style
    for style in styles.values():
        base = []
        b_style = style
        while b_style is not None:
            #Recursively find all the base styles for this one
            base.append(b_style)
            b_style = styles.get(b_style.base_style, None)
            # Just append the style.base_style to the list, 
            # until the style with that ID isn't found anymore.
        style.bases = base[:]
        
    # To do inheritance, we simply copy the data to ensure all items have data defined for every used style.
    for item in data['Item']:
        for vers in item.versions:
            for id, style in styles.items():
                if id not in vers['styles']:
                    for base_style in style.bases:
                        if base_style.id in vers['styles']:
                            # Copy the values for the parent to the child style
                            vers['styles'][id] = vers['styles'][base_style.id]
                            break
                    else:
                        # None found, use the first style in the list
                        vers['styles'][id] = vers['def_style']
class Style:
    def __init__(self, id, name, author, desc, icon, editor, config=None, base_style=None, short_name=None, suggested=None):
        self.id=id
        self.auth = author
        self.name = name
        self.desc = desc
        self.icon = icon
        self.short_name = name if short_name is None else short_name
        self.editor = editor
        self.base_style = base_style
        self.suggested = suggested or {}
        if config == None:
            self.config = Property(None, [])
        else:
            self.config = config
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a style definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        base = info['base', 'NONE']
        
        sugg = info.find_key('suggested', [])
        sugg = (sugg['quote',None], sugg['music',None], sugg['skybox','SKY_BLACK'], sugg['goo','GOO_NORM'])
        
        if short_name == '':
            short_name = None
        if base == 'NONE':
            base = None
        files = zip.namelist()
        folder = 'styles/' + info['folder']
        config = folder + '/vbsp_config.cfg'
        with zip.open(folder + '/items.txt', 'r') as item_data:
            items = Property.parse(item_data, folder+'/items.txt')
        if config in files:
            with zip.open(config, 'r') as vbsp_config:
                vbsp = Property.parse(vbsp_config, config)
        else:
            vbsp = None
        return cls(id, name, auth, desc, icon, items, vbsp, base, short_name=short_name, suggested=sugg)
        
    def add_over(self, override, zip):
        '''Add the additional commands to ourselves.'''
        self.editor.extend(override.editor)
        self.config.extend(override.config)
        self.auth.extend(override.auth)
        
    def __repr__(self):
        return '<Style:' + self.id + '>'

class Item:
    def __init__(self, id, versions):
        self.id=id
        self.versions=versions
        self.def_data = versions[0]['def_style']
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse an item definition.'''
        versions = []
        folders = {}
        
        for ver in info.find_all("version"):
            vals = {
            'name'    : ver['name', ''],
            'is_beta' : ver['beta', '0'] == '1',
            'is_dep'  : ver['deprecated', '0'] == '1',
            'styles'  :  {},
            'def_style' : None
            }
            for sty_list in ver.find_all('styles'):
                for sty in sty_list:
                    if vals['def_style'] is None:
                        vals['def_style'] = sty.value
                    vals['styles'][sty.name] = sty.value
                    folders[sty.value] = True
            versions.append(vals)
        for fold in folders:
            files = zip.namelist()
            prop_path = 'items/' + fold + '/properties.txt'
            editor_path = 'items/' + fold + '/editoritems.txt'
            config_path = 'items/' + fold + '/vbsp_config.cfg'
            if prop_path in files and editor_path in files:
                with zip.open(prop_path, 'r') as prop_file:
                    props = Property.parse(prop_file, prop_path).find_key('Properties')
                with zip.open(editor_path, 'r') as editor_file:
                    editor = Property.parse(editor_file, editor_path)
                    
                editor_iter = Property.find_all(editor, 'Item')
                folders[fold] = {
                        'auth': sep_values(props['authors', ''],','),
                        'tags': sep_values(props['tags', ''],';'),
                        'desc': list(desc_parse(props)),
                        'ent':  props['ent_count', '??'],
                        'url':  props['infoURL', None],
                        'icons': {p.name:p.value for p in props['icon', []]},
                        'all_name': props['all_name', None],
                        'all_icon': props['all_icon', None],
                        'editor' : next(editor_iter), # The first Item block found
                        'editor_extra': list(editor_iter), # Any extra blocks (offset catchers, extent items)
                        'vbsp': []
                       }
                
                # If we have at least 1, but not all of the grouping icon
                # definitions then notify the author.
                if (0 < ((folders[fold]['all_name'] is not None) + 
                     (folders[fold]['all_icon'] is not None) +
                     ('all' in folders[fold]['icons'])) < 3):
                     print('Warning: "'  + prop_path + '" has incomplete grouping icon definition!')
                     
                if config_path in files:
                    with zip.open(config_path, 'r') as vbsp_config:
                        folders[fold]['vbsp'] = Property.parse(vbsp_config, config_path)
            else:
                raise IOError('"items/' + fold + '" not valid! Folder likely missing! (Editor=' + 
                                str(editor in files) + ', Props=' + str(props in files) + ')')
        for ver in versions:
            if ver['def_style'] in folders:
                ver['def_style'] = folders[vals['def_style']]
            for sty, fold in ver['styles'].items():
                ver['styles'][sty] = folders[fold]
        return cls(id, versions)
        
    def add_over(self, override, zip):
        '''Add the other item data to ourselves.'''
        pass
    
    def __repr__(self):
        return '<Item:' + self.id + '>'

class Voice:
    def __init__(self, id, name, config, icon, desc, auth=None, short_name=None):
        self.id = id
        self.name = name
        self.icon = icon
        self.short_name = name if short_name is None else short_name
        self.desc = desc
        self.auth = [] if auth is None else auth
        self.config = config
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a voice line definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)        
        path = 'voice/' + info['file'] + '.voice'
        with zip.open(path, 'r') as conf:
            config = Property.parse(conf, path)
        
        return cls(id, name, config, icon, desc, auth=auth, short_name=short_name)
        
    def add_over(self, override, zip):
        '''Add the additional lines to ourselves.'''
        pass
    def __repr__(self):
        return '<Voice:' + self.id + '>'

class Skybox:
    def __init__(self, id, name, ico, config, mat, auth, desc, short_name=None):
        self.id=id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.material = mat
        self.config = config
        self.auth = auth
        self.desc = desc
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a skybox definition.'''
        config_dir = info['config', '']
        name, short_name, auth, icon, desc = get_selitem_data(info)
        mat = info['material', 'sky_black']
        if config_dir == '': # No config at all
            config = []
        else:
            path = 'skybox/' + name + '.cfg'
            if path in zip.namelist():
                with zip.open(name, 'r') as conf:
                    config = Property.parse(conf)
            else:
                print(name + '.cfg not in zip!')
                config = Property(None, [])
        return cls(id, name, icon, config, mat, auth, desc, short_name)
        
    def add_over(self, override, zip):
        '''Add the additional vbsp_config commands to ourselves.'''
        self.auth.extend(sky.auth)
        self.config.extend(sky.config)
    
    def __repr__(self):
        return '<Skybox ' + self.id + '>'
        
class Goo:
    def __init__(self, id, name, ico, mat, mat_cheap, auth, desc, short_name=None, config=None):
        self.id=id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.material = mat
        self.cheap_material = mat_cheap
        self.auth = auth
        self.desc = desc
        self.config = config or Property(None, [])
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a goo definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        mat = info['material', 'nature/toxicslime_a2_bridge_intro']
        mat_cheap = info['material_cheap', mat]
        
        config_dir = 'goo/' + info['config', '']
        if config_dir in zip.namelist():
            with zip.open(config_dir, 'r') as conf:
                config = Property.parse(conf, config_dir)
        else:
            config = Property(None, [])
            
        return cls(id, name, icon, mat, mat_cheap, auth, desc, short_name, config)
        
    def add_over(self, override, zip):
        '''Add the additional vbsp_config commands to ourselves.'''
        self.config.extend(override.config)
        self.auth.extend(override.auth)
    
    def __repr__(self):
        return '<Goo ' + self.id + '>'
  
class Music:
    def __init__(self, id, name, ico, inst, auth, desc, short_name=None, config=None):
        self.id=id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.inst = inst
        self.auth = auth
        self.desc = desc
        self.config = config or Property(None, [])
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a music definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        inst = info['instance']
        
        config_dir = 'music/' + info['config', '']
        if config_dir in zip.namelist():
            with zip.open(config_dir, 'r') as conf:
                config = Property.parse(conf, config_dir)
        else:
            config = Property(None, [])
        return cls(id, name, icon, inst, auth, desc, short_name, config=config)
        
    def add_over(self, override, zip):
        '''Add the additional vbsp_config commands to ourselves.'''
        self.config.extend(override.config)
        self.auth.extend(override.auth)
    
    def __repr__(self):
        return '<Music ' + self.id + '>'
        
class StyleVar:
    def __init__(self, id, name, styles, default=False):
        self.id = id
        self.name = name
        self.styles = styles
        self.default = default
        
    @classmethod
    def parse(cls, zip, id, info):
        name = info['name']
        styles = [prop.value for prop in info.find_all('Style')]
        default = info['enabled', '0'] == '1'
        return cls(id, name, styles, default)
        
    def add_over(self, override, zip):
        self.styles.extend(override.styles)
        
    def __repr__(self):
        return '<StyleVar ' + self.id + '>'
        
def desc_parse(info):
    for prop in info.find_all("description"):
        if prop.has_children():
            for line in prop:
                yield (line.name.casefold(), line.value)
        else:
            yield ("line", prop.value)
        
def get_selitem_data(info):
    '''Return the common data for all item types - name, author, description.'''
    auth = sep_values(info['authors', ''],',')
    # Multiple description lines will be joined together, for easier multi-line writing.""
    desc = list(desc_parse(info))
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', '_blank']
    return name, short_name, auth, icon, desc
    
def sep_values(str, delimiter):
    if str == '':
        return []
    else:
        vals = str.split(delimiter)
        return [stripped for stripped in (val.strip() for val in vals) if stripped]
            
obj_types = {
    'Style' : Style,
    'Item' : Item,
    'QuotePack': Voice,
    'Skybox': Skybox,
    'Goo' : Goo,
    'Music' : Music,
    'StyleVar' : StyleVar
    }
    
if __name__ == '__main__':
    loadAll('packages\\', False)