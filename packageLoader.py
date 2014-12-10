'''
Handles scanning through the zip packages to find all items, styles, voice lines, etc.
'''
import os
import os.path
from zipfile import ZipFile


from property_parser import Property
import utils

__all__ = ('loadAll', 'Style', 'Item', 'Voice', 'Skybox', 'Music', 'Goo')

obj = {}
obj_override = {}
packages = {}

data = {}
zips = []

def loadAll(dir):
    "Scan and read in all packages in the specified directory."
    dir=os.path.join(os.getcwd(),dir)
    contents=os.listdir(dir) # this is both files and dirs
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
                        info=Property.parse(info_file)
                    id = Property.find_key(info, 'ID').value
                    packages[id] = (id, zip, info, name)
                else:
                    print("ERROR: Bad package'"+name+"'!")
            
        for type in obj_types:
            obj[type] = {}
            obj_override[type] = {}
            data[type] = []
        
        for id, zip, info, name in packages.values():
            print("Scanning package '"+id+"'")
            is_valid=parse_package(zip, info, name, id)
            print("Done!")
            
        for type, objs in obj.items():
            for id, object in objs.items():
                print("Loading " + type + ' "' + id + '"!')
                over = obj_override[type].get(id, [])
                # parse through the object and return the resultant class
                object = obj_types[type].parse(object[0], id, object[1])
                if id in obj_override[type]:
                    for over in obj_override[type][id]:
                        object.add_over(obj_types[type].parse(over[0], id, over[1]))
                data[type].append(object)
    finally:
        for z in zips: #close them all, we've already read the contents.
            z.close()
    return data
        
def parse_package(zip, info, filename, id):
    "Parse through the given package to find all the components."
    for pre in Property.find_key(info, 'Prerequisites', []).value:
        if pre.value not in packages:
            utils.con_log('Package "' + pre.value + '" required for "' + id + '" - ignoring package!')
            return False
    
    # First read through all the components we have, so we can match overrides to the originals
    for comp_type in obj_types:
        for object in Property.find_all(info, comp_type):
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
                obj[comp_type][id] = (zip, object)

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
            self.config = Property('ItemData', [])
        else:
            self.config = Property('ItemData', config)
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a style definition.'''
        name, short_name, auth, icon, desc = get_selitem_data(info)
        base = info['base', 'NONE']
        
        sugg = info.find_key('suggested', [])
        sugg = (sugg['quote',''], sugg['music',''], sugg['skybox',''], sugg['goo',''])
        
        if short_name == '':
            short_name = None
        if base == 'NONE':
            base = None
        files = zip.namelist()
        folder = 'styles/' + info['folder']
        config = folder + '/vbsp_config.cfg'
        with zip.open(folder + '/items.txt', 'r') as item_data:
            items = Property.parse(item_data)
        if config in files:
            with zip.open(config, 'r') as vbsp_config:
                vbsp = Property.parse(vbsp_config)
        else:
            vbsp = None
        return cls(id, name, auth, desc, icon, items, vbsp, base, short_name=short_name, suggested=sugg)
        
    def add_over(self, overide):
        '''Add the additional commands to ourselves.'''
        pass
        
    def __repr__(self):
        return '<Style:' + self.id + '>'

class Item:
    def __init__(self, id, versions):
        self.id=id
        self.versions=versions
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse an item definition.'''
        versions = []
        folders = {}
        
        for ver in info.find_all("version"):
            vals = {}
            vals['name'] = ver['name', '']
            vals['is_beta'] = ver['deta', '0'] == '1'
            vals['is_dep'] = ver['deprecated', '0'] == '1'
            
            vals['styles'] = {}
            for sty_list in ver.find_all('styles'):
                for sty in sty_list:
                    vals['styles'][sty.name.casefold()] = sty.value
                    folders[sty.value.casefold()] = True
            versions.append(vals)
        for fold in folders:
            files = zip.namelist()
            props = 'items/' + fold + '/properties.txt'
            editor = 'items/' + fold + '/editoritems.txt'
            config = 'items/' + fold + '/vbsp_config.cfg'
            if props in files and editor in files:
                with zip.open(props, 'r') as prop_file:
                    props = Property.find_key(Property.parse(prop_file), 'Properties')
                with zip.open(editor, 'r') as editor_file:
                    editor = Property.parse(editor_file)
                folders[fold] = {
                        'auth': props['authors', ''].split(', '),
                        'tags': props['tags', ''].split(';'),
                        'desc': '\n'.join(p.value for p in props.find_all('description')),
                        'ent':  props['ent_count', '0'],
                        'url':  props['infoURL', 'NONE'],
                        'icons': {p.name:p.value for p in props['icon', []]},
                        'editor': list(Property.find_all(editor, 'Item')),
                        'vbsp': None
                       }
                if config in files:
                    with zip.open(config, 'r') as vbsp_config:
                        folders[fold]['vbsp'] = Property.parse(vbsp_config)
        for ver in versions:
            for sty, fold in ver['styles'].items():
                ver['styles'][sty] = folders[fold]
        return cls(id, versions)
        
    def add_over(self, overide):
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
            config = Property.parse(conf)
        
        return cls(id, name, config, icon, desc, auth=auth, short_name=short_name)
        
    def add_over(self, overide):
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
                config = []
        return cls(id, name, icon, config, mat, auth, desc, short_name)
        
    def add_over(self, override):
        '''Add the additional vbsp_config commands to ourselves.'''
        for zip, sky in override:
            self.auth.extend(sky.auth)
            self.config.extend(sky.config)
    
    def __repr__(self):
        return '<Skybox ' + self.id + '>'
        
class Goo:
    def __init__(self, id, name, ico, mat, mat_cheap, auth, desc, short_name=None):
        self.id=id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.material = mat
        self.cheap_material = mat_cheap
        self.auth = auth
        self.desc = desc
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a goo definition.'''
        config_dir = info['config', '']
        name, short_name, auth, icon, desc = get_selitem_data(info)
        mat = info['material', 'nature/toxicslime_a2_bridge_intro']
        mat_cheap = info['material_cheap', mat]
        return cls(id, name, icon, mat, mat_cheap, auth, desc, short_name)
        
    def add_over(self, override):
        '''Add the additional vbsp_config commands to ourselves.'''
        pass
    
    def __repr__(self):
        return '<Goo ' + self.id + '>'
  
class Music:
    def __init__(self, id, name, ico, inst, auth, desc, short_name=None):
        self.id=id
        self.short_name = name if short_name is None else short_name
        self.name = name
        self.icon = ico
        self.inst = inst
        self.auth = auth
        self.desc = desc
     
    @classmethod
    def parse(cls, zip, id, info):
        '''Parse a music definition.'''
        config_dir = info['config', '']
        name, short_name, auth, icon, desc = get_selitem_data(info)
        inst = info['instance']
        return cls(id, name, icon, inst, auth, desc, short_name)
        
    def add_over(self, override):
        '''Add the additional vbsp_config commands to ourselves.'''
        pass
    
    def __repr__(self):
        return '<Music ' + self.id + '>'
        
def get_selitem_data(info):
    '''Return the common data for all item types - name, author, description.'''
    auth = info['authors', ''].split(', ')
    # Multiple description lines will be joined together, for easier multi-line writing.""
    desc = '\n'.join(prop.value for prop in info if prop.name.casefold()=="description" or prop.name.casefold()=="desc")
    desc = desc.replace("[*]", "\x07") # Convert [*] into the bullet character
    short_name = info['shortName', None]
    name = info['name']
    icon = info['icon', '_blank']
    return name, short_name, auth, icon, desc
            
obj_types = {
    'Style' : Style,
    'Item' : Item,
    'QuotePack': Voice,
    'Skybox': Skybox,
    'Goo' : Goo,
    'Music' : Music
    }
    
if __name__ == '__main__':
    loadAll('packages\\')