import os
import os.path
import sys
import subprocess
import shutil
import random
import itertools
from collections import defaultdict

from property_parser import Property, KeyValError, NoKeyError
from utils import Vec
import vmfLib as VLib
import utils

unique_counter=0 # counter for instances to ensure unique targetnames

TEX_VALVE = { # all the textures produced by the Puzzlemaker, and their replacement keys:
    #"metal/black_floor_metal_001c"       : "black.floor",
    #"tile/white_floor_tile002a"          : "white.floor",
    #"metal/black_floor_metal_001c"       : "black.ceiling",
    #"tile/white_floor_tile002a"          : "white.ceiling",
    "tile/white_wall_tile003a"            : "white.wall",
    "tile/white_wall_tile003h"            : "white.wall",
    "tile/white_wall_tile003c"            : "white.2x2",
    "tile/white_wall_tile003f"            : "white.4x4",
    "metal/black_wall_metal_002c"         : "black.wall",
    "metal/black_wall_metal_002e"         : "black.wall",
    "metal/black_wall_metal_002a"         : "black.2x2",
    "metal/black_wall_metal_002b"         : "black.4x4",
    "signage/signage_exit"                : "overlay.exit",
    "signage/signage_overlay_arrow"       : "overlay.arrow",
    "signage/signage_overlay_catapult1"   : "overlay.catapultfling",
    "signage/signage_overlay_catapult2"   : "overlay.catapultland",
    "signage/shape01"                     : "overlay.dot",
    "signage/shape02"                     : "overlay.moon",
    "signage/shape03"                     : "overlay.triangle",
    "signage/shape04"                     : "overlay.cross",
    "signage/shape05"                     : "overlay.square",
    "signage/signage_shape_circle"        : "overlay.circle",
    "signage/signage_shape_sine"          : "overlay.sine",
    "signage/signage_shape_slash"         : "overlay.slash",
    "signage/signage_shape_star"          : "overlay.star",
    "signage/signage_shape_wavy"          : "overlay.wavy",
    "anim_wp/framework/backpanels_cheap"  : "special.behind",
    "plastic/plasticwall004a"             : "special.pedestalside",
    "anim_wp/framework/squarebeams"       : "special.edge",
    "nature/toxicslime_a2_bridge_intro"   : "special.goo",
    "nature/toxicslime_puzzlemaker_cheap" : "special.goo_cheap",
    "glass/glasswindow007a_less_shiny"    : "special.glass",
    "metal/metalgrate018"                 : "special.grating",
    "effects/laserplane"                  : "special.laserfield",
    "sky_black"                           : "special.sky",
    }
    
TEX_DEFAULTS = [ # extra default replacements we need to specially handle
        # These have the same item so we can't store this in the regular dictionary.
        ("metal/black_floor_metal_001c", "black.floor" ),
        ("tile/white_floor_tile002a",    "white.floor"),
        ("metal/black_floor_metal_001c", "black.ceiling"),
        ("tile/white_floor_tile002a",    "white.ceiling"),
        ("",                             "special.white"),
        ("",                             "special.black"),
        ("",                             "special.white_gap"),
        ("",                             "special.black_gap"),
        
        # And these have the extra scale information, which isn't in the maps.
        ("0.25|signage/indicator_lights/indicator_lights_floor", "overlay.antline"),
        ("1|signage/indicator_lights/indicator_lights_corner_floor", "overlay.antlinecorner")
        ] 
    
WHITE_PAN = [
             "tile/white_floor_tile002a",
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
            
WALLS = [
         "tile/white_wall_tile003a", 
         "tile/white_wall_tile003h", 
         "tile/white_wall_tile003c", 
         "metal/black_wall_metal_002c", 
         "metal/black_wall_metal_002e", 
         "metal/black_wall_metal_002a", 
         "metal/black_wall_metal_002b"
        ]
        
GOO_TEX = [
           "nature/toxicslime_a2_bridge_intro",
           "nature/toxicslime_puzzlemaker_cheap"
          ]

ANTLINES = {                              
    "signage/indicator_lights/indicator_lights_floor" : "antline",
    "signage/indicator_lights/indicator_lights_corner_floor" : "antlinecorner"
    } # these need to be handled separately to accommodate the scale-changing

DEFAULTS = {
    "bottomless_pit"          : "0",
    "remove_info_lighting"    : "0",
    "fix_glass"               : "0",
    "fix_portal_bump"         : "0",
    "random_blackwall_scale"  : "0",
    "no_mid_voices"           : "0",
    "use_screenshot"          : "0",
    "force_fizz_reflect"      : "0",
    "force_brush_reflect"     : "0",
    "remove_exit_signs"       : "0",
    "force_paint"             : "0",
    "sky"                     : "sky_black",
    "glass_scale"             : "0.15",
    "staticPan"               : "NONE",
    "signInst"                : "NONE",
    "glassInst"               : "NONE",
    "gratingInst"             : "NONE",
    "clump_wall_tex"          : "0",
    "clump_size"              : "4",
    "clump_width"             : "2",
    "clump_number"            : "6",
    }

# These instances have to be specially handled / we want to identify them
# The corridors are used as a startsWith match, others are exact only
inst_file = {
    "coopExit"    : "instances/p2editor/coop_exit.vmf",
	"coopEntry"   : "instances/p2editor/door_entrance_coop_1.vmf",
	"spExit"      : "instances/p2editor/elevator_exit.vmf",
	"spEntry"     : "instances/p2editor/elevator_entrance.vmf",
    "spExitCorr"  : "instances/p2editor/door_exit_",
    "spEntryCorr" : "instances/p2editor/door_entrance_",
    "coopCorr"    : "instances/p2editor/door_exit_coop_",
    "clearPanel"  : "instances/p2editor/panel_clear.vmf",
    "ambLight"    : "instances/p2editor/point_light.vmf",
    "largeObs"    : "instances/p2editor/observation_room_256x128_1.vmf",
    # although unused, editoritems allows having different instances for toggle/timer panels
    "indPanCheck" : "instances/p2editor/indicator_panel.vmf",
    "indPanTimer" : "instances/p2editor/indicator_panel.vmf",
    "glass"       : "instances/p2editor/glass_128x128.vmf"
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
    "-90 -90 0" : "90 90 0"
    }

TEX_FIZZLER = {
    "effects/fizzler_center" : "center",
    "effects/fizzler_l"      : "left",
    "effects/fizzler_r"      : "right",
    "effects/fizzler"        : "short",
    }
    
FIZZ_OPTIONS = {
    "scanline"       : "0",
    }
    
settings = {
            "textures"           : {},
            "fizzler"            : {},
            "options"            : {},
            "pit"                : {},
            "deathfield"         : {},
            
            "style_vars"         : defaultdict(lambda: False),
            "has_attr"           : defaultdict(lambda: False),
            
            "cust_fizzlers"      : [],
            "conditions"         : [],
           }
 
###### UTIL functions #####
 
def unique_id():
    "Return a unique prefix so we ensure instances don't overlap if making them."
    global unique_counter
    unique_counter+=1
    return str(unique_counter)
    
def get_opt(name):
    return settings['options'][name.casefold()]

def get_tex(name):
    if name in settings['textures']:
        return random.choice(settings['textures'][name])
    else:
        raise Exception('No texture "' + name + '"!')
    
def alter_mat(prop, seed=None):
    "Randomise the texture used for a face, based on configured textures."
    mat=prop.mat.casefold()
    if seed:
        random.seed(seed)
    if mat in TEX_VALVE: # should we convert it?
        prop.mat = get_tex(TEX_VALVE[mat])
        return True
    elif mat in TEX_FIZZLER:
        prop.mat = settings['fizzler'][TEX_FIZZLER[mat]]
    else:
        return False

##### MAIN functions ######

def load_settings():
    '''Load in all our settings from vbsp_config.'''
    global settings
    if os.path.isfile("vbsp_config.cfg"): # do we have a config file?
        with open("vbsp_config.cfg", "r") as config: 
            conf=Property.parse(config, 'vbsp_config.cfg')
    else:
        conf = Property(None, []) 
        # All the find_all commands will fail, and we will use the defaults.
                
    tex_defaults = list(TEX_VALVE.items()) + TEX_DEFAULTS
        
    for item,key in tex_defaults: # collect textures from config
        cat, name = key.split(".")
        value = [prop.value for prop in conf.find_all('textures', cat, name)]
        if len(value)==0:
            settings['textures'][key] = [item]
        else:
            settings['textures'][key] = value
            
    # get misc options
    for option_block in conf.find_all('options'):
        for opt in option_block:
            settings['options'][opt.name.casefold()] = opt.value
    for key, default in DEFAULTS.items():
        if key.casefold() not in settings['options']:
            settings['options'][key.casefold()] = default
     
    for item, key in TEX_FIZZLER.items():
        settings['fizzler'][key] = item
        
    for key, item in FIZZ_OPTIONS.items():
        settings['fizzler'][key] = item
        
    for fizz_opt in conf.find_all('fizzler'):
        for item, key in TEX_FIZZLER.items():
            settings['fizzler'][key] = fizz_opt[key, settings['fizzler'][key]]
            
        for key,item in FIZZ_OPTIONS.items():
            settings['fizzler'][key] = fizz_opt[key, settings['fizzler'][key]]
    
    for prop in conf.find_all('instancefiles'):
        for key,val in inst_file.items():
            inst_file[key] = prop[key, val]
    
    for fizz in conf.find_all('cust_fizzlers'):
        flag = fizz['flag']
        if flag in settings['cust_fizzler']:
            raise Exception('Two Fizzlers with same flag!!')
        cust_fizzlers[flag] = {
            'left'     : fizz['left', 'tools/toolstrigger'],
            'right'    : fizz['right', 'tools/toolstrigger'],
            'center'   : fizz['center', 'tools/toolstrigger'],
            'short'    : fizz['short', 'tools/toolstrigger'],
            'scanline' : fizz['scanline', settings['fizzler']['scanline']]
            }
        
    deathfield = conf.find_key("deathfield", [])
    settings['deathfield'] = {
        'left'     : deathfield['left', 'BEE2/fizz/lp/death_field_clean_left'],
        'right'    : deathfield['right', 'BEE2/fizz/lp/death_field_clean_right'],
        'center'   : deathfield['center', 'BEE2/fizz/lp/death_field_clean_center'],
        'short'    : deathfield['short', 'BEE2/fizz/lp/death_field_clean_short'],
        'texwidth' : VLib.conv_int(deathfield['texwidth', '_'], 512),
        'scanline' : deathfield['scanline', settings['fizzler']['scanline']],
        }
        
    for stylevar_block in conf.find_all('stylevar'):
        for var in stylevar_block:
            settings['style_vars'][var.name.casefold()] = var.value
        
    for pack_block in conf.find_all('packer'):
        for pack_cmd in pack_block:
            process_packer(pack_cmd.value)
    for cond in conf.find_all('conditions', 'condition'):
        type = cond['type', ''].upper()
        if type not in ("AND", "OR"):
            type = "AND"
        flags = []
        for f in ("instFlag" , "ifMat", "ifQuote", "ifStyleTrue", 
                  "ifStyleFalse", "ifMode", "ifPreview", "instance", 
                  "StyleVar", "instVar", 'hasInst'):
            flags += list(cond.find_all(f))
        results = []
        for val in cond.find_all('result'):
            results.extend(val.value) # join multiple ones together
        if len(results) > 0: # is it valid?
            con = {"flags" : flags, "results" : results, "type": type}
            settings['conditions'].append(con)
     
    if get_opt('bottomless_pit') == "1":
        pit = conf.find_key("bottomless_pit",[])
        settings['pit']['tex_goo'] = pit['goo_tex', 'nature/toxicslime_a2_bridge_intro']
        settings['pit']['tex_sky'] = pit['sky_tex', 'tools/toolsskybox']
        settings['pit']['should_tele'] = pit['teleport', '0'] == '1'
        settings['pit']['tele_dest'] = pit['tele_target', '@goo_targ']
        settings['pit']['tele_ref'] = pit['tele_ref', '@goo_ref']
        settings['pit']['off_x']  = VLib.conv_int(pit['off_x', '0'], 0)
        settings['pit']['off_y']  = VLib.conv_int(pit['off_y', '0'], 0)
        settings['pit']['height']  = VLib.conv_int(pit['max_height', '386'], 386)
        settings['pit']['side'] = [prop.value for prop in pit.find_all("side_inst")]
        if len(settings['pit']['side']) == 0:
            settings['pit']['side'] = [""]

    process_inst_overlay(conf.find_all('instances', 'overlayInstance'))
    utils.con_log("Settings Loaded!")
    
def load_map(path):
    global map
    with open(path, "r") as file:
        utils.con_log("Parsing Map...")
        props = Property.parse(file, path)
    map=VLib.VMF.parse(props)
    utils.con_log("Parsing complete!")

def check_glob_conditions():
    "Check all the global conditions, like style vars."
    utils.con_log("Checking global conditions...")
    
    game_mode = 'ERR'
    is_preview = 'ERR'
    inst_files = [] # Get a list of every instance in the map.
    for item in map.iter_ents(classname='func_instance'):
        if item['file'] == inst_file['coopExit']:
            game_mode = 'COOP'
        elif item['file'] == inst_file['spExit']:
            game_mode = 'SP'
        elif (item['file'] == inst_file['spEntry'] or 
             item['file'].startswith(inst_file['coopCorr'])):
            is_preview = item.get_fixup('no_player_start') == '0'
        if item['file'] not in inst_files:
            inst_files.append(item['file'])
            
    utils.con_log("Game Mode: " + game_mode)
    utils.con_log("Is Preview: " + str(is_preview))
            
    false_ent = VLib.Entity(map, id=999999999) # create a fake entity to apply file-changing commands to
    
    for cond in settings['conditions'][:]:
        to_rem = []
        for flag in cond['flags'][:]:
            name = flag.name.casefold()
            val = flag.value.casefold()
            if name in ("ifstyletrue", "ifstylefalse"):
                if val in DEFAULTS.keys(): # is it a valid var?
                    if (get_opt(val) == "1" and name.endswith("true")):
                        cond['flags'].remove(flag)
                    elif (get_opt(val) == "0" and name.endswith("false")):
                        cond['flags'].remove(flag)
            elif name == "ifmode":
                if game_mode=='COOP' and val == "coop":
                    cond['flags'].remove(flag)
                if game_mode=='SP' and val == "sp":
                    cond['flags'].remove(flag)
            elif name == "ifpreview" and is_preview == (val=="1"):
                cond['flags'].remove(flag)
            elif name == "hasinst" and val in inst_files:
                    cond['flags'].remove(flag)
        for res in cond['results']:
            if res.name.casefold() == 'variant':
                res.value = variant_weight(res)
            elif res.name.casefold() == 'custantline':
                res.value = {
                    'instance' : res.find_key('instance', '').value,
                    'antline' : [p.value for p in res.find_all('straight')],
                    'antlinecorner' : [p.value for p in res.find_all('corner')],
                    'outputs' : list(res.find_all('addOut'))
                    }
                if len(res.value['antline']) == 0 or len(res.value['antlinecorner']) == 0:
                    cond['results'].remove(res) # invalid
        if len(cond['results']) == 0:
            settings['conditions'].remove(cond)
        satisfy_condition(cond, false_ent)
    utils.con_log("Done!")
    
def satisfy_condition(cond, inst):
    '''Try to satisfy this condition. 
    
    This may delete the condition from the settings list, so iterate using a copy only.
    '''
    isAnd = cond['type'].casefold() == 'and'
    sat = isAnd
    for flag in cond['flags']:
        subres = False
        name = flag.name.casefold()
        if name == 'instance':
            subres = (inst['file'] == flag.value)
        elif name == 'instflag':
            subres = flag.value in inst['file', '']
        elif name == 'instvar':
            bits = flag.value.split(' ')
            subres = inst.get_fixup(bits[0]) == bits[1]
        elif name == 'stylevartrue':
            subres = settings['style_vars'].get(flag.value.casefold(), False)
        elif name == 'stylevarfalse':
            subres = settings['style_vars'].get(flag.value.casefold(), True)
        elif name == 'has':
            subres = settings['has_attr'][flag.value]
        elif name == 'nothas':
            subres = not settings['has_attr'][flag.value]
        if isAnd:
            sat = sat and subres
        else:
            sat = sat or subres
    if len(cond['flags']) == 0:
        sat = True # Always satisfy this!
    if sat:
        for res in cond['results'][:]:
            name = res.name.casefold()
            inst['file'] = inst['file', ''][:-4] # our suffixes won't touch the .vmf extension
            if name == "changeinstance":
                # Set the file to a value
                inst['file'] = res.value
            elif name == "packer":
                process_packer(res.value)
                cond['results'].remove(res)
            elif name == 'suffix':
                # Add the specified suffix to the filename
                inst['file'] += res.value
            elif name == 'instvar':
                if res.has_children():
                    val = inst.get_fixup(res['variable', ''])
                    for rep in res: # lookup the number to determine the appending value
                        if rep.name.casefold() == 'variable':
                            continue # this isn't a lookup command!
                        if rep.name == val:
                            inst['file'] += '_' + rep.value
                            break
                else: # append the value         
                    inst['file'] += '_' + inst.get_fixup(res.value, '')
            elif name == "variant":
                # add _var4 or so to the instance name
                if inst['targetname', ''] == '':
                    # some instances don't get names, so use the global seed instead
                    # for stuff like elevators, the origin is constant so we can't just use that
                    random.seed(map_seed + inst['origin'] + inst['angles'])
                else:
                    random.seed(inst['targetname'])
                inst['file'] += "_var" + random.choice(res.value)
            elif name == "addglobal":
                # Add one instance in a location, but only once
                if res.value is not None:
                    new_inst = VLib.Entity(map, keys={
                                 "classname" : "func_instance",
                                 "targetname" : res['name', ''],
                                 "file" : res['file', ''],
                                 "angles" : "0 0 0",
                                 "origin" : res['position', '']
                               })
                    if new_inst['targetname'] == '':
                        new_inst['targetname'] = "inst_"+str(unique_id())
                    map.add_ent(new_inst)
                    res.value = None # Disable this
            elif name == "addoverlay": 
                # Add another instance on top of this one
                new_inst = VLib.Entity(map, keys={
                             "classname" : "func_instance",
                             "targetname" : inst['targetname'],
                             "file" : res['file', ''],
                             "angles" : inst['angles'],
                             "origin" : inst['origin']
                           })
                map.add_ent(new_inst)
            elif name == "custoutput":
                # Add an additional output to the instance with any values
                # Always points to the targeted item.
                over_name ='@' + inst['targetname'] + '_indicator'
                for toggle in map.iter_ents(classname='func_instance'):
                    if toggle.get_fixup('indicator_name', '') == over_name:
                        toggle_name = toggle['targetname']
                        break
                else:
                    toggle_name = '' # we want to ignore the toggle instance, if it exists
                targets = [o.target for o in inst.outputs if o.target != toggle_name]
                done = []
                
                kill_signs = res["remIndSign", '0'] == '1'
                dec_con_count = res["decConCount", '0'] == '1'
                if kill_signs or dec_con_count:
                    for con_inst in map.iter_ents(classname='func_instance'):
                        if con_inst['targetname'] in targets:
                            if kill_signs and (con_inst['file'] == inst_file['indPanTimer'] or
                                               con_inst['file'] == inst_file['indPanCheck']):
                                map.remove_ent(con_inst)
                            if dec_con_count and con_inst.has_fixup('connectioncount'):
                            # decrease ConnectionCount on the ents, 
                            # so they can still process normal inputs
                                try:
                                    val = int(con_inst.get_fixup('connectioncount'))
                                    con_inst.set_fixup('connectioncount', str(val-1))
                                except ValueError:
                                    # skip if it's invalid
                                    utils.con_log(con_inst['targetname'] + ' has invalid ConnectionCount!')
                for targ in targets:
                    if targ not in done:
                        for out in res.find_all('addOut'):
                            cond_out(inst, out, targ)
                        done.append(targ)
            elif name == "custantline":
                # customise the output antline texture, toggle instances
                # allow adding extra outputs between the instance and the toggle
                over_name ='@' + inst['targetname'] + '_indicator'
                for over in map.iter_ents(
                        classname='info_overlay',
                        targetname=over_name):
                    random.seed(over['origin'])
                    new_tex = random.choice(res.value[ANTLINES[over['material'].casefold()]])
                    set_antline_mat(over, new_tex)
                if res.value['instance'] != '': # allow replacing the indicator_toggle instance
                    for toggle in map.iter_ents(classname='func_instance'):
                        if toggle.get_fixup('indicator_name', '') == over_name:
                            toggle['file'] = res.value['instance']
                            if len(res.value['outputs'])>0:
                                for out in inst.outputs[:]:
                                    if out.target == toggle['targetname']:
                                        inst.outputs.remove(out) # remove the original outputs
                                for out in res.value['outputs']:
                                    # Allow adding extra outputs to customly trigger the toggle
                                    cond_out(inst, out, toggle['targetname'])
            elif name == "faithmods":
                # Get data about the trigger this instance uses for flinging
                fixup_var = res['instvar', '']
                for trig in map.iter_ents(classname="trigger_catapult"):
                    if inst['targetname']  in trig['targetname']:
                        for out in trig.outputs:
                            if out.inst_in == 'animate_angled_relay':
                                out.inst_in = res['angled_targ', 'animate_angled_relay']
                                out.input = res['angled_in', 'Trigger']
                                if fixup_var:
                                    inst.set_fixup(fixup_var, 'angled')
                                break
                            elif out.inst_in == 'animate_straightup_relay':
                                out.inst_in = res['straight_targ', 'animate_straightup_relay']
                                out.input = res['straight_in', 'Trigger']
                                if fixup_var:
                                    inst.set_fixup(fixup_var, 'straight')
                                break
                        else:
                            continue # Check the next trigger
                        break # If we got here, we've found the output - stop scanning
            elif name == "styleVar":
                for opt in res.value:
                    if opt.name.casefold() == 'settrue':
                        settings['style_vars'][opt.value] = True
                    elif opt.name.casefold() == 'setfalse':
                        settings['style_vars'][opt.value] = False
            elif name == "has":
                for opt in res.value:
                    if opt.value.casefold() == '1':
                        settings['has_attr'][opt.name] = True
                    elif opt.value.casefold() == '0':
                        settings['has_attr'][opt.name] = False
            elif name == "styleopt":
                for opt in res.value:
                    if opt.name.casefold() in settings['options']:
                        settings['options'][opt.name.casefold()] = opt.value
            if not inst['file'].endswith('vmf'):
                inst['file'] += '.vmf'
        if len(cond['results']) == 0:
            settings['conditions'].remove(cond)
    return sat
    
def cond_out(inst, prop, target):
    inst.add_out(VLib.Output(
        prop['output',''],
        target,
        prop['input',''], 
        inst_in=prop['targ_in',''], 
        inst_out=prop['targ_out','']))
    
def process_inst_overlay(lst):
    for inst in lst:
        try:
            flag = inst['flag']
            settings['overlay_inst'].append((flag,inst['file'], inst['name']))
        except KeyValError:
            util.con_log('Invalid instance overlay command detected!')
            continue # ignore this one
    
def process_packer(f_list):
    "Read packer commands from settings."
    for cmd in f_list:
        if cmd.name.casefold()=="add":
            to_pack.append(cmd.value)
        if cmd.name.casefold()=="add_list":
            to_pack.append("|list|" + cmd.value)
            
def variant_weight(var):
    "Read variant commands from settings and create the weight list."
    count = var['number', '']
    if count.isdecimal():
        count = int(count)
        weight = var['weights', '']
        if weight == '' or ',' not in weight:
            utils.con_log('Invalid weight! (' + weight + ')')
            weight = [str(i) for i in range(1,count + 1)]
        else:
            vals=weight.split(',')
            weight=[]
            if len(vals) == count:
                for i,val in enumerate(vals):
                    if val.isdecimal():
                        weight.extend([str(i+1) for tmp in range(1,int(val)+1)]) # repeat the index the correct number of times
                    else:
                        break
            if len(weight) == 0:
                utils.con_log('Failed parsing weight! (' + weight + ')')
                weight = [str(i) for i in range(1,count + 1)]
        # random.choice(weight) will now give an index with the correct probabilities.
        return weight
    else:
        return [''] # This won't append anything to the file

def calc_rand_seed():
    '''Use the ambient light entities to create a map seed, so textures remain the same.'''
    lst = [inst['targetname'] for inst in map.iter_ents(classname='func_instance', file=inst_file['ambLight'])]
    if len(lst) == 0:
        return 'SEED'
    else:
        return '|'.join(lst)
        
def make_bottomless_pit(solids):
    '''Transform all the goo pits into bottomless pits.'''
    tex_sky = settings['pit']['tex_sky']
    teleport = settings['pit']['should_tele']
    tele_ref = settings['pit']['tele_ref']
    tele_dest = settings['pit']['tele_dest']
    tele_off_x = settings['pit']['off_x']+64
    tele_off_y = settings['pit']['off_y']+64
    for solid, wat_face in solids:
        wat_face.mat = tex_sky
        for vec in wat_face.planes:
            vec.z = float(str(int(vec.z)-96) + ".5")
            # subtract 95.5 from z axis to make it 0.5 units thick
            # we do the decimal with strings to ensure it adds floats precisely
    pit_height = settings['pit']['height']
    edges = defaultdict(lambda: [None, None, None, None])
    dirs = [
        (0, 0, 128,  '0 270 0'), # North
        (1, 0, -128, '0 90 0'), # South
        (2, 128, 0,  '0 180 0'), # East
        (3, -128, 0, '0 0 0') # West
    ]
    for trig in map.iter_ents(classname='trigger_multiple', wait='0.1'):
        if teleport: # transform the skybox physics triggers into teleports to move cubes into the skybox zone
            bbox_min, bbox_max = trig.get_bbox()
            origin = (bbox_min + bbox_max)/2
            if origin.z < pit_height:
                trig['classname'] = 'trigger_teleport'
                trig['spawnflags'] = '4106' # Physics and npcs
                trig['landmark'] = tele_ref
                trig['target'] = tele_dest
                trig.outputs = [] # remove the usual outputs
                print('box:', trig.get_bbox())
                for x in range(int(bbox_min.x), int(bbox_max.x), 128):
                    for y in range(int(bbox_min.y), int(bbox_max.y), 128):
                        edges[x,y] = None # Remove the pillar from the center of the item
                        for i, xoff, yoff, angle in dirs:
                            side = edges[x+xoff,y+yoff]
                            if side is not None:
                                side[i] = origin.z - 13
                
                # The triggers are 26 high, so make them 10 units thick to make it harder to see the teleport
                for side in trig.sides():
                    for plane in side.planes:
                        if plane.z > origin.z:
                            plane.z -= 16
                          
    file_opts = settings['pit']['side']
    for (x,y), mask in edges.items():
        if mask is not None:
            for i, xoff, yoff, angle in dirs:
                if mask[i] is not None:
                    random.seed(str(x) + str(y) + angle)
                    file = random.choice(file_opts)
                    if file != '':
                        map.add_ent(VLib.Entity(map, keys={
                            'classname' : 'func_instance',
                            'file' : file,
                            'targetname' : 'goo_side' + unique_id(),
                            'origin' : str(x+tele_off_x) + ' ' + str(y+tele_off_y) + ' ' + str(mask[i]) ,
                            'angles' : angle}))
    

def change_brush():
    "Alter all world/detail brush textures to use the configured ones."
    utils.con_log("Editing Brushes...")
    glass_inst = get_opt('glassInst')
    glass_scale = get_opt('glass_scale')
    is_bottomless = get_opt('bottomless_pit') == "1"
    
    # Check the clump algorithm has all its arguements
    can_clump = (get_opt("clump_wall_tex") == "1" and 
                 get_opt("clump_size").isnumeric() and 
                 get_opt("clump_width").isnumeric() and 
                 get_opt("clump_number").isnumeric())
                 
    if is_bottomless:
        pit_solids = []
        pit_height = settings['pit']['height']
        pit_goo_tex = settings['pit']['tex_goo']
    if glass_inst == "NONE":
        glass_inst = None
    for solid in map.iter_wbrushes(world=True, detail=True):
        for face in solid:
            is_glass=False
            if face.mat.casefold() in GOO_TEX:
                settings['has_attr']['goo'] = True
                if is_bottomless:
                    if face.planes[2].z < pit_height:
                        settings['has_attr']['bottomless_pit'] = True
                        pit_solids.append((solid, face))
                    else:
                        face.mat = pit_goo_tex
            if face.mat.casefold()=="glass/glasswindow007a_less_shiny":
                split_u=face.uaxis.split(" ")
                split_v=face.vaxis.split(" ")
                split_u[-1] = glass_scale # apply the glass scaling option
                split_v[-1] = glass_scale
                face.uaxis=" ".join(split_u)
                face.vaxis=" ".join(split_v)
                
                is_glass=True
        if is_glass and glass_inst is not None:
            inst = find_glass_inst(soild.get_origin())
            inst['file'] = glass_inst                  
    if is_bottomless:
        utils.con_log('Creating Bottomless Pits!')
        make_bottomless_pit(pit_solids)
        utils.con_log('Done!')
        
    if can_clump:
        clump_walls()
    else:
        random_walls()
        
        
def find_glass_inst(origin):
    '''Find the glass instance placed on the specified origin.'''
    loc = Vec(origin.x//128*128 + 64,
              origin.y//128*128 + 64,
              origin.z//128*128 + 64)
    print('loc', origin, (loc-origin).norm())
    for inst in map.iter_ents(classname='func_instance', 
                              origin=loc.join(' '), 
                              file=inst_file['glass']):
        print('angle', inst['angles', ''])
    # TODO - make this actually work
    return {'file': ''}
    
def face_seed(face):
    '''Create a seed unique to this brush face, which is the same regardless of side.'''
    origin = face.get_origin()
    for axis in "xyz":
        if origin[axis] % 128 < 2:
            origin[axis] = origin[axis] // 128 # This side
        else:
            origin[axis] = origin[axis] // 128 + 64
    return origin.join()

def random_walls():
    "The original wall style, with completely randomised walls."
    for solid in map.iter_wbrushes(world=True, detail=True):
        for face in solid:
            is_blackceil = roof_tex(face)
            if (face.mat.casefold() in BLACK_PAN[1:] or is_blackceil) and get_opt("random_blackwall_scale") == "1":
                random.seed(face_seed(face) + '_SCALE_VAL')
                scale = random.choice(("0.25", "0.5", "1")) # randomly scale textures to achieve the P1 multi-sized black tile look
                split=face.uaxis.split(" ")
                split[-1] = scale
                face.uaxis=" ".join(split)  
                
                split=face.vaxis.split(" ")
                split[-1] = scale
                face.vaxis=" ".join(split)
            alter_mat(face, face_seed(face))
    
def clump_walls():
    "A wall style where textures are used in small groups near each other, clumped together."
    walls = {}
    others = {} # we keep a list for the others, so we can nodraw them if needed
    for solid in map.iter_wbrushes(world=True, detail=True):
        for face in solid: # first build a list of all textures and their locations...
            mat=face.mat.casefold()
            if face.mat in ('glass/glasswindow007a_less_shiny', 
                             'metal/metalgrate018', 
                             'anim_wp/framework/squarebeams',
                             'tools/toolsnodraw'):
                # These textures aren't always on grid, ignore them..
                alter_mat(face)
                continue
            origin = face.get_origin().as_tuple()
            if mat in WALLS:
                if mat in WHITE_PAN: # placeholder to indicate these can be replaced.
                    face.mat = "WHITE"
                elif mat in BLACK_PAN:
                    face.mat = "BLACK"
                if origin in walls:
                    # The only time two textures will be in the same place is if they are covering each other - nodraw them both and ignore them
                    face.mat  = "tools/toolsnodraw"
                    walls[origin].mat = "tools/toolsnodraw"
                    del walls[origin]
                else:
                    walls[origin] = face
            else:
                if origin in others:
                    # The only time two textures will be in the same place is if they are covering each other - delete them both.
                    face.mat = "tools/toolsnodraw"
                    others[origin].mat = "tools/toolsnodraw"
                    del others[origin]
                else:
                    others[origin] = face
                    random.seed(origin)
                    roof_tex(face)
                
    todo_walls = len(walls) # number of walls un-edited
    clump_size = int(get_opt("clump_size"))
    clump_wid = int(get_opt("clump_width"))
    clump_numb = (todo_walls // clump_size) * int(get_opt("clump_number"))
    wall_pos = sorted(list(walls.keys()))
    random.seed(map_seed)
    for i in range(clump_numb):
        pos = random.choice(wall_pos)
        type = walls[pos].mat
        state=random.getstate() # keep using the map_seed for the clumps
        if type == "WHITE" or type=="BLACK":
            random.seed(pos)
            pos_min = [0,0,0]
            pos_max = [0,0,0]
            direction = random.randint(0,2) # these are long strips extended in one direction
            for i in range(3): 
                if i == direction:
                    pos_min[i] = int(pos[i] - random.randint(0, clump_size) * 128)
                    pos_max[i] = int(pos[i] + random.randint(0, clump_size) * 128)
                else:
                    pos_min[i] = int(pos[i] - random.randint(0, clump_wid) * 128)
                    pos_max[i] = int(pos[i] + random.randint(0, clump_wid) * 128)
                
            tex = get_tex("white.wall" if type=="WHITE" else "black.wall")
            #utils.con_log("Adding clump from ", pos_min, "to", pos_max, "with tex:", tex)
            for x in range(pos_min[0], pos_max[0], 128):
                for y in range(pos_min[1], pos_max[1], 128):
                    for z in range(pos_min[2], pos_max[2]):
                        if (x,y,z) in walls:
                            side = walls[x,y,z]
                            if side.mat == type:
                                side.mat = tex
        random.setstate(state)
    
    for pos, face in walls.items():   
        random.seed(pos)
        if face.mat =="WHITE":
        # we missed these ones!
            if not get_tex("special.white_gap") == "":
                face.mat = get_tex("special.white_gap")
            else:
                    face.mat = get_tex("white.wall")
        elif face.mat == "BLACK":
            if not get_tex("special.black_gap") == "":
                    face.mat = get_tex("special.black_gap")
            else:
                    face.mat = get_tex("black.wall")
        else:
            alter_mat(face, seed=pos)
    
def roof_tex(face):
    "Determine if a texture is on the roof or if it's on the floor, and apply textures appropriately."
    is_blackceil=False # we only want to change size of black ceilings, not floor so use this flag
    if face.mat.casefold() in ("metal/black_floor_metal_001c",  "tile/white_floor_tile002a"):
        # The roof/ceiling texture are identical, we need to examine the planes to figure out the orientation!
        # y-val for first if < last if ceiling
        side = "ceiling" if int(face.planes[0]['y']) < int(face.planes[2]['y']) else "floor"
        type = "black." if face.mat.casefold() in BLACK_PAN else "white."
        face.mat = get_tex(type+side)
        return (type+side == "black.ceiling")
    else:
        alter_mat(face)
        return False
       
def set_antline_mat(over,mat):
    mat=mat.split('|')
    if len(mat)==2:
        over['endu']=mat[0] # rescale antlines if needed
        over['material']=mat[1]
    elif len(mat)==3:
        over['endu']=mat[0]
        over['material']=mat[1]
        if mat[2] == 'static':
            over['targetname'] = '' # if the antline doesn't have frames, allow it to be static.
    else:
        over['material']=mat
    
def change_overlays():
    "Alter the overlays."
    utils.con_log("Editing Overlays...")
    sign_inst = get_opt('signInst')
    if sign_inst == "NONE":
        sign_inst = None
    for over in map.iter_ents(classname='info_overlay'):
        if over['material'].casefold() in TEX_VALVE:
            sign_type = TEX_VALVE[over['material'].casefold()]
            if sign_inst is not None:
                new_inst = VLib.Entity(map, keys={
                                'classname': 'func_instance',
                                'origin': over['origin'],
                                'angles': over['angles', '0 0 0'],
                                'file': sign_inst
                            })
                new_inst.set_fixup('mat', sign_type.replace('overlay.', ''))
                map.add_ent(new_inst)
                for cond in settings['conditions'][:]:
                    satisfy_condition(cond, new_inst)
            over['material'] = get_tex(sign_type)
        if over['material'].casefold() in ANTLINES:
            angle = over['angles'].split(" ") # get the three parts
            #TODO : analyse this, determine whether the antline is on the floor or wall (for P1 style)
            new_tex = get_tex('overlay.'+ANTLINES[over['material'].casefold()])
            set_antline_mat(over, new_tex)
        if (over['targetname'] in ("exitdoor_stickman","exitdoor_arrow")) :
            if get_opt("remove_exit_signs") =="1":
                map.remove_ent(over) # some have instance-based ones, remove the originals if needed to ensure it looks nice.
            else:
                del over['targetname'] # blank the targetname, so we don't get the info_overlay_accessors
    
def change_trig():
    "Check the triggers and fizzlers."
    utils.con_log("Editing Triggers...")
    for trig in map.iter_ents(classname='trigger_portal_cleanser'):
        for side in trig.sides():
            alter_mat(side)
        trig['useScanline'] = settings["fizzler"]["scanline"]
        trig['drawInFastReflection'] = get_opt("force_fizz_reflect")

def change_func_brush():
    "Edit func_brushes."
    utils.con_log("Editing Brush Entities...")
    grating_inst = get_opt("gratingInst")
    for brush in itertools.chain(map.iter_ents(classname='func_brush'),
                                 map.iter_ents(classname='func_door_rotating')):
        brush['drawInFastReflection'] = get_opt("force_brush_reflect")
        parent = brush['parentname', '']
        type="" 
        # Func_brush/func_rotating -> angled panels and flip panels often use different textures, so let the style do that.
        top_side = None
        is_grating=False
        for side in brush.sides():
            if side.mat.casefold() == "anim_wp/framework/squarebeams" and "special.edge" in settings['textures']:
                side.mat = get_tex("special.edge")
            elif side.mat.casefold() in WHITE_PAN:
                type="white"
                top_side=side
                if not get_tex("special.white") == "":
                    side.mat = get_tex("special.white")
                elif not alter_mat(side):
                    side.mat = get_tex("white.wall")
            elif side.mat.casefold() in BLACK_PAN:
                type="black"
                top_side=side
                if not get_tex("special.black") == "":
                    side.mat = get_tex("special.black")
                elif not alter_mat(side):
                    side.mat = get_tex("black.wall")
            else:
                if side.mat.casefold() == 'metal/metalgrate018':
                    is_grating=True
                alter_mat(side) # for gratings, laserfields and some others
        if is_grating and grating_inst is not None:
            inst = find_glass_inst(brush.get_origin())
            inst['file'] = grating_inst
        if "-model_arms" in parent: # is this an angled panel?:
            targ='-'.join(parent.split("-")[:-1]) # strip only the model_arms off the end
            for ins in map.iter_ents(classname='func_instance', targetname=targ):
                if make_static_pan(ins, type):
                    map.remove_ent(brush) # delete the brush, we don't want it if we made a static one
                else:
                    brush['targetname']=brush['targetname'].replace('_panel_top', '-brush')
    
def make_static_pan(ent, type):
    "Convert a regular panel into a static version, to save entities and improve lighting."
    if get_opt("staticPan") == "NONE":
        return False # no conversion allowed!
    angle="00"
    if ent.get_fixup('animation') is not None:
        # the 5:7 is the number in "ramp_45_deg_open"
        angle = ent.get_fixup('animation')[5:7]
    if ent.get_fixup('start_deployed') == "0":
        angle = "00" # different instance flat with the wall
    if ent.get_fixup('connectioncount') != "0":
        return False
    ent["file"] = get_opt("staticPan") + angle + "_" + type + ".vmf" # something like "static_pan/45_white.vmf"
    return True
    
def make_static_pist(ent):
    "Convert a regular piston into a static version, to save entities and improve lighting."
    if get_opt("staticPan") == "NONE":
        return False # no conversion allowed!
    print("Trying to make static...")
    bottom_pos=ent.get_fixup('bottom_level', '-1')
    print(ent._fixup)
    if ent.get_fixup('connectioncount') != "0" or ent.get_fixup('disable_autodrop') != "0": # can it move?
        if int(bottom_pos) > 0:
            # The piston doesn't go fully down, use alt instances.
            ent['file'] = ent['file'][:-4] + "_" + bottom_pos + ".vmf"
    else: # we are static
        ent['file'] = (get_opt("staticPan") + "pist_"
            + (ent.get_fixup('top_level') if ent.get_fixup('start_up')=="1" else bottom_pos)
            + ".vmf" )
        # something like "static_pan/pist_3.vmf"
    return True
            
def change_ents():
    "Edit misc entities."
    utils.con_log("Editing Other Entities...")
    if get_opt("remove_info_lighting") == "1":
        # styles with brush-based glass edges don't need the info_lighting, delete it to save ents.
        for ent in map.iter_ents(classname='info_lighting'):
            ent.remove()
    for auto in map.iter_ents(classname='logic_auto'):
        # remove all the logic_autos that set attachments, we can replicate this in the instance
        for out in auto.outputs:
            if 'panel_top' in out.target:
                map.remove_ent(auto)

def fix_inst():
    "Fix some different bugs with instances, especially fizzler models and implement custom compiler changes."
    utils.con_log("Editing Instances...")
    for inst in map.iter_ents(classname='func_instance'):
        if "_modelStart" in inst.get('targetname','') or "_modelEnd" in inst.get('targetname',''):
            if "_modelStart" in inst['targetname']: # strip off the extra numbers on the end, so fizzler models recieve inputs correctly
                inst['targetname'] = inst['targetname'].split("_modelStart")[0] + "_modelStart" 
            else:
                inst['targetname'] = inst['targetname'].split("_modelEnd")[0] + "_modelEnd"
            
            # one side of the fizzler models are rotated incorrectly (upsidown), fix that...
            if inst['angles'] in fizzler_angle_fix.keys():
                inst['angles'] =fizzler_angle_fix[inst['angles']]
                    
            if "ccflag_comball" in inst['file']:
                inst['targetname'] = inst['targetname'].split("_")[0] + "-model" + unique_id() # the field models need unique names, so the beams don't point at each other.
            if "ccflag_death_fizz_model" in inst['file']:
                inst['targetname'] = inst['targetname'].split("_")[0] # we need to be able to control them directly from the instances, so make them have the same name as the base.
        elif "ccflag_paint_fizz" in inst['file']:
            # convert fizzler brush to trigger_paint_cleanser (this is part of the base's name)
            for trig in triggers:
                if trig['classname']=="trigger_portal_cleanser" and trig['targetname'] == inst['targetname'] + "_brush": # fizzler brushes are named like "barrierhazard46_brush"
                    trig['classname'] = "trigger_paint_cleanser"
                    for side in trig.sides():
                        side.mat = "tools/toolstrigger"
        elif "ccflag_comball_base" in inst['file']: # Rexaura Flux Fields
            for trig in map.iter_ents(classname='trigger_portal_cleanser', targetname=(inst['targetname'] + "_brush")):
                # find the triggers that match this entity and mod them
                trig['classname'] = "trigger_multiple"
                for side in trig.sides():
                    side.mat = "tools/toolstrigger"
                trig["filtername"] = "@filter_pellet"
                trig["wait"] = "0.1"
                trig['spawnflags'] = "72" # Physics Objects and 'Everything'
                trig.add_out(VLib.Output("OnStartTouch", inst['targetname']+"-branch_toggle", "FireUser1"))
                # generate the output that triggers the pellet logic.
                trig['targetname'] = inst['targetname'] + "-trigger" # get rid of the _, allowing direct control from the instance.
            inst.outputs.clear() # all the original ones are junk, delete them!
            for in_out in map.iter_ents_tags(
                   vals={'classname':'func_instance', 'origin':inst['origin'], 'angles':inst['angles']}, 
                   tags={'file':'ccflag_comball_out'}):
                # find the instance to use for output and add the commands to trigger its logic
                inst.add_out(VLib.Output("OnUser1", in_out['targetname'], "FireUser1", inst_in='in', inst_out='out'))
                inst.add_out(VLib.Output("OnUser2", in_out['targetname'], "FireUser2", inst_in='in', inst_out='out'))
        elif "ccflag_death_fizz_base" in inst['file']: # LP's Death Fizzler
            for trig in triggers:
                if trig['classname']=="trigger_portal_cleanser" and trig['targetname'] == inst['targetname'] + "_brush": 
                    death_fizzler_change(inst, trig)
        if inst['file'] == inst_file['clearPanel']:
            make_static_pan(inst, "glass") # white/black are identified based on brush
        if "ccflag_pist_plat" in inst['file']:
            make_static_pist(inst) #try to convert to static piston
        for cond in settings['conditions'][:]:
            satisfy_condition(cond, inst)
            
    utils.con_log('Map has attributes: ', settings['has_attr'])
    utils.con_log('Style Vars:', settings['style_vars'])
    for inst in map.iter_ents(classname='func_instance', file=''):
        map.remove_ent(inst) # Remove instances with blank file attr, allows conditions to strip the instances when requested

def death_fizzler_change(inst, trig):
    "Convert the passed fizzler brush into the required brushes for Death Fizzlers."
    # The Death Fizzler has 4 brushes:
    # new_trig - trigger_portal_cleanser with standard fizzler texture for fizzler-only mode (-fizz_blue)
    #trig - trigger_portal_cleanser with death fizzler texture  for both mode (-fizz_red)
    #hurt - trigger_hurt for deathfield mode (-hurt)
    #brush - func_brush for the deathfield-only mode (-brush)
    
    new_trig = trig.copy()
    hurt = trig.copy()
    brush = trig.copy()
    map.add_ent(new_trig)
    map.add_ent(hurt)
    map.add_ent(brush)
    
    for side in trig.sides():
        if side.mat.casefold() in TEX_FIZZLER: #is this not nodraw?
            # convert to death fizzler textures
            side.mat = settings["deathfield"][TEX_FIZZLER[side.mat.casefold()]]
    trig['targetname'] = inst['targetname'] + "-fizz_red"
    trig['spawnflags'] = "9" # clients + physics objects
    
    new_trig['targetname'] = inst['targetname'] + "-fizz_blue"
    new_trig['spawnflags'] = "9" # clients + physics objects
    
    # Create the trigger_hurt
    is_short = False # if true we can shortcut for the brush
    for side in trig.sides():
        if side.mat.casefold() == "effects/fizzler":
            is_short=True
        side.mat = "tools/toolstrigger"
        
    hurt['classname'] = "trigger_hurt"
    hurt['targetname'] = inst['targetname'] + "-hurt"
    hurt['spawnflags']="1" # clients only
    hurt['damage'] = '100000'
    hurt['damagetype'] ='1024'
    hurt['nodmgforce'] = '1'
    
    brush['targetname'] = inst['targetname'] + "-brush"
    brush['classname'] = 'func_brush'
    brush['spawnflags'] = "2"  # ignore player +USE
    brush['solidity'] = '1' # not solid
    brush['renderfx'] = '14' # constant glow
    brush['drawinfastreflection'] ='1'
    
    if is_short:
        for side in brush.find_all('entity', 'solid', 'side'):
            mat=side['material']
            if "effects/fizzler" in mat.value.casefold():
                mat.value=get_tex('special.laserfield')
            alter_mat(mat) # convert to the styled version
            
            uaxis = side.uaxis.split(" ")
            vaxis = side.vaxis.split(" ")
            # the format is like "[1 0 0 -393.4] 0.25"
            uaxis[3]="0]"
            uaxis[4]="0.25"
            vaxis[4]="0.25"
            side['uaxis'] = " ".join(uaxis)
            side['vaxis'] = " ".join(vaxis)
    else:
        # We need to stretch the brush to get rid of the side sections.
        # This is the same as moving all the solids to match the bounding box.
        # first get the origin, used to figure out if a point should be max or min
        origin=Vec(*[int(v) for v in brush['origin'].split(' ')])
        bbox_max,bbox_min=brush.get_bbox()
        for side in trig.sides():
            for v in side.planes:
                for i in range(3): #x,y,z
                    if int(v[i]) > origin[i]:
                        v[i]=str(bbox_max[i])
                    else:
                        v[i]=str(bbox_min[i])
        
        tex_width = settings['deathfield']['texwidth']
        for side in brush.solids[1].sides:
            if side.mat.casefold() == "effects/fizzler_center":
                side.mat=get_tex('special.laserfield')
            alter_mat(mat) # convert to the styled version
            bounds_max,bounds_min=side.get_bbox()
            dimensions = [0,0,0]
            for i in range(3):
                dimensions[i] = bounds_max[i] - bounds_min[i]
            if 2 in dimensions: # The front/back won't have this dimension
                mat.value="tools/toolsnodraw"
            else:
                uaxis=side['uaxis'].split(" ")
                vaxis=side['vaxis'].split(" ")
                # the format is like "[1 0 0 -393.4] 0.25"
                size=0
                offset=0
                for i,w in enumerate(dimensions):
                    if int(w)>size:
                        size=int(w)
                        offset=int(bounds_min[i])
                print(size)
                print(uaxis[3], size)
                uaxis[3]=str(tex_width/size * -offset) + "]" # texture offset to fit properly
                uaxis[4]=str(size/tex_width) # scaling
                vaxis[3]="256]"
                vaxis[4]="0.25" # widthwise it's always the same
                side['uaxis'] = " ".join(uaxis)
                side['vaxis'] = " ".join(vaxis)
            
        brush.value.remove(solids[2])
        brush.value.remove(solids[0]) # we only want the middle one with the center, the others are invalid
        del solids
    
def fix_worldspawn():
    "Adjust some properties on WorldSpawn."
    utils.con_log("Editing WorldSpawn")
    if map.spawn['paintinmap'] != '1':
        # if PeTI thinks there should be paint, don't touch it
        map.spawn['paintinmap'] = get_opt('force_paint')
    map.spawn['skyname'] = get_tex("special.sky")

def hammer_pack_scan():
    "Look through entities to see if any packer commands exist, and add if needed."
    global to_pack
    to_pack=[] # We aren't using the ones found in vbsp_config
    utils.con_log("Searching for packer commands...")
    for ent in map.entities:
        com = ent.editor.get('comments', '')
        if "packer_" in com:
            parts = com.split()
            last_op = -1 # 1=item, 2=file
            print(parts)
            for frag in parts:
                if frag.endswith("packer_additem:"): # space between command and file
                    last_op = 1
                elif frag.endswith("packer_addfile:"):
                    last_op = 2
                elif "packer_additem:" in frag: # has no space between command and file
                    last_op = -1
                    to_pack.append(frag.split("packer_additem:")[1])
                elif "packer_addfile:" in frag:
                    last_op = -1
                    to_pack.append("|list|" + frag.split("packer_addfile:")[1])
                else: # the file by itself
                    if last_op == 1:
                        to_pack.append(frag)
                    elif last_op == 2:
                        to_pack.append("|list|" + frag)
    print(to_pack)
                
                    
def make_packlist(vmf_path):
    "Create the required packer file for BSPzip to use."
    pack_file = vmf_path[:-4] + "['file']list.txt"
    folders=get_valid_folders()
    utils.con_log("Creating Pack list...")
    has_items = False
    with open(pack_file, 'w') as fil:
        for item in to_pack:
            if item.startswith("|list|"):
                item = os.path.join(os.getcwd(),"pack_lists",item[6:])
                print('Opening "' + item + '"!')
                if os.path.isfile(item):
                    with open(item, 'r') as lst:
                        for line in lst:
                            line=line.strip() # get rid of carriage returns etc
                            utils.con_log("Adding " + line)
                            full=expand_source_name(line, folders)
                            if full:
                                fil.write(line + "\n")
                                fil.write(full + "\n")
                                has_items = True
                else:
                    utils.con_log("Error: File not found, skipping...")
            else:
                full=expand_source_name(item, folders)
                if full:
                    fil.write(item + "\n")
                    fil.write(full + "\n")
                    has_items = True
    if not has_items:
        utils.con_log("No packed files!")
        os.remove(pack_file) # delete it if we aren't storing anything
    utils.con_log("Done!")
                
def get_valid_folders():
    "Look through our game path to find folders in order of priority"
    dlc_count = 1
    priority = ["portal2"]
    while os.path.isdir(os.path.join(root, "portal2_dlc" + str(dlc_count))):
        priority.append("portal2_dlc" + str(dlc_count))
        dlc_count+=1
    if os.path.isdir(os.path.join(root, "update")):
        priority.append("update")
    blacklist = ("bin", "Soundtrack", "sdk_tools", "sdk_content") # files are definitely not here
    all_folders = [f for f in os.listdir(root) if os.path.isdir(os.path.join(root, f)) and f not in priority and f not in blacklist]
    in_order = [x for x in reversed(priority)] + all_folders
    return in_order
    
def expand_source_name(file, folders):
    "Determine the full path for an item with a truncated path."
    for f in folders:
        poss=os.path.normpath(os.path.join(root, f, file))
        if os.path.isfile(poss):
            return poss
    utils.con_log( file + " not found!")
    return False
    
def save():
    "Save the modified map back to the correct location."
    out = []
    utils.con_log("Saving New Map...")
    with open(new_path, 'w') as f:
        map.export(file=f, inc_version=True) 
    utils.con_log("Complete!")
    
def run_vbsp(args, do_swap):
    "Execute the original VBSP, copying files around so it works correctly."
    if do_swap: # we can't overwrite the original vmf, so we run VBSP from a separate location.
        if os.path.isfile(path.replace(".vmf", ".log")):
            shutil.copy(path.replace(".vmf",".log"), new_path.replace(".vmf",".log"))
    args = [('"' + x + '"' if " " in x else x) for x in args] # put quotes around args which contain spaces
    arg = '"' + os.path.normpath(os.path.join(os.getcwd(),"vbsp_original")) + '" ' + " ".join(args)
    utils.con_log("Calling original VBSP...")
    utils.con_log(arg)
    code=subprocess.call(arg, stdout=None, stderr=subprocess.PIPE, shell=True)
    if code==0:
        utils.con_log("Done!")
    else:
        utils.con_log("VBSP failed! (" + str(code) + ")")
        sys.exit(code)
    if do_swap: # copy over the real files so vvis/vrad can read them
        for exp in (".bsp", ".log", ".prt"):
            if os.path.isfile(new_path.replace(".vmf", exp)):
                shutil.copy(new_path.replace(".vmf", exp), path.replace(".vmf", exp))

# MAIN
utils.con_log("BEE2 VBSP hook initiallised.")

to_pack = [] # the file path for any items that we should be packing

root = os.path.dirname(os.getcwd())
args = " ".join(sys.argv)
new_args=sys.argv[1:]
old_args=sys.argv[1:]
new_path=""
path=""
for i,a in enumerate(new_args):
    fixed_a = os.path.normpath(a)
    if "sdk_content\\maps\\" in fixed_a:
        new_args[i] = fixed_a.replace("sdk_content\\maps\\","sdk_content\\maps\\styled\\",1)
        new_path=new_args[i]
        path=a
    # we need to strip these out, otherwise VBSP will get confused
    if a == '-force_peti' or a == '-force_hammer':
        new_args[i] = ''
        old_args[i] = ''

utils.con_log('Map path is "' + path + '"')
if path == "":
    raise Exception("No map passed!")
if not path.endswith(".vmf"):
    path += ".vmf"
    new_path += ".vmf"

utils.con_log("Loading settings...")
load_settings() 

if '-force_peti' in args or '-force_hammer' in args:
    # we have override command!
    if '-force_peti' in args:
        utils.con_log('OVERRIDE: Attempting to convert!')
        is_hammer = False
    else:
        utils.con_log('OVERRIDE: Abandoning conversion!')
        is_hammer = True
else:
    # If we don't get the special -force args, check for the entity 
    # limit to determine if we should convert
    is_hammer = "-entity_limit 1750" not in args
if is_hammer: 
    utils.con_log("Hammer map detected! skipping conversion..")
    run_vbsp(old_args, False)
    make_packlist(path)
else:
    utils.con_log("PeTI map detected!")
    unique_counter=0
    
    load_map(path)
    
    map_seed = calc_rand_seed()
    progs = [
             check_glob_conditions, fix_inst, 
             change_ents, change_brush, change_overlays, 
             change_trig, change_func_brush, 
             fix_worldspawn, save
            ]
    for func in progs:
        func() # run all these in order
    run_vbsp(new_args, True)
    make_packlist(path) # VRAD will access the original BSP location
    
utils.con_log("BEE2 VBSP hook finished!")