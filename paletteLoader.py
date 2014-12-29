import os
import os.path
import io
import zipfile
import shutil

from property_parser import Property
import utils

pal_dir = "palettes\\"

pal_list = []

class Palette:
    def __init__(self, name, pos, options=None, filename=None):
        self.opt={} if options is None else options
        self.name=name
        self.filename = name if filename is None else filename
        self.pos=pos
        
    def getName(self):
        return self.name
        
    def __str__(self):
        return '<Pal: "' + self.name + '">'
        
    def save(self, allow_overwrite, name=None):
        '''Save the palette file into the specified location.'''
        print('Saving "' + self.name + '"!')
        if name is None:
            name = self.filename
        is_zip = name.endswith('.zip')
        path = os.path.join(pal_dir, name)
        if not allow_overwrite:
            if os.path.isdir(path) or os.path.isfile(path):
                print('"' + name + '" exists already!')
                return False
        try:
            if is_zip:
                pos_file = io.StringIO()
                prop_file = io.StringIO()
            else:
                if not os.path.isdir(path):
                    os.mkdir(path)
                pos_file = open(os.path.join(path,'positions.txt'), 'w')
                prop_file = open(os.path.join(path,'properties.txt'), 'w')
            
            for ind, row in enumerate(self.pos):
                if ind%4 == 0:
                    if ind != 0:
                        pos_file.write('\n') # Don't start the file with a newline
                    pos_file.write("//Row " + str(ind//4) + '\n')
                pos_file.write('"' + row[0] + '", ' + str(row[1]) + '\n')
            
            prop_file.write('"Name" "' + self.name + '"\n')
            for opt, val in self.opt.items():
                prop_file.write('"' + opt + '" "' + val + '"\n')
                
            if is_zip:
                with zipfile.ZipFile(path, 'w') as zip:
                    zip.writestr('properties.txt', prop_file.getvalue())
                    zip.writestr('positions.txt', pos_file.getvalue())
        finally:
            pos_file.close()
            prop_file.close()
            
    def delete_from_disk(self, name=None):
        '''Delete this palette from disk.'''
        if name is None:
            name = self.filename
        is_zip = name.endswith('.zip')
        path = os.path.join(pal_dir, name)
        if is_zip:
            os.remove(path)
        else:
            shutil.rmtree(path)

def loadAll(dir):
    "Scan and read in all palettes in the specified directory."
    global pal_dir, pal_list
    pal_dir = dir
    dir=os.path.join(os.getcwd(),dir)
    contents=os.listdir(dir) # this is both files and dirs
   
    pal_list=[]
    for name in contents:
        print("Loading '"+name+"'")
        path=os.path.join(dir,name)
        if name.endswith('.zip'):
            with zipfile.ZipFile(path, 'r') as zip:
                if 'positions.txt' in zip.namelist() and 'properties.txt' in zip.namelist(): # Is it valid?
                    pal=parse(zip.open('positions.txt', 'r'), zip.open('properties.txt', 'r'), name)
                    if pal!=False:
                        pal_list.append(pal)
                else:
                    print("ERROR: Bad palette file '"+name+"'!")
        elif os.path.isdir(path)==1:
            if 'positions.txt' in os.listdir(path) and 'properties.txt' in os.listdir(path): # Is it valid?
                with open(os.path.join(path,'positions.txt'), 'r') as pos:
                    with open(os.path.join(path,'properties.txt'), 'r') as prop:
                        pal=parse(pos, prop, name)
                        if pal!=False:
                            pal_list.append(pal)
    return pal_list
    
def parse(posfile, propfile, path):
    "Parse through the given palette file to get all data."
    props=Property.parse(propfile, path + ':properties.txt')
    name="Unnamed"
    opts = {}
    for option in props:
        if option.name.casefold() == "name":
            name = option.value
        else:
            opts[option.name.casefold()] = option.value
    pos=[]
    for dirty_line in posfile:
        line=utils.clean_line(dirty_line)
        if line:
            if line.startswith('"'):
                val=line.split('",')
                if len(val)==2:
                    pos.append([val[0][1:],int(val[1].strip())])
                else:
                    print("Malformed row '"+line+"'!")
                    return False
    return Palette(name, pos, opts, filename=path)
    
def save_pal(items, name):
    '''Save a palette under the specified name.'''
    pos = [(it.id, it.subKey) for it in items]
    print(name, pos, name, [])
    new_palette = Palette(name, pos)
    
    for pal in pal_list[:]:
        if pal.name == name:
            pal_list.remove(name)
    pal_list.append(new_palette)
    return new_palette.save(allow_overwrite=False) 
    
if __name__ == '__main__':
    file=loadAll('palettes\\')