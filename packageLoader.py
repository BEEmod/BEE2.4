'''
Handles scanning through the zip packages to find all items, styles, voice lines, etc.
'''
import os
import os.path
import zipfile

from property_parser import Property
import utils

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
                zip = zipfile.ZipFile(name, 'r')
                zips.append(zip)
                if 'info.txt' in zip.namelist(): # Is it valid?
                    info=Property.parse(zip.open('info.txt', 'r'))
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
                data[type].append(obj_types[type].parse(object[0], id, object[1], over))
    finally:
        for z in zips: #close them all, we've already read the contents.
            z.close()
        
def parse_package(zip, info, filename, id):
    "Parse through the given package to find all the components."
    for pre in Property.find_key(info, 'Prerequisites', []).value:
        if pre.value not in packages:
            utils.con_log('Package "' + pre.value + '" required for "' + id + '" - ignoring package!')
            return False
    
    # First read through all the components we have, so we can match overrides to the originals
    for comp_type in obj_types:
        for object in Property.find_all(info, comp_type):
            id = object.find_key('id').value
            is_sub = object.find_key('overrideOrig', '0') == '1'
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
    def __init__(self, id):
        self.id=id
     
    @classmethod
    def parse(cls, zip, id, info, over):
        '''Parse a style definition.'''
        return cls(id)
    
    def __str__(self):
        return '<Style>' + self.id

class Item:
    def __init__(self, id):
        self.id=id
     
    @classmethod
    def parse(cls, zip, id, info, over):
        '''Parse an item definition.'''
        return cls(id)
    
    def __repr__(self):
        return '<Item>' + self.id

class Voice:
    def __init__(self, id, name, icon):
        self.id = id
        self.name = name
        self.icon = icon
     
    @classmethod
    def parse(cls, zip, id, info, over):
        '''Parse a voice line definition.'''
        name = info.find_key('name').value
        icon = info.find_key('icon', '_blank').value
        return cls(id, name, icon)
    
    def __repr__(self):
        return '<Voice Pack>' + self.id

class Skybox:
    def __init__(self, id):
        self.id=id
     
    @classmethod
    def parse(cls, zip, id, info, over):
        '''Parse a skybox definition.'''
        return cls(id)
    
    def __repr__(self):
        return '<Skybox>' + self.id
            
obj_types = {
    'Style' : Style,
    'Item' : Item,
    'QuotePack': Voice,
    'Skybox': Skybox
    }

    
if __name__ == '__main__':
    loadAll('packages\\')