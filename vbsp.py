import os
import os.path
import sys

from property_parser import Property
import utils
import random

instances=[] # All instances
overlays=[]
brushes=[] # All world and func_detail brushes generated
detail=[]
other_ents=[] # anything else, including some logic_autos, func_brush, trigger_multiple, trigger_hurt, trigger_portal_cleanser, etc

TEX_VALVE = { # all the textures produced by the Puzzlemaker, and their replacement keys:
    "metal/black_floor_metal_001c"       : "blackFloor",
    "tile/white_floor_tile002a"          : "whiteFloor",
    "tile/white_wall_tile003f"           : "whiteWall",
    "tile/white_wall_tile003a"           : "whiteWall",
    "tile/white_wall_tile003h"           : "whiteWall",
    "tile/white_wall_tile003c"           : "whiteWall",
    "metal/black_wall_metal_002c"        : "blackWall",
    "metal/black_wall_metal_002e"        : "blackWall",
    "metal/black_wall_metal_002a"        : "blackWall",
    "metal/black_wall_metal_002b"        : "blackWall",
    "anim_wp/framework/backpanels_cheap" : "behind",
    "plastic/plasticwall004a"            : "pedestalSide",
    "anim_wp/framework/squarebeams"      : "edge",
    "signage/signage_exit"               : "signExit",
    "signage/signage_overlay_arrow"      : "signArrow",
    "signage/signage_overlay_catapult1"  : "signCatapultFling",
    "signage/signage_overlay_catapult2"  : "signCatapultLand",
    "signage/shape01"                    : "shapeDot",
    "signage/shape02"                    : "shapeMoon",
    "signage/shape03"                    : "shapeTriangle",
    "signage/shape04"                    : "shapeCross",
    "signage/shape05"                    : "shapeSquare",
    "signage/signage_shape_circle"       : "shapeCircle",
    "signage/signage_shape_sine"         : "shapeSine",
    "signage/signage_shape_slash"        : "shapeSlash",
    "signage/signage_shape_star"         : "shapeStar",
    "signage/signage_shape_wavy"         : "shapeWavy",
    "nature/toxicslime_a2_bridge_intro"  : "goo",
    "glass/glasswindow007a_less_shiny"   : "glass",
    "metal/metalgrate018"                : "grating",
    "effects/fizzler_l"                  : "fizzlerLeft",
    "effects/fizzler_r"                  : "fizzlerRight",
    "effects/fizzler_center"             : "fizzlerCenter",
    "effects/fizzler"                    : "fizzlerShort",
    "effects/laserplane"                 : "laserField",
    "tools/toolsnodraw"                  : "nodraw" # Don't know why someone would want to change this, but anyway...
    }
ANTLINE_STRAIGHT = "signage/indicator_lights/indicator_lights_floor"
ANTLINE_CORNER   = "signage/indicator_lights/indicator_lights_corner_floor" # these need to be handled seperately to accomadate the scale-changing

def load_settings():
    global settings
    with open("vbsp_config.cfg", "r") as config: # this should be outputted when editoritems is exported, so we don't have to trawl through editoritems to find our settings.
        conf=Property.parse(config)
    settings = {}
    for item in conf: # convert properties into simpler dictionary
        if item.name in settings:
            settings[item.name].append(item.value)
        else:
            settings[item.name]=[item.value] # all values are a list of the different ones used
    
     
    for mat in TEX_VALVE.keys() : # add the default to the config if not present already
        if not TEX_VALVE[mat] in settings:
            settings[TEX_VALVE[mat]]=[mat]
    
def load_map():
    global map
    path = "preview_test.vmf"
    #path="F:\SteamLibrary\SteamApps\common\Portal 2\sdk_content\maps\preview.vmf"
    with open(path, "r") as file:
        map=Property.parse(file)
    

def load_entities():
    "Read through all the entities and sort to different lists based on classname"
    
    ents=Property.find_all(map,'entity')
    for item in ents:
        name=Property.find_all(item, 'entity"targetname')
        cls=Property.find_all(item, 'entity"classname')
        if len(cls)==1:
            item.cls=cls[0].value
        else:
            print("Error - entity missing class, skipping!")
            continue
        if len(name)==1:
            item.targname=name[0].value
        else:
            item.targname=""
            
        if item.cls=="func_instance":
            instances.append(item)
        elif item.cls=="info_overlay":
            overlays.append(item)
        elif item.cls=="func_detail":
            detail.append(item)
        else:
            other_ents.append(item)
    
def change_brush():
    "Alter all world/detail brush textures to use the configured ones."
    sides=Property.find_all(map, 'world"solid"side') + Property.find_all(detail, 'entity"solid"side')
    for face in sides:
        mat=Property.find_all(face, 'side"material')
        if len(mat)==1:
            mat=mat[0]
            if mat.value.casefold() in TEX_VALVE: # should we convert it?
                mat.value = random.choice(settings[TEX_VALVE[mat.value.casefold()].casefold()])
            else:
                print("Unknown tex: "+mat.value)
                
def save():
    out = []
    for p in map:
        for s in p.to_strings():
            out.append(s + '\n')
    with open('preview_styled.vmf', 'w') as f:
        f.writelines(out)
        
for func in (load_settings, load_map, load_entities, change_brush, save):
    func()