import os
import os.path
import zipfile

from property_parser import Property
import utils

class Palette:
    def __init__(self, name, pos, options):
        self.opt=options
        self.name=name
        self.pos=pos
    def getName(self):
        return self.name
    def __str__(self):
        return self.name

def loadAll(dir):
    "Scan and read in all palettes in the specified directory."
    dir=os.path.join(os.getcwd(),dir)
    contents=os.listdir(dir) # this is both files and dirs
    palettes=[]
    for name in contents:
        print("Loading '"+name+"'")
        name=os.path.join(dir,name)
        if name.endswith('.zip'):
            with zipfile.ZipFile(name, 'r') as zip:
                if 'positions.txt' in zip.namelist() and 'properties.txt' in zip.namelist(): # Is it valid?
                    pal=parse(zip.open('positions.txt', 'r'),zip.open('properties.txt', 'r'))
                    if pal!=False:
                        palettes.append(pal)
                else:
                    print("ERROR: Bad palette file '"+name+"'!")
        elif os.path.isdir(name)==1:
            if 'positions.txt' in os.listdir(name) and 'properties.txt' in os.listdir(name): # Is it valid?
                with open(os.path.join(name,'positions.txt'), 'r') as pos:
                    with open(os.path.join(name,'properties.txt'), 'r') as prop:
                        pal=parse(pos,prop)
                        if pal!=False:
                            palettes.append(pal)
    return palettes
    
def parse(posfile, propfile):
    "Parse through the given palette file to get all data."
    props=Property.parse(propfile)
    name=Property.find_key(props, "Name").value
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
    return Palette(name, pos, [])
    
    
if __name__ == '__main__':
    file=loadAll('palettes\\')