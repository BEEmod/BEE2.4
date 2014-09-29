import os
import os.path
import sys

from property_parser import Property
import utils
import random

instances=[] # All instances
overlays=[]
brushes=[] # All world and func_detail brushes generated
f_brushes=[] # Func_brushes
detail=[]
triggers=[]
other_ents=[] # anything else, including some logic_autos, func_brush, trigger_multiple, trigger_hurt, trigger_portal_cleanser, etc

CONN_SEP = chr(27) # non-printing char VMFs use to sepearte parts of outputs.

HAS_MAT={ # autodetect these and add to a logic_auto to notify the voices of it
         "glass"      : 0,
         "goo"        : 0,
         "grating"    : 0,
         "fizzler"    : 0,
         "laserfield" : 0
         }

TEX_VALVE = { # all the textures produced by the Puzzlemaker, and their replacement keys:
    "metal/black_floor_metal_001c"       : "blackfloor",
    "tile/white_floor_tile002a"          : "whitefloor",
    "tile/white_wall_tile003f"           : "whitewall_4",
    "tile/white_wall_tile003a"           : "whitewall",
    "tile/white_wall_tile003h"           : "whitewall",
    "tile/white_wall_tile003c"           : "whitewall_2",
    "metal/black_wall_metal_002c"        : "blackwall",
    "metal/black_wall_metal_002e"        : "blackwall",
    "metal/black_wall_metal_002a"        : "blackwall_2",
    "metal/black_wall_metal_002b"        : "blackwall_4",
    "anim_wp/framework/backpanels_cheap" : "behind",
    "plastic/plasticwall004a"            : "pedestalside",
    "anim_wp/framework/squarebeams"      : "edge",
    "signage/signage_exit"               : "signexit",
    "signage/signage_overlay_arrow"      : "signarrow",
    "signage/signage_overlay_catapult1"  : "signcatapultfling",
    "signage/signage_overlay_catapult2"  : "signcatapultland",
    "signage/shape01"                    : "shapedot",
    "signage/shape02"                    : "shapemoon",
    "signage/shape03"                    : "shapetriangle",
    "signage/shape04"                    : "shapecross",
    "signage/shape05"                    : "shapesquare",
    "signage/signage_shape_circle"       : "shapecircle",
    "signage/signage_shape_sine"         : "shapesine",
    "signage/signage_shape_slash"        : "shapeslash",
    "signage/signage_shape_star"         : "shapestar",
    "signage/signage_shape_wavy"         : "shapewavy",
    "nature/toxicslime_a2_bridge_intro"  : "goo",
    "glass/glasswindow007a_less_shiny"   : "glass",
    "metal/metalgrate018"                : "grating",
    "effects/fizzler_l"                  : "fizzlerleft",
    "effects/fizzler_r"                  : "fizzlerright",
    "effects/fizzler_center"             : "fizzlercenter",
    "effects/fizzler"                    : "fizzlershort",
    "effects/laserplane"                 : "laserfield",
    "tools/toolsnodraw"                  : "nodraw" # Don't know why someone would want to change this, but anyway...
    }
ANTLINES = {
    "signage/indicator_lights/indicator_lights_floor" : "antline",
    "signage/indicator_lights/indicator_lights_corner_floor" : "antlineCorner"
    } # these need to be handled seperately to accomadate the scale-changing

DEFAULTS = {
    "bottomless_pit"          : 0,
    "remove_info_lighting"    : 0,
    "fix_glass"               : 0,
    "random_black_wall_scale" : 0,
    "use_screenshot"          : 0,
    "run_bsp_zip"             : 0,
    "fizzler_scanline"        : 1,
    "force_fizz_reflect"      : 0,
    "force_brush_reflect"     : 0,
    }
    
fizzler_angle_fix = {
    "0 0 -90"   : "0 180 90",
    "-90 -90 0" : "90 90 0",
    "0 0 90"    : "0 180 -90",
    "90 -90 0"  : "-90 90 0",
    "90 180 0"  : "-90 0 0",
    "0 90 -90"  : "0 -90 90",
    "-90 180 0" : "90 0 0",
    "0 -90 -90" : "0 90 90"
    }
    
    
def alter_mat(prop):
    if prop.value.casefold() in TEX_VALVE: # should we convert it?
        prop.value = random.choice(settings[TEX_VALVE[prop.value.casefold()].casefold()])

def load_settings():
    global settings
    with open("vbsp_config.cfg", "r") as config: # this should be outputted when editoritems is exported, so we don't have to trawl through editoritems to find our settings.
        conf=Property.parse(config)
    print("Settings Loaded!")
    settings = {}
    for item in conf: # convert properties into simpler dictionary
        if item.name.casefold() in settings:
            settings[item.name.casefold()].append(item.value)
        else:
            settings[item.name.casefold()]=[item.value] # all values are a list of the different ones used
    
    for opt in DEFAULTS.keys() :  # add the default to the config if not present already
        if not opt in settings:
            settings[opt]=[str(DEFAULTS[opt])] 
            
    for mat in TEX_VALVE.keys() :
        if not TEX_VALVE[mat] in settings:
            settings[TEX_VALVE[mat]]=[str(mat)]
            
    for mat in ANTLINES.keys() : 
        if not ANTLINES[mat] in settings:
            settings[ANTLINES[mat]]=[mat]
    
def load_map():
    global map
    path = sys.argv
    print(path)
    path="preview_test.vmf"
    #path="F:\SteamLibrary\SteamApps\common\Portal 2\sdk_content\maps\preview.vmf"
    with open(path, "r") as file:
        print("Parsing Map...")
        map=Property.parse(file)
    

def load_entities():
    "Read through all the entities and sort to different lists based on classname"
    print("Scanning Entities...")
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
        elif item.cls=="func_detail" or item.cls=="func_rotating": # 2nd is not detail, but it's the easiest way to convert those textures.
            detail.append(item)
        elif item.cls in ("trigger_portal_cleanser", "trigger_hurt", "trigger_multiple"):
            triggers.append(item)
        elif item.cls=="func_brush":
            f_brushes.append(item)
        else:
            other_ents.append(item)
    
def change_brush():
    "Alter all world/detail brush textures to use the configured ones."
    print("Editing Brushes...")
    sides=Property.find_all(map, 'world"solid"side') + Property.find_all(detail, 'entity"solid"side')
    for face in sides:
        mat=Property.find_all(face, 'side"material')
        if len(mat)==1:
            alter_mat(mat[0])
    
def change_overlays():
    "Alter the overlays."
    print("Editing Overlays...")
    for over in overlays:
        mat=Property.find_all(over, 'entity"material')
        if len(mat)==1:
            mat=mat[0]
            alter_mat(mat)
            if mat.value.casefold() in ANTLINES:
                angle = Property.find_all(over, 'entity"angles')
                if len(angle)==1:
                    angle=angle[0].value.split(" ") # get the three parts
                    #TODO : analyse this, determine whether the antline is on the floor or wall (for P1 style)
                new_tex = random.choice(settings[ANTLINES[mat.value.casefold()].casefold()]).split("|")
                if len(new_tex)==2:
                    if len(Property.find_all(over, 'entity"endu')) == 1: # rescale antlines if needed
                        Property.find_all(over, 'entity"endu')[0].value=new_tex[0]
                    mat.value=new_tex[1]
                else:
                    mat.value=new_tex
    
def change_trig():
    "Check the triggers and fizzlers."
    print("Editing Triggers...")
    for trig in triggers:
        if trig.cls=="trigger_portal_cleanser":
            sides=Property.find_all(trig, 'entity"solid"side"material')
            for mat in sides:
                alter_mat(mat)
            use_scanline = Property.find_all(trig, 'entity"useScanline')
            if len(use_scanline) == 1:
                use_scanline[0].value = settings["fizzler_scanline"][0]
            fast_ref = Property.find_all(trig, 'entity"drawInFastReflection')
            if len(fast_ref) == 1:
                fast_ref[0].value = settings["force_fizz_reflect"][0]

def change_func_brush():
    "Edit func_brushes."
    print("Editing Brush Entities...")
    for brush in f_brushes:
        sides=Property.find_all(brush, 'entity"solid"side"material')
        for mat in sides:
            alter_mat(mat)
        fast_ref = Property.find_all(brush, 'entity"drawInFastReflection')
        if len(fast_ref) == 1:
            fast_ref[0].value = settings["force_brush_reflect"][0]
            print(fast_ref[0].value)
        else:
            brush.value.append(Property("drawinfastreflection", settings["force_brush_reflect"][0]))
            
def change_ents():
    "Edit misc entities."
    print("Editing Other Entities...")
    to_rem=[] # entities to delete
    for ent in other_ents:
        if ent.cls == "info_lighting" and (settings["remove_info_lighting"][0]=="1"):
            to_rem.append(ent) # styles with brush-based glass edges don't need the info_lighting, delete it to save ents.
    for rem in to_rem:
        map.remove(rem) # need to delete it from the map's list tree for it to not be outputted
    del to_rem

def fix_inst():
    "Fix some different bugs with instances, especially fizzler models."
    for inst in instances:
        if "_modelStart" in inst.targname or "_modelEnd" in inst.targname:
            print(inst.targname)
            name=Property.find_all(inst, 'entity"targetname')[0]
            if "_modelStart" in inst.targname: # strip off the extra numbers on the end, so fizzler models recieve inputs correctly
                name.value = inst.targname.split("_modelStart")[0] + "_modelStart" 
            else:
                name.value = inst.targname.split("_modelEnd")[0] + "_modelEnd" 
            # one side of the fizzler models are rotated incorrectly (upsidown), fix that...
            angles=Property.find_all(inst, 'entity"angles')[0]
            if angles.value in fizzler_angle_fix.keys():
                angles.value=fizzler_angle_fix[angles.value]

                
def save():
    out = []
    print("Saving New Map...")
    for p in map:
        for s in p.to_strings():
            out.append(s + '\n')
    with open("F:\SteamLibrary\SteamApps\common\Portal 2\sdk_content\maps\styled\preview.vmf", 'w') as f:
        f.writelines(out)
    print("Complete!")
        
for func in (load_settings, load_map, load_entities, change_brush, change_overlays, change_trig, change_func_brush, change_ents, fix_inst, save):
    func()