import os
import os.path
import sys

from property_parser import Property
import utils

def load_map():
    global map
    path = "preview_test.vmf"
    #path="F:\SteamLibrary\SteamApps\common\Portal 2\sdk_content\maps\preview.vmf"
    file=open(path, "r")
    map=Property.parse(file)

def load_instances():
    global instances
    instances=[]
    ents=Property.find_all(map,'entity')
    for item in ents:
        print(Property.find_all(ents, 'classname'))
       
load_map()
load_instances()