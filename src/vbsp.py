import utils
# Do this very early, so we log the startup sequence.
LOGGER = utils.init_logging('bee2/vbsp.log')

import os
import os.path
import sys
import subprocess
import shutil
import random
import itertools
from enum import Enum
from collections import defaultdict, namedtuple
from decimal import Decimal

from property_parser import Property
from utils import Vec
from BEE2_config import ConfigFile
import vmfLib as VLib
import voiceLine
import instanceLocs
import conditions

from typing import (
    Dict, Tuple,
)


# Configuration data extracted from VBSP_config
settings = {
    "textures":       {},
    "fizzler":        {},
    "options":        {},
    "pit":            None,
    "elev_opt":       {},

    "style_vars":      defaultdict(bool),
    "has_attr":        defaultdict(bool),
    "packtrigger":     defaultdict(list),

    "voice_data":   Property("Quotes", []),
    }


TEX_VALVE = {
    # all the non-wall textures produced by the Puzzlemaker, and their
    # replacement keys:
    'signage/signage_exit': "overlay.exit",
    "signage/signage_overlay_arrow": "overlay.arrow",
    "signage/shape01": "overlay.dot",
    "signage/shape02": "overlay.moon",
    "signage/shape03": "overlay.triangle",
    "signage/shape04": "overlay.cross",
    "signage/shape05": "overlay.square",
    "signage/signage_shape_circle": "overlay.circle",
    "signage/signage_shape_sine": "overlay.sine",
    "signage/signage_shape_slash": "overlay.slash",
    "signage/signage_shape_star": "overlay.star",
    "signage/signage_shape_wavy": "overlay.wavy",
    "anim_wp/framework/backpanels_cheap": "special.behind",
    "plastic/plasticwall004a": "special.pedestalside",
    "anim_wp/framework/squarebeams": "special.edge",
    "nature/toxicslime_a2_bridge_intro": "special.goo",
    "nature/toxicslime_puzzlemaker_cheap": "special.goo_cheap",
    "glass/glasswindow007a_less_shiny": "special.glass",
    "metal/metalgrate018": "special.grating",
    "effects/laserplane": "special.laserfield",
    "sky_black": "special.sky",
    }

# Load and register these conditions
import cutoutTile  # This uses TEX_VALVE, so ensure that's defined

TEX_DEFAULTS = [
    # Extra default replacements we need to specially handle.

    # These have the same item so we can't store this in the regular
    # dictionary.
    ('metal/black_floor_metal_001c', 'black.floor'),
    ('tile/white_floor_tile002a',    'white.floor'),
    ('metal/black_floor_metal_001c', 'black.ceiling'),
    ('tile/white_floor_tile002a',    'white.ceiling'),
    ('tile/white_wall_tile003a',     'white.wall'),
    ('tile/white_wall_tile003h',     'white.wall'),
    ('tile/white_wall_tile003c',     'white.2x2'),
    ('tile/white_wall_tile003f',     'white.4x4'),
    ('metal/black_wall_metal_002c',  'black.wall'),
    ('metal/black_wall_metal_002e',  'black.wall'),
    ('metal/black_wall_metal_002a',  'black.2x2'),
    ('metal/black_wall_metal_002b',  'black.4x4'),

    # These replacements are deactivated when unset
    ('', 'special.white'),
    ('', 'special.black'),
    ('', 'special.white_wall'),
    ('', 'special.black_wall'),
    ('', 'special.white_gap'),
    ('', 'special.black_gap'),
    ('', 'special.goo_wall'),
    ('', 'special.edge_special'),
    ('', 'special.fizz_border'),

    # And these defaults have the extra scale information, which isn't
    # in the maps.
    ('0.25|signage/indicator_lights/indicator_lights_floor',
        'overlay.antline'),
    ('1|signage/indicator_lights/indicator_lights_corner_floor',
        'overlay.antlinecorner'),

    # This is for the P1 style, where antlines use different textures
    # on the floor and wall.
    # We just use the regular version if unset.
    ('', 'overlay.antlinecornerfloor'),
    ('', 'overlay.antlinefloor'),

    # Broken version of antlines
    ('', 'overlay.antlinebroken'),
    ('', 'overlay.antlinebrokencorner'),
    ('', 'overlay.antlinebrokenfloor'),
    ('', 'overlay.antlinebrokenfloorcorner'),

    # Only used if set - replace the decals with textures
    ('', 'special.bullseye_white_wall'),
    ('', 'special.bullseye_white_floor'),
    ('', 'special.bullseye_white_ceiling'),
    ('', 'special.bullseye_black_wall'),
    ('', 'special.bullseye_black_floor'),
    ('', 'special.bullseye_black_ceiling'),
]


class ORIENT(Enum):
    floor = 1
    wall = 2
    ceiling = 3
    ceil = 3

    def __str__(self):
        if self is ORIENT.floor:
            return 'floor'
        elif self is ORIENT.wall:
            return 'wall'
        elif self is ORIENT.ceiling:
            return 'ceiling'

# The textures used for white surfaces.
WHITE_PAN = [
    "tile/white_floor_tile002a",
    "tile/white_wall_tile003a",
    "tile/white_wall_tile003h",

    "tile/white_wall_tile003c",  # 2x2
    "tile/white_wall_tile003f",  # 4x4
    ]

# Ditto for black surfaces.
BLACK_PAN = [
    "metal/black_floor_metal_001c",
    "metal/black_wall_metal_002c",
    "metal/black_wall_metal_002e",
    "metal/black_wall_metal_002a",  # 2x2
    "metal/black_wall_metal_002b",  # 4x4
    ]

GOO_TEX = [
    "nature/toxicslime_a2_bridge_intro",
    "nature/toxicslime_puzzlemaker_cheap",
    ]

ANTLINES = {
    'straight': "signage/indicator_lights/indicator_lights_floor",
    'corner': "signage/indicator_lights/indicator_lights_corner_floor",
    }

DEFAULTS = {
    "goo_mist":                 "0",  # Add info_particle_systems to goo pits

    "remove_info_lighting":     "0",  # Remove the glass info_lighting ents
    "remove_pedestal_plat":     "0",  # Remove pedestal button platforms
    "remove_exit_signs":        "0",  # Remove the exit sign overlays

    "random_blackwall_scale":   "0",  # P1 style randomly sized black walls

    "rotate_edge":              "0",  # Rotate squarebeams textures 90 degrees.
    "reset_edge_off":           "0",  # Reset the scale on
    "edge_scale":               "0.15",  # The scale on squarebeams textures
    "rotate_edge_special":      "0",    # Ditto for angled/flip panels
    "reset_edge_off_special":   "",
    "edge_scale_special":       "0.15",

    # Reset offsets for all white/black brushes, so embedface has correct
    # texture matching
    "tile_texture_lock":        "1",

    "fizz_border_vertical":     "0",  # The texture is oriented vertically
    "fizz_border_thickness":    "8",  # The width of the overlays
    "fizz_border_repeat":       "128",  # The width lengthways

    "force_fizz_reflect":       "0",  # Force fast reflections on fizzlers
    "force_brush_reflect":      "0",  # Force fast reflections on func_brushes

    # Allow changing flip panel sounds.
    "flip_sound_start":        "World.a3JumpIntroRotatingPanelTravel",
    "flip_sound_stop":         "World.a3JumpIntroRotatingPanelArrive",


    "staticPan":                "NONE",  # folder for static panels
    # Template used for static panels set to 0 degrees
    "static_pan_temp_flat":     "BEE2_STATIC_PAN_FLAT",
    # Template used for angled static panels
    "static_pan_temp_white":     "BEE2_STATIC_PAN_ANGLED",
    "static_pan_temp_black":     "BEE2_STATIC_PAN_ANGLED",

    "signInst":                 "NONE",  # adds this instance on all the signs.
    "signSize":                 "32",  # Allow resizing the sign overlays
    "signPack":                 "",  # Packlist to use when sign inst is added

    "broken_antline_chance":    "0",  # The chance an antline will be 'broken'
    # The maximum distance of a single broken section
    "broken_antline_distance":  "3",

    "glass_scale":              "0.15",  # Scale of glass texture
    "grating_scale":            "0.15",  # Scale of grating texture
    "goo_scale":                "1",  # Scale of goo material

    # Add lights to disguise the bottomless pit transition
    "pit_blend_light":          "",

    # Textures used for the glass/grating clips.
    "glass_clip":               "BEE2/glass_player_clip",
    "grating_clip":             "BEE2/grate_player_clip",
    # Packlists for glass and gratings
    "glass_pack":               "PACK_PLAYER_CLIP_GLASS",
    "grating_pack":             "PACK_PLAYER_CLIP_GRATE",
    # Filter used on grating vphysics_clips
    "grating_filter":           "@not_paint_bomb",

    "clump_wall_tex":           "0",  # Use the clumping wall algorithm
    "clump_ceil":               "0",  # Use if for ceilings?
    "clump_floor":              "0",  # Use it for floors?
    "clump_size":               "4",  # The maximum length of a clump
    "clump_width":              "2",  # The width of a clump
    "clump_number":             "6",  # The number of clumps created

    # Default to the origin of the elevator instance - that's likely to
    # be enclosed
    "music_location_sp":        "-2000 2000 0",
    "music_location_coop":      "-2000 -2000 0",
    # Instance used for pti_ents
    "global_pti_ents":          "instances/BEE2/global_pti_ents.vmf",
    # Default pos is next to arrival_departure_ents
    # Note that many other ents are added at this point, since it's
    # boxed in.
    "global_pti_ents_loc":      "-2400 -2800 0",
    # Location of the model changer instance if needed
    "model_changer_loc":        "-2400 -2800 -256",

    ######
    # The following are set by the BEE2.4 app automatically:

    # The file path of the BEE2 app that generated the config
    "bee2_loc":                 "",
    "game_id":                  "620",  # The game's steam ID
    "music_id":                 "<NONE>",  # The music ID which was selected
    "music_instance":           "",  # The instance for the chosen music
    "music_soundscript":        "",  # The soundscript for the chosen music
    "elev_type":                "RAND",  # What type of script to use:
    # Either "RAND", "FORCE", "NONE" or "BSOD"
    "elev_horiz":               "",  # The horizontal elevator video to use
    "elev_vert":                "",  # The vertical elevator video to use
    "voice_id":                 "<NONE>",  # The voice pack which was selected
    "voice_char":               "",  # Characters in the pack
    "cave_port_skin":           "",  # If a Cave map, indicate which portrait to use.
    }

# angles needed to ensure fizzlers are not upside-down
# (key=original, val=fixed)
FIZZLER_ANGLE_FIX = {
    "0 0 -90":    "0 180 90",
    "0 0 180":    "0 180 180",
    "0 90 0":     "0 -90 0",
    "0 90 -90":   "0 -90 90",
    "0 180 -90":  "0 0 90",
    "0 -90 -90":  "0 90 90",
    "90 180 0":   "-90 0 0",
    "90 -90 0":   "-90 90 0",
    "-90 180 0":  "90 0 0",
    "-90 -90 0":  "90 90 0",
    }

TEX_FIZZLER = {
    "effects/fizzler_center": "center",
    "effects/fizzler_l": "left",
    "effects/fizzler_r": "right",
    "effects/fizzler": "short",
    "tools/toolsnodraw": "nodraw",
    }

FIZZ_OPTIONS = {
    "scanline": "0",
    }

BEE2_config = None  # ConfigFile

GAME_MODE = 'ERR'
IS_PREVIEW = 'ERR'

# These are faces & overlays which have been forceably set by conditions,
# and will not be overwritten later.
IGNORED_FACES = set()
IGNORED_OVERLAYS = set()

TO_PACK = set()  # The packlists we want to pack.
PACK_FILES = set()  # Raw files we force pack

##################
# UTIL functions #
##################


def get_opt(name) -> str:
    return settings['options'][name.casefold()]


def get_bool_opt(name, default=False):
    return utils.conv_bool(get_opt(name), default)


def get_tex(name):
    if name in settings['textures']:
        return random.choice(settings['textures'][name])
    else:
        raise Exception('No texture "' + name + '"!')


def alter_mat(face, seed=None, texture_lock=True):
    """Randomise the texture used for a face, based on configured textures.

    This uses the TEX_VALVE dict to identify the kind of texture, but
    uses the face orientation to determine the wall direction - the
    PeTI often uses textures on the wrong sides for various reasons.

    If texture_lock is false, the offset of the texture will be reset to 0,0.
    That ensures embedface will have aligned textures.
    """
    mat = face.mat.casefold()
    if seed:
        random.seed(seed)

    if mat in TEX_VALVE:  # should we convert it?
        face.mat = get_tex(TEX_VALVE[mat])
        return True
    elif mat in BLACK_PAN or mat in WHITE_PAN:
        orient = get_face_orient(face)
        face.mat = get_tex(get_tile_type(mat, orient))

        if not texture_lock:
            face.offset = 0

        return True
    elif mat in TEX_FIZZLER:
        face.mat = settings['fizzler'][TEX_FIZZLER[mat]]
    else:
        return False


def get_tile_type(mat, orient):
    """Get the texture command for a texture."""
    surf_type = 'white' if mat in WHITE_PAN else 'black'
    # We need to handle specially the 4x4 and 2x4 variants.
    # These are used in the embedface brushes, so they should
    # remain having small tile size. Wall textures have 4x4 and 2x2,
    # but floor/ceilings only have 4x4 sizes (since they usually
    # just stay the same).
    if orient == ORIENT.wall:
        if (mat == 'metal/black_wall_metal_002b' or
                mat == 'tile/white_wall_tile003f'):
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
    return surf_type + '.' + orient

##################
# MAIN functions #
##################


def load_settings():
    """Load in all our settings from vbsp_config."""
    global BEE2_config
    try:
        with open("bee2/vbsp_config.cfg") as config:
            conf = Property.parse(config, 'bee2/vbsp_config.cfg')
    except FileNotFoundError:
        LOGGER.warning('Error: No vbsp_config file!')
        conf = Property(None, [])
        # All the find_all commands will fail, and we will use the defaults.

    tex_defaults = list(TEX_VALVE.items()) + TEX_DEFAULTS

    # Collect texture values from the config.
    # They are collected in a list for each option, allowing
    # multiple random textures for each slot.
    for item, key in tex_defaults:
        cat, name = key.split(".")
        value = [
            prop.value
            for prop in
            conf.find_all('textures', cat, name)
        ]
        if len(value) == 0:
            # If there are no values, just use the original value
            settings['textures'][key] = [item]
        else:
            settings['textures'][key] = value

    # Get main config options. All options must be in the DEFAULTS dict -
    # if not set, they fallback to that value.
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

        for key, item in FIZZ_OPTIONS.items():
            settings['fizzler'][key] = fizz_opt[key, settings['fizzler'][key]]

    # The voice line property block
    for quote_block in conf.find_all("quotes"):
        settings['voice_data'] += quote_block.value

    # Configuration properties for styles.
    for stylevar_block in conf.find_all('stylevars'):
        for var in stylevar_block:
            settings['style_vars'][
                var.name.casefold()] = utils.conv_bool(var.value)

    # Load in the config file holding item data.
    # This is used to lookup item's instances, or their connection commands.
    with open('bee2/instances.cfg') as f:
        instance_file = Property.parse(
            f, 'bee2/instances.cfg'
        )
    # Parse that data in the relevant modules.
    instanceLocs.load_conf(instance_file)

    # Parse all the conditions.
    for cond in conf.find_all('conditions', 'condition'):
        conditions.add(cond)

    # These are custom textures we need to pack, if they're in the map.
    # (World brush textures, antlines, signage, glass...)
    for trigger in conf.find_all('PackTriggers', 'material'):
        mat = trigger['texture', ''].casefold()
        packlist = trigger['packlist', '']
        if mat and packlist:
            settings['packtrigger'][mat].append(packlist)

    # Files that the BEE2.4 app knows we need to pack - music, style, etc.
    # This is a bit better than a lot of extra conditions.
    for force_files in conf.find_all('PackTriggers', 'Forced', 'File'):
        PACK_FILES.add(force_files.value)

    # Get configuration for the elevator, defaulting to ''.
    elev = conf.find_key('elevator', [])
    settings['elevator'] = {
        key: elev[key, '']
        for key in
        (
            'type', 'horiz', 'vert',
            'scr_rand', 'scr_force', 'scr_bsod',
        )
    }

    # Bottomless pit configuration
    pit = conf.find_key("bottomless_pit", [])
    if pit:
        settings['pit'] = {
            'tex_goo': pit['goo_tex', 'nature/toxicslime_a2_bridge_intro'],
            'tex_sky': pit['sky_tex', 'tools/toolsskybox'],
            'should_tele': utils.conv_bool(pit['teleport', '0']),
            'tele_dest': pit['tele_target', '@goo_targ'],
            'tele_ref': pit['tele_ref', '@goo_ref'],
            'off_x': utils.conv_int(pit['off_x', '0']),
            'off_y': utils.conv_int(pit['off_y', '0']),
            'height': utils.conv_int(pit['max_height', '386'], 386),
            'skybox': pit['sky_inst', ''],
            'skybox_ceil': pit['sky_inst_ceil', ''],
            'targ': pit['targ_inst', ''],
            'blend_light': pit['blend_light', '']
        }
        pit_inst = settings['pit']['inst'] = {}
        for inst_type in (
                'support',
                'side',
                'corner',
                'double',
                'triple',
                'pillar',
                ):
            vals = [prop.value for prop in pit.find_all(inst_type + '_inst')]
            if len(vals) == 0:
                vals = [""]
            pit_inst[inst_type] = vals
    else:
        settings['pit'] = None

    if get_opt('BEE2_loc') != '':
        BEE2_config = ConfigFile(
            'config/compile.cfg',
            root=get_opt('BEE2_loc'),
        )
    else:
        BEE2_config = ConfigFile(None)

    LOGGER.info("Settings Loaded!")


def load_map(map_path):
    """Load in the VMF file."""
    global VMF
    with open(map_path) as file:
        LOGGER.info("Parsing Map...")
        props = Property.parse(file, map_path)
    LOGGER.info('Reading Map...')
    VMF = VLib.VMF.parse(props)
    LOGGER.info("Parsing complete!")


@conditions.meta_cond(priority=100)
def add_voice(_):
    """Add voice lines to the map."""
    voiceLine.add_voice(
        voice_data=settings['voice_data'],
        has_items=settings['has_attr'],
        style_vars_=settings['style_vars'],
        vmf_file=VMF,
        map_seed=MAP_SEED,
        )


@conditions.meta_cond(priority=-250)
def add_fizz_borders(_):
    """Generate overlays at the top and bottom of fizzlers.

    This is used in 50s and BTS styles.
    """
    tex = settings['textures']['special.fizz_border']
    if tex == ['']:
        # No textures were defined!
        return

    flip_uv = get_bool_opt('fizz_border_vertical')
    overlay_thickness = utils.conv_int(get_opt('fizz_border_thickness'), 8)
    overlay_repeat = utils.conv_int(get_opt('fizz_border_repeat'), 128)

    # First, figure out the orientation of every fizzler via their model.
    fizz_directions = {}  # type: Dict[str, Tuple[Vec, Vec, Vec]]
    for inst in VMF.by_class['func_instance']:
        if '_modelStart' not in inst['targetname', '']:
            continue
        name = inst['targetname'].rsplit('_modelStart', 1)[0] + '_brush'
        # Once per fizzler only!
        if name not in fizz_directions:
            fizz_directions[name] = (
                # Normal direction of surface
                Vec(1, 0, 0).rotate_by_str(inst['angles']),
                # 'Horizontal' direction (for vertical fizz attached to walls)
                Vec(0, 0, 1).rotate_by_str(inst['angles']),
                # 'Vertical' direction (for vertical fizz attached to walls)
                Vec(0, 1, 0).rotate_by_str(inst['angles']),
            )

    for brush_ent in (VMF.by_class['trigger_portal_cleanser'] |
                      VMF.by_class['func_brush']):
        try:
            norm, horiz, vert = fizz_directions[brush_ent['targetname']]
        except KeyError:
            continue
        norm_dir = norm.axis()
        horiz_dir = horiz.axis()
        vert_dir = vert.axis()

        bbox_min, bbox_max = brush_ent.get_bbox()
        dimensions = bbox_max - bbox_min

        # We need to snap the axis normal_axis to the grid, since it could
        # be forward or back.
        min_pos = bbox_min.copy()
        min_pos[norm_dir] = min_pos[norm_dir] // 128 * 128 + 64

        max_pos = min_pos.copy()
        max_pos[vert_dir] += 128

        min_faces = []
        max_faces = []

        overlay_len = int(dimensions[horiz_dir])

        for offset in range(64, overlay_len, 128):
            # Each position on top or bottom, inset 64 from each end
            min_pos[horiz_dir] = bbox_min[horiz_dir] + offset
            max_pos[horiz_dir] = min_pos[horiz_dir]

            solid = conditions.SOLIDS.get(min_pos.as_tuple())
            if solid is not None:
                min_faces.append(solid.face)
            solid = conditions.SOLIDS.get(max_pos.as_tuple())
            if solid is not None:
                max_faces.append(solid.face)

        if flip_uv:
            u_rep = 1
            v_rep = overlay_len / overlay_repeat
        else:
            u_rep = overlay_len / overlay_repeat
            v_rep = 1

        if min_faces:
            min_origin = bbox_min.copy()
            min_origin[norm_dir] += 1
            min_origin[horiz_dir] += overlay_len/2
            min_origin[vert_dir] += 16
            VLib.make_overlay(
                VMF,
                normal=abs(vert),
                origin=min_origin,
                uax=horiz * overlay_len,
                vax=norm * overlay_thickness,
                material=random.choice(tex),
                surfaces=min_faces,
                u_repeat=u_rep,
                v_repeat=v_rep,
                swap=flip_uv,
            )
        if max_faces:
            max_origin = bbox_max.copy()
            max_origin[norm_dir] -= 1
            max_origin[horiz_dir] -= overlay_len/2
            max_origin[vert_dir] -= 16
            VLib.make_overlay(
                VMF,
                normal=-abs(vert),
                origin=max_origin,
                uax=horiz * overlay_len,
                vax=norm * overlay_thickness,
                material=random.choice(tex),
                surfaces=max_faces,
                u_repeat=u_rep,
                v_repeat=v_rep,
                swap=flip_uv,
            )


@conditions.meta_cond(priority=-200, only_once=False)
def fix_fizz_models(inst):
    """Fix some bugs with fizzler model instances.
    This removes extra numbers from model instances, which prevents
    inputs from being read correctly.
    It also rotates fizzler models so they are both facing the same way.
    """
    # Fizzler model names end with this special string
    if ("_modelStart" in inst['targetname', ''] or
            "_modelEnd" in inst['targetname', '']):

        # strip off the extra numbers on the end, so fizzler
        # models recieve inputs correctly (Valve bug!)
        if "_modelStart" in inst['targetname', '']:

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
        if inst['angles'] in FIZZLER_ANGLE_FIX:
            inst['angles'] = FIZZLER_ANGLE_FIX[inst['angles']]


@conditions.meta_cond(priority=-100, only_once=False)
def static_pan(inst):
    """Switches glass angled panels to static instances, if needed."""
    if inst['file'].casefold() in instanceLocs.resolve('<ITEM_PANEL_CLEAR>'):
        # white/black are found via the func_brush
        make_static_pan(inst, "glass")


ANGLED_PAN_BRUSH = {}  # Dict mapping locations -> func_brush face, name
FLIP_PAN_BRUSH = {}  # locations -> white, black faces
# Record info_targets at the angled panel positions, so we can correct
# their locations for static panels
PANEL_FAITH_TARGETS = defaultdict(list)


@conditions.meta_cond(-1000)
def find_panel_locs(_):
    """Find the locations of panels, used for FaithBullseye."""
    # Angled Panels
    for brush in VMF.by_class['func_brush']:
        if "-model_arms" not in brush['parentname', '']:
            continue
        for face in brush.sides():
            # Find the face which isn't backpanel/squarebeams
            if face.mat.casefold() not in (
                    'anim_wp/framework/squarebeams',
                    'anim_wp/framework/backpanels_cheap'):
                ANGLED_PAN_BRUSH[face.get_origin().as_tuple()] = (
                    face,
                    # Repeat the change done later in change_func_brush()
                    brush['targetname'].replace(
                        '_panel_top',
                        '-brush',
                    ),
                )
                break

    # Flip panels
    for brush in VMF.by_class['func_door_rotating']:
        white_face = None
        black_face = None
        for face in brush.sides():
            if face.mat.casefold() in WHITE_PAN:
                white_face = face
            if face.mat.casefold() in BLACK_PAN:
                black_face = face
        if white_face and black_face:
            # The white face is positioned facing outward, so its origin is
            # centered nicely.
            FLIP_PAN_BRUSH[white_face.get_origin().as_tuple()] = (
                white_face,
                black_face,
            )


@conditions.make_result_setup('FaithBullseye')
def res_faith_bullseye_check(res):
    """Do a check to ensure there are actually textures availble."""
    for col in ('white', 'black'):
        for orient in ('wall', 'floor', 'ceiling'):
            if settings['textures'][
                    'special.bullseye_{}_{}'.format(col, orient)
                                        ] != ['']:
                return res.value
    return None  # No textures!


@conditions.make_result('FaithBullseye')
def res_faith_bullseye(inst, res):
    """Replace the bullseye instances with textures instead."""

    pos = Vec(0, 0, -64).rotate_by_str(inst['angles'])
    pos = (pos + Vec.from_str(inst['origin'])).as_tuple()

    norm = Vec(0, 0, -1).rotate_by_str(inst['angles'])

    face = None
    color = None

    # Look for a world brush
    if pos in conditions.SOLIDS:
        solid = conditions.SOLIDS[pos]
        if solid.normal == norm:
            face = solid.face
            color = solid.color
            if make_bullseye_face(face, color):
                # Use an alternate instance, without the decal ent.
                inst['file'] = res.value

    # Look for angled panels
    if face is None and pos in ANGLED_PAN_BRUSH:
        face, br_name = ANGLED_PAN_BRUSH[pos]
        if face.mat.casefold() in WHITE_PAN:
            color = 'white'
        elif face.mat.casefold() in BLACK_PAN:
            color = 'black'
        else:
            # Should never happen - no angled panel should be textured
            # yet. Act as if the panel wasn't there.
            face = None

        if face is not None and make_bullseye_face(face, color):
            # The instance won't be used -
            # there's already a helper
            inst['file'] = ''
            # We want to find the info_target, and parent it to the panel.

            # The target is located at the center of the brush, which
            # we already calculated.

            for targ in VMF.by_class['info_target']:
                if Vec.from_str(targ['origin']) == pos:
                    targ['parentname'] = br_name
                    PANEL_FAITH_TARGETS[pos].append(targ)

    # Look for flip panels
    if face is None and pos in FLIP_PAN_BRUSH:
        white_face, black_face = FLIP_PAN_BRUSH[pos]
        flip_orient = get_face_orient(white_face)
        if make_bullseye_face(white_face, 'white', flip_orient):
            # Use the white panel orient for both sides since the
            # black panel spawns facing backward.
            if make_bullseye_face(black_face, 'black', flip_orient):
                # Flip panels also have their own helper..
                inst['file'] = ''

    # There isn't a surface - blank the instance, it's in goo or similar
    if face is None:
        inst['file'] = ''
        return


def make_bullseye_face(
    face: VLib.Side,
    color,
    orient: ORIENT=None,
    ) -> bool:
    """Switch the given face to use a bullseye texture.

    Returns whether it was sucessful or not.
    """
    if orient is None:
        orient = get_face_orient(face)

    mat = get_tex('special.bullseye_{}_{!s}'.format(color, orient))

    # Fallback to floor texture if using ceiling or wall
    if orient is not ORIENT.floor and mat == '':
        face.mat = get_tex('special.bullseye_{}_floor'.format(color))

    if face.mat == '':
        return False
    else:
        face.mat = mat
        IGNORED_FACES.add(face)
        return True

FIZZ_BUMPER_WIDTH = 32  # The width of bumper brushes
FIZZ_NOPORTAL_WIDTH = 16  # Width of noportal_volumes


@conditions.meta_cond(priority=200, only_once=True)
def anti_fizz_bump(inst):
    """Create portal_bumpers and noportal_volumes surrounding fizzlers.

    This makes it more difficult to portal-bump through an active fizzler.
    It is only applied to trigger_portal_cleansers with the Client flag
    checked.
    """
    # Subtract 2 for the fizzler width, and divide
    # to get the difference for each face.

    if not utils.conv_bool(settings['style_vars']['fixfizzlerbump']):
        return True

    # Only use 1 bumper entity for each fizzler, since we can.
    bumpers = {}

    LOGGER.info('Adding Portal Bumpers to fizzlers...')
    for cleanser in VMF.by_class['trigger_portal_cleanser']:
        # Client bit flag = 1, triggers without it won't destroy portals
        # - so don't add a bumper.
        if int(cleanser['spawnflags']) & 1 != 1:
            continue

        fizz_name = cleanser['targetname']
        if fizz_name.endswith('_brush'):
            # Fizzlers will be changed to this in fix_func_brush()
            fizz_name = fizz_name[:-6] + '-br_brush'

        # Only have 1 bumper per brush
        if fizz_name not in bumpers:
            bumper = bumpers[fizz_name] = VMF.create_ent(
                classname='func_portal_bumper',
                targetname=fizz_name,
                origin=cleanser['origin'],
                spawnflags='1',
                # Start off, we can't really check if the original
                # does, but that's usually handled by the instance anyway.
            )
        else:
            bumper = bumpers[fizz_name]

        # Noportal_volumes need separate parts, since they can't be
        # concave.
        noportal = VMF.create_ent(
            classname='func_noportal_volume',
            targetname=fizz_name,
            origin=cleanser['origin'],
            spawnflags='1',
        )

        # Copy one of the solids to use as a base, so the texture axes
        # are correct.
        if len(cleanser.solids) == 1:
            # It's a 128x128 brush, with only one solid
            bumper_brush = cleanser.solids[0].copy()
        else:
            # It's a regular one, we want the middle/large section
            bumper_brush = cleanser.solids[1].copy()
        bumper.solids.append(bumper_brush)

        noportal_brush = bumper_brush.copy()
        noportal.solids.append(noportal_brush)

        conditions.widen_fizz_brush(
            bumper_brush,
            FIZZ_BUMPER_WIDTH,
            bounds=cleanser.get_bbox(),
        )

        conditions.widen_fizz_brush(
            noportal_brush,
            FIZZ_NOPORTAL_WIDTH,
            bounds=cleanser.get_bbox(),
        )

        for face in bumper_brush:
            face.mat = 'tools/toolsinvisible'

        for face in noportal_brush:
            face.mat = 'tools/toolsinvisible'

    LOGGER.info('Done!')


@conditions.meta_cond(priority=500, only_once=True)
def set_player_portalgun(inst):
    """Controls which portalgun the player will be given.

    This does not apply to coop. It checks the 'blueportal' and
    'orangeportal' attributes to see what are in the map.
    - If there are no spawners in the map, the player gets a dual portal
      device.
    - If there are only blue portal spawners, the player gets a orange-only
      gun.
    - If there are only orange portal spawners, the player gets a blue-
      only gun (Regular single portal device)
    - If there are both spawner types, the player doesn't get a gun.
    - The two relays '@player_has_blue' and '@player_has_oran' will be
      triggered OnMapSpawn if the player has those portals.
    """
    if GAME_MODE == 'COOP':
        return  # Don't change portalgun in Portal 2 Coop
    if get_opt('game_id') == utils.STEAM_IDS['TAG']:
        return  # Aperture Tag doesn't have Portal Guns!

    LOGGER.info('Setting Portalgun:')

    has = settings['has_attr']

    blue_portal = not has['blueportal']
    oran_portal = not has['orangeportal']

    LOGGER.info('Blue: {}, Orange: {!s}',
        'Y' if blue_portal else 'N',
        'Y' if oran_portal else 'N',
    )

    if blue_portal and oran_portal:
        has['spawn_dual'] = True
        has['spawn_single'] = False
        has['spawn_nogun'] = False
    elif blue_portal or oran_portal:
        has['spawn_dual'] = False
        has['spawn_single'] = True
        has['spawn_nogun'] = False
        inst = VMF.create_ent(
            classname='func_instance',
            targetname='pgun_logic',
            origin=get_opt('global_pti_ents_loc'),  # Reuse this location
            angles='0 0 0',
            file='instances/BEE2/logic/pgun/pgun_single.vmf',
        )
        # Set which portals this weapon_portalgun can fire
        inst.fixup['blue_portal'] = utils.bool_as_int(blue_portal)
        inst.fixup['oran_portal'] = utils.bool_as_int(oran_portal)
    else:
        has['spawn_dual'] = False
        has['spawn_single'] = False
        has['spawn_nogun'] = True
        has_gun = False
        # This instance only has a trigger_weapon_strip.
        VMF.create_ent(
            classname='func_instance',
            targetname='pgun_logic',
            origin=get_opt('global_pti_ents_loc'),
            angles='0 0 0',
            file='instances/BEE2/logic/pgun/no_pgun.vmf',
        )

    if blue_portal or oran_portal:
        auto = VMF.create_ent(
            classname='logic_auto',
            origin=get_opt('global_pti_ents_loc'),
            spawnflags='1',  # Remove on Fire
        )
        if blue_portal:
            auto.add_out(VLib.Output(
                'OnMapSpawn',
                '@player_has_blue',
                'Trigger',
                times=1,
            ))
        if oran_portal:
            auto.add_out(VLib.Output(
                'OnMapSpawn',
                '@player_has_oran',
                'Trigger',
                times=1,
            ))

    LOGGER.info('Done!')


@conditions.meta_cond(priority=750, only_once=True)
def add_screenshot_logic(inst):
    """If the screenshot type is 'auto', add in the needed ents."""
    if BEE2_config.get_val(
        'Screenshot', 'type', 'PETI'
    ).upper() == 'AUTO':
        VMF.create_ent(
            classname='func_instance',
            file='instances/BEE2/logic/screenshot_logic.vmf',
            origin=get_opt('global_pti_ents_loc'),
            angles='0 0 0',
        )
        LOGGER.info('Added Screenshot Logic')


@conditions.meta_cond(priority=50, only_once=True)
def set_elev_videos(_):
    vid_type = settings['elevator']['type'].casefold()

    LOGGER.info('Elevator type: {}', vid_type.upper())

    if vid_type == 'none' or GAME_MODE == 'COOP':
        # The style doesn't have an elevator...
        return
    elif vid_type == 'bsod':
        # This uses different video shaping!
        script = settings['elevator']['scr_bsod']
        vert_vid = 'bluescreen'
        horiz_vid = 'bluescreen'
    elif vid_type == 'force':
        # Use the given video
        script = settings['elevator']['scr_force']
        vert_vid = settings['elevator']['vert']
        horiz_vid = settings['elevator']['horiz']
    elif vid_type == 'rand':
        script = settings['elevator']['scr_rand']
        vert_vid = None
        horiz_vid = None
    else:
        LOGGER.warning('Invalid elevator type!')
        return

    transition_ents = instanceLocs.resolve('[transitionents]')
    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in transition_ents:
            continue
        if vert_vid:
            inst.fixup['$vert_video'] = 'media/' + vert_vid + '.bik'
        if horiz_vid:
            inst.fixup['$horiz_video'] = 'media/' + horiz_vid + '.bik'

        # Create the video script
        VMF.create_ent(
            classname='logic_script',
            targetname='@video_splitter',
            vscripts=script,
            origin=inst['origin'],
        )
    # Ensure the script gets packed.
    PACK_FILES.add('scripts/vscripts/' + script)


@conditions.meta_cond(priority=200, only_once=True)
def ap_tag_modifications(_):
    """Perform modifications for Aperture Tag.

    * All fizzlers will be combined with a trigger_paint_cleanser
    * Paint is always present in every map!
    * Suppress ATLAS's Portalgun in coop
    * Override the transition ent instance to have the Gel Gun
    * Create subdirectories with the user's steam ID
    """
    if get_opt('game_id') != utils.STEAM_IDS['APTAG']:
        return  # Wrong game!

    LOGGER.info('Performing Aperture Tag modifications...')

    has = settings['has_attr']
    # This will enable the PaintInMap property.
    has['Gel'] = True

    # Set as if the player spawned with no pgun
    has['spawn_dual'] = False
    has['spawn_single'] = False
    has['spawn_nogun'] = True

    for fizz in VMF.by_class['trigger_portal_cleanser']:
        p_fizz = fizz.copy()
        p_fizz['classname'] = 'trigger_paint_cleanser'
        VMF.add_ent(p_fizz)

        if p_fizz['targetname'].endswith('_brush'):
            p_fizz['targetname'] = p_fizz['targetname'][:-6] + '-br_fizz'

        del p_fizz['drawinfastreflection']
        del p_fizz['visible']
        del p_fizz['useScanline']

        for side in p_fizz.sides():
            side.mat = 'tools/toolstrigger'
            side.scale = 0.25

    if GAME_MODE == 'COOP':
        VMF.create_ent(
            classname='info_target',
            targetname='supress_blue_portalgun_spawn',
            origin=get_opt('global_pti_ents_loc'),
            angles='0 0 0'
        )

    transition_ents = instanceLocs.resolve('[transitionents]')
    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in transition_ents:
            continue
        inst['file'] = 'instances/bee2/transition_ents_tag.vmf'

    # Because of a bug in P2, these folders aren't created automatically.
    # We need a folder with the user's ID in portal2/maps/puzzlemaker.
    try:
        puzz_folders = os.listdir('../aperturetag/puzzles')
    except FileNotFoundError:
        LOGGER.warning("Aperturetag/puzzles/ doesn't exist??")
    else:
        for puzz_folder in puzz_folders:
            new_folder = os.path.abspath(os.path.join(
                '../portal2/maps/puzzlemaker',
                puzz_folder,
            ))
            LOGGER.info('Creating', new_folder)
            os.makedirs(
                new_folder,
                exist_ok=True,
            )


def get_map_info():
    """Determine various attributes about the map.

    This also set the 'preview in elevator' options and forces
    a particular entry/exit hallway.

    - SP/COOP status
    - if in preview mode
    """
    global GAME_MODE, IS_PREVIEW

    inst_files = set()  # Get a set of every instance in the map.
    file_coop_exit = instanceLocs.resolve('[coopExit]')
    file_sp_exit = instanceLocs.resolve('[spExit]')
    file_sp_entry = instanceLocs.resolve('[spEntry]')
    file_coop_corr = instanceLocs.resolve('[coopCorr]')
    file_sp_entry_corr = instanceLocs.resolve('[spEntryCorr]')
    file_sp_exit_corr = instanceLocs.resolve('[spExitCorr]')
    file_sp_door_frame = instanceLocs.resolve('[door_frame]')

    # Should we force the player to spawn in the elevator?
    elev_override = BEE2_config.get_bool('General', 'spawn_elev')

    if elev_override:
        # Make conditions set appropriately
        LOGGER.info('Forcing elevator spawn!')
        IS_PREVIEW = False

    no_player_start_inst = (
        # All the instances that have the no_player start value
        file_sp_entry +
        file_coop_corr +
        file_sp_entry_corr +
        file_sp_exit_corr
    )

    # Door frames use the same instance for both the entry and exit doors,
    # and it'd be useful to disinguish between them. Add an instvar to help.
    door_frames = []
    entry_origin = Vec(-999, -999, -999)
    exit_origin = Vec(-999, -999, -999)

    override_sp_entry = BEE2_config.get_int('Corridor', 'sp_entry', 0)
    override_sp_exit = BEE2_config.get_int('Corridor', 'sp_exit', 0)
    override_coop_corr = BEE2_config.get_int('Corridor', 'coop', 0)

    for item in VMF.by_class['func_instance']:
        # Loop through all the instances in the map, looking for the entry/exit
        # doors.
        # - Read the $no_player_start var to see if we're in preview mode,
        #   or override the value if specified in compile.cfg
        # - Determine whether the map is SP or Coop by the
        #   presence of certain instances.
        # - Switch the entry/exit corridors to particular ones if specified
        #   in compile.cfg
        # Also build a set of all instances, to make a condition check easy
        # later

        file = item['file'].casefold()
        LOGGER.debug('File:', file)
        if file in no_player_start_inst:
            if elev_override:
                item.fixup['no_player_start'] = '1'
            else:
                IS_PREVIEW = not utils.conv_bool(item.fixup['no_player_start'])
        if file in file_sp_exit_corr:
            GAME_MODE = 'SP'
            exit_origin = Vec.from_str(item['origin'])
            if override_sp_exit == 0:
                LOGGER.info(
                    'Using random exit ({})',
                    str(file_sp_exit_corr.index(file) + 1)
                )
            else:
                LOGGER.info('Setting exit to {}', override_sp_exit)
                item['file'] = file_sp_exit_corr[override_sp_exit-1]
        elif file in file_sp_entry_corr:
            GAME_MODE = 'SP'
            entry_origin = Vec.from_str(item['origin'])
            if override_sp_entry == 0:
                LOGGER.info(
                    'Using random entry ({})',
                    str(file_sp_entry_corr.index(file) + 1),
                )
            else:
                LOGGER.info('Setting entry to {}', override_sp_entry)
                item['file'] = file_sp_entry_corr[override_sp_entry-1]
        elif file in file_coop_corr:
            GAME_MODE = 'COOP'
            if override_coop_corr == 0:
                LOGGER.info(
                    'Using random exit ({})',
                    str(file_coop_corr.index(file) + 1),
                )
            else:
                LOGGER.info('Setting coop exit to {}', override_coop_corr)
                item['file'] = file_coop_corr[override_coop_corr-1]
        elif file in file_coop_exit:
            GAME_MODE = 'COOP'
        elif file in file_sp_exit or file in file_sp_entry:
            GAME_MODE = 'SP'
        elif file in file_sp_door_frame:
            door_frames.append(item)
        inst_files.add(item['file'])

    LOGGER.info("Game Mode: " + GAME_MODE)
    LOGGER.info("Is Preview: " + str(IS_PREVIEW))

    if GAME_MODE == 'ERR':
        raise Exception(
            'Unknown game mode - Map missing exit room!'
        )
    if IS_PREVIEW == 'ERR':
        raise Exception(
            "Can't determine if preview is enabled "
            '- Map likely missing entry room!'
        )

    # Now check the door frames, to allow distinguishing between
    # the entry and exit frames.
    for door_frame in door_frames:
        origin = Vec.from_str(door_frame['origin'])
        if origin.x == entry_origin.x and origin.y == entry_origin.y:
            door_frame.fixup['door_type'] = 'entry'
        elif origin.x == exit_origin.x and origin.y == exit_origin.y:
            door_frame.fixup['door_type'] = 'exit'

    # Return the set of all instances in the map.
    return inst_files


def calc_rand_seed():
    """Use the ambient light entities to create a map seed.

     This ensures textures remain the same when the map is recompiled.
    """
    amb_light = instanceLocs.resolve('<ITEM_POINT_LIGHT>')
    lst = [
        inst['targetname'] or '-'  # If no targ
        for inst in
        VMF.by_class['func_instance']
        if inst['file'].casefold() in amb_light
        ]
    if len(lst) == 0:
        # Very small maps won't have any ambient light entities at all.
        return 'SEED'
    else:
        return '|'.join(lst)


def make_bottomless_pit(solids, max_height):
    """Transform all the goo pits into bottomless pits."""
    tex_sky = settings['pit']['tex_sky']
    teleport = settings['pit']['should_tele']

    tele_ref = settings['pit']['tele_ref']
    tele_dest = settings['pit']['tele_dest']

    tele_off_x = settings['pit']['off_x']+64
    tele_off_y = settings['pit']['off_y']+64

    # Controlled by the style, not skybox!
    blend_light = get_opt('pit_blend_light')

    for solid, wat_face in solids:
        wat_face.mat = tex_sky
        for vec in wat_face.planes:
            vec.z = float(Decimal(vec.z) - Decimal('95.5'))
            # subtract 95.5 from z axis to make it 0.5 units thick
            # we do the calc with Decimal to ensure precision
    pit_height = settings['pit']['height']

    if settings['pit']['skybox'] != '':
        # Add in the actual skybox edges and triggers
        VMF.create_ent(
            classname='func_instance',
            file=settings['pit']['skybox'],
            targetname='skybox',
            angles='0 0 0',
            origin='{!s} {!s} 0'.format(
                tele_off_x - 64,
                tele_off_y - 64,
            ),
        )

    if settings['pit']['skybox_ceil'] != '':
        # We dynamically add the ceiling so it resizes to match the map,
        # and lighting won't be too far away.
        VMF.create_ent(
            classname='func_instance',
            file=settings['pit']['skybox_ceil'],
            targetname='skybox',
            angles='0 0 0',
            origin='{!s} {!s} {!s}'.format(
                tele_off_x - 64,
                tele_off_y - 64,
                max_height,
            ),
        )

    if settings['pit']['targ'] != '':
        # Add in the actual skybox edges and triggers
        VMF.create_ent(
            classname='func_instance',
            file=settings['pit']['targ'],
            targetname='skybox',
            angles='0 0 0',
            origin='0 0 0',
        )

    # To figure out what positions need edge pieces, we use a dict
    # indexed by XY tuples. The four Nones match the NSEW directions.
    # For each trigger, we loop through the grid points it's in. We
    # set all the center parts to None, but set the 4 neighbouring
    # blocks if they aren't None.
    # If a value = None, it is occupied by goo.
    edges = defaultdict(lambda: [None, None, None, None])
    dirs = [
        # x, y, offsets
        (0, 128),   # North
        (0, -128),  # South
        (128, 0),   # East
        (-128, 0)   # West
    ]
    if teleport:
        # transform the skybox physics triggers into teleports to move cubes
            # into the skybox zone
        for trig in VMF.by_class['trigger_multiple']:
            if trig['wait'] != '0.1':
                continue

            bbox_min, bbox_max = trig.get_bbox()
            origin = (bbox_min + bbox_max) / 2  # type: Vec
            # We only modify triggers which are below the given z-index
            if origin.z >= pit_height:
                continue

            trig['classname'] = 'trigger_teleport'
            trig['spawnflags'] = '4106'  # Physics and npcs
            trig['landmark'] = tele_ref
            trig['target'] = tele_dest
            trig.outputs.clear()
            for x, y in utils.iter_grid(
                min_x=int(bbox_min.x),
                max_x=int(bbox_max.x),
                min_y=int(bbox_min.y),
                max_y=int(bbox_max.y),
                stride=128,
            ):
                # Remove the pillar from the center of the item
                edges[x, y] = None
                for i, (xoff, yoff) in enumerate(dirs):
                    side = edges[x + xoff, y + yoff]
                    if side is not None:
                        side[i] = origin.z - 13

                if blend_light:
                    # Generate dim lights at the skybox location,
                    # to blend the lighting together.
                    VMF.create_ent(
                        classname='light',
                        origin='{} {} {}'.format(
                            x + 64,
                            y + 64,
                            origin.z + 3,
                        ),
                        _light=blend_light,
                        _fifty_percent_distance='256',
                        _zero_percent_distance='512',
                    )
                    VMF.create_ent(
                        classname='light',
                        origin='{} {} {}'.format(
                            x + tele_off_x,
                            y + tele_off_y,
                            origin.z + 3,
                        ),
                        _light=blend_light,
                        _fifty_percent_distance='256',
                        _zero_percent_distance='512',
                    )

            # The triggers are 26 high, make them 10 units thick to
            # make it harder to see the teleport
            for side in trig.sides():
                for plane in side.planes:
                    if plane.z > origin.z:
                        plane.z -= 16

    instances = settings['pit']['inst']

    side_types = {
        utils.CONN_TYPES.side: instances['side'],
        utils.CONN_TYPES.corner: instances['corner'],
        utils.CONN_TYPES.straight: instances['double'],
        utils.CONN_TYPES.triple: instances['triple'],
        utils.CONN_TYPES.all: instances['pillar'],
        utils.CONN_TYPES.none: [''],  # Never add instance if no walls
    }

    for (x, y), mask in edges.items():
        if mask is None:
            continue  # This is goo

        random.seed(str(x) + str(y) + 'sides')

        inst_type, angle = utils.CONN_LOOKUP[
            tuple((val is not None) for val in mask)
        ]

        file = random.choice(side_types[inst_type])

        if file != '':
            VMF.create_ent(
                classname='func_instance',
                file=file,
                targetname='goo_side',
                origin='{!s} {!s} {!s}'.format(
                    x+tele_off_x,
                    y+tele_off_y,
                    max(
                        x
                        for x in mask
                        if x is not None
                    ),
                ),
                angles=angle,
            ).make_unique()

        random.seed(str(x) + str(y) + '-support')
        file = random.choice(instances['support'])

        if file != '':
            VMF.create_ent(
                classname='func_instance',
                file=file,
                targetname='goo_support',
                angles='0 ' + str(random.randrange(0, 360,90)) + ' 0',
                origin='{!s} {!s} {!s}'.format(
                    x+tele_off_x,
                    y+tele_off_y,
                    pit_height,
                ),
            ).make_unique()


def add_goo_mist(sides):
    """Add water_mist* particle systems to goo.

    This uses larger particles when needed to save ents.
    """
    needs_mist = set(sides)  # Locations that still need mist
    sides = sorted(sides)
    fit_goo_mist(
        sides, needs_mist,
        grid_x=1024,
        grid_y=512,
        particle='water_mist_1024_512',
        angles='0 0 0',
    )

    fit_goo_mist(
        sides, needs_mist,
        grid_x=512,
        grid_y=1024,
        particle='water_mist_1024_512',
        angles='0 90 0',
    )

    fit_goo_mist(
        sides, needs_mist,
        grid_x=512,
        grid_y=512,
        particle='water_mist_512',
    )

    fit_goo_mist(
        sides, needs_mist,
        grid_x=256,
        grid_y=256,
        particle='water_mist_256',
    )

    # There isn't a 128 particle so use 256 centered
    fit_goo_mist(
        sides, needs_mist,
        grid_x=128,
        grid_y=128,
        particle='water_mist_256',
    )


def fit_goo_mist(
        sides,
        needs_mist,
        grid_x,
        grid_y,
        particle,
        angles='0 0 0',
        ):
    """Try to add particles of the given size.

    needs_mist is a set of all added sides, so we don't double-up on a space.
    """
    if grid_y is None:
        grid_y = grid_x
    for pos in sides:
        if pos not in needs_mist:
            continue  # We filled this space already
        for x, y in utils.iter_grid(grid_x, grid_y, stride=128):
            if (pos.x+x, pos.y+y, pos.z) not in needs_mist:
                break  # Doesn't match
        else:
            VMF.create_ent(
                classname='info_particle_system',
                targetname='@goo_mist',
                start_active='1',
                effect_name=particle,
                origin='{x!s} {y!s} {z!s}'.format(
                    x=pos.x + (grid_x/2 - 64),
                    y=pos.y + (grid_y/2 - 64),
                    z=pos.z + 48,
                ),
                angles=angles,
            )
            for (x, y) in utils.iter_grid(grid_x, grid_y, stride=128):
                needs_mist.remove((pos.x+x, pos.y+y, pos.z))


def change_goo_sides():
    """Replace the textures on the sides of goo with specific ones.

    """
    if settings['textures']['special.goo_wall'] == ['']:
        return
    LOGGER.info("Changing goo sides...")
    face_dict = {}
    for solid in VMF.iter_wbrushes(world=True, detail=False):
        for face in solid:
            if face.mat.casefold() != 'tools/toolsnodraw':
                # Don't record the goo textured brushes
                x, y, z = face.get_origin()
                face_dict[x, y, z] = face

    dirs = [
        # x, y, z
        (0, 64, 0),  # North
        (0, -64, 0),  # South
        (64, 0, 0),  # East
        (-64, 0, 0),  # West
        (0, 0, -64),  # Down
    ]
    for trig in VMF.by_class['trigger_multiple']:
        if trig['wait'] != '0.1':
            continue
        bbox_min, bbox_max = trig.get_bbox()
        z = int(bbox_min.z + 64)
        for x in range(int(bbox_min.x)+64, int(bbox_max.x), 128):
            for y in range(int(bbox_min.y)+64, int(bbox_max.y), 128):
                for xoff, yoff, zoff in dirs:
                    try:
                        face = face_dict[x+xoff, y+yoff, z+zoff]
                    except KeyError:
                        continue

                    if (
                            face.mat.casefold() in BLACK_PAN or
                            face.mat.casefold() == 'tools/toolsnodraw'
                            ):
                        face.mat = get_tex('special.goo_wall')
    LOGGER.info("Done!")


def collapse_goo_trig():
    """Collapse the goo triggers to only use 2 entities for all pits."""
    LOGGER.info('Collapsing goo triggers...')

    hurt_trig = None
    cube_trig = None
    for trig in VMF.by_class['trigger_multiple']:
        if trig['wait'] == '0.1' and trig['targetname', ''] == '':
            if cube_trig is None:
                cube_trig = trig
            else:
                cube_trig.solids.extend(trig.solids)
                trig.remove()

    for trig in VMF.by_class['trigger_hurt']:
        if trig['targetname', ''] == '':
            if hurt_trig is None:
                hurt_trig = trig
            else:
                hurt_trig.solids.extend(trig.solids)
                trig.remove()

    if hurt_trig is not None:
        hurt_trig['damage'] = '99999'
        hurt_trig.outputs.append(
            VLib.Output(
                'OnHurtPlayer',
                '@goo_fade',
                'Fade',
            ),
        )

    LOGGER.info('Done!')


def remove_static_ind_toggles():
    """Remove indicator_toggle instances that don't have assigned overlays.

    If a style has static overlays, this will make antlines basically free.
    """
    LOGGER.info('Removing static indicator toggles...')
    toggle_file = instanceLocs.resolve('<ITEM_INDICATOR_TOGGLE>')
    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in toggle_file:
            continue

        overlay = inst.fixup['$indicator_name', '']
        if overlay == '' or len(VMF.by_target[overlay]) == 0:
            inst.remove()
    LOGGER.info('Done!')


def remove_barrier_ents():
    """If glass_clip or grating_clip is defined, we should remove the glass instances.

    They're not used since we added their contents into the map directly.
    """
    if not get_opt('grating_clip') or not get_opt('glass_clip'):
        return  # They're being used.

    barrier_file = instanceLocs.resolve('[glass_128]')

    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() in barrier_file:
            inst.remove()


def fix_squarebeams(face, rotate, reset_offset: bool, scale: float):
    '''Fix a squarebeams brush for use in other styles.

    If rotate is True, rotate the texture 90 degrees.
    offset is the offset for the texture.
    '''
    if rotate:
        # To rotate, swap the two values
        face.uaxis, face.vaxis = face.vaxis, face.uaxis

    # We want to modify the value with an offset
    if face.uaxis.offset != 0:
        targ = face.uaxis
    else:
        targ = face.vaxis

    if reset_offset:
        targ.offset = 0
    targ.scale = scale


def change_brush():
    """Alter all world/detail brush textures to use the configured ones."""
    LOGGER.info("Editing Brushes...")
    glass_clip_mat = get_opt('glass_clip')
    glass_scale = utils.conv_float(get_opt('glass_scale'), 0.15)
    goo_scale = utils.conv_float(get_opt('goo_scale'), 1)

    # Goo mist must be enabled by both the style and the user.
    make_goo_mist = get_bool_opt('goo_mist') and utils.conv_bool(
        settings['style_vars'].get('AllowGooMist', '1')
    )
    mist_solids = set()

    if utils.conv_bool(get_opt('remove_pedestal_plat')):
        # Remove the pedestal platforms
        for ent in VMF.by_class['func_detail']:
            for side in ent.sides():
                if side.mat.casefold() == 'plastic/plasticwall004a':
                    VMF.remove_ent(ent)
                    break  # Skip to next entity

    make_bottomless = settings['pit'] is not None
    LOGGER.info('Make Bottomless Pit: {}', make_bottomless)
    if make_bottomless:
        pit_solids = []
        pit_height = settings['pit']['height']
        pit_goo_tex = settings['pit']['tex_goo']

    highest_brush = 0

    for solid in VMF.iter_wbrushes(world=True, detail=True):
        is_glass = False
        for face in solid:
            highest_brush = max(
                highest_brush,
                face.planes[0].z,
                face.planes[1].z,
                face.planes[2].z,
            )
            if face.mat.casefold() in GOO_TEX:
                # Force this voice attribute on, since conditions can't
                # detect goo pits / bottomless pits
                settings['has_attr']['goo'] = True
                if make_bottomless:
                    if face.planes[2].z < pit_height:
                        settings['has_attr']['bottomless_pit'] = True
                        pit_solids.append((solid, face))
                    else:
                        face.mat = pit_goo_tex
                        if make_goo_mist:
                            mist_solids.add(
                                solid.get_origin().as_tuple()
                            )
                elif make_goo_mist:
                    mist_solids.add(
                        solid.get_origin().as_tuple()
                    )
                # Apply goo scaling
                face.scale = goo_scale
            if face.mat.casefold() == "glass/glasswindow007a_less_shiny":
                # Apply the glass scaling option
                face.scale = glass_scale
                settings['has_attr']['glass'] = True
                is_glass = True
        if is_glass and glass_clip_mat:
            glass_clip = make_barrier_solid(solid.get_origin(), glass_clip_mat)
            VMF.add_brush(glass_clip.solid)

    if get_opt('glass_pack') and settings['has_attr']['glass']:
        TO_PACK.add(get_opt('glass_pack').casefold())

    if make_bottomless:
        LOGGER.info('Creating Bottomless Pits...')
        make_bottomless_pit(pit_solids, highest_brush)
        LOGGER.info('Done!')

    if make_goo_mist:
        LOGGER.info('Adding Goo Mist...')
        add_goo_mist(mist_solids)
        LOGGER.info('Done!')

    if can_clump():
        clump_walls()
    else:
        random_walls()


def can_clump():
    """Check the clump algorithm has all its arguments."""
    if not get_bool_opt("clump_wall_tex"):
        return False
    if not get_opt("clump_size").isnumeric():
        return False
    if not get_opt("clump_width").isnumeric():
        return False
    return get_opt("clump_number").isnumeric()


def make_barrier_solid(origin, material):
    """Make a brush covering a given glass/grating location.
    """
    # Find the center point of this location to find where the brush
    # will be.
    loc = Vec(
        origin.x // 128 * 128 + 64,
        origin.y // 128 * 128 + 64,
        origin.z // 128 * 128 + 64,
        )
    normal = (origin - loc).norm()  # This points outward.
    # This sets the two side axes to 1, and the normal axis to 0.
    side_offset = 1 - abs(normal)  # type: Vec
    side_offset *= 64

    return VMF.make_prism(
        # Adding the side_offset moves the other directions out 64
        # to make it 128 large in total.
        # We want the brush to be 4 units thick.
        (loc + normal * 60 + side_offset),
        (loc + normal * 64 - side_offset),
        mat=material,
    )



def face_seed(face):
    """Create a seed unique to this brush face.

    This is the same regardless of side direction.
    """
    origin = face.get_origin()
    for axis in "xyz":
        if origin[axis] % 128 < 2:
            origin[axis] = (origin[axis] // 64) * 64
        else:
            origin[axis] = (origin[axis] // 128) * 128 + 64
    return origin.join(' ')


def get_grid_sizes(face: VLib.Side):
    """Determine the grid sizes that fits on this brush."""
    bbox_min, bbox_max = face.get_bbox()
    dim = bbox_max - bbox_min

    if dim.x == 0:
        u, v = dim.y, dim.z
    elif dim.y == 0:
        u, v = dim.x, dim.z
    elif dim.z == 0:
        u, v = dim.x, dim.y
    else:
        raise Exception(str(dim) + ' not on grid!')

    if u % 128 == 0 and v % 128 == 0:  # regular square
        return "0.25", "0.5", "0.5", "1", "1",
    if u % 64 == 0 and v % 64 == 0:  # 2x2 grid
        return "0.5",
    if u % 32 == 0 and v % 32 == 0:  # 4x4 grid
        return "0.25",


def random_walls():
    """The original wall style, with completely randomised walls."""
    rotate_edge = get_bool_opt('rotate_edge')
    texture_lock = get_bool_opt('tile_texture_lock', True)
    edge_off = get_bool_opt('reset_edge_off', False)
    edge_scale = utils.conv_float(get_opt('edge_scale'), 0.15)

    for solid in VMF.iter_wbrushes(world=True, detail=True):
        for face in solid:
            if face in IGNORED_FACES:
                continue

            if face.mat.casefold() == 'anim_wp/framework/squarebeams':
                fix_squarebeams(face, rotate_edge, edge_off, edge_scale)

            alter_mat(face, face_seed(face), texture_lock)


Clump = namedtuple('Clump', [
    'min_pos',
    'max_pos',
    'tex',
])


def clump_walls():
    """A wall style where textures are used in small groups near each other.

    This replicates the Old Aperture maps, which are cobbled together
    from many different materials.
    """
    # For this, we ignore all of Valve's wall textures.
    # We then start making clumps.
    # These are 2x2x4 maximum rectangular areas (configurable), which all get
    #  the same texture. We don't overwrite previously-set ones though.
    # After that, we fill in any unset textures with the white/black_gap ones.
    # This makes it look like those areas were patched up.

    texture_lock = get_bool_opt('tile_texture_lock', True)
    rotate_edge = get_bool_opt('rotate_edge')
    edge_off = get_bool_opt('reset_edge_off', False)
    edge_scale = utils.conv_float(get_opt('edge_scale'), 0.15)

    # Possible locations for clumps - every face origin, not including
    # ignored faces or nodraw
    possible_locs = [
        face.get_origin()
        for face in
        VMF.iter_wfaces(world=True, detail=True)
        if face not in IGNORED_FACES
        if face.mat.casefold() in WHITE_PAN or face.mat.casefold() in BLACK_PAN
    ]

    clump_size = utils.conv_int(get_opt("clump_size"), 4)
    clump_wid = utils.conv_int(get_opt("clump_width"), 2)

    clump_numb = len(possible_locs) // (clump_size * clump_wid * clump_wid)
    clump_numb *= utils.conv_int(get_opt("clump_number"), 6)

    # Also clump ceilings or floors?
    clump_ceil = get_bool_opt('clump_ceil')
    clump_floor = get_bool_opt('clump_floor')

    LOGGER.info('Clumping: {} clumps', clump_numb)

    random.seed(MAP_SEED)

    clumps = []

    for _ in range(clump_numb):
        # Picking out of the map origins helps ensure at least 1 texture is
        # modded by a clump
        pos = random.choice(possible_locs) // 128 * 128  # type: Vec

        pos_min = Vec()
        pos_max = Vec()
        # Clumps are long strips mainly extended in one direction
        # In the other directions extend by 'width'. It can point any axis.
        direction = random.choice('xyz')
        for axis in 'xyz':
            if axis == direction:
                dist = clump_size
            else:
                dist = clump_wid
            pos_min[axis] = pos[axis] - random.randint(0, dist) * 128
            pos_max[axis] = pos[axis] + random.randint(0, dist) * 128
        cur_state = random.getstate()
        random.seed('CLUMP_TEX_' + pos_min.join() + '_' + pos_max.join(' '))
        clumps.append(Clump(
            pos_min,
            pos_max,
            # For each clump, every tile gets the same texture!
            {
                (color + '.' + size): get_tex(color + '.' + size)
                for color in ('white', 'black')
                for size in ('wall', 'floor', 'ceiling', '2x2', '4x4')
            }
        ))
        random.setstate(cur_state)

    # Now modify each texture!
    for face in VMF.iter_wfaces(world=True, detail=True):
        if face in IGNORED_FACES:
            continue

        mat = face.mat.casefold()

        if mat == 'anim_wp/framework/squarebeams':
            # Handle squarebeam transformations
            alter_mat(face, face_seed(face), texture_lock)
            fix_squarebeams(face, rotate_edge, edge_off, edge_scale)
            continue

        if mat not in WHITE_PAN and mat not in BLACK_PAN:
            # Don't clump non-wall textures
            alter_mat(face, face_seed(face), texture_lock)
            continue

        orient = get_face_orient(face)

        if (
                (orient is ORIENT.floor and not clump_floor) or
                (orient is ORIENT.ceiling and not clump_ceil)):
            # Don't clump if configured not to for this orientation
            alter_mat(face, face_seed(face), texture_lock)
            continue

        # Clump the texture!
        origin = face.get_origin()
        for clump in clumps:
            if clump.min_pos <= origin <= clump.max_pos:
                face.mat = clump.tex[get_tile_type(mat, orient)]
                break
        else:
            # Not in a clump!
            # Allow using special textures for these, to fill in gaps.
            orig_mat = mat
            if mat in WHITE_PAN:
                face.mat = get_tex("special.white_gap")
                if not face.mat:
                    face.mat = orig_mat
                    alter_mat(face, texture_lock=texture_lock)
            elif mat in BLACK_PAN:
                face.mat = get_tex("special.black_gap")
                if not face.mat:
                    face.mat = orig_mat
                    alter_mat(face, texture_lock=texture_lock)
            else:
                alter_mat(face, texture_lock=texture_lock)


def get_face_orient(face):
    """Determine the orientation of an on-grid face."""
    norm = face.normal()
    # Even if not axis-aligned, make mostly-flat surfaces
    # floor/ceiling (+-40 degrees)
    # sin(40) = ~0.707
    if norm.z < -0.8:
        return ORIENT.floor
    if norm.z > 0.8:
        return ORIENT.ceiling
    return ORIENT.wall


def broken_antline_iter(dist, max_step, chance):
    """Iterator used in set_antline_mat().

    This produces min,max pairs which fill the space from 0-dist.
    Their width is random, from 1-max_step.
    Neighbouring sections will be merged when they have the same type.
    """
    last_val = next_val = 0
    last_type = random.randrange(100) < chance

    while True:
        is_broken = (random.randrange(100) < chance)

        next_val += random.randint(1, max_step)

        if next_val >= dist:
            # We hit the end - make sure we don't overstep.
            yield last_val, dist, is_broken
            return

        if is_broken == last_type:
            # Merge the two sections - don't make more overlays
            # than needed..
            continue

        yield last_val, next_val, last_type
        last_type = is_broken
        last_val = next_val


def set_antline_mat(
        over,
        mats: list,
        floor_mats: list=(),
        broken_chance=0,
        broken_dist=0,
        broken: list=(),
        broken_floor: list=(),
        ):
    """Retexture an antline, with various options encoded into the material.

    floor_mat, if set is an alternate material to use for floors.
    The material is split into 3 parts, separated by '|':
    - Scale: the u-axis width of the material, used for clean antlines.
    - Material: the material
    - Static: if 'static', the antline will lose the targetname. This
      makes it non-dynamic, and removes the info_overlay_accessor
      entity from the compiled map.
    If only 2 parts are given, the overlay is assumed to be dynamic.
    If one part is given, the scale is assumed to be 0.25.

    For broken antlines,  'broken_chance' is the percentage chance for
    brokenness. broken_dist is the largest run of lights that can be broken.
    broken and broken_floor are the textures used for the broken lights.
    """
    # Choose a random one
    random.seed(over['origin'])

    if broken_chance and any(broken):  # We can have `broken` antlines.
        bbox_min, bbox_max = VLib.overlay_bounds(over)
        # Number of 'circles' and the length-wise axis
        length = max(bbox_max - bbox_min)
        long_axis = Vec(0, 1, 0).rotate_by_str(over['angles']).axis()

        # It's a corner or short antline - replace instead of adding more
        if length // 16 < broken_dist:
            if random.randrange(100) < broken_chance:
                mats = broken
                floor_mats = broken_floor
        else:
            min_origin = Vec.from_str(over['origin'])
            min_origin[long_axis] -= length / 2

            broken_iter = broken_antline_iter(
                length // 16,
                broken_dist,
                broken_chance,
            )
            for sect_min, sect_max, is_broken in broken_iter:

                if is_broken:
                    tex, floor_tex = broken, broken_floor
                else:
                    tex, floor_tex = mats, floor_mats

                sect_length = sect_max - sect_min

                # Make a section - base it off the original, and shrink it
                new_over = over.copy()
                VMF.add_ent(new_over)
                # Make sure we don't restyle this twice.
                IGNORED_OVERLAYS.add(new_over)

                # Repeats lengthways
                new_over['startV'] = str(sect_length)
                sect_center = (sect_min + sect_max) / 2

                sect_origin = min_origin.copy()
                sect_origin[long_axis] += sect_center * 16
                new_over['basisorigin'] = new_over['origin'] = sect_origin.join(' ')

                # Set the 4 corner locations to determine the overlay size.
                # They're in local space - x is -8/+8, y=length, z=0
                # Match the sign of the current value
                for axis in '0123':
                    pos = Vec.from_str(new_over['uv' + axis])
                    if pos.y < 0:
                        pos.y = -8 * sect_length
                    else:
                        pos.y = 8 * sect_length
                    new_over['uv' + axis] = pos.join(' ')

                # Recurse to allow having values in the material value
                set_antline_mat(new_over, tex, floor_tex, broken_chance=0)
            # Remove the original overlay
            VMF.remove_ent(over)

    if any(floor_mats):  # Ensure there's actually a value
        # For P1 style, check to see if the antline is on the floor or
        # walls.
        if Vec.from_str(over['basisNormal']).z != 0:
            mats = floor_mats

    mat = random.choice(mats).split('|')
    opts = []

    if len(mat) == 2:
        # rescale antlines if needed
        over['endu'], over['material'] = mat
    elif len(mat) > 2:
        over['endu'], over['material'], *opts = mat
    else:
        # Unpack to ensure it only has 1 section
        over['material'], = mat
        over['endu'] = '0.25'

    if 'static' in opts:
        # If specified, remove the targetname so the overlay
        # becomes static.
        del over['targetname']


def change_overlays():
    """Alter the overlays."""
    LOGGER.info("Editing Overlays...")

    # A frame instance to add around all the 32x32 signs
    sign_inst = get_opt('signInst')
    # Resize the signs to this size. 4 vertexes are saved relative
    # to the origin, so we must divide by 2.
    sign_size = utils.conv_int(get_opt('signSize'), 32) / 2
    if sign_inst == "NONE":
        sign_inst = None

    # A packlist associated with the sign_inst.
    sign_inst_pack = get_opt('signPack')

    # Grab all the textures we're using...

    tex_dict = settings['textures']
    ant_str = tex_dict['overlay.antline']
    ant_str_floor = tex_dict['overlay.antlinefloor']
    ant_corn = tex_dict['overlay.antlinecorner']
    ant_corn_floor = tex_dict['overlay.antlinecornerfloor']

    broken_ant_str = tex_dict['overlay.antlinebroken']
    broken_ant_corn = tex_dict['overlay.antlinebrokencorner']
    broken_ant_str_floor = tex_dict['overlay.antlinebrokenfloor']
    broken_ant_corn_floor = tex_dict['overlay.antlinebrokenfloorcorner']

    broken_chance = utils.conv_float(get_opt('broken_antline_chance'))
    broken_dist = utils.conv_float(get_opt('broken_antline_distance'))

    for over in VMF.by_class['info_overlay']:
        if over in IGNORED_OVERLAYS:
            continue

        if (over['targetname'] == 'exitdoor_stickman' or
                over['targetname'] == 'exitdoor_arrow'):
            if get_bool_opt("remove_exit_signs"):
                # Some styles have instance-based ones, remove the
                # originals if needed to ensure it looks nice.
                VMF.remove_ent(over)
                continue  # Break out, to make sure the instance isn't added
            else:
                # blank the targetname, so we don't get the
                # useless info_overlay_accessors for these signs.
                del over['targetname']

        case_mat = over['material'].casefold()

        if case_mat in TEX_VALVE:
            sign_type = TEX_VALVE[case_mat]
            if sign_inst is not None:
                new_inst = VMF.create_ent(
                    classname='func_instance',
                    origin=over['origin'],
                    angles=over['angles', '0 0 0'],
                    file=sign_inst,
                )
                if sign_inst_pack:
                    TO_PACK.add(sign_inst_pack.casefold())
                new_inst.fixup['mat'] = sign_type.replace('overlay.', '')

            over['material'] = get_tex(sign_type)
            if sign_size != 16:
                # Resize the signage overlays
                # These are the 4 vertex locations
                # Each axis is set to -16, 16 or 0 by default
                for prop in ('uv0', 'uv1', 'uv2', 'uv3'):
                    val = Vec.from_str(over[prop])
                    val /= 16
                    val *= sign_size
                    over[prop] = val.join(' ')
        if case_mat == ANTLINES['straight']:
            set_antline_mat(
                over,
                ant_str,
                ant_str_floor,
                broken_chance,
                broken_dist,
                broken_ant_str,
                broken_ant_str_floor,
            )
        elif case_mat == ANTLINES['corner']:
            set_antline_mat(
                over,
                ant_corn,
                ant_corn_floor,
                broken_chance,
                broken_dist,
                broken_ant_corn,
                broken_ant_corn_floor,
            )


def change_trig():
    """Check the triggers and fizzlers."""
    LOGGER.info("Editing Triggers...")

    for trig in VMF.by_class['trigger_portal_cleanser']:
        for side in trig.sides():
            alter_mat(side)
        target = trig['targetname', '']

        # Change this so the base instance can directly modify the brush.
        if target.endswith('_brush'):
            trig['targetname'] = target[:-6] + '-br_fizz'

        # Apply some config options - scanline and Fast Reflections
        trig['useScanline'] = settings["fizzler"]["scanline"]
        trig['drawInFastReflection'] = get_opt("force_fizz_reflect")

    for trig in VMF.by_class['trigger_hurt']:
        target = trig['targetname', '']
        # Change this so the base instance can directly modify the brush.
        if target.endswith('_brush'):
            trig['targetname'] = target[:-6] + '-br_hurt'


def add_extra_ents(mode):
    """Add the various extra instances to the map."""
    LOGGER.info("Adding Music...")

    if mode == "COOP":
        loc = get_opt('music_location_coop')
    else:
        loc = get_opt('music_location_sp')

    # These values are exported by the BEE2 app, indicating the
    # options on the music item.
    sound = get_opt('music_soundscript')
    inst = get_opt('music_instance')

    if sound != '':
        VMF.create_ent(
            classname='ambient_generic',
            spawnflags='17',  # Looping, Infinite Range, Starts Silent
            targetname='@music',
            origin=loc,
            message=sound,
            health='10',  # Volume
            )

    if inst != '':
        VMF.create_ent(
            classname='func_instance',
            targetname='music',
            angles='0 0 0',
            origin=loc,
            file=inst,
            fixup_style='0',
            )

    # Add the global_pti_ents instance automatically, with disable_pti_audio
    # set.

    pti_file = get_opt("global_pti_ents")
    pti_loc = get_opt("global_pti_ents_loc")
    if pti_file != '':
        LOGGER.info('Adding Global PTI Ents')
        global_pti_ents = VMF.create_ent(
            classname='func_instance',
            targetname='global_pti_ents',
            angles='0 0 0',
            origin=pti_loc,
            file=pti_file,
            fixup_style='0',
            )

        has_cave = utils.conv_bool(
            settings['style_vars'].get('multiversecave', '1')
        )
        global_pti_ents.fixup[
            'disable_pti_audio'
            ] = utils.bool_as_int(not has_cave)

    # Add the model changer instance.
    # We don't change the player model in Coop, or if Bendy is selected.

    model_changer_loc = get_opt('model_changer_loc')
    chosen_model = BEE2_config.get_val('General', 'player_model', 'PETI')
    if mode == 'SP' and chosen_model != 'PETI' and model_changer_loc != '':
        VMF.create_ent(
            classname='func_instance',
            targetname='model_changer',
            angles='0 0 0',
            origin=model_changer_loc,
            file='instances/BEE2/logic/model_changer/' + chosen_model + '.vmf',
            fixup_style='0',
        )


def change_func_brush():
    """Edit func_brushes."""
    LOGGER.info("Editing Brush Entities...")
    grating_clip_mat = get_opt("grating_clip")
    grating_scale = utils.conv_float(get_opt("grating_scale"), 0.15)

    # All the textures used for faith plate bullseyes
    bullseye_white = set(itertools.chain.from_iterable(
        settings['textures']['special.bullseye_white_' + orient]
        for orient in ('floor', 'wall', 'ceiling')
    ))
    bullseye_black = set(itertools.chain.from_iterable(
        settings['textures']['special.bullseye_black_' + orient]
        for orient in ('floor', 'wall', 'ceiling')
    ))

    if get_tex('special.edge_special') == '':
        edge_tex = 'special.edge'
        rotate_edge = get_bool_opt('rotate_edge', False)
        edge_off = get_bool_opt('reset_edge_off')
        edge_scale = utils.conv_float(get_opt('edge_scale'), 0.15)
    else:
        edge_tex = 'special.edge_special'
        rotate_edge = get_bool_opt('rotate_edge_special', False)
        edge_off = get_bool_opt('reset_edge_off_special')
        edge_scale = utils.conv_float(get_opt('edge_scale_special'), 0.15)

    # Clips are shared every 512 grid spaces
    grate_clips = {}
    # Merge nearby grating brushes
    grating_brush = {}

    for brush in (
            VMF.by_class['func_brush'] |
            VMF.by_class['func_door_rotating']
            ):
        brush['drawInFastReflection'] = get_opt("force_brush_reflect")
        parent = brush['parentname', '']
        # Used when creating static panels
        brush_type = ""
        is_bullseye = False

        target = brush['targetname', '']
        # Fizzlers need their custom outputs.
        # Change this so the base instance can directly modify the brush.
        if target.endswith('_brush'):
            brush['targetname'] = target[:-6] + '-br_brush'

        # Func_brush/func_rotating (for angled panels and flip panels)
        # often use different textures, so let the style do that.

        is_grating = False
        delete_brush = False
        for side in brush.sides():
            # If it's set to a bullseye texture, it's in the ignored_faces
            # set!
            if side.mat in bullseye_white:
                brush_type = 'white'
                is_bullseye = True
            elif side.mat in bullseye_black:
                brush_type = 'black'
                is_bullseye = True

            if side in IGNORED_FACES:
                continue

            if side.mat.casefold() == "anim_wp/framework/squarebeams":
                side.mat = get_tex(edge_tex)
                fix_squarebeams(
                    side,
                    rotate_edge,
                    edge_off,
                    edge_scale,
                )
                continue

            if side.mat.casefold() in WHITE_PAN:
                brush_type = "white"
                set_special_mat(side, 'white')

            elif side.mat.casefold() in BLACK_PAN:
                brush_type = "black"
                set_special_mat(side, 'black')
            else:
                if side.mat.casefold() == 'metal/metalgrate018':
                    is_grating = True
                    side.scale = grating_scale
                alter_mat(side)  # for gratings, laserfields and some others

            # The style blanked the material, so delete the brush
            if side.mat == '':
                delete_brush = True
                break

        if delete_brush:
            VMF.remove_ent(brush)
            continue

        if is_grating:
            # Set solidbsp to true on grating brushes. This makes the
            # correct footstep sounds play.
            brush['solidbsp'] = '1'
            settings['has_attr']['grating'] = True

            brush_loc = brush.get_origin()  # type: Vec
            brush_key = (brush_loc // 512 * 512).as_tuple()

            # Merge nearby grating brush entities
            if brush_key not in grating_brush:
                grating_brush[brush_key] = brush
            else:
                grating_brush[brush_key].solids += brush.solids
                VMF.remove_ent(brush)

        if is_grating and grating_clip_mat:
            grate_clip = make_barrier_solid(brush.get_origin(), grating_clip_mat)
            VMF.add_brush(grate_clip.solid)

            grate_phys_clip_solid = grate_clip.solid.copy()  # type: VLib.Solid
            for face in grate_phys_clip_solid.sides:
                face.mat = 'tools/toolstrigger'

            if brush_key not in grate_clips:
                grate_clips[brush_key] = clip_ent = VMF.create_ent(
                    classname='func_clip_vphysics',
                    origin=brush_loc.join(' '),
                    filtername=get_opt('grating_filter')
                )
            else:
                clip_ent = grate_clips[brush_key]
            clip_ent.solids.append(grate_phys_clip_solid)

        if "-model_arms" in parent:  # is this an angled panel?:
            # strip only the model_arms off the end
            targ = '-'.join(parent.split("-")[:-1])
            # Now find the associated instance
            for ins in (
                    VMF.by_class['func_instance'] &
                    VMF.by_target[targ]
                    ):
                if make_static_pan(ins, brush_type, is_bullseye):
                    # delete the brush, we don't want it if we made a
                    # static one
                    VMF.remove_ent(brush)
                else:
                    # Oherwise, rename the brush to -brush, so the panel
                    # can be sent inputs.
                    brush['targetname'] = brush['targetname'].replace(
                        '_panel_top',
                        '-brush',
                        )
                    # Add the attachment name to the parent, so it
                    # automatically sets the attachment point for us.
                    brush['parentname'] += ',panel_attach'

    if get_opt('grating_pack') and settings['has_attr']['grating']:
        TO_PACK.add(get_opt('grating_pack').casefold())


def alter_flip_panel():
    flip_panel_start = get_opt('flip_sound_start')
    flip_panel_stop = get_opt('flip_sound_stop')
    if (
            flip_panel_start != DEFAULTS['flip_sound_start'] or
            flip_panel_stop != DEFAULTS['flip_sound_stop']
            ):
        for flip_pan in VMF.by_class['func_door_rotating']:
            # Change flip panel sounds by editing the func_door_rotating
            flip_pan['noise1'] = flip_panel_start
            flip_pan['noise2'] = flip_panel_stop


def set_special_mat(face, side_type):
    """Set a face to a special texture.

    Those include checkers or portal-here tiles, used on flip
    and angled panels.
    side_type should be either 'white' or 'black'.
    """
    # We use a wall-specific texture, or the floor texture,
    # or fallback to regular textures
    rep_texture = 'special.' + side_type
    orient = get_face_orient(face)
    if orient is ORIENT.wall and get_tex(rep_texture + '_wall'):
        face.mat = get_tex(rep_texture + '_wall')
    elif get_tex(rep_texture):
        face.mat = get_tex(rep_texture)
    elif not alter_mat(face):
        face.mat = get_tex(side_type + '.' + str(orient))


def make_static_pan(ent, pan_type, is_bullseye=False):
    """Convert a regular panel into a static version.

    This is done to save entities and improve lighting."""
    if get_opt("staticPan") == "NONE":
        return False  # no conversion allowed!

    angle = "00"
    if ent.fixup['animation']:
        # the 5:7 is the number in "ramp_45_deg_open"
        angle = ent.fixup['animation'][5:7]
    if ent.fixup['start_deployed'] == "0":
        angle = "00"  # different instance flat with the wall
    if ent.fixup['connectioncount', '0'] != "0":
        return False
    # Handle glass panels
    if pan_type == 'glass':
        ent["file"] = get_opt("staticPan") + angle + '_glass.vmf'
        return True

    # Handle white/black panels:
    ent['file'] = get_opt("staticPan") + angle + '_surf.vmf'

    # We use a template for the surface, so it can use correct textures.
    if angle == '00':
        # Special case: flat panels use different templates
        world, detail, overlays = conditions.import_template(
            get_opt('static_pan_temp_flat'),
            origin=Vec.from_str(ent['origin']),
            angles=Vec.from_str(ent['angles']),
            targetname=ent['targetname'],
            force_type=conditions.TEMP_TYPES.detail,
        )
        # Some styles have 8-unit thick flat panels, others use 4-units.
        # Put the target halfway.
        faith_targ_pos = Vec(0, 0, -64 + 6).rotate_by_str(ent['angles'])
        faith_targ_pos += Vec.from_str(ent['origin'])
    else:
        # For normal surfaces, we need an  origin and angles
        #  rotated around the hinge point!
        temp_origin = Vec(-64, 0, -64).rotate_by_str(ent['angles'])
        temp_origin += Vec.from_str(ent['origin'])

        temp_angles = Vec.from_str(ent['angles'])

        # figure out the right axis to rotate for the face
        facing_dir = Vec(0, 1, 0).rotate_by_str(ent['angles'])
        # Rotating counterclockwise
        if facing_dir.z == 1:
            temp_angles.y = (temp_angles.y - int(angle)) % 360
        # Rotating clockwise
        elif facing_dir.z == -1:
            temp_angles.y = (temp_angles.y + int(angle)) % 360
        else:
            normal = Vec(0, 0, 1).rotate_by_str(ent['angles'])
            if normal.z == -1:
                # On ceiling
                temp_angles.x = (temp_angles.x + int(angle)) % 360
            else:
                # Floor or rotating upright on walls
                temp_angles.x = (temp_angles.x - int(angle)) % 360
        # The target should be centered on the rotated panel!
        faith_targ_pos = Vec(64, 0, 0)
        faith_targ_pos.localise(temp_origin, temp_angles)

        world, detail, overlays = conditions.import_template(
            get_opt('static_pan_temp_' + pan_type),
            temp_origin,
            temp_angles,
            force_type=conditions.TEMP_TYPES.detail,
        )
    conditions.retexture_template(
        world,
        detail,
        overlays,
        origin=Vec.from_str(ent['origin']),
        force_colour=(
            conditions.MAT_TYPES.white
            if pan_type == 'white' else
            conditions.MAT_TYPES.black
        ),
        use_bullseye=is_bullseye,
    )

    # Search for the info_targets of catapults aimed at the panel,
    # and adjust them so they're placed precicely on the surface.
    base_pos = Vec(0, 0, -64).rotate_by_str(ent['angles'])
    base_pos += Vec.from_str(ent['origin'])
    # Since it's a defaultdict, misses will give an empty list.
    for target in PANEL_FAITH_TARGETS[base_pos.as_tuple()]:
        target['origin'] = faith_targ_pos.join(' ')
        # Clear the parentname, since the brush is now gone!
        del target['parentname']

    return True


def change_ents():
    """Edit misc entities."""
    LOGGER.info("Editing Other Entities...")
    if get_bool_opt("remove_info_lighting"):
        # Styles with brush-based glass edges don't need the info_lighting,
        # delete it to save ents.
        for ent in VMF.by_class['info_lighting']:
            ent.remove()
    for auto in VMF.by_class['logic_auto']:
        # Remove all the logic_autos that set attachments, we can
        # replicate this in the instance
        for out in auto.outputs:
            if 'panel_top' in out.target:
                VMF.remove_ent(auto)


def fix_inst():
    for inst in VMF.by_class['func_instance']:
        # TODO: remake this in a condition
        if "ccflag_comball_base" in inst['file', '']:  # Rexaura Flux Fields
            # find the triggers that match this entity and mod them
            for trig in VMF.iter_ents(
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
                trig['spawnflags'] = "72"  # Physics Objects, Everything
                # generate the output that triggers the pellet logic.
                trig.add_out(VLib.Output(
                    "OnStartTouch",
                    inst['targetname'] + "-branch_toggle",
                    "FireUser1",
                    ))

            inst.outputs.clear()  # All the original ones are junk, delete them!

            for in_out in VMF.iter_ents_tags(
                    vals={
                        'classname': 'func_instance',
                        'origin': inst['origin'],
                        'angles': inst['angles'],
                        },
                    tags={
                        'file': 'ccflag_comball_out',
                        }
                    ):
                # Find the instance to use for output and add the
                # commands to trigger its logic
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


def fix_worldspawn():
    """Adjust some properties on WorldSpawn."""
    LOGGER.info("Editing WorldSpawn")
    if VMF.spawn['paintinmap'] != '1':
        # If PeTI thinks there should be paint, don't touch it
        # Otherwise set it based on the 'gel' voice attribute
        # If the game is Aperture Tag, it's always forced on
        VMF.spawn['paintinmap'] = utils.bool_as_int(
            settings['has_attr']['gel'] or
            get_opt('game_id') == utils.STEAM_IDS['APTAG']
        )
    VMF.spawn['skyname'] = get_tex("special.sky")


@conditions.make_result('Pack')
def packlist_cond(_, res):
    """Add the files in the given packlist to the map."""
    TO_PACK.add(res.value.casefold())

    return conditions.RES_EXHAUSTED


def make_packlist(map_path):
    """Write the list of files that VRAD should pack."""

    # Scan map materials for marked materials
    # This way world-brush materials can be packed.
    pack_triggers = settings['packtrigger']

    if pack_triggers:
        def face_iter():
            """Check all these locations for the target textures."""
            # We need the iterator to allow breaking out of the loop.
            for face in VMF.iter_wfaces():
                yield face.mat.casefold()
            for ent in (
                VMF.by_class['func_brush'] |
                VMF.by_class['func_door_rotating'] |
                VMF.by_class['trigger_portal_cleanser']
                    ):
                for side in ent.sides():
                    yield side.mat.casefold()

            for overlay in VMF.by_class['info_overlay']:
                # Check overlays too
                yield overlay['material', ''].casefold()

        for mat in face_iter():
            if mat in pack_triggers:
                TO_PACK.update(pack_triggers[mat])
                del pack_triggers[mat]
                if not pack_triggers:
                    break  # No more left

    if not TO_PACK:
        # Nothing to pack - wipe the packfile!
        open(map_path[:-4] + '.filelist.txt', 'w').close()

    LOGGER.info('Making Pack list...')

    with open('bee2/pack_list.cfg') as f:
        props = Property.parse(
            f,
            'bee2/pack_list.cfg'
        ).find_key('PackList', [])

    for pack_id in TO_PACK:
        PACK_FILES.update(
            prop.value
            for prop in
            props[pack_id, ()]
        )

    with open(map_path[:-4] + '.filelist.txt', 'w') as f:
        for file in sorted(PACK_FILES):
            f.write(file + '\n')
            LOGGER.info(file)

    LOGGER.info('Packlist written!')


def make_vrad_config():
    """Generate a config file for VRAD from our configs.

    This way VRAD doesn't need to parse through vbsp_config, or anything else.
    """
    LOGGER.info('Generating VRAD config...')
    conf = Property('Config', [
    ])
    conf['force_full'] = utils.bool_as_int(
        BEE2_config.get_bool('General', 'vrad_force_full')
    )
    conf['screenshot'] = BEE2_config.get_val(
        'Screenshot', 'loc', ''
    )
    conf['screenshot_type'] = BEE2_config.get_val(
        'Screenshot', 'type', 'PETI'
    ).upper()
    conf['clean_screenshots'] = utils.bool_as_int(
        BEE2_config.get_bool('Screenshot', 'del_old')
    )
    conf['is_preview'] = utils.bool_as_int(
        IS_PREVIEW
    )
    conf['game_id'] = get_opt('game_id')

    with open('bee2/vrad_config.cfg', 'w') as f:
        for line in conf.export():
            f.write(line)


def save(path):
    """Save the modified map back to the correct location.
    """
    LOGGER.info("Saving New Map...")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        VMF.export(dest_file=f, inc_version=True)
    LOGGER.info("Complete!")


def run_vbsp(vbsp_args, do_swap, path, new_path):
    """Execute the original VBSP, copying files around so it works correctly."""

    # We can't overwrite the original vmf, so we run VBSP from a separate
    # location.
    if do_swap:
        if os.path.isfile(path.replace(".vmf", ".log")):
            shutil.copy(
                path.replace(".vmf", ".log"),
                new_path.replace(".vmf", ".log"),
            )
    # Put quotes around args which contain spaces, and remove blank args.
    vbsp_args = [('"' + x + '"' if " " in x else x) for x in vbsp_args if x]

    if utils.MAC:
        os_suff = '_osx'
    elif utils.LINUX:
        os_suff = '_linux'
    else:
        os_suff = ''

    arg = (
        '"' +
        os.path.normpath(
            os.path.join(
                os.getcwd(),
                "vbsp" + os_suff + "_original"
                )
            ) +
        '" ' +
        " ".join(vbsp_args)
        )

    utils.con_log("Calling original VBSP...")
    utils.con_log(arg)
    code = subprocess.call(
        arg,
        stdout=None,
        stderr=subprocess.PIPE,
        shell=True,
    )
    if code == 0:
        utils.con_log("Done!")
    else:
        utils.con_log("VBSP failed! (" + str(code) + ")")
        sys.exit(code)
    if do_swap:  # copy over the real files so vvis/vrad can read them
        for ext in (".bsp", ".log", ".prt"):
            if os.path.isfile(new_path.replace(".vmf", ext)):
                shutil.copy(
                    new_path.replace(".vmf", ext),
                    path.replace(".vmf", ext),
                )


def main():
    """Main program code.

    """
    global MAP_SEED, IS_PREVIEW, GAME_MODE
    LOGGER.info("BEE{} VBSP hook initiallised.", utils.BEE_VERSION)

    args = " ".join(sys.argv)
    new_args = sys.argv[1:]
    old_args = sys.argv[1:]
    path = sys.argv[-1]  # The path is the last argument to vbsp

    if not old_args:
        # No arguments!
        LOGGER.info(
            'No arguments!\n'
            "The BEE2 VBSP takes all the regular VBSP's "
            'arguments, with some extra arguments:\n'
            '-dump_conditions: Print a list of all condition flags,\n'
            '  results, and metaconditions.\n'
            '-force_peti: Force enabling map conversion. \n'
            "-force_hammer: Don't convert the map at all.\n"
            '-entity_limit: A default VBSP command, this is inspected to'
            'determine if the map is PeTI or not.'
        )
        sys.exit()

    if old_args[0].casefold() == '-dump_conditions':
        # Print all the condition flags, results, and metaconditions
        conditions.dump_conditions()
        sys.exit()

    if not path.endswith(".vmf"):
        path += ".vmf"

    # Append styled/ to the directory path.
    path_dir, path_file = os.path.split(path)
    new_path = new_args[-1] = os.path.join(
        path_dir,
        'styled',
        path_file,
    )

    for i, a in enumerate(new_args):
        # We need to strip these out, otherwise VBSP will get confused.
        if a == '-force_peti' or a == '-force_hammer':
            new_args[i] = ''
            old_args[i] = ''
        # Strip the entity limit, and the following number
        if a == '-entity_limit':
            new_args[i] = ''
            if len(new_args) > i+1 and new_args[i+1] == '1750':
                new_args[i+1] = ''

    LOGGER.info('Map path is "' + path + '"')
    LOGGER.info('New path: "' + new_path + '"')
    if path == "":
        raise Exception("No map passed!")

    if '-force_peti' in args or '-force_hammer' in args:
        # we have override command!
        if '-force_peti' in args:
            LOGGER.warning('OVERRIDE: Attempting to convert!')
            is_hammer = False
        else:
            LOGGER.warning('OVERRIDE: Abandoning conversion!')
            is_hammer = True
    else:
        # If we don't get the special -force args, check for the entity
        # limit to determine if we should convert
        is_hammer = "-entity_limit 1750" not in args
    if is_hammer:
        LOGGER.warning("Hammer map detected! skipping conversion..")
        run_vbsp(
            vbsp_args=old_args,
            do_swap=False,
            path=path,
            new_path=new_path,
        )
    else:
        LOGGER.info("PeTI map detected!")

        LOGGER.info("Loading settings...")
        load_settings()

        load_map(path)

        MAP_SEED = calc_rand_seed()

        all_inst = get_map_info()

        conditions.init(
            seed=MAP_SEED,
            inst_list=all_inst,
            vmf_file=VMF,
            )

        fix_inst()
        alter_flip_panel()  # Must be done before conditions!
        conditions.check_all()
        add_extra_ents(mode=GAME_MODE)

        change_ents()
        change_goo_sides()  # Must be done before change_brush()!
        change_brush()
        change_overlays()
        change_trig()
        collapse_goo_trig()  # Do after make_bottomless_pits
        change_func_brush()
        remove_static_ind_toggles()
        remove_barrier_ents()
        fix_worldspawn()

        make_packlist(path)
        make_vrad_config()

        save(new_path)
        run_vbsp(
            vbsp_args=new_args,
            do_swap=True,
            path=path,
            new_path=new_path,
        )

    LOGGER.info("BEE2 VBSP hook finished!")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import logging
        # Log the error, finalise the logs, and then crash.
        LOGGER.exception('Exception Occurred:')
        logging.shutdown()
        raise
