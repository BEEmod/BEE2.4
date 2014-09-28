import os
import os.path
import sys

from property_parser import Property
import utils

instances=[]
overlays=[]
other_ents=[]

TEX_VALVE = { # all the textures produced by the Puzzlemaker, and their replacement keys:
    "metal/black_floor_metal_001c"                           : "blackFloor",
    "tile/white_floor_tile002a"                              : "whiteFloor",
    "tile/white_wall_tile003f"                               : "whiteWall",
    "tile/white_wall_tile003a"                               : "whiteWall",
    "tile/white_wall_tile003h"                               : "whiteWall",
    "tile/white_wall_tile003c"                               : "whiteWall",
    "metal/black_wall_metal_002c"                            : "blackWall",
    "metal/black_wall_metal_002e"                            : "blackWall",
    "metal/black_wall_metal_002a"                            : "blackWall",
    "metal/black_wall_metal_002b"                            : "blackWall",
    "anim_wp/framework/backpanels_cheap"                     : "behind",
    "plastic/plasticwall004a"                                : "pedestalSide",
    "anim_wp/framework/squarebeams"                          : "edge",
    "signage/indicator_lights/indicator_lights_floor"        : "antline",
    "signage/indicator_lights/indicator_lights_corner_floor" : "antlineCorner",
    "signage/signage_exit"                                   : "signExit",
    "signage/signage_overlay_arrow"                          : "signArrow",
    "signage/signage_overlay_catapult1"                      : "signCatapult1",
    "signage/signage_overlay_catapult2"                      : "signCatapult2",
    "signage/shape01"                                        : "shapeDot",
    "signage/shape02"                                        : "shapeMoon",
    "signage/shape03"                                        : "shapeTriangle",
    "signage/shape04"                                        : "shapeCross",
    "signage/shape05"                                        : "shapeSquare",
    "signage/signage_shape_circle"                           : "shapeCircle",
    "signage/signage_shape_sine"                             : "shapeSine",
    "signage/signage_shape_slash"                            : "shapeSlash",
    "signage/signage_shape_star"                             : "shapeStar",
    "signage/signage_shape_wavy"                             : "shapeWavy",
    "nature/toxicslime_a2_bridge_intro"                      : "goo",
    "glass/glasswindow007a_less_shiny"                       : "glass",
    "metal/metalgrate018"                                    : "grating",
    "effects/fizzler_l"                                      : "fizzlerLeft",
    "effects/fizzler_r"                                      : "fizzlerRight",
    "effects/fizzler_center"                                 : "fizzlerCenter",
    "effects/fizzler"                                        : "fizzlerShort",
    "effects/laserplane"                                     : "laserField",
    }

def load_settings():
    global settings
    with open("vbsp_config.cfg", "r"):
        conf=Property.parse(settings)
    settings = {}
    for item in conf: # convert properties into simpler dictionary
        if settings.has_key(item.name):
            settings[item.name].append(item.value)
        else:
            settings[item.name]=[item.value] # all values are a list of the different ones used
    
def load_map():
    global map
    path = "preview_test.vmf"
    #path="F:\SteamLibrary\SteamApps\common\Portal 2\sdk_content\maps\preview.vmf"
    with open(path, "r") as file:
        map=Property.parse(file)
    

def load_entities():
    global instances, overlays, other_ents
    ents=Property.find_all(map,'entity')
    for item in ents:
        name=Property.find_all(item, 'entity"targetname')
        cls=Property.find_all(item, 'entity"classname')
        if len(cls)==1:
            item.cls=cls[0].value
        else:
            print("Error - entity missing class!")
            continue
        if len(name)==1:
            item.targname=name[0].value
        else:
            item.targname=""
            
        if item.cls=="func_instance":
            instances.append(item)
        elif item.cls=="info_overlay":
            overlays.append(item)
        else:
            other_ents.append(item)
    
def change_tex():
       
load_map()
load_entities()