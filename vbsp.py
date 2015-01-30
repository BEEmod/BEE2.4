import os
import os.path
import sys
import subprocess
import shutil
import random
import itertools
from enum import Enum
from collections import defaultdict

from property_parser import Property
from utils import Vec
import vmfLib as VLib
import conditions
import utils
import voiceLine

TEX_VALVE = { # all the textures produced by the Puzzlemaker, and their replacement keys:
    #"metal/black_floor_metal_001c"       : "black.floor",
    #"tile/white_floor_tile002a"          : "white.floor",
    #"metal/black_floor_metal_001c"       : "black.ceiling",
    #"tile/white_floor_tile002a"          : "white.ceiling",
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
    ("tile/white_wall_tile003a",     "white.wall"),
    ("tile/white_wall_tile003h",     "white.wall"),
    ("tile/white_wall_tile003c",     "white.2x2"),
    ("tile/white_wall_tile003f",     "white.4x4"),
    ("metal/black_wall_metal_002c",  "black.wall"),
    ("metal/black_wall_metal_002e",  "black.wall"),
    ("metal/black_wall_metal_002a",  "black.2x2"),
    ("metal/black_wall_metal_002b",  "black.4x4"),
    ("",                             "special.white"),
    ("",                             "special.black"),
    ("",                             "special.white_gap"),
    ("",                             "special.black_gap"),

    # And these defaults have the extra scale information, which isn't in the maps.
    ("0.25|signage/indicator_lights/indicator_lights_floor", "overlay.antline"),
    ("1|signage/indicator_lights/indicator_lights_corner_floor", "overlay.antlinecorner")
    ]
    
class ORIENT(Enum):
    floor = 1
    wall = 2
    ceiling = 3
    ceil = 3

WHITE_PAN = [
    "tile/white_floor_tile002a",
    "tile/white_wall_tile003a",
    "tile/white_wall_tile003h",
    "tile/white_wall_tile003c",
    "tile/white_wall_tile003f",
    ]
    
BLACK_PAN = [
    "metal/black_floor_metal_001c",
    "metal/black_wall_metal_002c",
    "metal/black_wall_metal_002e",
    "metal/black_wall_metal_002a",
    "metal/black_wall_metal_002b",
    ]

GOO_TEX = [
    "nature/toxicslime_a2_bridge_intro",
    "nature/toxicslime_puzzlemaker_cheap",
    ]

ANTLINES = {
    "signage/indicator_lights/indicator_lights_floor" : "antline",
    "signage/indicator_lights/indicator_lights_corner_floor" : "antlinecorner"
    } # these need to be handled separately to accommodate the scale-changing

DEFAULTS = {
    "bottomless_pit"          : "0", # Convert goo into bottomless pits
    "remove_info_lighting"    : "0", # Remove the glass info_lighting ents
    "remove_pedestal_plat"    : "0", # Remove pedestal button platforms
    "fix_glass"               : "0",
    "fix_portal_bump"         : "0", # P1 style randomly sized black walls
    "random_blackwall_scale"  : "0", 
    "no_mid_voices"           : "0", # Remove the midpoint voice lines
    "force_fizz_reflect"      : "0",
    "force_brush_reflect"     : "0",
    "remove_exit_signs"       : "0", # Remove the exit sign overlays
    "force_paint"             : "0", # Force paintinmap = 1
    "sky"                     : "sky_black", # Change the skybox
    "glass_scale"             : "0.15",
    "staticPan"               : "NONE",
    "signInst"                : "NONE",
    "glassInst"               : "NONE",
    "gratingInst"             : "NONE",
    "clump_wall_tex"          : "0", # Use the clumping wall algorithm
    "clump_size"              : "4", # The maximum dimensions of a clump
    "clump_width"             : "2",
    "clump_number"            : "6", # The number of clumps created
    "music_instance"          : "", # The instance for the chosen music
    "music_soundscript"       : "", # The soundscript for the chosen music
    # default to the origin of the elevator instance
    # That's likely to be enclosed
    "music_location_sp"       : "-2000 2000 0",
    "music_location_coop"     : "-2000 -2000 0",
    "music_id"                : "<NONE>",
    "global_pti_ents"         : "",
    #default pos is next to arivial_departure_ents
    "global_pti_ents_loc"     : "-2400 -2800 0",
    }

# These instances have to be specially handled / we want to identify them
# The corridors are used as a startsWith match, others are exact only
INST_FILE = {
    "coopExit"    : "instances/p2editor/coop_exit.vmf",
	"coopEntry"   : "instances/p2editor/door_entrance_coop_1.vmf",
	"spExit"      : "instances/p2editor/elevator_exit.vmf",
	"spEntry"     : "instances/p2editor/elevator_entrance.vmf",
    "spExitCorr"  : "instances/p2editor/door_exit_",
    "spEntryCorr" : "instances/p2editor/door_entrance_",
    "coopCorr"    : "instances/p2editor/door_exit_coop_",
    "clearPanel"  : "instances/p2editor/panel_clear.vmf",
    "pistPlat"    : "instances/p2editor/lift_standalone.vmf",
    "ambLight"    : "instances/p2editor/point_light.vmf",
    "largeObs"    : "instances/p2editor/observation_room_256x128_1.vmf",
    # although unused, editoritems allows having different instances 
    # for toggle/timer panels
    "indPanCheck" : "instances/p2editor/indicator_panel.vmf",
    "indPanTimer" : "instances/p2editor/indicator_panel.vmf",
    "glass"       : "instances/p2editor/glass_128x128.vmf",
}
# angles needed to ensure fizzlers are not upside-down 
# (key=original, val=fixed)
fizzler_angle_fix = {
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

# Configuration data extracted from VBSP_config
settings = {
            "textures"           : {},
            "fizzler"            : {},
            "options"            : {},
            "pit"                : {},
            "deathfield"         : {},

            "style_vars"         : defaultdict(bool),
            "has_attr"           : defaultdict(bool),

            "voice_data_sp"      : Property("Quotes_SP", []),
            "voice_data_coop"    : Property("Quotes_COOP", []),
           }

# A list of sucessful AddGlobal commands, so we can prevent adding the same instance twice.
global_instances = []


###### UTIL functions #####

unique_counter = 0 # counter for instances to ensure unique targetnames
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

def alter_mat(face, seed=None):
    "Randomise the texture used for a face, based on configured textures."
    mat=face.mat.casefold()
    if seed:
        random.seed(seed)
        
    if mat in TEX_VALVE: # should we convert it?
        face.mat = get_tex(TEX_VALVE[mat])
        return True
    elif mat in BLACK_PAN or mat in WHITE_PAN:
        type = 'white' if mat in WHITE_PAN else 'black'
        orient = get_face_orient(face)
        if orient == ORIENT.wall:
            if (mat == 'metal/black_wall_metal_002b' or 
                    mat == 'tile/white_wall_tile_003f'):
                orient = '4x4'
            elif (mat == 'metal/black_wall_metal_002a' or 
                    mat == 'tile/white_wall_tile003c'):
                orient = '2x2'
            else:
                orient = 'wall'
        elif orient == ORIENT.floor:
            orient = 'floor'
        elif orient == ORIENT.ceiling:
            orient = 'ceiling'
        face.mat = get_tex(type + '.' + orient)
        return True
    elif mat in TEX_FIZZLER:
        face.mat = settings['fizzler'][TEX_FIZZLER[mat]]
    else:
        return False

##### MAIN functions ######

def load_settings():
    '''Load in all our settings from vbsp_config.'''
    if os.path.isfile("vbsp_config.cfg"): # do we have a config file?
        with open("vbsp_config.cfg", "r") as config:
            conf=Property.parse(config, 'vbsp_config.cfg')
    else:
        conf = Property(None, [])
        # All the find_all commands will fail, and we will use the defaults.

    tex_defaults = list(TEX_VALVE.items()) + TEX_DEFAULTS

    for item, key in tex_defaults: # collect textures from config
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
        for key, val in INST_FILE.items():
            INST_FILE[key] = prop[key, val]
        
    for quote_block in conf.find_all("quotes_sp"):
        settings['voice_data_sp'] += quote_block.value
        
    for quote_block in conf.find_all("quotes_coop"):
        settings['voice_data_coop'] += quote_block.value

    for stylevar_block in conf.find_all('stylevars'):
        for var in stylevar_block:
            settings['style_vars'][var.name.casefold()] = VLib.conv_bool(var.value)

    for pack_block in conf.find_all('packer'):
        for pack_cmd in pack_block:
            process_packer(pack_cmd.value)
            
    for cond in conf.find_all('conditions', 'condition'):
        conditions.add(cond)

    if get_opt('bottomless_pit') == "1":
        pit = conf.find_key("bottomless_pit",[])
        settings['pit'] = {
            'tex_goo': pit['goo_tex', 'nature/toxicslime_a2_bridge_intro'],
            'tex_sky': pit['sky_tex', 'tools/toolsskybox'],
            'should_tele': pit['teleport', '0'] == '1',
            'tele_dest': pit['tele_target', '@goo_targ'],
            'tele_ref': pit['tele_ref', '@goo_ref'],
            'off_x': VLib.conv_int(pit['off_x', '0'], 0),
            'off_y': VLib.conv_int(pit['off_y', '0'], 0),
            'height': VLib.conv_int(pit['max_height', '386'], 386),
            'side': [prop.value for prop in pit.find_all("side_inst")],
            }
        if len(settings['pit']['side']) == 0:
            settings['pit']['side'] = [""]

    utils.con_log("Settings Loaded!")

def load_map(path):
    global map
    with open(path, "r") as file:
        utils.con_log("Parsing Map...")
        props = Property.parse(file, path)
    file.close()
    map=VLib.VMF.parse(props)
    utils.con_log("Parsing complete!")
    
def add_voice(voice_timer_pos, mode):
    inst_loc = {}
    print(mode)
    if mode == 'COOP':
        utils.con_log('Adding Coop voice lines!')
        data = settings['voice_data_coop']
    elif mode == 'SP':
        utils.con_log('Adding Singleplayer voice lines!')
        data = settings['voice_data_sp']
    else:
        return
        
    voiceLine.add_voice(
        voice_data=data,
        map_attr=settings['has_attr'],
        style_vars=settings['style_vars'],
        VMF=map,
        config=voice_timer_pos,
        )
        
def get_map_info():
    '''Determine various attributes about the map.
    
    - SP/COOP status
    - if in preview mode
    - timer values for entry/exit corridors
    '''
    game_mode = 'ERR'
    is_preview = 'ERR'
    
    # Timer_delay values for the entry/exit corridors, needed for quotes
    voice_timer_pos = {} 
    
    inst_files = [] # Get a list of every instance in the map.
    FILE_COOP_EXIT = INST_FILE['coopExit']
    FILE_SP_EXIT = INST_FILE['spExit']
    FILE_COOP_CORR = INST_FILE['coopCorr']
    FILE_SP_ENTRY_CORR = INST_FILE['spEntryCorr']
    FILE_SP_EXIT_CORR = INST_FILE['spExitCorr'] 
    FILE_OBS = INST_FILE['largeObs']
    FILE_COOP_ENTRY = INST_FILE['coopEntry']
    for item in map.iter_ents(classname='func_instance'):
        file = item['file']
        if file == FILE_COOP_EXIT:
            game_mode = 'COOP'
        elif file == FILE_SP_EXIT:
            game_mode = 'SP'
        elif file == INST_FILE['spEntry']:
            is_preview = item.fixup['no_player_start'] == '0'
            
        elif file.startswith(FILE_COOP_CORR):
            is_preview = item.fixup['no_player_start'] == '0'
            voice_timer_pos['exit'] = (
                item.fixup['timer_delay', '0']
                )
        elif file.startswith(FILE_SP_ENTRY_CORR):
            voice_timer_pos['entry'] = (
                item.fixup['timer_delay', '0']
                )
        elif file.startswith(FILE_SP_EXIT_CORR):
            voice_timer_pos['exit'] = (
                item.fixup['timer_delay', '0']
                )
        elif file == FILE_COOP_ENTRY:
            voice_timer_pos['entry'] = (
                item.fixup['timer_delay', '0']
                )
        elif file == FILE_OBS:
            voice_timer_pos['obs'] = (
                item.fixup['timer_delay', '0']
                )
                
        if item['file'] not in inst_files:
            inst_files.append(item['file'])

    utils.con_log("Game Mode: " + game_mode)
    utils.con_log("Is Preview: " + str(is_preview))
    
    return is_preview, game_mode, voice_timer_pos, inst_files

def process_packer(f_list):
    "Read packer commands from settings."
    for cmd in f_list:
        if cmd.name.casefold()=="add":
            to_pack.append(cmd.value)
        if cmd.name.casefold()=="add_list":
            to_pack.append("|list|" + cmd.value)

def calc_rand_seed():
    '''Use the ambient light entities to create a map seed, so textures remain the same.'''
    lst = [inst['targetname'] for inst in map.iter_ents(classname='func_instance', file=INST_FILE['ambLight'])]
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
    
    # To figure out what positions need edge pieces, we use a dict
    # indexed by XY tuples. The four Nones match the NSEW directions.
    # For each trigger, we loop through the grid points it's in. We
    # set all the center parts to None, but set the 4 neighbouring
    # blocks if they aren't None.
    # If a value = None, it is occupied by goo.
    edges = defaultdict(lambda: [None, None, None, None])
    dirs = [
        # index, x, y, angles
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
                trig.outputs.clear()
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
                 
    if get_opt('remove_pedestal_plat'):
        # Remove the pedestal platforms
        for ent in map.iter_ents(classname='func_detail'):
            for side in ent.sides():
                if side.mat.casefold() == 'plastic/plasticwall004a':
                    map.remove_ent(ent)
                    break # Skip to next entity

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
                # Force this voice attribute on, since conditions can't
                # detect goo pits / bottomless pits
                settings['has_attr']['goo'] = True
                if is_bottomless:
                    if face.planes[2].z < pit_height:
                        settings['has_attr']['bottomless_pit'] = True
                        pit_solids.append((solid, face))
                    else:
                        face.mat = pit_goo_tex
            if face.mat.casefold() == "glass/glasswindow007a_less_shiny":
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
                              file=INST_FILE['glass']):
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
    scale_walls = get_opt("random_blackwall_scale") == "1"
    for solid in map.iter_wbrushes(world=True, detail=True):
        for face in solid:
            orient = get_face_orient(face)
            # Only modify black walls and ceilings
            if scale_walls and face.mat.casefold() in BLACK_PAN and orient is not ORIENT.floor:
                random.seed(face_seed(face) + '_SCALE_VAL')
                # randomly scale textures to achieve the P1 multi-sized black tile look
                scale = random.choice(("0.25", "0.5", "1"))
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
            orient = get_face_orient(face)
            if orient is ORIENT.wall:
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
                    alter_mat(face, face_seed(face))

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
        
def get_face_orient(face):
    '''Determine the orientation of an on-grid face.'''
    if face.planes[0]['z'] == face.planes[1]['z'] == face.planes[2]['z']:
        if face.planes[0]['y'] < face.planes[2]['y']:
            return ORIENT.ceiling
        else:
            return ORIENT.floor
    else:
        return ORIENT.wall

def set_antline_mat(over,mat):
    mat = mat.split('|')
    if len(mat) == 2:
        # rescale antlines if needed
        over['endu'], over['material'] = mat
    elif len(mat) == 3:
        over['endu'], over['material'], static = mat
        if static == 'static':
            # If specified, remove the targetname so the overlay
            # becomes static.
            over['targetname'] = ''
    else:
        over['material'] = mat

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
                    'file': sign_inst,
                    })
                new_inst.fixup['mat'] = sign_type.replace('overlay.', '')
                map.add_ent(new_inst)
                conditions.check_inst(new_inst)
                
            over['material'] = get_tex(sign_type)
        if over['material'].casefold() in ANTLINES:
            angle = over['angles'].split(" ") # get the three parts
            # TODO: analyse this, determine whether the antline is on
            # the floor or wall (for P1 style)

            new_tex = get_tex(
                'overlay.' +
                ANTLINES[over['material'].casefold()]
                )
            set_antline_mat(over, new_tex)

        if (over['targetname'] in ("exitdoor_stickman","exitdoor_arrow")):
            if get_opt("remove_exit_signs") =="1":
                # Some styles have instance-based ones, remove the
                # originals if needed to ensure it looks nice.
                map.remove_ent(over)
            else:
                # blank the targetname, so we don't get the
                # useless info_overlay_accessors
                del over['targetname']

def change_trig():
    "Check the triggers and fizzlers."
    utils.con_log("Editing Triggers...")
    for trig in map.iter_ents(classname='trigger_portal_cleanser'):
        for side in trig.sides():
            alter_mat(side)
        trig['useScanline'] = settings["fizzler"]["scanline"]
        trig['drawInFastReflection'] = get_opt("force_fizz_reflect")

def add_extra_ents(mode):
    '''Add the various extra instances to the map.'''
    utils.con_log("Adding Music...")
    if mode == "COOP":
        loc = get_opt('music_location_coop')
    else:
        loc = get_opt('music_location_sp')

    sound = get_opt('music_soundscript')
    inst = get_opt('music_instance')
    if sound != '':
        map.add_ent(VLib.Entity(map, keys={
            'classname': 'ambient_generic',
            'spawnflags': '17', # Looping, Infinite Range, Starts Silent
            'targetname': '@music',
            'origin': loc,
            'message': sound,
            'health': '10', # Volume
            }))

    if inst != '':
        map.add_ent(VLib.Entity(map, keys={
            'classname': 'func_instance',
            'targetname': 'music',
            'angles': '0 0 0',
            'origin': loc,
            'file': inst,
            'fixup_style': '0',
            }))
    pti_file = get_opt("global_pti_ents")
    pti_loc = get_opt("global_pti_ents_loc")
    if pti_file != '':
        utils.con_log('Adding Global PTI Ents')
        global_pti_ents = VLib.Entity(map, keys={
            'classname': 'func_instance',
            'targetname': 'global_pti_ents',
            'angles': '0 0 0',
            'origin': pti_loc,
            'file': pti_file,
            'fixup_style': '0',
            })
        has_cave = settings['style_vars'].get('multiversecave', '1') == '1'
        global_pti_ents.fixup[
            'disable_pti_audio'
            ] = utils.bool_as_int(not has_cave)
        map.add_ent(global_pti_ents)

def change_func_brush():
    "Edit func_brushes."
    utils.con_log("Editing Brush Entities...")
    grating_inst = get_opt("gratingInst")
    for brush in itertools.chain(
            map.iter_ents(classname='func_brush'),
            map.iter_ents(classname='func_door_rotating'),
            ):
        brush['drawInFastReflection'] = get_opt("force_brush_reflect")
        parent = brush['parentname', '']
        type=""

        # Func_brush/func_rotating (for angled panels and flip panels)
        # often use different textures, so let the style do that.

        top_side = None
        is_grating=False
        for side in brush.sides():
            if (side.mat.casefold() == "anim_wp/framework/squarebeams" and
                    "special.edge" in settings['textures']):
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
            for ins in map.iter_ents(
                    classname='func_instance',
                    targetname=targ,
                    ):
                if make_static_pan(ins, type):
                    map.remove_ent(brush) # delete the brush, we don't want it if we made a static one
                else:
                    brush['targetname'] = brush['targetname'].replace(
                        '_panel_top',
                        '-brush',
                        )

def make_static_pan(ent, type):
    '''Convert a regular panel into a static version
    
    This is done to save entities and improve lighting.'''
    if get_opt("staticPan") == "NONE":
        return False # no conversion allowed!

    angle="00"
    if ent.fixup['animation'] is not None:
        # the 5:7 is the number in "ramp_45_deg_open"
        angle = ent.fixup['animation'][5:7]
    if ent.fixup['start_deployed'] == "0":
        angle = "00" # different instance flat with the wall
    if ent.fixup['connectioncount', '0'] != "0":
        return False
    # something like "static_pan/45_white.vmf"
    ent["file"] = get_opt("staticPan") + angle + "_" + type + ".vmf"
    return True

def make_static_pist(ent):
    '''Convert a regular piston into a static version.
    
    This is done to save entities and improve lighting.'''
    if get_opt("staticPan") == "NONE":
        return False # no conversion allowed!

    print("Trying to make static...")
    bottom_pos = ent.fixup['bottom_level', '-1']

    if (ent.fixup['connectioncount', '0'] != "0" or
            ent.fixup['disable_autodrop'] != "0"): # can it move?
        if int(bottom_pos) > 0:
            # The piston doesn't go fully down, use alt instances.
            ent['file'] = ent['file'][:-4] + "_" + bottom_pos + ".vmf"
    else: # we are static
        ent['file'] = (
            get_opt("staticPan") + "pist_"
            + (
                ent.fixup['top_level', '1']
                if ent.fixup['start_up'] == "1"
                else bottom_pos
                )
            + ".vmf"
            )
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
    '''Fix some different bugs with instances, especially fizzler models and implement custom compiler changes.'''

    utils.con_log("Editing Instances...")
    for inst in map.iter_ents(classname='func_instance'):
        # Fizzler model names end with this special string
        if ("_modelStart" in inst.get('targetname','') or
                "_modelEnd" in inst.get('targetname','')):

            # strip off the extra numbers on the end, so fizzler
            # models recieve inputs correctly (Valve bug!)
            if "_modelStart" in inst['targetname']:

                inst['targetname'] = (
                    inst['targetname'].split("_modelStart")[0] +
                    "_modelStart"
                    )
            else:
                inst['targetname'] = (
                    inst['targetname'].split("_modelEnd")[0] +
                    "_modelEnd"
                    )

            # one side of the fizzler models are rotated incorrectly
            # (upsidown), fix that...
            if inst['angles'] in fizzler_angle_fix:
                inst['angles'] = fizzler_angle_fix[inst['angles']]

        elif "ccflag_comball_base" in inst['file']: # Rexaura Flux Fields
            # find the triggers that match this entity and mod them
            for trig in map.iter_ents(
                    classname='trigger_portal_cleanser',
                    targetname=inst['targetname'] + "_brush",
                    ):
                for side in trig.sides():
                    side.mat = "tools/toolstrigger"

                # get rid of the _, allowing direct control from the instance.
                trig['targetname'] = inst['targetname'] + "-trigger"
                trig['classname'] = "trigger_multiple"
                trig["filtername"] = "@filter_pellet"
                trig["wait"] = "0.1"
                trig['spawnflags'] = "72" # Physics Objects, Everything
                # generate the output that triggers the pellet logic.
                trig.add_out(VLib.Output(
                    "OnStartTouch",
                    inst['targetname'] + "-branch_toggle",
                    "FireUser1",
                    ))

            inst.outputs.clear() # all the original ones are junk, delete them!

            for in_out in map.iter_ents_tags(
                    vals={
                        'classname':'func_instance',
                        'origin':inst['origin'],
                        'angles':inst['angles'],
                        },
                    tags={
                        'file':'ccflag_comball_out',
                        }
                    ):
                # find the instance to use for output and add the commands to trigger its logic
                inst.add_out(VLib.Output(
                    "OnUser1",
                    in_out['targetname'],
                    "FireUser1",
                    inst_in='in',
                    inst_out='out',
                    ))
                inst.add_out(VLib.Output(
                    "OnUser2",
                    in_out['targetname'],
                    "FireUser2",
                    inst_in='in',
                    inst_out='out',
                    ))
                    
        elif inst['file'] == INST_FILE['clearPanel']:
            make_static_pan(inst, "glass") # white/black are identified based on brush
        elif inst['file'] == INST_FILE['pistPlat']:
            make_static_pist(inst) #try to convert to static piston
            
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
    folders = get_valid_folders()
    utils.con_log("Creating Pack list...")
    has_items = False
    with open(pack_file, 'w') as fil:
        for item in to_pack:
            if item.startswith("|list|"):
                item = os.path.join(os.getcwd(), "pack_lists", item[6:])
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
                full = expand_source_name(item, folders)
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

    blacklist = [ # files are definitely not here
        "bin",
        "Soundtrack",
        "sdk_tools",
        "sdk_content"
        ]

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
    os.makedirs(os.path.dirname(new_path), exist_ok=True)
    with open(new_path, 'w') as f:
        map.export(file=f, inc_version=True)
    utils.con_log("Complete!")

def run_vbsp(args, do_swap):
    "Execute the original VBSP, copying files around so it works correctly."
    if do_swap: # we can't overwrite the original vmf, so we run VBSP from a separate location.
        if os.path.isfile(path.replace(".vmf", ".log")):
            shutil.copy(path.replace(".vmf",".log"), new_path.replace(".vmf",".log"))
    # Put quotes around args which contain spaces, and remove blank args.
    args = [('"' + x + '"' if " " in x else x) for x in args if x]

    arg = (
        '"'
        + os.path.normpath(
            os.path.join(
                os.getcwd(),
                "vbsp_original"
                )
            )
        + '" '
        + " ".join(args)
        )

    utils.con_log("Calling original VBSP...")
    utils.con_log(arg)
    code = subprocess.call(arg, stdout=None, stderr=subprocess.PIPE, shell=True)
    if code == 0:
        utils.con_log("Done!")
    else:
        utils.con_log("VBSP failed! (" + str(code) + ")")
        sys.exit(code)
    if do_swap: # copy over the real files so vvis/vrad can read them
        for exp in (".bsp", ".log", ".prt"):
            if os.path.isfile(new_path.replace(".vmf", exp)):
                shutil.copy(new_path.replace(".vmf", exp), path.replace(".vmf", exp))

# MAIN
if __name__ == '__main__': 
    utils.con_log("BEE2 VBSP hook initiallised.")

    to_pack = [] # the file path for any items that we should be packing

    root = os.path.dirname(os.getcwd())
    args = " ".join(sys.argv)
    new_args = sys.argv[1:]
    old_args = sys.argv[1:]
    new_path = ""
    path = ""
    for i, a in enumerate(new_args):
        fixed_a = os.path.normpath(a)
        if "sdk_content\\maps\\" in fixed_a:
            new_args[i] = fixed_a.replace(
                'sdk_content\\maps\\',
                'sdk_content\\maps\styled\\',
                1,
                )
            new_path = new_args[i]
            path = a
        # We need to strip these out, otherwise VBSP will get confused.
        if a == '-force_peti' or a == '-force_hammer':
            new_args[i] = ''
            old_args[i] = ''
        # Strip the entity limit, and the following number
        if a == '-entity_limit':
            new_args[i] = ''
            if len(new_args) > i+1 and new_args[i+1] == '1750':
                new_args[i+1] = ''

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

        load_map(path)

        map_seed = calc_rand_seed()

        (
        IS_PREVIEW, 
        GAME_MODE, 
        voice_timer_pos, 
        all_inst,
        ) = get_map_info()
        
        conditions.init(
            settings=settings, 
            vmf=map, 
            seed=map_seed, 
            preview=IS_PREVIEW, 
            mode=GAME_MODE,
            inst_list=all_inst,
            inst_files=INST_FILE,
            )
        
        fix_inst()
        conditions.check_all()
        add_extra_ents(mode=GAME_MODE)
        
        change_ents()
        change_brush()
        change_overlays()
        change_trig()
        change_func_brush()
        
        fix_worldspawn()
        add_voice(voice_timer_pos, GAME_MODE)
        save()

        run_vbsp(new_args, True)
        make_packlist(path) # VRAD will access the original BSP location

    utils.con_log("BEE2 VBSP hook finished!")
