import os
import os.path
import zipfile

from property_parser import Property
import utils

class Palette:
    def __init__(name, rows, options):
        self.opt=options
        self.name=name
        self.rows=rows

def loadAll(dir):
    "Scan and read in all palettes in the specified directory."
    dir=os.path.join(os.getcwd(),dir)
    print(dir)
    contents=os.listdir(dir) # this is both files and dirs
    palettes=[]
    for name in contents:
        print("Loading '"+name+"'")
        name=os.path.join(dir,name)
        if name.endswith('.zip'): #zipfile.is_zipfile(name):
            with zipfile.ZipFile(name, 'r') as zip:
                if 'positions.txt' in zip.namelist() and 'properties.txt' in zip.namelist(): # Is it valid?
                    pal=parse(zip.open('positions.txt', 'r'),zip.open('properties.txt', 'r'))
                        if pal:
                            palettes.append(pal)
                else:
                    print("ERROR: Bad palette file '"+name+"'!")
        elif os.path.isdir(name)==1:
            if 'positions.txt' in os.listdir(name) and 'properties.txt' in os.listdir(name): # Is it valid?
                with open(os.path.join(name,'positions.txt'), 'r') as pos:
                    with open(os.path.join(name,'properties.txt'), 'r') as prop:
                        pal=parse(pos,prop)
                        if pal:
                            palettes.append(pal)
    return palettes
    
def parse(posfile, propfile):
    "Parse through the given palette file to get all data."
    props=Property.parse(propfile)
    name=props.find_all("Name")
    if len(name)==1:
        name=name[0]
    else:
        print("Palettes may only have 1 name!")
        return False
    rows=[]
    for dirty_line in posfile:
        line=utils.clean_line(dirty_line)
        if line:
            if line.startswith('"'):
                val=line.split('",')
                if len(val)==2:
                    rows.append([val[0][1:],int(val[1].strip())])
                else:
                    print("Malformed row '"+line+"'!")
                    return False

    
def readKey(prop, key, default):
    val=prop.find_all(key)
    if len(val)==0:
        return default
    if len(val)==1:
        return val[0]
    if len(val)>1:
        return val
    
    
if __name__ == '__main__':
    file=loadAll('palettes\\')