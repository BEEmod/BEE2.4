import os
import os.path
import sys
import subprocess
import shutil
import random

from property_parser import Property
import utils

# COMPILER FLAGS (used as part of instance filename)
# ccflag_comball
# ccflag_comball_base
# ccflag_paint_fizz
# ccflag_death_fizz_base
# ccflag_panel_clear

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
    #"metal/black_floor_metal_001c"       : "black.floor",
    #"tile/white_floor_tile002a"          : "white.floor",
    #"metal/black_floor_metal_001c"       : "black.ceiling",
    #"tile/white_floor_tile002a"          : "white.ceiling",
    "tile/white_wall_tile003a"                               : "white.wall",
    "tile/white_wall_tile003h"                               : "white.wall",
    "tile/white_wall_tile003c"                               : "white.2x2",
    "tile/white_wall_tile003f"                               : "white.4x4",
    "metal/black_wall_metal_002c"                            : "black.wall",
    "metal/black_wall_metal_002e"                            : "black.wall",
    "metal/black_wall_metal_002a"                            : "black.2x2",
    "metal/black_wall_metal_002b"                            : "black.4x4",
    "signage/signage_exit"                                   : "overlay.exit",
    "signage/signage_overlay_arrow"                          : "overlay.arrow",
    "signage/signage_overlay_catapult1"                      : "overlay.catapultfling",
    "signage/signage_overlay_catapult2"                      : "overlay.catapultland",
    "signage/shape01"                                        : "overlay.dot",
    "signage/shape02"                                        : "overlay.moon",
    "signage/shape03"                                        : "overlay.triangle",
    "signage/shape04"                                        : "overlay.cross",
    "signage/shape05"                                        : "overlay.square",
    "signage/signage_shape_circle"                           : "overlay.circle",
    "signage/signage_shape_sine"                             : "overlay.sine",
    "signage/signage_shape_slash"                            : "overlay.slash",
    "signage/signage_shape_star"                             : "overlay.star",
    "signage/signage_shape_wavy"                             : "overlay.wavy",
    "anim_wp/framework/backpanels_cheap"                     : "special.behind",
    "plastic/plasticwall004a"                                : "special.pedestalside",
    "anim_wp/framework/squarebeams"                          : "special.edge",
    "nature/toxicslime_a2_bridge_intro"                      : "special.goo",
    "glass/glasswindow007a_less_shiny"                       : "special.glass",
    "metal/metalgrate018"                                    : "special.grating",
    "BEE2/fizz/lp/death_field_clean_"                        : "special.lp_death_field", # + short/left/right/center
    "effects/laserplane"                                     : "special.laserfield",
    "sky_black"                                              : "special.sky",
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
    "signage/indicator_lights/indicator_lights_corner_floor" : "antlinecorner"
    } # these need to be handled seperately to accomedate the scale-changing

DEFAULTS = {
    "bottomless_pit"          : "0",
    "remove_info_lighting"    : "0",
    "fix_glass"               : "0",
    "fix_portal_bump"         : "0",
    "random_blackwall_scale" : "0",
    "use_screenshot"          : "0",
    "run_bsp_zip"             : "0",
    "force_fizz_reflect"      : "0",
    "force_brush_reflect"     : "0",
    "remove_exit_signs"       : "0",
    "force_paint"             : "0",
    "sky"                     : "sky_black",
    "glass_scale"             : "0.15",
    "staticPan"               : "NONE"
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

TEX_FIZZLER = {
    "effects/fizzler_center" : "center",
    "effects/fizzler_l"      : "left",
    "effects/fizzler_r"      : "right",
    "effects/fizzler"        : "short",
    "0"                      : "scanline"
    }
    
FIXUP_KEYS = ["replace0" + str(i) for i in range(1,10)] + ["replace" + str(i) for i in range(10,17)]
    # $replace01, $replace02,
 
###### UTIL functions #####
 
def unique_id():
    "Return a unique prefix so we ensure instances don't overlap if making them."
    global unique_counter
    unique_counter+=1
    return str(unique_counter)
   
def log(text):
    print(text, flush=True)
        
def get_opt(name):
    return settings['options'][name]

def get_tex(name):
    if name in settings['textures']:
        return random.choice(settings['textures'][name])
    else:
        raise ValueError('No texture "' + name + '"!')
    
def alter_mat(prop):
    mat=prop.value.casefold()
    if mat in TEX_VALVE: # should we convert it?
        prop.value = get_tex(TEX_VALVE[mat])
        return True
    else:
        return False

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

def split_plane(plane):
    "Extract the plane from a brush into an array."
    # Plane looks like "(575 0 128) (575 768 128) (575 768 256)"
    verts = plane.value[1:-1].split(") (") # break into 3 groups of 3d vertexes
    for i,v in enumerate(verts):
        verts[i]=v.split(" ")
    return verts

def join_plane(verts):
    "Join the verts back into the proper string."
    plane=""
    for vert in verts:
        plane += ("(" + " ".join(vert) + ") ")
    return plane[:-1] # take off the last space
    
def get_bbox(planes):
    "Generate the highest and lowest points these planes form."
    bbox_max=[]
    bbox_min=[]
    preset=True
    for pl in planes:
        verts=split_plane(pl)
        if preset:
            preset=False
            bbox_max=[int(x)-9999 for x in verts[0][:]]
            bbox_min=[int(x)+9999 for x in verts[0][:]]
        for v in verts:
            for i in range(0,3):
                bbox_max[i] = max(int(v[i]), bbox_max[i])
                bbox_min[i] = min(int(v[i]), bbox_min[i])
    return bbox_max, bbox_min

def find_key(ent, key, norm=None):
    "Safely get a subkey from an instance (not lists of multiple). If it fails, throw an exception to crash the compiler safely."
    result = Property.find_all(ent, ent.name + '"' + key)
    if len(result) == 1:
        return result[0]
    elif len(result) == 0:
        if norm==None:
            raise ValueError('No key "' + key + '"!')
        else:
            return norm
    else:
        raise ValueError('Duplicate keys "' + key + '"!')

##### MAIN functions ######

def load_settings():
    global settings
    with open("vbsp_config.cfg", "r") as config: # this should be outputted when editoritems is exported, so we don't have to trawl through editoritems to find our settings.
        conf=Property.parse(config)
    settings = {"textures"      : {},
                "fizzler"       : {},
                "cust_fizzlers" : [],
                "options"       : {},
                "deathfield"    : {},
                "instances"     : {}
                }
    tex_defaults = list(TEX_VALVE.items()) + [
        ("metal/black_floor_metal_001c", "black.floor" ),
        ("tile/white_floor_tile002a",    "white.floor"),
        ("metal/black_floor_metal_001c", "black.ceiling"),
        ("tile/white_floor_tile002a",    "white.ceiling"),
        # These have the same item so we can't store this in the regular dictionary.
        ("0.25|signage/indicator_lights/indicator_lights_floor", "overlay.antline"),
        ("1|signage/indicator_lights/indicator_lights_corner_floor", "overlay.antlinecorner")
        ] # And these have the extra scale information
    for item,key in tex_defaults: # collect textures from config
        cat, name = key.split(".")
        value = [prop.value for prop in Property.find_all(conf, 'textures"' + cat + '"' + name)]
        if len(value)==0:
            settings['textures'][key] = [item]
        else:
            settings['textures'][key] = value
            
    for key in DEFAULTS.keys(): # get misc options
        value = Property.find_all(conf, 'options"' + key)
        if len(value)==0:
            settings['options'][key] = DEFAULTS[key]
        else:
            settings['options'][key] = value[0].value
    
    for item,key in TEX_FIZZLER.items():
        value = Property.find_all(conf, 'fizzler"' + key)
        if len(value)==0:
            settings['fizzler'][key] = item
        else:
            settings['fizzler'][key] = value[0].value
           
    cust_fizzlers = Property.find_all(conf, 'cust_fizzlers')
    for fizz in cust_fizzlers:
        if len(Property.find_all(fizz, 'cust_fizzlers"flag')) == 1:
            flag = find_key(fizz, 'flag')
            if flag in settings['cust_fizzler']:
                raise ValueError('Two Fizzlers with same flag!!')
            data= {}
            data['left']     = find_key(fizz, 'left', 'tools/toolstrigger'),
            data['right']    = find_key(fizz, 'right', 'tools/toolstrigger'),
            data['center']   = find_key(fizz, 'center', 'tools/toolstrigger'),
            data['short']    = find_key(fizz, 'short', 'tools/toolstrigger'),
            data['scanline'] = find_key(fizz, 'scanline', settings['fizzler']['scanline'])
            cust_fizzlers[flag] = data
    log("Settings Loaded!")
    
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
        if mat.value.casefold()=="nature/toxicslime_a2_bridge_intro" and (get_opt("bottomless_pit")=="1"):
            plane=find_key(face,'plane')
            verts=split_plane(plane)
            for v in verts:
                v[2] = str(int(v[2])- 96) + ".5" # subtract 95.5 from z axis to make it 0.5 units thick
                # we do the decimal with strings to ensure it adds floats precisely
            plane.value=join_plane(verts)
            
        if mat.value.casefold()=="glass/glasswindow007a_less_shiny":
            for val in (find_key(face, 'uaxis'),find_key(face, 'vaxis')):
                split=val.value.split(" ")
                split[-1] = get_opt("glass_scale") # apply the glass scaling option
                val.value=" ".join(split)
        
        is_blackceil=False # we only want to change size of black ceilings, not floor so use this flag
        if mat.value.casefold() in ("metal/black_floor_metal_001c",  "tile/white_floor_tile002a"):
            # The roof/ceiling texture are identical, we need to examine the planes to figure out the orientation!
            verts = split_plane(find_key(face,'plane'))
            # y-val for first if < last if ceiling
            side = "ceiling" if int(verts[0][1]) < int(verts[2][1]) else "floor"
            type = "black." if mat.value.casefold() in BLACK_PAN else "white."
            is_blackceil = (type+side == "black.ceiling")
            mat.value = get_tex(type+side)
            
        if (mat.value.casefold() in BLACK_PAN[1:] or is_blackceil) and get_opt("random_blackwall_scale") == "1":
            scale = random.choice(("0.25", "0.5", "1")) # randomly scale textures to achieve the P1 multi-sized black tile look
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
            new_tex = get_tex('overlay.'+ANTLINES[mat.value.casefold()]).split("|")
            print(new_tex)
            if len(new_tex)==2:
                find_key(over, 'endu').value=new_tex[0] # rescale antlines if needed
                mat.value=new_tex[1]
            else:
                mat.value=new_tex
        if (over.targname in ("exitdoor_stickman","exitdoor_arrow")) and (get_opt("remove_exit_signs") =="1"):
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
            find_key(trig, 'useScanline').value = options["fizzler"]["scanline"]
            find_key(trig, 'drawInFastReflection').value = get_opt("force_fizz_reflect")

def change_func_brush():
    "Edit func_brushes."
    log("Editing Brush Entities...")
    to_rem=[]
    for brush in f_brushes:
        sides=Property.find_all(brush, 'entity"solid"side"material')
        type=""
        for mat in sides: # Func_brush/func_rotating -> angled panels and flip panels often use different textures, so let the style do that.
            if mat.value.casefold() == "anim_wp/framework/squarebeams" and "special.edge" in settings['textures']:
                mat.value = get_tex("special.edge")
            elif mat.value.casefold() in WHITE_PAN:
                type="white"
                if "special.white" in settings['textures']:
                    mat.value = get_tex("special.white")
                elif not alter_mat(mat):
                    mat.value = get_tex("white.wall")
            elif mat.value.casefold() in BLACK_PAN:
                type="black"
                if "special.black" in settings['textures']:
                    mat.value = get_tex("special.black")
                elif not alter_mat(mat):
                    mat.value = get_tex("black.wall")
            else:
                alter_mat(mat) # for gratings, laserfields and some others
        parent=Property.find_all(brush, 'entity"parentname')
        if brush.cls=="func_brush" and len(parent) == 1 and"-model_arms" in parent[0].value: # is this the angled panel?:
            targ=parent[0].value.split("-model_arms")[0]
            for inst in instances:
                if inst.targname == targ:
                    if make_static_pan(inst, type):
                        to_rem.append(brush) # delete the brush, we don't want it
                    break
        fast_ref = Property.find_all(brush, 'entity"drawInFastReflection')
        if len(fast_ref) == 1:
            fast_ref[0].value = get_opt("force_brush_reflect")
        else:
            brush.value.append(Property("drawinfastreflection", settings["force_brush_reflect"][0]))
    for item in to_rem:
        map.remove(item)
    del to_rem
    
def make_static_pan(ent, type):
    "Convert a regular panel into a static version, to save entities and improve lighting."
    if get_opt("staticPan") == "NONE":
        return False # no conversion allowed!
    angle="er"
    is_static=False
    is_flush=False
    for i in FIXUP_KEYS:
        var = Property.find_all(ent, 'entity"' + i)
        if(len(var)==1):
            print(type, var[0].value)
            if var[0].value == "$connectioncount 0":
                is_static=True
            if "$start_deployed 0" in var[0].value:
                is_flush=True
            if "$animation" in var[0].value:
                angle = var[0].value[16:18] # the number in "$animation ramp_45_deg_open"
    if is_flush:
        angle = "00" # different instance flat with the wall
    if not is_static:
        return False
    find_key(ent, "file").value = get_opt("staticPan") + angle + "_" + type + ".vmf" # something like "static_pan/45_white.vmf"
    return True
            
def change_ents():
    "Edit misc entities."
    log("Editing Other Entities...")
    to_rem=[] # entities to delete
    for ent in other_ents:
        if ent.cls == "info_lighting" and (get_opt("remove_info_lighting")=="1"):
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
            for i in FIXUP_KEYS:
                var = Property.find_all(inst, 'entity"' + i)
                if len(var) == 1 and "$skin" in var[0].value:
                    if settings['fizzler']['splitInstances']=="1":
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
                        # The Death Fizzler has 4 brushes:
                        # - trigger_portal_cleanser with standard fizzler texture for fizzler-only mode (-fizz_blue)
                        # - trigger_portal_cleanser with death fizzler texture  for both mode (-fizz_red)
                        # - trigger_hurt for deathfield mode (-hurt)
                        # - func_brush for the deathfield-only mode (-brush)
                        trig_src = []
                        for l in trig.to_strings():
                            trig_src.append(l + "\n")
                        sides=Property.find_all(trig, 'entity"solid"side"material')
                        for mat in sides:
                            if mat.value.casefold() in TEX_FIZZLER.keys():
                                mat.value = settings["deathfield"][TEX_FIZZLER[mat.value.casefold()]]
                        find_key(trig, 'targetname').value = inst.targname + "-fizz_red"
                        find_key(trig, 'spawnflags').value = "9"
                        
                        new_trig = Property.parse(trig_src)[0] # get a duplicate of the trigger by serialising and deserialising
                        find_key(new_trig, 'targetname').value = inst.targname + "-fizz_blue"
                        find_key(new_trig, 'spawnflags').value = "9"
                        map.append(new_trig)
                        
                        hurt = Property.parse(trig_src)[0]
                        sides=Property.find_all(hurt, 'entity"solid"side"material')
                        is_short = False # (if true we can shortcut for the brush)
                        for mat in sides:
                            if mat.value.casefold() == "effects/fizzler":
                                is_short=True
                            mat.value = "tools/toolstrigger"
                        find_key(hurt, 'classname').value = "trigger_hurt"
                        find_key(hurt, 'targetname').value = inst.targname + "-hurt"
                        find_key(hurt, 'spawnflags').value="1"
                        
                        prop=find_key(hurt, 'usescanline')
                        prop.name="damage"
                        prop.value="100000"
                        
                        prop=find_key(hurt, 'visible')
                        prop.name="damagetype"
                        prop.value="1024"
                        
                        hurt.value.append(Property('nodmgforce', '1'))
                        map.append(hurt)
                        
                        brush = Property.parse(trig_src)[0]
                        find_key(brush, 'targetname').value = inst.targname + "-brush"
                        find_key(brush, 'classname').value = 'func_brush'
                        find_key(brush, 'spawnflags').value = "1"
                        
                        prop=find_key(brush, 'visible')
                        prop.name="solidity"
                        prop.value="1"
                        
                        prop=find_key(brush, 'usescanline')
                        prop.name="renderfx"
                        prop.value="14"
                        brush.value.append(Property('drawinfastreflection', "1"))
                        
                        if is_short:
                            sides=Property.find_all(brush, 'entity"solid"side')
                            for side in sides:
                                mat=find_key(side,'material')
                                if "effects/fizzler" in mat.value.casefold():
                                    mat.value="effects/laserplane"
                                alter_mat(mat) # convert to the styled version
                                
                                uaxis = find_key(side, 'uaxis').value.split(" ")
                                vaxis = find_key(side, 'vaxis').value.split(" ")
                                # the format is like "[1 0 0 -393.4] 0.25"
                                uaxis[3]="0" + "]"
                                uaxis[4]="0.25"
                                vaxis[4]="0.25"
                                find_key(side, 'uaxis').value = " ".join(uaxis)
                                find_key(side, 'vaxis').value = " ".join(vaxis)
                        else:
                            # We need to stretch the brush to get rid of the side sections.
                            # This is the same as moving all the solids to match the bounding box.
                            
                            # get the origin, used to figure out if a point should be max or min
                            origin=[int(v) for v in find_key(brush,'origin').value.split(' ')]
                            planes=Property.find_all(brush, 'entity"solid"side"plane')
                            bbox_max,bbox_min=get_bbox(planes)
                            for pl in planes:
                                verts=split_plane(pl)
                                for v in verts:
                                    for i in range(0,3): #x,y,z
                                        if int(v[i]) > origin[i]:
                                            v[i]=str(bbox_max[i])
                                        else:
                                            v[i]=str(bbox_min[i])
                                pl.value=join_plane(verts)
                            solids=Property.find_all(brush, 'entity"solid')
                            
                            sides=Property.find_all(solids[1],'solid"side')
                            for side in sides:
                                mat=find_key(side, 'material')
                                if mat.value.casefold() == "effects/fizzler_center":
                                    mat.value="effects/laserplane"
                                alter_mat(mat) # convert to the styled version
                                bounds_max,bounds_min=get_bbox(Property.find_all(side,'side"plane'))
                                dimensions = [0,0,0]
                                for i,g in enumerate(dimensions):
                                    dimensions[i] = bounds_max[i] - bounds_min[i]
                                if 2 in dimensions: # The front/back won't have this dimension
                                    mat.value="tools/toolsnodraw"
                                else:
                                    uaxis=find_key(side, 'uaxis').value.split(" ")
                                    vaxis=find_key(side, 'vaxis').value.split(" ")
                                    # the format is like "[1 0 0 -393.4] 0.25"
                                    size=0
                                    offset=0
                                    for i,w in enumerate(dimensions):
                                        if int(w)>size:
                                            size=int(w)
                                            offset=int(bounds_min[i])
                                    print(size)
                                    print(uaxis[3], size)
                                    uaxis[3]=str(512/size * -offset) + "]" # texture offset to fit properly
                                    uaxis[4]=str(size/512) # scaling
                                    vaxis[4]="0.25" # widthwise it's always the same
                                    find_key(side, 'uaxis').value = " ".join(uaxis)
                                    find_key(side, 'vaxis').value = " ".join(vaxis)
                                
                            brush.value.remove(solids[2])
                            brush.value.remove(solids[0]) # we only want the middle one with the center, the others are invalid
                            del solids
                        map.append(brush)
            elif "ccflag_panel_clear" in file[0].value:
                make_static_pan(inst, "glass") # white/black are identified based on brush                        
    
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
                has_paint[0].value = get_opt("force_paint")
        else:
            root.value.append(Property("has_paint", get_opt("force_paint")))
        sky = Property.find_all(root, 'world"skyname')
        if len(sky) == 1:
            sky[0].value = get_tex("special.sky") # allow random sky to be chosen
        else:
            root.value.append(Property("skyname", get_tex("special.sky")))

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
        if type in settings['instances']:
            max_ent_id = max_ent_id + 1
            for inst in get_inst(type):
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
             fix_inst, change_ents, #add_extra_ents,
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
