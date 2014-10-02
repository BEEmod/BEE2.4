import os
import os.path
import sys
import subprocess
import shutil
import random

from property_parser import Property
import utils

instances=[] # All instances
overlays=[]
brushes=[] # All world and func_detail brushes generated
f_brushes=[] # Func_brushes
detail=[]
triggers=[]
other_ents=[] # anything else, including some logic_autos, func_brush, trigger_multiple, trigger_hurt, trigger_portal_cleanser, etc
unique_counter=0 # counter for instances to ensure unique targetnames
max_ent_id = 1 # maximum known entity id, so we know what we can set new ents to be.

HAS_MAT={ # autodetect these and add to a logic_auto to notify the voices of it
         "glass"   : 0,
         "goo"     : 0,
         "grating" : 0,
         "fizzler" : 0,
         "laser"   : 0,
         "deadly"  : 0, # also if laserfield exists
         }

TEX_VALVE = { # all the textures produced by the Puzzlemaker, and their replacement keys:
    "metal/black_floor_metal_001c"       : "blackfloor",
    "tile/white_floor_tile002a"          : "whitefloor",
    "metal/black_floor_metal_001c"       : "blackceiling",
    "tile/white_floor_tile002a"          : "whiteceiling",
    "tile/white_wall_tile003a"           : "whitewall",
    "tile/white_wall_tile003h"           : "whitewall",
    "tile/white_wall_tile003c"           : "white_2",
    "tile/white_wall_tile003f"           : "white_4",
    "metal/black_wall_metal_002c"        : "blackwall",
    "metal/black_wall_metal_002e"        : "blackwall",
    "metal/black_wall_metal_002a"        : "black_2",
    "metal/black_wall_metal_002b"        : "black_4",
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
    "BEE2/fizz/lp/death_field_clean_"    : "lp_death_field", # + short/left/right/center
    "effects/laserplane"                 : "laserfield",
    "tools/toolsnodraw"                  : "nodraw" # Don't know why someone would want to change this, but anyway...
    }
WHITE_PAN = ["tile/white_floor_tile002a",
             "tile/white_wall_tile003a", 
             "tile/white_wall_tile003h", 
             "tile/white_wall_tile003c", 
             "tile/white_wall_tile003f"
            ]
BLACK_PAN = [
             "metal/black_floor_metal_001c", 
             "metal/black_wall_metal_002c", 
             "metal/black_wall_metal_002e", 
             "metal/black_wall_metal_002a", 
             "metal/black_wall_metal_002b"
            ]

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
    "remove_exit_signs"       : 0,
    "force_paint"             : 0,
    "change_fizz_inst"        : 0,
    "sky"                     : "sky_black",
    "glass_scale"             : "0.15",    
    "blackfloor"              : "metal/black_floor_metal_001c", # add these to make sure they overide if none specified
    "whitefloor"              : "tile/white_floor_tile002a",
    "antline"                 : "0.25|signage/indicator_lights/indicator_lights_floor",
    "antlinecorner"           : "1|signage/indicator_lights/indicator_lights_corner_floor"
    }
    
fizzler_angle_fix = { # angles needed to ensure fizzlers are not upsidown (key=original, val=fixed)
    "0 0 -90"   : "0 180 90",
    "0 0 180"   : "0 180 180",
    "0 90 0"    : "0 -90 0",
    "0 90 -90"  : "0 -90 90",
    "0 180 -90" : "0 0 90",
    "0 -90 -90" : "0 90 90",
    "90 180 0"  : "-90 0 0",
    "90 -90 0"  : "-90 90 0",
    "-90 180 0" : "90 0 0",
    "-90 -90 0" : "90 90 0",
    }

DEATH_FIZZLER_SUFFIX = {
    "effects/fizzler_center" : "center",
    "effects/fizzler_l"      : "left",
    "effects/fizzler_r"      : "right",
    "effects/fizzler"        : "short"
    }
 
def unique_id():
    "Return a unique prefix so we ensure instances don't overlap if making them."
    global unique_counter
    unique_counter+=1
    return str(unique_counter)
   
def log(text):
    print(text, flush=True)
    
def alter_mat(prop):
    if prop.value.casefold() in TEX_VALVE: # should we convert it?
        prop.value = random.choice(settings[TEX_VALVE[prop.value.casefold()].casefold()])

def add_output(entity, output, target, input, params="", delay="0", times="-1"):
    "Add a new output to an entity with the given values, generating a connections part if needed."
    conn = Property.find_all(entity, 'entity"connections')
    if len(conn) == 0:
        conn = Property("connections", [])
        entity.value.append(conn)
    else:
        conn = conn[0]
    out=Property(output, chr(27).join((target, input, params, delay, times)))
    # character 27 (which is the ASCII escape control character) is the delimiter for VMF outputs. 
    log("adding output :" + out.value)
    conn.value.append(out)

def find_key(ent, key):
    "Safely get a subkey from an instance (not lists of multiple). If it fails, throw an exception to crash the compiler safely."
    result = Property.find_all(ent, ent.name + '"' + key)
    if len(result) == 1:
        return result[0]
    else:
        raise ValueError("No key " + key + "!")

def load_settings():
    global settings
    with open("vbsp_config.cfg", "r") as config: # this should be outputted when editoritems is exported, so we don't have to trawl through editoritems to find our settings.
        conf=Property.parse(config)
    log("Settings Loaded!")
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
            print(mat)
            
    for mat in ANTLINES.keys() : 
        if not ANTLINES[mat] in settings:
            settings[ANTLINES[mat]]=[mat]
def load_map(path):
    global map
    with open(path, "r") as file:
        log("Parsing Map...")
        map=Property.parse(file)
    

def load_entities():
    "Read through all the entities and sort to different lists based on classname"
    global max_ent_id
    log("Scanning Entities...")
    ents=Property.find_all(map,'entity')
    for item in ents:
        name=Property.find_all(item, 'entity"targetname')
        cls=Property.find_all(item, 'entity"classname')
        id=find_key(item, 'id')
        if len(cls)==1:
            item.cls=cls[0].value
        else:
            log("Error - entity missing class, skipping!")
            continue
        if len(name)==1:
            item.targname=name[0].value
        else:
            item.targname=""
        if int(id.value):
            max_ent_id = max(max_ent_id,int(id.value))
        if item.cls=="func_instance":
            instances.append(item)
        elif item.cls=="info_overlay":
            overlays.append(item)
        elif item.cls=="func_detail":
            detail.append(item)
        elif item.cls in ("trigger_portal_cleanser", "trigger_hurt", "trigger_multiple"):
            triggers.append(item)
        elif item.cls in ("func_brush" , "func_door_rotating"):
            f_brushes.append(item)
        else:
            other_ents.append(item)
    
def change_brush():
    "Alter all world/detail brush textures to use the configured ones."
    log("Editing Brushes...")
    sides=Property.find_all(map, 'world"solid"side') + Property.find_all(detail, 'entity"solid"side')
    for face in sides:
        mat=find_key(face, 'material')   
        if mat.value.casefold()=="nature/toxicslime_a2_bridge_intro" and (settings["bottomless_pit"][0]=="1"):
            plane=find_key(face,'plane')
            pos=plane.value.split(" ")
            for i in (2,5,8): # these are the z index, but with an extra paranthesis - pos[2] = "96)", for examp
                pos[i]= str((int(pos[i][:-1])-96)) + ".1)" #split off the ), subtract 95.9 to make the brush 0.1 units thick, then add back the )
            plane.value = " ".join(pos)
            
        if mat.value.casefold()=="glass/glasswindow007a_less_shiny":
            for val in (find_key(face, 'uaxis'),find_key(face, 'vaxis')):
                split=val.value.split(" ")
                split[-1] = settings["glass_scale"][0]
                val.value=" ".join(split)
        
        is_blackceil=False # we only want to change size of black ceilings, not floor so use this flag
        if mat.value.casefold() in ("metal/black_floor_metal_001c",  "tile/white_floor_tile002a"):
            # The roof/ceiling texture are identical, we need to examine the planes to figure out the orientation!
            verts = find_key(face, 'plane').value[1:-1].split(") (") # break into 3 groups of 3d vertexes
            for i,v in enumerate(verts):
                verts[i]=v.split(" ")
            # y-val for first if < last if ceiling
            side = "ceiling" if int(verts[0][1]) < int(verts[2][1]) else "floor"
            type = "black" if mat.value.casefold() in BLACK_PAN else "white"
            is_blackceil = (type+side == "blackceiling")
            mat.value = random.choice(settings[type+side])
            
        if (mat.value.casefold() in BLACK_PAN[1:] or is_blackceil) and settings["random_blackwall_scale"][0] == "1":
            scale= random.choice(("0.25", "0.5", "1"))
            for val in (find_key(face, 'uaxis'),find_key(face, 'vaxis')):
                if len(val)==1:
                    split=val[0].value.split(" ")
                    split[-1] = scale
                    val[0].value=" ".join(split)    
        alter_mat(mat)
            
def change_overlays():
    "Alter the overlays."
    log("Editing Overlays...")
    to_rem=[]
    for over in overlays:
        mat=find_key(over, 'material')
        alter_mat(mat)
        if mat.value.casefold() in ANTLINES:
            angle = find_key(over, 'angles').value.split(" ") # get the three parts
            #TODO : analyse this, determine whether the antline is on the floor or wall (for P1 style)
            new_tex = random.choice(settings[ANTLINES[mat.value.casefold()].casefold()]).split("|")
            if len(new_tex)==2:
                find_key(over, 'endu').value=new_tex[0] # rescale antlines if needed
                mat.value=new_tex[1]
            else:
                mat.value=new_tex
        if (over.targname in ("exitdoor_stickman","exitdoor_arrow")) and (settings["remove_exit_signs"][0]=="1"):
            to_rem.append(over) # some have instance-based ones, remove the originals if needed to ensure it looks nice.
    for rem in to_rem:
        map.remove(rem) # need to delete it from the map's list tree for it to not be outputted
    del to_rem
    
def change_trig():
    "Check the triggers and fizzlers."
    log("Editing Triggers...")
    for trig in triggers:
        if trig.cls=="trigger_portal_cleanser":
            sides=Property.find_all(trig, 'entity"solid"side"material')
            for mat in sides:
                alter_mat(mat)
            find_key(trig, 'useScanline').value = settings["fizzler_scanline"][0]
            find_key(trig, 'drawInFastReflection').value = settings["force_fizz_reflect"][0]

def change_func_brush():
    "Edit func_brushes."
    log("Editing Brush Entities...")
    for brush in f_brushes:
        sides=Property.find_all(brush, 'entity"solid"side"material')
        for mat in sides: # Func_brush/func_rotating -> angled panels and flip panels often use different textures, so let the style do that.
            if mat.value.casefold() == "anim_wp/framework/squarebeams" and "edge_special" in settings:
                mat.value = random.choice(settings["edge_special"])
            elif mat.value.casefold() in WHITE_PAN and "white_special" in settings:
                mat.value = random.choice(settings["white_special"])
            elif mat.value.casefold() in BLACK_PAN and "black_special" in settings:
                mat.value = random.choice(settings["black_special"])
            else:
                alter_mat(mat) # for gratings, laserfields and some others
            
        fast_ref = Property.find_all(brush, 'entity"drawInFastReflection')
        if len(fast_ref) == 1:
            fast_ref[0].value = settings["force_brush_reflect"][0]
        else:
            brush.value.append(Property("drawinfastreflection", settings["force_brush_reflect"][0]))
            
def change_ents():
    "Edit misc entities."
    log("Editing Other Entities...")
    to_rem=[] # entities to delete
    for ent in other_ents:
        if ent.cls == "info_lighting" and (settings["remove_info_lighting"][0]=="1"):
            to_rem.append(ent) # styles with brush-based glass edges don't need the info_lighting, delete it to save ents.
    for rem in to_rem:
        map.remove(rem) # need to delete it from the map's list tree for it to not be outputted
    del to_rem

def fix_inst():
    "Fix some different bugs with instances, especially fizzler models."
    log("Editing Instances...")
    for inst in instances:
        file=Property.find_all(inst, 'entity"file')
        if "_modelStart" in inst.targname or "_modelEnd" in inst.targname:
            name=Property.find_all(inst, 'entity"targetname')[0]
            if "_modelStart" in inst.targname: # strip off the extra numbers on the end, so fizzler models recieve inputs correctly
                name.value = inst.targname.split("_modelStart")[0] + "_modelStart" 
            else:
                name.value = inst.targname.split("_modelEnd")[0] + "_modelEnd" 
            # one side of the fizzler models are rotated incorrectly (upsidown), fix that...
            angles=Property.find_all(inst, 'entity"angles')[0]
            if angles.value in fizzler_angle_fix.keys():
                angles.value=fizzler_angle_fix[angles.value]
            for i in ("00", "01", "02", "03", "04", "05", "06", "07", "08" ,"09", "10", "11", "12", "13", "14", "15", "16"):
                var = Property.find_all(inst, 'entity"replace' + i)
                if len(var) == 1 and "$skin" in var[0].value:
                    if settings['change_fizz_inst'][0]=="1":
                        # switch to alternate instances depending on what type of fizzler, to massively save ents
                        if "$skin 0" in var[0].value and len(file)==1 and "barrier_hazard_model" in file[0].value:
                            file[0].value = file[0].value[:-4] + "_fizz.vmf" 
                        # we don't want to do it to custom ones though
                        if "$skin 2" in var[0].value and len(file)==1 and "barrier_hazard_model" in file[0].value:
                            file[0].value = file[0].value[:-4] + "_las.vmf"
                    break
            if len(file) == 1 and "ccflag_comball" in file[0].value:
                name.value = inst.targname.split("_")[0] + "-model" + unique_id() # the field models need unique names, so the beams don't point at each other.
            if len(file) == 1 and "ccflag_death_fizz_model" in file[0].value:
                name.value = inst.targname.split("_")[0] # we need to be able to control them directly from the instances, so make them have the same name as the base.
        if len(file) == 1:
            if "ccflag_paint_fizz" in file[0].value:
                # convert fizzler brush to trigger_paint_cleanser (this is part of the base's name)
                for trig in triggers:
                    if trig.cls=="trigger_portal_cleanser" and trig.targname == inst.targname + "_brush": # fizzler brushes are named like "barrierhazard46_brush"
                        Property.find_all(trig, 'entity"classname')[0].value = "trigger_paint_cleanser"
                        sides=Property.find_all(trig, 'entity"solid"side"material')
                        for mat in sides:
                            mat.value = "tools/toolstrigger"
            elif "ccflag_comball_base" in file[0].value: # Rexaura Flux Fields
                for trig in triggers:
                    if trig.cls=="trigger_portal_cleanser" and trig.targname == inst.targname + "_brush": 
                        Property.find_all(trig, 'entity"classname')[0].value = "trigger_multiple"
                        sides=Property.find_all(trig, 'entity"solid"side"material')
                        for mat in sides:
                            mat.value = "tools/toolstrigger"
                        trig.value.append(Property("filtername", "@filter_pellet"))
                        trig.value.append(Property("wait", "0.1"))
                        flags=Property.find_all(trig, 'entity"spawnflags')
                        if len(flags) == 1:
                            flags[0].value="72"
                        add_output(trig, "OnStartTouch", inst.targname+"-branch_toggle", "FireUser1")
                        # generate the output that triggers the pellet logic.
                        Property.find_all(trig, 'entity"targetname')[0].value = inst.targname + "-trigger" # get rid of the _, allowing direct control from the instance.
                pos = find_key(inst, 'origin').value
                angle=find_key(inst, 'angles').value
                for in_out in instances: # find the instance to use for output
                    out_pos = Property.find_all(in_out, 'entity"origin')[0].value
                    out_angle=Property.find_all(in_out, 'entity"angles')
                    if len(out_angle)==1 and pos == out_pos and angle==out_angle[0].value:
                        add_output(inst, "instance:out;OnUser1", in_out.targname, "instance:in;FireUser1") # add ouptuts to the output proxy instance
                        add_output(inst, "instance:out;OnUser2", in_out.targname, "instance:in;FireUser2")
            elif "ccflag_death_fizz_base" in file[0].value: # LP's Death Fizzler
                for trig in triggers:
                    if trig.cls=="trigger_portal_cleanser" and trig.targname == inst.targname + "_brush": 
                        trig_src = []
                        for l in trig.to_strings():
                            trig_src.append(l + "\n")
                        sides=Property.find_all(trig, 'entity"solid"side"material')
                        for mat in sides:
                            if mat.value.casefold() in DEATH_FIZZLER_SUFFIX.keys():
                                mat.value = settings["lp_death_field"][0] + DEATH_FIZZLER_SUFFIX[mat.value.casefold()]
                        find_key(trig, 'targetname').value = inst.targname + "-fizz_red"
                        find_key(trig, 'spawnflags').value = "0"
                        
                        new_trig = Property.parse(trig_src)[0] # get a duplicate of the trigger by serialising and deserialising
                        find_key(new_trig, 'targetname').value = inst.targname + "-fizz_blue"
                        find_key(new_trig, 'spawnflags').value = "9"
                        map.append(new_trig)
                        
                        hurt = Property.parse(trig_src)[0]
                        sides=Property.find_all(hurt, 'entity"solid"side"material')
                        for mat in sides:
                            mat.value = "tools/toolstrigger"
                        find_key(hurt, 'classname').value = "trigger_hurt"
                        find_key(hurt, 'targetname').value = inst.targname + "-hurt"
                        find_key(trig, 'spawnflags').value="1"
                        
                        prop=Property.find_all(hurt, 'entity"usescanline')[0]
                        prop.name="damage"
                        prop.value="100000"
                        
                        prop=Property.find_all(hurt, 'entity"visible')[0]
                        prop.name="damagetype"
                        prop.value="1024"
                        
                        hurt.value.append(Property('nodmgforce', '1'))
                        map.append(hurt)
                        
                      
                        
                        
def fix_worldspawn():
    "Adjust some properties on WorldSpawn."
    log("Editing WorldSpawn")
    root=Property.find_all(map, 'world')
    if len(root)==1:
        root=root[0]
        has_paint = Property.find_all(root, 'world"paintinmap')
        log(has_paint)
        if len(has_paint) == 1:
            if has_paint[0].value == "0":
                has_paint[0].value = settings["force_paint"][0]
        else:
            root.value.append(Property("has_paint", settings["force_paint"][0]))
        sky = Property.find_all(root, 'world"skyname')
        if len(sky) == 1:
            sky[0].value = random.choice(settings["sky"]) # allow random sky to be chosen
        else:
            root.value.append(Property("skyname", random.choice(settings["sky"])))

def add_extra_ents():
    "Add our various extra instances to enable some features."
    global max_ent_id
    inst_types = {
                    "global" : [-8192, "0 0"],
                    "skybox" : [ 5632, "0 0"], 
                    "other"  : [-5888, "-3072 0"],
                    "voice"  : [-8192, "0 512"]
                 }
    for type in inst_types.keys():
        if "inst_"+type in settings:
            max_ent_id = max_ent_id + 1
            for inst in settings["inst_"+type]:
                opt = inst.split("|")
                if len(opt)== 2:
                    inst_types[type][0] += int(opt[0])
                    keys = [
                             Property("id", str(max_ent_id)),
                             Property("classname", "func_instance"),
                             Property("targetname", "inst_"+str(max_ent_id)),
                             Property("file", opt[1]),
                             Property("angles", "0 0 0"),
                             Property("origin", str(inst_types[type][0]) + " " + inst_types[type][1])
                           ]
                    new_inst = Property("entity", keys)
                    map.append(new_inst)
          
def save():
    out = []
    log("Saving New Map...")
    for p in map:
        for s in p.to_strings():
            out.append(s + '\n')
    with open("F:\SteamLibrary\SteamApps\common\Portal 2\sdk_content\maps\styled\preview.vmf", 'w') as f:
        f.writelines(out)
    log("Complete!")
    
def run_vbsp(args, compile_loc, target):
    "Execute the original VBSP, copying files around so it works correctly."
    # TODO: Get the ingame VBSP progress bar to work right. Probably involves making sure P2 gets the VBSP console output.
    log("Calling original VBSP...")
    shutil.copy(target.replace(".vmf",".log"), compile_loc.replace(".vmf",".log"))
    subprocess.call([os.path.join(os.getcwd(),"vbsp_original")] + args, stdout=None, stderr=subprocess.PIPE, shell=True)
    shutil.copy(compile_loc.replace(".vmf",".bsp"), target.replace(".vmf",".bsp"))
    shutil.copy(compile_loc.replace(".vmf",".log"), target.replace(".vmf",".log"))
    shutil.copy(compile_loc.replace(".vmf",".prt"), target.replace(".vmf",".prt")) # copy over the real files so vvis/vrad can read them
    
args = " ".join(sys.argv)
new_args=sys.argv[1:]
new_path=""
path=""
for i,a in enumerate(new_args):
    if "sdk_content\\maps/" in a:
        new_args[i] = a.replace("sdk_content\\maps/","sdk_content/maps/styled/",1)
        new_path=new_args[i]
        path=a
log("Map path is " + path)
if "-entity_limit 1750" in args: # PTI adds this, we know it's a map to convert!
    log("PeTI map detected! (has Entity Limit of 1750)")
    load_map(path)
    max_ent_id=-1
    unique_counter=0
    progs = [
             load_settings, load_entities, 
             fix_inst, change_ents, add_extra_ents,
             change_brush, change_overlays, 
             change_trig, change_func_brush, 
             fix_worldspawn, save
            ]
    for func in progs:
        func()
    run_vbsp(new_args, new_path, path)
else:
    log("Hammer map detected! skipping conversion..")
    run_vbsp(sys.argv[1:], path, path)
