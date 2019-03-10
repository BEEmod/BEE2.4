"""Implements the BEE2 VBSP compiler replacement."""
# Do this very early, so we log the startup sequence.
from srctools.logger import init_logging

LOGGER = init_logging('bee2/vbsp.log')

import os
import sys
import shutil
import random
import itertools
import logging
from enum import Enum
from io import StringIO
from collections import defaultdict, namedtuple, Counter

from srctools import Property, Vec, AtomicWriter, Entity
from BEE2_config import ConfigFile
import utils
import srctools.vmf as VLib
import srctools.run
import srctools.logger
import antlines
import voiceLine
import vbsp_options
import instanceLocs
import brushLoc
import bottomlessPit
import packing
import conditions
import connections
import instance_traits
import template_brush
import fizzler
import comp_consts as consts
import cubes
import barriers

from typing import (
    Dict, Tuple, List,
    Set,
)

COND_MOD_NAME = 'VBSP'

# Configuration data extracted from VBSP_config
settings = {
    "textures":       {},
    "options":        {},
    "fog":            {},
    "elev_opt":       {},
    'music_conf':     None,

    "style_vars":     defaultdict(bool),
    "has_attr":       defaultdict(bool),
    "packtrigger":    defaultdict(list),
}


TEX_VALVE = {
    # all the non-wall textures produced by the Puzzlemaker, and their
    # replacement keys:
    consts.Signage.EXIT: "overlay.exit",
    consts.Signage.ARROW: "overlay.arrow",
    consts.Signage.SHAPE_DOT: "overlay.dot",
    consts.Signage.SHAPE_MOON: "overlay.moon",
    consts.Signage.SHAPE_TRIANGLE: "overlay.triangle",
    consts.Signage.SHAPE_CROSS: "overlay.cross",
    consts.Signage.SHAPE_SQUARE: "overlay.square",
    consts.Signage.SHAPE_CIRCLE: "overlay.circle",
    consts.Signage.SHAPE_SINE: "overlay.sine",
    consts.Signage.SHAPE_SLASH: "overlay.slash",
    consts.Signage.SHAPE_STAR: "overlay.star",
    consts.Signage.SHAPE_WAVY: "overlay.wavy",
    consts.Special.BACKPANELS_CHEAP: "special.behind",
    consts.Special.PED_SIDE: "special.pedestalside",
    consts.Special.SQUAREBEAMS: "special.edge",
    consts.Special.GLASS: "special.glass",
    consts.Special.GRATING: "special.grating",
}


TEX_DEFAULTS = [
    # Extra default replacements we need to specially handle.

    # These have the same item so we can't store this in the regular
    # dictionary.
    (consts.BlackPan.BLACK_FLOOR,    'black.floor'),
    (consts.WhitePan.WHITE_FLOOR,    'white.floor'),
    (consts.BlackPan.BLACK_FLOOR,    'black.ceiling'),
    (consts.WhitePan.WHITE_FLOOR,    'white.ceiling'),
    (consts.WhitePan.WHITE_1x1,     'white.wall'),
    (consts.WhitePan.WHITE_2x1,     'white.wall'),
    (consts.WhitePan.WHITE_2x2,     'white.2x2'),
    (consts.WhitePan.WHITE_4x4,     'white.4x4'),
    (consts.BlackPan.BLACK_1,  'black.wall'),
    (consts.BlackPan.BLACK_2,  'black.wall'),
    (consts.BlackPan.BLACK_2x2,  'black.2x2'),
    (consts.BlackPan.BLACK_4x4,  'black.4x4'),

    # This must be specially handled, switching between these.
    (consts.Goo.REFLECTIVE, 'special.goo'),
    (consts.Goo.CHEAP, 'special.goo_cheap'),

    # These replacements are deactivated when unset
    ('', 'special.white'),
    ('', 'special.black'),
    ('', 'special.white_wall'),
    ('', 'special.black_wall'),
    ('', 'special.white_gap'),
    ('', 'special.black_gap'),
    ('', 'special.goo_wall'),
    ('', 'special.goo_floor'),
    ('', 'special.edge_special'),
    ('', 'special.fizz_border'),

    # If set and enabled, adds frames for >10 sign pairs
    # to distinguish repeats.
    ('', 'overlay.shapeframe'),

    # Only used if set - replace the decals with textures
    ('', 'special.bullseye_white_wall'),
    ('', 'special.bullseye_white_floor'),
    ('', 'special.bullseye_white_ceiling'),
    ('', 'special.bullseye_black_wall'),
    ('', 'special.bullseye_black_floor'),
    ('', 'special.bullseye_black_ceiling'),
]


class ORIENT(Enum):
    """The different orientations a surface can have.

    This mainly affects which textures are added.
    """
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

BEE2_config = None  # type: ConfigFile

GAME_MODE = 'ERR'  # SP or COOP?
# Are we in preview mode? (Spawn in entry door instead of elevator)
IS_PREVIEW = 'ERR'  # type: bool

# A seed value for randomness, based on the general map layout.
# This stops patterns from repeating in different maps, but keeps it the same
# when recompiling.
MAP_RAND_SEED = ''

# The actual map.
VMF = None  # type: VLib.VMF

# These are faces, overlays and brush entitites which have been modified by
# conditions, and shouldn't be restyled or modified later.
IGNORED_FACES = set()
IGNORED_OVERLAYS = set()
IGNORED_BRUSH_ENTS = set()

GLOBAL_OUTPUTS = []  # A list of outputs which will be put into a logic_auto.


PRESET_CLUMPS = []  # Additional clumps set by conditions, for certain areas.

##################
# UTIL functions #
##################


def get_tex(name: str) -> str:
    if name in settings['textures']:
        return random.choice(settings['textures'][name])
    else:
        raise Exception('No texture "' + name + '"!')


def alter_mat(
    face: VLib.Side,
    seed: str=None,
    texture_lock: bool=True,
) -> bool:
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
    elif mat in consts.BlackPan or mat in consts.WhitePan:
        orient = get_face_orient(face)
        face.mat = get_tex(get_tile_type(mat, orient))

        if not texture_lock:
            face.offset = 0

        return True
    else:
        return False


def get_tile_type(mat: str, orient: ORIENT) -> str:
    """Get the texture command for a texture."""
    surf_type = 'white' if mat in consts.WhitePan else 'black'
    # We need to handle specially the 4x4 and 2x4 variants.
    # These are used in the embedface brushes, so they should
    # remain having small tile size. Wall textures have 4x4 and 2x2,
    # but floor/ceilings only have 4x4 sizes (since they usually
    # just stay the same).
    if orient == ORIENT.wall:
        if mat == consts.BlackPan.BLACK_4x4 or mat == consts.WhitePan.WHITE_4x4:
            orient = '4x4'
        elif mat == consts.BlackPan.BLACK_2x2 or mat == consts.WhitePan.WHITE_2x2:
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
        with open("bee2/vbsp_config.cfg", encoding='utf8') as config:
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
            settings['textures'][key] = [str(item)]
        else:
            settings['textures'][key] = value

    # Antline texturing settings.
    # We optionally allow different ones for floors.
    ant_wall = ant_floor = None
    for prop in conf.find_all('Textures', 'Antlines'):
        if 'floor' in prop:
            ant_floor = antlines.AntType.parse(prop.find_key('floor'))
        if 'wall' in prop:
            ant_wall = antlines.AntType.parse(prop.find_key('wall'))
        # If both are not there, allow omitting the subkey.
        if ant_wall is ant_floor is None:
            ant_wall = ant_floor = antlines.AntType.parse(prop)
    if ant_wall is None:
        ant_wall = antlines.AntType.default()
    if ant_floor is None:
        ant_floor = ant_wall

    # Load in our main configs..
    vbsp_options.load(conf.find_all('Options'))

    # The voice line property block
    for quote_block in conf.find_all("quotes"):
        voiceLine.QUOTE_DATA += quote_block.value

    # Configuration properties for styles.
    for stylevar_block in conf.find_all('stylevars'):
        for var in stylevar_block:
            settings['style_vars'][
                var.name.casefold()] = srctools.conv_bool(var.value)

    # Load in templates.
    template_brush.load_templates()

    # Load in the config file holding item data.
    # This is used to lookup item's instances, or their connection commands.
    with open('bee2/instances.cfg') as f:
        instance_file = Property.parse(
            f, 'bee2/instances.cfg'
        )
    # Parse that data in the relevant modules.
    instanceLocs.load_conf(instance_file)
    conditions.build_itemclass_dict(instance_file)
    connections.read_configs(instance_file)

    # Parse packlist data.
    with open('bee2/pack_list.cfg') as f:
        props = Property.parse(
            f,
            'bee2/pack_list.cfg'
        )
    packing.parse_packlists(props)

    # Parse all the conditions.
    for cond in conf.find_all('conditions', 'condition'):
        conditions.add(cond)

    # Data for different cube types.
    cubes.parse_conf(conf)

    # Fizzler data
    fizzler.read_configs(conf)

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

    settings['music_conf'] = conf['MusicScript', []]

    # Bottomless pit configuration
    pit = conf.find_key("bottomless_pit", [])
    bottomlessPit.load_settings(pit)

    # Fog settings - from the skybox (env_fog_controller, env_tonemap_controller)
    fog_config = conf.find_key("fog", [])
    # Update inplace so imports get the settings
    settings['fog'].update({
        # These defaults are from Clean Style.
        'start': fog_config['start', '128'],
        'end': fog_config['end', '5000'],
        'density': fog_config['density', '0.95'],
        'primary': fog_config['primaryColor', '40 53 64'],
        'secondary': fog_config['secondaryColor', ''],
        'direction': fog_config['direction', '0 0 0'],
        # These appear to be always the same..
        'height_start': fog_config['height_start', '0'],
        'height_density': fog_config['height_density', '0'],
        'height_max_density': fog_config['height_max_density', '1'],

        # Shadow background
        'shadow': fog_config['shadowColor', '98 102 106'],

        'tonemap_rate': fog_config['tonemap_rate', '0.25'],
        'tonemap_brightpixels': fog_config['tonemap_brightpixels', '5'],
        'tonemap_bloom_scale': fog_config['tonemap_bloom_scale', ''],
        'tonemap_exp_min': fog_config['tonemap_exposure_min', '.5'],
        'tonemap_exp_max': fog_config['tonemap_exposure_max', '3'],
    })

    # Find the location of the BEE2 app, and load the options
    # set in the 'Compiler Pane'.
    bee2_loc = vbsp_options.get(str, 'BEE2_loc')
    if bee2_loc:
        BEE2_config = ConfigFile('compile.cfg')
        vbsp_options.ITEM_CONFIG = ConfigFile('item_cust_configs.cfg')
    else:
        BEE2_config = ConfigFile(None)

    LOGGER.info("Settings Loaded!")
    return ant_floor, ant_wall


def load_map(map_path):
    """Load in the VMF file."""
    global VMF
    with open(map_path) as file:
        LOGGER.info("Parsing Map...")
        props = Property.parse(file, map_path)
    LOGGER.info('Reading Map...')
    VMF = VLib.VMF.parse(props)
    LOGGER.info("Loading complete!")


@conditions.meta_cond(priority=100)
def add_voice():
    """Add voice lines to the map."""
    voiceLine.add_voice(
        has_items=settings['has_attr'],
        style_vars_=settings['style_vars'],
        vmf_file_=VMF,
        map_seed=MAP_RAND_SEED,
        use_priority=BEE2_config.get_bool('General', 'use_voice_priority', True),
    )


def add_fizz_borders():
    """Generate overlays at the top and bottom of fizzlers.

    This is used in 50s and BTS styles.
    """
    tex = settings['textures']['special.fizz_border']
    if tex == ['']:
        # No textures were defined!
        return

    flip_uv = vbsp_options.get(bool, 'fizz_border_vertical')
    overlay_thickness = vbsp_options.get(int, 'fizz_border_thickness')
    overlay_repeat = vbsp_options.get(int, 'fizz_border_repeat')

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


@conditions.meta_cond(priority=-100, only_once=False)
def static_pan(inst: Entity):
    """Switches glass angled panels to static instances, if needed."""
    if inst['file'].casefold() in instanceLocs.resolve('<ITEM_PANEL_CLEAR>'):
        # white/black are found via the func_brush
        make_static_pan(inst, "glass")

# Dict mapping locations -> func_brush face, name
ANGLED_PAN_BRUSH = {}   # type: Dict[Tuple[float, float, float], Tuple[VLib.Side, str]]
# locations -> white, black faces
FLIP_PAN_BRUSH = {}  # type: Dict[Tuple[float, float, float], Tuple[VLib.Side, VLib.Side]]
# Record info_targets at the angled panel positions, so we can correct
# their locations for static panels
PANEL_FAITH_TARGETS = defaultdict(list) # type: Dict[Tuple[float, float, float], List[VLib.Entity]]


@conditions.meta_cond(-1000)
def find_panel_locs() -> None:
    """Find the locations of panels, used for FaithBullseye."""

    non_panel_mats = {
        consts.Special.SQUAREBEAMS,
        consts.Special.BACKPANELS,
        consts.Special.BACKPANELS_CHEAP
    }

    # Angled Panels
    for brush in VMF.by_class['func_brush']:
        if "-model_arms" not in brush['parentname', '']:
            continue
        for face in brush.sides():
            # Find the face which isn't backpanel/squarebeams
            if face.mat.casefold() not in non_panel_mats:
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
            if face.mat in consts.WhitePan:
                white_face = face
            if face.mat in consts.BlackPan:
                black_face = face
        if white_face and black_face:
            # The white face is positioned facing outward, so its origin is
            # centered nicely.
            FLIP_PAN_BRUSH[white_face.get_origin().as_tuple()] = (
                white_face,
                black_face,
            )


@conditions.meta_cond(100)
def set_flip_panel_keyvalues() -> None:
    """Set keyvalues on flip panels."""
    flip_panel_start = vbsp_options.get(str, 'flip_sound_start') or ''
    flip_panel_stop = vbsp_options.get(str, 'flip_sound_stop') or ''

    for flip_pan in VMF.by_class['func_door_rotating']:
        # Don't edit non flip panels!
        pan_name = flip_pan['targetname']
        if not pan_name.endswith('-flipping_panel'):
            continue
        try:
            item = connections.ITEMS[flip_pan['targetname'][:-15]]
        except KeyError:
            continue

        flip_pan['spawnpos'] = int(not item.inst.fixup.bool('$start_deployed'))
        flip_pan['noise1'] = flip_panel_start
        flip_pan['noise2'] = flip_panel_stop


@conditions.make_result_setup('FaithBullseye')
def res_faith_bullseye_check(res: Property) -> None:
    """Do a check to ensure there are actually textures availble."""
    for col in ('white', 'black'):
        for orient in ('wall', 'floor', 'ceiling'):
            if settings['textures'][
                    'special.bullseye_{}_{}'.format(col, orient)
                                        ] != ['']:
                return res.value
    return None  # No textures!


@conditions.make_result('FaithBullseye')
def res_faith_bullseye(inst: Entity, res: Property):
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
        if face.mat in consts.WhitePan:
            color = 'white'
        elif face.mat in consts.BlackPan:
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

    Returns whether it was successful or not.
    """
    if orient is None:
        orient = get_face_orient(face)

    if orient is ORIENT.ceil:  # We use the full 'ceiling' here, instead of 'ceil'.
        orient = 'ceiling'

    mat = get_tex('special.bullseye_{!s}_{!s}'.format(color, orient))

    # Fallback to floor texture if using ceiling or wall
    if orient is not ORIENT.floor and mat == '':
        mat = get_tex('special.bullseye_{}_floor'.format(color))

    if mat == '':
        return False
    else:
        face.mat = mat
        IGNORED_FACES.add(face)
        return True

FIZZ_BUMPER_WIDTH = 32  # The width of bumper brushes
FIZZ_NOPORTAL_WIDTH = 16  # Width of noportal_volumes


@conditions.meta_cond(priority=200, only_once=True)
def anti_fizz_bump():
    """Create portal_bumpers and noportal_volumes surrounding fizzlers.

    This makes it more difficult to portal-bump through an active fizzler.
    It is only applied to trigger_portal_cleansers with the Client flag
    checked.
    """
    # Subtract 2 for the fizzler width, and divide
    # to get the difference for each face.

    if not srctools.conv_bool(settings['style_vars']['fixfizzlerbump']):
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

# The paths for player models and the portalgun skin
PLAYER_MODELS = {
    'sp': ('player/chell/player', 0),
    'atlas': ('player/ballbot/ballbot', 1),
    'pbody': ('player/eggbot/eggbot', 2),
}


@conditions.meta_cond(priority=400, only_once=True)
def set_player_model():
    """Set the player model in SinglePlayer."""

    # Add the model changer instance.
    # We don't change the player model in Coop, or if Bendy is selected.

    if GAME_MODE == 'COOP':  # Not in coop..
        return

    loc = vbsp_options.get(Vec, 'model_changer_loc')
    chosen_model = BEE2_config.get_val('General', 'player_model', 'PETI').casefold()

    if chosen_model == 'peti':
        # The default model..
        return

    model_path, pgun_skin = PLAYER_MODELS[chosen_model]

    # Plug leaks
    VMF.add_brushes(VMF.make_hollow(
        loc - (32, 32, 64),
        loc + (32, 32, 64),
    ))

    # Precache the model, so we can switch to it.
    VMF.create_ent(
        classname='prop_dynamic_override',
        origin=loc + (0, 0, -60),
        model='models/' + model_path + '.mdl',

        rendermode=10,
        startDisabled=1,
        holdAnimation=1,
        disableshadows=1,
        disableshadowdepth=1,
        disableflashlight=1,
        disablereceiveshadows=1,
    )

    auto = VMF.create_ent(
        classname='logic_auto',
        spawnflags=0,  # Don't remove on fire.
        origin=loc + (0, 0, 32),
    )

    # The delay is required to ensure the portalgun parents properly
    # to the player's hand.
    auto.add_out(VLib.Output(
        'OnMapSpawn',
        '@command',
        'Command',
        'setmodel ' + model_path,
        delay=0.1,
    ))

    # We need to redo this whenever a saved game is loaded..
    auto.add_out(VLib.Output(
        'OnLoadGame',
        '@command',
        'Command',
        'setmodel ' + model_path,
        delay=0.1,
    ))

    if pgun_skin and vbsp_options.get(str, 'game_id') == utils.STEAM_IDS['PORTAL2']:
        # Only change portalgun skins in Portal 2 - this is the vanilla
        # portalgun weapon/viewmodel.
        auto.add_out(VLib.Output(
            'OnMapSpawn',
            'viewmodel',  # Classname of the viewmodel.
            'Skin',
            str(pgun_skin),
            delay=0.1,
        ))
        auto.add_out(VLib.Output(
            'OnMapSpawn',
            # Classname of the portalgun.
            # This will also change pedestals and the like,
            # but that's fine.
            'weapon_portalgun',
            'Skin',
            str(pgun_skin),
            delay=0,
        ))


@conditions.meta_cond(priority=500, only_once=True)
def set_player_portalgun() -> None:
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
    - 'PortalGunOnOff' or 'NeedsPortalMan' will also be checked to
      activate that logic.
    """

    if vbsp_options.get(str, 'game_id') == utils.STEAM_IDS['TAG']:
        return  # Aperture Tag doesn't have Portal Guns!

    LOGGER.info('Setting Portalgun:')

    has = settings['has_attr']

    blue_portal = not has['blueportal']
    oran_portal = not has['orangeportal']
    has_btn_onoff = has['portalgunonoff']
    force_portal_man = has_btn_onoff or has['needsportalman']

    LOGGER.info(
        'Blue: {}, Orange: {!s}',
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
    else:
        has['spawn_dual'] = False
        has['spawn_single'] = False
        has['spawn_nogun'] = True

    ent_pos = vbsp_options.get(Vec, 'global_pti_ents_loc')

    if not blue_portal or not oran_portal or force_portal_man:
        pgun_script = VMF.create_ent(
            classname='point_template',
            targetname='@portalgun',
            vscripts='bee2/portal_man.nut',
            origin=ent_pos,
        )

        if GAME_MODE == 'SP':
            VMF.create_ent(
                classname='weapon_portalgun',
                targetname='__pgun_template',
                CanFirePortal1=0,
                CanFirePortal2=0,
                spawnflags=0,
                origin=ent_pos - (12, 0, 0),
            )
            pgun_script['Template01'] = '__pgun_template'
            pgun_script['spawnflags'] = 2
        else:
            # In coop we have not need to actually spawn portalguns.
            pgun_script['classname'] = 'logic_script'

            # For Absolute Fizzler or otherwise, this fizzles portals on a
            # player remotely.
            cleanser = VMF.create_ent(
                classname='trigger_portal_cleanser',
                targetname='__pgun_cleanser',
                parentname=pgun_script['targetname'],
                origin=ent_pos,
                startdisabled=0,
                visible=0,
                spawnflags=1,  # Clients only.
            )
            cleanser.solids.append(VMF.make_prism(
                ent_pos - 4, ent_pos + 4,
                mat=consts.Tools.TRIGGER,
            ).solid)

        # For removing portalguns from players.
        trig_stripper = VMF.create_ent(
            targetname='__pgun_weapon_strip',
            classname='trigger_weapon_strip',
            origin=ent_pos,
            startdisabled=1,
            spawnflags=1,  # Players
            KillWeapons=1,
        )
        # Max map size is +-16384, for some reason we can't have a brush bigger than
        # that in any dimension?
        whole_map = VMF.make_prism(
            Vec(-8192, -8192, -8192),
            Vec(8192, 8192, 8192),
            mat=consts.Tools.TRIGGER,
        ).solid

        trig_stripper.solids = [whole_map]

        # Detect the group ID of portals placed in the map, and write to
        # the entities what we determine.
        if GAME_MODE == 'COOP':
            port_ids = (0, 1, 2)
        else:
            port_ids = (0, )

        for port_id in port_ids:
            trigger_portal = VMF.create_ent(
                targetname='__pgun_port_detect_{}'.format(port_id),
                classname='func_portal_detector',
                origin=ent_pos,
                CheckAllIDs=0,
                LinkageGroupID=port_id,
            )
            trigger_portal.solids = [whole_map.copy()]
            trigger_portal.add_out(
                VLib.Output(
                    'OnStartTouchPortal1',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_is_oran <- 0; '
                    '__pgun_port_id <- {}; '
                    '__pgun_active <- 1'.format(port_id),
                ),
                VLib.Output(
                    'OnStartTouchPortal2',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_is_oran <- 1; '
                    '__pgun_port_id <- {}; '
                    '__pgun_active <- 1'.format(port_id),
                ),
                VLib.Output(
                    'OnEndTouchPortal',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_active <- 0',
                ),
            )

        # Checking for held cubes, for pgun buttons.
        if has_btn_onoff:
            trig_cube = VMF.create_ent(
                targetname='__pgun_held_trig',
                classname='trigger_multiple',
                origin=ent_pos,
                filtername='@filter_held',
                startdisabled=1,
                spawnflags=8,  # Physics
                wait=0.01,
            )
            trig_cube.solids = [whole_map.copy()]
            trig_cube.add_out(VLib.Output(
                'OnStartTouch',
                '@portalgun',
                'RunScriptCode',
                '_mark_held_cube()',
            ))

        if GAME_MODE == 'SP':
            GLOBAL_OUTPUTS.append(VLib.Output(
                'OnMapSpawn',
                '@portalgun',
                'RunScriptCode',
                'init({}, {}, {})'.format(
                    'true' if blue_portal else 'false',
                    'true' if oran_portal else 'false',
                    'true' if has_btn_onoff else 'false',
                ),
                delay=0.1,
                only_once=True,
            ))

        # Shuts down various parts when you've reached the exit.
        import conditions.instances
        conditions.instances.global_input(VMF, ent_pos, VLib.Output(
            'OnTrigger',
            '@portalgun',
            'RunScriptCode',
            'map_won()',
        ), relay_name='@map_won')

    if blue_portal:
        GLOBAL_OUTPUTS.append(VLib.Output(
            'OnMapSpawn',
            '@player_has_blue',
            'Trigger',
            only_once=True,
        ))
    if oran_portal:
        GLOBAL_OUTPUTS.append(VLib.Output(
            'OnMapSpawn',
            '@player_has_oran',
            'Trigger',
            only_once=True,
        ))

    LOGGER.info('Done!')


@conditions.meta_cond(priority=750, only_once=True)
def add_screenshot_logic() -> None:
    """If the screenshot type is 'auto', add in the needed ents."""
    if BEE2_config.get_val(
        'Screenshot', 'type', 'PETI'
    ).upper() == 'AUTO' and IS_PREVIEW:
        VMF.create_ent(
            classname='func_instance',
            file='instances/bee2/logic/screenshot_logic.vmf',
            origin=vbsp_options.get(Vec, 'global_ents_loc'),
            angles='0 0 0',
        )
        LOGGER.info('Added Screenshot Logic')


@conditions.meta_cond(priority=100, only_once=True)
def add_fog_ents():
    """Add the tonemap and fog controllers, based on the skybox."""
    pos = vbsp_options.get(Vec, 'global_ents_loc')
    VMF.create_ent(
        classname='env_tonemap_controller',
        targetname='@tonemapper',
        origin=pos + (-16, 0, 0),
    )

    fog_opt = settings['fog']

    random.seed(MAP_RAND_SEED + '_shadow_angle')
    VMF.create_ent(
        classname='shadow_control',
        # Slight variations around downward direction.
        angles=Vec(random.randrange(85, 90), random.randrange(0, 360), 0),
        origin=pos + (0, 16, 0),
        distance=100,
        color=fog_opt['shadow'],
        disableallshadows=0,
        enableshadowsfromlocallights=1,
    )

    fog_controller = VMF.create_ent(
        classname='env_fog_controller',
        targetname='@fog_controller',
        origin=pos + (16, 0, 0),
        angles=fog_opt['direction'],

        fogcolor=fog_opt['primary'],
        fogstart=fog_opt['start'],
        fogend=fog_opt['end'],

        fogenable='1',
        use_angles='1',
        foglerptime='2',
        fogMaxDensity='1',

        heightFogStart=fog_opt['height_start'],
        heightFogDensity=fog_opt['height_density'],
        heightFogMaxDensity=fog_opt['height_max_density'],
    )

    if fog_opt['secondary']:
        # Only enable fog blending if a secondary color is enabled
        fog_controller['fogblend'] = '1'
        fog_controller['fogcolor2'] = fog_opt['secondary']
        fog_controller['use_angles'] = '1'

    GLOBAL_OUTPUTS.extend([
        VLib.Output(
            'OnMapSpawn',
            '@clientcommand',
            'Command',
            'r_flashlightbrightness 1',
        ),

        VLib.Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetTonemapPercentBrightPixels',
            fog_opt['tonemap_brightpixels'],
            only_once=True,
        ),
        VLib.Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetTonemapRate',
            fog_opt['tonemap_rate'],
            only_once=True,
        ),
        VLib.Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetAutoExposureMin',
            fog_opt['tonemap_exp_min'],
            only_once=True,
        ),
        VLib.Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetAutoExposureMax',
            fog_opt['tonemap_exp_max'],
            only_once=True,
        ),
    ])

    if fog_opt['tonemap_bloom_scale']:
        GLOBAL_OUTPUTS.append(VLib.Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetBloomScale',
            fog_opt['tonemap_bloom_scale'],
            only_once=True,
        ))

    if GAME_MODE == 'SP':
        GLOBAL_OUTPUTS.append(VLib.Output(
            'OnMapSpawn',
            '!player',
            'SetFogController',
            '@fog_controller',
            only_once=True,
        ))
    else:
        GLOBAL_OUTPUTS.append(VLib.Output(
            'OnMapSpawn',
            '!player_blue',
            'SetFogController',
            '@fog_controller',
            only_once=True,
        ))
        GLOBAL_OUTPUTS.append(VLib.Output(
            'OnMapSpawn',
            '!player_orange',
            'SetFogController',
            '@fog_controller',
            only_once=True,
        ))


@conditions.meta_cond(priority=50, only_once=True)
def set_elev_videos() -> None:
    """Add the scripts and options for customisable elevator videos to the map."""
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
        LOGGER.warning('Invalid elevator video type!')
        return

    transition_ents = instanceLocs.resolve('[transitionents]')
    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in transition_ents:
            continue
        if vert_vid:
            inst.fixup[consts.FixupVars.BEE_ELEV_VERT] = 'media/' + vert_vid + '.bik'
        if horiz_vid:
            inst.fixup[consts.FixupVars.BEE_ELEV_HORIZ] = 'media/' + horiz_vid + '.bik'

        # Create the video script
        VMF.create_ent(
            classname='logic_script',
            targetname='@video_splitter',
            vscripts=script,
            origin=inst['origin'],
        )


def get_map_info() -> Set[str]:
    """Determine various attributes about the map.

    This also set the 'preview in elevator' options and forces
    a particular entry/exit hallway.

    - SP/COOP status
    - if in preview mode
    """
    global GAME_MODE, IS_PREVIEW

    inst_files = set()  # Get a set of every instance in the map.

    file_coop_entry = instanceLocs.get_special_inst('coopEntry')
    file_coop_exit = instanceLocs.get_special_inst('coopExit')
    file_sp_exit = instanceLocs.get_special_inst('spExit')
    file_sp_entry = instanceLocs.get_special_inst('spEntry')

    # These have multiple instances, so 'in' must be used.
    # If both frames are set to "", get_special returns None so fix that.
    file_coop_corr = instanceLocs.get_special_inst('coopCorr')
    file_sp_entry_corr = instanceLocs.get_special_inst('spEntryCorr')
    file_sp_exit_corr = instanceLocs.get_special_inst('spExitCorr')
    file_sp_door_frame = instanceLocs.get_special_inst('door_frame_sp')
    file_coop_door_frame = instanceLocs.get_special_inst('door_frame_coop')

    # Should we force the player to spawn in the elevator?
    elev_override = BEE2_config.get_bool('General', 'spawn_elev')

    if elev_override:
        # Make conditions set appropriately
        LOGGER.info('Forcing elevator spawn!')
        IS_PREVIEW = False

    # Door frames use the same instance for both the entry and exit doors,
    # and it'd be useful to disinguish between them. Add an instvar to help.
    door_frames = []
    entry_origin = Vec(-999, -999, -999)
    exit_origin = Vec(-999, -999, -999)

    exit_fixup = entry_fixup = None  # Copy the exit/entry fixup to the frame.

    override_sp_entry = BEE2_config.get_int('Corridor', 'sp_entry', 0)
    override_sp_exit = BEE2_config.get_int('Corridor', 'sp_exit', 0)
    override_coop_corr = BEE2_config.get_int('Corridor', 'coop', 0)

    # The type of corridor - used to replace doorframes, if needed.
    # 0-7 = normal, 'up'/'down' = vert up/down
    entry_corr_type = exit_corr_type = 0
    entry_corr_name = exit_corr_name = ""

    # The door frame instances
    entry_door_frame = exit_door_frame = None

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
        LOGGER.debug('File: "{}"', file)
        if file in file_sp_exit_corr:
            GAME_MODE = 'SP'
            # In SP mode the same instance is used for entry and exit door
            # frames. Use the position of the item to distinguish the two.
            # We need .rotate() since they could be in the same block.
            exit_origin = Vec(0, 0, -64).rotate_by_str(item['angles'])
            exit_origin += Vec.from_str(item['origin'])
            exit_corr_name = item['targetname']
            exit_fixup = item.fixup
            exit_corr_type = mod_entryexit(
                item,
                'spExitCorr',
                'SP Exit',
                elev_override,
                override_sp_exit,
                is_exit=True,
            )
        elif file in file_sp_entry_corr:
            GAME_MODE = 'SP'
            entry_origin = Vec(0, 0, -64).rotate_by_str(item['angles'])
            entry_origin += Vec.from_str(item['origin'])
            entry_corr_name = item['targetname']
            entry_fixup = item.fixup
            entry_corr_type = mod_entryexit(
                item,
                'spEntryCorr',
                'SP Entry',
                elev_override,
                override_sp_entry,
            )
        elif file in file_coop_corr:
            GAME_MODE = 'COOP'
            exit_corr_name = item['targetname']
            exit_fixup = item.fixup
            exit_corr_type = mod_entryexit(
                item,
                'coopCorr',
                'Coop Exit',
                elev_override,
                override_coop_corr,
                is_exit=True,
            )
        elif file_coop_entry == file:
            GAME_MODE = 'COOP'
            entry_corr_name = item['targetname']
            entry_fixup = item.fixup
            mod_entryexit(
                item,
                'coopCorr',
                'Coop Spawn',
                elev_override,
            )
        elif file_coop_exit == file:
            GAME_MODE = 'COOP'
            # Elevator instances don't get named - fix that...
            item['targetname'] = 'coop_exit'
            if elev_override:
                item.fixup['no_player_start'] = '1'
        elif file_sp_exit == file or file_sp_entry == file:
            GAME_MODE = 'SP'
            if elev_override:
                item.fixup['no_player_start'] = '1'
            # Elevator instances don't get named - fix that...
            item['targetname'] = (
                'elev_entry' if
                file_sp_entry == file
                else 'elev_exit'
            )
        elif file in file_sp_door_frame:
            # We need to inspect origins to determine the entry door type.
            door_frames.append(item)
        elif file in file_coop_door_frame:
            # The coop frame must be the exit door...
            exit_door_frame = item

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
        origin = Vec(0, 0, -64).rotate_by_str(door_frame['angles'])
        # Corridors are placed 64 units below doorframes - reverse that.
        origin.z -= 64
        origin += Vec.from_str(door_frame['origin'])
        if origin == entry_origin:
            door_frame.fixup['door_type'] = 'entry'
            entry_door_frame = door_frame
            if entry_fixup is not None:
                # Copy the entry-door's fixup values to the frame itself..
                door_frame.fixup.update(entry_fixup)
        elif origin == exit_origin:
            door_frame.fixup['door_type'] = 'exit'
            exit_door_frame = door_frame
            if exit_fixup is not None:
                door_frame.fixup.update(exit_fixup)

    if GAME_MODE == 'COOP':
        mod_doorframe(
            exit_door_frame,
            'ITEM_COOP_EXIT_DOOR',
            exit_corr_type,
            exit_corr_name,
        )
    else:
        mod_doorframe(
            entry_door_frame,
            'ITEM_ENTRY_DOOR',
            entry_corr_type,
            entry_corr_name,
        )
        mod_doorframe(
            exit_door_frame,
            'ITEM_EXIT_DOOR',
            exit_corr_type,
            exit_corr_name,
        )

    # Return the set of all instances in the map.
    return inst_files


def mod_entryexit(
        inst: VLib.Entity,
        resolve_name,
        pretty_name,
        elev_override=False,
        override_corr=-1,
        is_exit=False,
    ):
    """Modify this entrance or exit.

    This sets IS_PREVIEW, switches to vertical variants, and chooses a
    particular corridor number.
    This returns the corridor used - 1-7, 'up', or 'down'.
    The corridor used is also copied to '$corr_index'.
    """
    global IS_PREVIEW
    normal = Vec(0, 0, 1).rotate_by_str(inst['angles'])

    if is_exit:
        # Swap the normal direction, so the up/down names match the direction
        # of travel.
        normal = -normal

    vert_up = instanceLocs.get_special_inst(resolve_name + 'Up')
    vert_down = instanceLocs.get_special_inst(resolve_name + 'Down')
    files = instanceLocs.get_special_inst(resolve_name)

    # The coop spawn instance doesn't have no_player_start..
    if 'no_player_start' in inst.fixup:
        if elev_override:
            inst.fixup['no_player_start'] = '1'
        else:
            IS_PREVIEW = not srctools.conv_bool(inst.fixup['no_player_start'])

    if normal == (0, 0, 1) and vert_up is not None:
        LOGGER.info(
            'Using upward variant for {}',
            pretty_name,
        )
        inst['file'] = vert_up
        return 'vert_up'

    if normal == (0, 0, -1) and vert_down is not None:
        LOGGER.info(
            'Using downward variant for {}',
            pretty_name,
        )
        inst['file'] = vert_down
        return 'vert_down'

    if override_corr == -1:
        return None  # There aren't any variants (coop spawn room)

    if override_corr == 0:
        index = files.index(inst['file'].casefold())
        inst.fixup[consts.FixupVars.BEE_CORR_INDEX] = index + 1
        LOGGER.info(
            'Using random {} ({})',
            pretty_name,
            index + 1,
        )
        return index
    else:
        LOGGER.info(
            'Setting {} to {}',
            pretty_name,
            override_corr,
        )
        inst.fixup[consts.FixupVars.BEE_CORR_INDEX] = override_corr
        inst['file'] = files[override_corr - 1]
        return override_corr - 1


def mod_doorframe(inst: VLib.Entity, corr_id, corr_type, corr_name):
    """Change the instance used by door frames, if desired.

    corr_id is the item ID of the dooor, and corr_type is the
    return value of mod_entryexit(). corr_name is the name of the corridor.
    """
    if inst is None:
        return  # This doorframe doesn't exist...

    is_white = inst['file'].casefold() in instanceLocs.get_special_inst(
        'white_frame',
    )

    inst['targetname'] = corr_name

    replace = instanceLocs.get_cust_inst(
        # Allow using a custom instance path to replace corridor types:
        # "frame_1_white", "frame_vert_down_white"
        corr_id,
        'frame_{type}_{color}'.format(
            type=corr_type,
            color='white' if is_white else 'black',
        )
    )
    if replace is not None:
        inst['file'] = replace


def calc_rand_seed() -> str:
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
        grid_x: int,
        grid_y: int,
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


def fixup_goo_sides() -> None:
    """Replace the textures on the sides of goo and bottomless pits.

    For goo these can use special textures, or black 4x4 walls.
    For pits sides use normal black walls.
    """

    if vbsp_options.get(str, 'goo_wall_scale_temp'):
        scale = template_brush.get_scaling_template(
            vbsp_options.get(str, 'goo_wall_scale_temp')
        )
    else:
        scale = None

    LOGGER.info("Changing goo sides...")
    for solid in VMF.brushes[:]:
        for face in solid:
            if face in IGNORED_FACES:
                continue
            if face.mat.casefold() != 'tools/toolsnodraw':
                origin = face.get_origin()
                norm = face.normal()
                if len(norm) != 1:
                    continue  # Not aligned to grid...

                block_type = brushLoc.POS['world': origin - 64 * norm]

                # We only want to alter black panel surfaces..
                if block_type.is_goo and face.mat.casefold() in BLACK_PAN:
                    face.mat = ''
                    if norm.z != 0:
                        face.mat = get_tex('special.goo_floor')

                    if face.mat == '':  # goo_floor is invalid, or not used
                        face.mat = get_tex('special.goo_wall')

                    if face.mat == '':  # No overrides, use normal textures.
                        face.mat = get_tex('black.4x4')

                    if scale is not None:
                        # Allow altering the orientation of the texture.
                        scale.apply(face, change_mat=False)

                    IGNORED_FACES.add(face)

                if block_type.is_pit:
                    if block_type.is_bottom and norm.z != 0:
                        bottomlessPit.fix_base_brush(VMF, solid, face)
                    else:
                        # Use the black textures, this should be textured normally.
                        face.mat = BLACK_PAN[1]

    LOGGER.info("Done!")


def collapse_goo_trig() -> None:
    """Collapse the goo triggers to only use 2 entities for all pits."""
    LOGGER.info('Collapsing goo triggers...')

    hurt_trig = None
    cube_trig = None
    for trig in VMF.by_class['trigger_multiple']:
        if trig in IGNORED_BRUSH_ENTS:
            continue

        if trig['wait'] == '0.1' and trig['targetname', ''] == '':
            if cube_trig is None:
                cube_trig = trig
            else:
                cube_trig.solids.extend(trig.solids)
                trig.remove()

    for trig in VMF.by_class['trigger_hurt']:
        if trig in IGNORED_BRUSH_ENTS:
            continue

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


@conditions.meta_cond(priority=-50)
def set_barrier_frame_type() -> None:
    """Set a $type instvar on glass frame.

    This allows using different instances on glass and grating.
    """
    barrier_types = {}  # origin, normal -> 'glass' / 'grating'

    barrier_pos = [] # type: List[Tuple[Vec, str]]

    # Find glass and grating brushes..
    for brush in VMF.iter_wbrushes(world=False, detail=True):
        for side in brush:
            if side.mat == consts.Special.GLASS:
                break
        else:
            # Not glass..
            continue
        barrier_pos.append((brush.get_origin(), 'glass'))

    for brush_ent in VMF.by_class['func_brush']:
        for side in brush_ent.sides():
            if side.mat == consts.Special.GRATING:
                break
        else:
            # Not grating..
            continue
        barrier_pos.append((brush_ent.get_origin(), 'grating'))

    # The origins are at weird offsets, calc a grid pos + normal instead
    for pos, barrier_type in barrier_pos:
        grid_pos = pos // 128 * 128 + (64, 64, 64)
        barrier_types[
            grid_pos.as_tuple(),
            (pos - grid_pos).norm().as_tuple()
        ] = barrier_type

    barrier_files = instanceLocs.resolve('<ITEM_BARRIER>')
    glass_file = instanceLocs.resolve('[glass_128]')
    for inst in VMF.by_class['func_instance']:
        if inst['file'].casefold() not in barrier_files:
            continue
        if inst['file'].casefold() in glass_file:
            # The glass instance faces a different way to the frames..
            norm = Vec(-1, 0, 0).rotate_by_str(inst['angles'])
        else:
            norm = Vec(0, 0, -1).rotate_by_str(inst['angles'])
        origin = Vec.from_str(inst['origin'])
        try:
            inst.fixup[consts.FixupVars.BEE_GLS_TYPE] = barrier_types[origin.as_tuple(), norm.as_tuple()]
        except KeyError:
            pass


def fix_squarebeams(
    face: VLib.Side,
    rotate: bool,
    reset_offset: bool,
    scale: float,
) -> None:
    """Fix a squarebeams brush for use in other styles.

    If rotate is True, rotate the texture 90 degrees.
    offset is the offset for the texture.
    """
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


def change_brush() -> None:
    """Alter all world/detail brush textures to use the configured ones."""
    LOGGER.info("Editing Brushes...")

    goo_scale = vbsp_options.get(float, 'goo_scale')

    # Goo mist must be enabled by both the style and the user.
    make_goo_mist = vbsp_options.get(bool, 'goo_mist') and srctools.conv_bool(
        settings['style_vars'].get('AllowGooMist', '1')
    )
    mist_solids = set()

    if vbsp_options.get(bool, 'remove_pedestal_plat'):
        # Remove the pedestal platforms
        for ent in VMF.by_class['func_detail']:
            if ent in IGNORED_BRUSH_ENTS:
                continue

            for side in ent.sides():
                if side.mat.casefold() == 'plastic/plasticwall004a':
                    VMF.remove_ent(ent)
                    break  # Skip to next entity

    make_bottomless = bottomlessPit.pits_allowed()
    LOGGER.info('Make Bottomless Pit: {}', make_bottomless)

    highest_brush = 0

    # Calculate the z-level with the largest number of goo brushes,
    # so we can ensure the 'fancy' pit is the largest one.
    # Valve just does it semi-randomly.
    goo_heights = Counter()
    for pos, block in brushLoc.POS.items():
        if block.is_goo and block.is_top:
            # Block position is the center,
            # save at the height of the top face
            goo_heights[brushLoc.g2w(pos).z + 32] += 1
    # Find key with the highest value = z-level with highest brush.
    try:
        best_goo = max(goo_heights.items(), key=lambda x: x[1])[0]
    except ValueError:
        # No goo in the map, it's fine.
        best_goo = 0

    LOGGER.info('Goo heights: {} <- {}', best_goo, goo_heights)

    for solid in VMF.iter_wbrushes(world=True, detail=True):
        for face in solid:
            highest_brush = max(
                highest_brush,
                face.planes[0].z,
                face.planes[1].z,
                face.planes[2].z,
            )
            if face.mat in consts.Goo:
                if make_goo_mist:
                    mist_solids.add(
                        solid.get_origin().as_tuple()
                    )
                # Apply goo scaling
                face.scale = goo_scale
                # Use fancy goo on the level with the
                # highest number of blocks.
                # All plane z are the same.
                face.mat = get_tex(
                    'special.goo' if
                    face.planes[0].z == best_goo
                    else 'special.goo_cheap'
                )

    if make_bottomless:
        LOGGER.info('Creating Bottomless Pits...')
        bottomlessPit.make_bottomless_pit(VMF, highest_brush)
        LOGGER.info('Done!')

    if make_goo_mist:
        LOGGER.info('Adding Goo Mist...')
        add_goo_mist(mist_solids)
        LOGGER.info('Done!')

    if can_clump():
        clump_walls()
    else:
        random_walls()


def can_clump() -> bool:
    """Check the clump algorithm is enabled."""
    return vbsp_options.get(bool, "clump_wall_tex")


def face_seed(face: VLib.Side) -> str:
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


def random_walls() -> None:
    """The original wall style, with completely randomised walls."""
    rotate_edge = vbsp_options.get(bool, 'rotate_edge')
    texture_lock = vbsp_options.get(bool, 'tile_texture_lock')
    edge_off = vbsp_options.get(bool, 'reset_edge_off')
    edge_scale = vbsp_options.get(float, 'edge_scale')

    for solid in VMF.iter_wbrushes(world=True, detail=True):
        for face in solid:
            if face in IGNORED_FACES:
                continue

            if face.mat == consts.Special.SQUAREBEAMS:
                fix_squarebeams(face, rotate_edge, edge_off, edge_scale)

            # Conditions can define special clumps for items, we want to
            # do those if needed.
            origin = face.get_origin()
            for clump in PRESET_CLUMPS:
                if clump.min_pos <= origin <= clump.max_pos:
                    face.mat = clump.tex[get_tile_type(
                        face.mat.casefold(),
                        get_face_orient(face),
                    )]
                    break
            else:  # No clump..
                alter_mat(face, face_seed(face), texture_lock)


Clump = namedtuple('Clump', [
    'min_pos',
    'max_pos',
    'tex',
])


@conditions.make_result_setup('SetAreaTex')
def cond_force_clump_setup(res: Property):
    point1 = Vec.from_str(res['point1'])
    point2 = Vec.from_str(res['point2'])

    # Except for white/black walls, all the textures fallback to each other.

    white_tex = res['white']
    white_floor = res['whiteFloor', white_tex]
    white_4x4 = res['white4x4', white_tex]

    black_tex = res['black']
    black_floor = res['blackFloor', white_tex]
    black_4x4 = res['black4x4', white_tex]

    tex_data = {
        'white.wall': white_tex,
        'white.floor': white_floor,
        'white.4x4': white_4x4,
        'white.ceiling': res['whiteCeiling', white_floor],
        'white.2x2': res['white2x2', white_4x4],

        'black.wall': black_tex,
        'black.floor': black_floor,
        'black.4x4': black_4x4,
        'black.ceiling': res['blackCeiling', black_floor],
        'black.2x2': res['black2x2', black_floor],
    }

    return point1, point2, tex_data


@conditions.make_result('SetAreaTex')
def cond_force_clump(inst: Entity, res: Property):
    """Force an area to use certain textures.

    This only works in styles using the clumping texture algorithm.
    """
    point1, point2, tex_data = res.value
    origin = Vec.from_str(inst['origin'])
    angles = Vec.from_str(inst['angles'])

    point1 = point1.copy().rotate(*angles)
    point1 += origin

    point2 = point2.copy().rotate(*angles)
    point2 += origin

    min_pos, max_pos = Vec.bbox(point1, point2)

    PRESET_CLUMPS.append(Clump(
        min_pos,
        max_pos,
        tex_data
    ))


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

    texture_lock = vbsp_options.get(bool, 'tile_texture_lock')
    rotate_edge = vbsp_options.get(bool, 'rotate_edge')
    edge_off = vbsp_options.get(bool, 'reset_edge_off')
    edge_scale = vbsp_options.get(float, 'edge_scale')

    # Possible locations for clumps - every face origin, not including
    # ignored faces or nodraw
    panel_mats = set(consts.WhitePan).union(consts.BlackPan)
    possible_locs = [
        face.get_origin()
        for face in
        VMF.iter_wfaces(world=True, detail=True)
        if face not in IGNORED_FACES
        if face.mat.casefold() in panel_mats
    ]

    clump_size = vbsp_options.get(int, "clump_size")
    clump_wid = vbsp_options.get(int, "clump_width")

    clump_numb = len(possible_locs) // (clump_size * clump_wid * clump_wid)
    clump_numb *= vbsp_options.get(int, "clump_number")

    # Also clump ceilings or floors?
    clump_ceil = vbsp_options.get(bool, 'clump_ceil')
    clump_floor = vbsp_options.get(bool, 'clump_floor')

    LOGGER.info(
        'Clumping: {} clumps (+ {} special)',
        clump_numb,
        len(PRESET_CLUMPS),
    )

    random.seed(MAP_RAND_SEED)

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

        if mat == consts.Special.SQUAREBEAMS:
            # Handle squarebeam transformations
            alter_mat(face, face_seed(face), texture_lock)
            fix_squarebeams(face, rotate_edge, edge_off, edge_scale)
            continue

        if mat not in panel_mats:
            # Don't clump non-wall textures
            alter_mat(face, face_seed(face), texture_lock)
            continue

        orient = get_face_orient(face)

        origin = face.get_origin()
        # Conditions can define special clumps for items, do those first
        # so they override the normal surfaces.
        # We want to do that regardless of the clump_floor and clump_ceil
        # settings
        clump_changed = False
        for clump in PRESET_CLUMPS:
            if clump.min_pos <= origin <= clump.max_pos:
                face.mat = clump.tex[get_tile_type(mat, orient)]
                clump_changed = True
                break
        if clump_changed:
            continue

        if (
                (orient is ORIENT.floor and not clump_floor) or
                (orient is ORIENT.ceiling and not clump_ceil)):
            # Don't clump if configured not to for this orientation
            alter_mat(face, face_seed(face), texture_lock)
            continue

        # Clump the texture!
        for clump in clumps:
            if clump.min_pos <= origin <= clump.max_pos:
                face.mat = clump.tex[get_tile_type(mat, orient)]
                break
        else:
            # Not in a clump!
            # Allow using special textures for these, to fill in gaps.
            orig_mat = mat
            if mat in consts.WhitePan:
                face.mat = get_tex("special.white_gap")
                if not face.mat:
                    face.mat = orig_mat
                    alter_mat(face, texture_lock=texture_lock)
            elif mat in consts.BlackPan:
                face.mat = get_tex("special.black_gap")
                if not face.mat:
                    face.mat = orig_mat
                    alter_mat(face, texture_lock=texture_lock)
            else:
                alter_mat(face, texture_lock=texture_lock)


def get_face_orient(face: VLib.Side) -> ORIENT:
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


def change_overlays() -> None:
    """Alter the overlays."""
    LOGGER.info("Editing Overlays...")

    # A frame instance to add around all the 32x32 signs
    sign_inst = vbsp_options.get(str, 'signInst')
    # Resize the signs to this size. 4 vertexes are saved relative
    # to the origin, so we must divide by 2.
    sign_size = vbsp_options.get(int, 'signSize') / 2

    # A packlist associated with the sign_inst.
    sign_inst_pack = vbsp_options.get(str, 'signPack')


    for over in VMF.by_class['info_overlay']:
        if over in IGNORED_OVERLAYS:
            # Overlays added by us, or conditions. These are styled aleady,
            # don't touch them.
            continue

        if (over['targetname'] == 'exitdoor_stickman' or
                over['targetname'] == 'exitdoor_arrow'):
            if vbsp_options.get(bool, "remove_exit_signs"):
                # Some styles have instance-based ones, remove the
                # originals if needed to ensure it looks nice.
                VMF.remove_ent(over)
                continue  # Break out, to make sure the instance isn't added
            else:
                # blank the targetname, so we don't get the
                # useless info_overlay_accessors for these signs.
                del over['targetname']

        case_mat = over['material'].casefold()

        if case_mat in consts.Signage:
            sign_type = TEX_VALVE[case_mat]
            if sign_inst is not None:
                new_inst = VMF.create_ent(
                    classname='func_instance',
                    origin=over['origin'],
                    angles=over['angles', '0 0 0'],
                    file=sign_inst,
                )
                if sign_inst_pack:
                    packing.pack_list(VMF, sign_inst_pack)
                new_inst.fixup['mat'] = sign_type.replace('overlay.', '')
            # Delete the overlay's targetname - signs aren't ever dynamic
            # This also means items set to signage only won't get toggle
            # instances.
            del over['targetname']

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


def add_extra_ents(mode):
    """Add the various extra instances to the map."""
    LOGGER.info("Adding Music...")

    loc = vbsp_options.get(Vec, 'global_ents_loc')

    # These values are exported by the BEE2 app, indicating the
    # options on the music item.
    inst = vbsp_options.get(str, 'music_instance')
    snd_length = vbsp_options.get(int, 'music_looplen')

    # Don't add our logic if an instance was provided.
    # If this settings is set, we have a music config.
    if settings['music_conf'] and not inst:
        music = VMF.create_ent(
            classname='ambient_generic',
            spawnflags='17',  # Looping, Infinite Range, Starts Silent
            targetname='@music',
            origin=loc,
            message='music.BEE2',
            health='10',  # Volume
        )

        music_start = VMF.create_ent(
            classname='logic_relay',
            spawnflags='0',
            targetname='@music_start',
            origin=loc + (-16, 0, -16),
        )
        music_stop = VMF.create_ent(
            classname='logic_relay',
            spawnflags='0',
            targetname='@music_stop',
            origin=loc + (16, 0, -16),
        )
        music_stop.add_out(
            VLib.Output('OnTrigger', music, 'StopSound'),
            VLib.Output('OnTrigger', music, 'Volume', '0'),
        )

        # In SinglePlayer, music gets killed during reload,
        # so we need to restart it.

        # If snd_length is set, we have a non-loopable MP3
        # and want to re-trigger it after the time elapses, to simulate
        # looping.

        # In either case, we need @music_restart to do that safely.
        if GAME_MODE == 'SP' or snd_length > 0:

            music_restart = VMF.create_ent(
                classname='logic_relay',
                spawnflags='2',  # Allow fast retrigger.
                targetname='@music_restart',
                StartDisabled='1',
                origin=loc + (0, 0, -16),
            )

            music_start.add_out(
                VLib.Output('OnTrigger', music_restart, 'Enable'),
                VLib.Output('OnTrigger', music_restart, 'Trigger', delay=0.01),
            )

            music_stop.add_out(
                VLib.Output('OnTrigger', music_restart, 'Disable'),
                VLib.Output('OnTrigger', music_restart, 'CancelPending'),
            )

            music_restart.add_out(
                VLib.Output('OnTrigger', music, 'StopSound'),
                VLib.Output('OnTrigger', music, 'Volume', '0'),
                VLib.Output('OnTrigger', music, 'Volume', '10', delay=0.1),
                VLib.Output('OnTrigger', music, 'PlaySound', delay=0.1),
            )

            if GAME_MODE == 'SP':
                # Trigger on level loads.
                VMF.create_ent(
                    classname='logic_auto',
                    origin=loc + (0, 0, 16),
                    spawnflags='0',  # Don't remove after fire
                    globalstate='',
                ).add_out(
                    VLib.Output('OnLoadGame', music_restart, 'CancelPending'),
                    VLib.Output('OnLoadGame', music_restart, 'Trigger', delay=0.01),
                )

            if snd_length > 0:
                # Re-trigger after the music duration.
                music_restart.add_out(
                    VLib.Output('OnTrigger', '!self', 'Trigger', delay=snd_length)
                )
                # Set to non-looping, so re-playing will restart it correctly.
                music['spawnflags'] = '49'
        else:
            # The music track never needs to have repeating managed,
            # just directly trigger.
            music_start.add_out(
                VLib.Output('OnTrigger', music, 'PlaySound'),
                VLib.Output('OnTrigger', music, 'Volume', '10'),
            )

    if inst:
        # We assume the instance is setup correct.
        VMF.create_ent(
            classname='func_instance',
            targetname='music',
            angles='0 0 0',
            origin=loc,
            file=inst,
            fixup_style='0',
        )

    LOGGER.info('Adding global ents...')

    # Add the global_pti_ents instance automatically, with disable_pti_audio
    # set.
    global_ents_pos = vbsp_options.get(Vec, 'global_ents_loc')
    pti_file = vbsp_options.get(str, 'global_pti_ents')
    pti_loc = vbsp_options.get(Vec, 'global_pti_ents_loc')

    # Add a nodraw box around the global entity location, to seal it.
    VMF.add_brushes(VMF.make_hollow(
        global_ents_pos + (128, 128, 128),
        global_ents_pos - (128, 128, 64),
    ))

    # Add a cubemap into the map, so materials get a blank one generated.
    # If none are present this doesn't happen...
    VMF.create_ent(
        classname='env_cubemap',
        cubemapsize=1,  # Make as small as possible..
        origin=global_ents_pos,
    )

    # So we have one in the map.
    VMF.create_ent(
        classname='info_node',
        origin=global_ents_pos - (0, 0, 64),
        nodeid=1,
        spawnflags=0,
        angles='0 0 0',
    )

    if settings['has_attr']['bridge'] or settings['has_attr']['lightbridge']:
        # If we have light bridges, make sure we precache the particle.
        VMF.create_ent(
            classname='info_particle_system',
            origin=global_ents_pos,
            effect_name='projected_wall_impact',
            start_active=0,
        )

    if pti_file:
        LOGGER.info('Adding Global PTI Ents')
        global_pti_ents = VMF.create_ent(
            classname='func_instance',
            targetname='global_pti_ents',
            angles='0 0 0',
            origin=pti_loc,
            file=pti_file,
            fixup_style='0',
            )

        has_cave = srctools.conv_bool(
            settings['style_vars'].get('multiversecave', '1')
        )
        global_pti_ents.fixup[
            'disable_pti_audio'
            ] = srctools.bool_as_int(not has_cave)

        # The scripts we want to run on the @glados entity.
        # This gets special functions called (especially in coop) for various
        # events we might want to track - death, pings, camera taunts, etc.
        glados_scripts = [
            'choreo/glados.nut',  # Implements Multiverse Cave..
        ]
        if voiceLine.has_responses():
            glados_scripts.append('bee2/coop_responses.nut')

        global_pti_ents.fixup['glados_script'] = ' '.join(glados_scripts)

    # Add a logic_auto with the set of global outputs.
    logic_auto = VMF.create_ent(
        classname='logic_auto',
        spawnflags='0',  # Don't remove on fire
        origin=global_ents_pos + (0, 0, 16),
    )
    logic_auto.outputs = GLOBAL_OUTPUTS


def change_func_brush():
    """Edit func_brushes."""
    LOGGER.info("Editing Brush Entities...")

    dynamic_pan_temp = vbsp_options.get(str, "dynamic_pan_temp")
    dynamic_pan_parent = vbsp_options.get(str, "dynamic_pan_parent")

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
        rotate_edge = vbsp_options.get(bool, 'rotate_edge')
        edge_off = vbsp_options.get(bool, 'reset_edge_off')
        edge_scale = vbsp_options.get(float, 'edge_scale')
    else:
        edge_tex = 'special.edge_special'
        rotate_edge = vbsp_options.get(bool, 'rotate_edge_special')
        edge_off = vbsp_options.get(bool, 'reset_edge_off_special')
        edge_scale = vbsp_options.get(float, 'edge_scale_special')

    for brush in VMF.by_class['func_brush'] | VMF.by_class['func_door_rotating']:  # type: VLib.Entity
        if brush in IGNORED_BRUSH_ENTS:
            continue

        brush['drawInFastReflection'] = vbsp_options.get(bool, "force_brush_reflect")
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

        surf_face = None  # The angled-panel top face..

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

            if side.mat == consts.Special.SQUAREBEAMS:
                side.mat = get_tex(edge_tex)
                fix_squarebeams(
                    side,
                    rotate_edge,
                    edge_off,
                    edge_scale,
                )
                continue

            if side.mat in consts.WhitePan:
                brush_type = "white"
                set_special_mat(side, 'white')
                surf_face = side

            elif side.mat in consts.BlackPan:
                brush_type = "black"
                set_special_mat(side, 'black')
                surf_face = side
            else:

                alter_mat(side)  # for gratings, laserfields and some others

            # The style blanked the material, so delete the brush
            if side.mat == '':
                delete_brush = True
                break

        if delete_brush:
            VMF.remove_ent(brush)
            continue

        if "-model_arms" in parent:  # is this an angled panel?:
            # strip only the model_arms off the end
            targ = '-'.join(parent.split("-")[:-1])
            # Now find the associated instance
            for ins in (
                VMF.by_class['func_instance'] &
                VMF.by_target[targ]
            ):

                if 'connectioncount' not in ins.fixup:
                    continue  # It's a static-style overlay instance, ignore.

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
                    brush['parentname'] = conditions.local_name(
                        ins,
                        dynamic_pan_parent,
                    )

                    if dynamic_pan_temp:
                        # Allow replacing the brush used for the surface.
                        new_brush = template_brush.import_template(
                            dynamic_pan_temp,
                            Vec.from_str(brush['origin']),
                            Vec.from_str(ins['angles']),
                            targetname=targ,
                            force_type=template_brush.TEMP_TYPES.detail,
                        )
                        brush.solids = new_brush.detail.solids
                        new_brush.detail.remove()
                        for side in brush.sides():
                            if side.mat.casefold() == 'metal/black_wall_metal_002c':
                                # Copy data from the original face...
                                side.mat = surf_face.mat
                                side.uaxis = surf_face.uaxis
                                side.vaxis = surf_face.vaxis
                                side.ham_rot = surf_face.ham_rot
                                side.smooth = surf_face.smooth
                                side.lightmap = surf_face.lightmap

                break  # Don't run twice - there might be a second matching
                # overlay instance!

    if vbsp_options.get(str, 'grating_pack') and settings['has_attr']['grating']:
        packing.pack_list(VMF, vbsp_options.get(str, 'grating_pack'))


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


def make_static_pan(
    ent: VLib.Entity,
    pan_type: str,
    is_bullseye: bool=False
) -> bool:
    """Convert a regular panel into a static version.

    This is done to save entities and improve lighting."""
    static_pan_folder = vbsp_options.get(str, 'staticPan')
    if not static_pan_folder:
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
        ent["file"] = static_pan_folder + angle + '_glass.vmf'
        return True

    # Handle white/black panels:
    ent['file'] = static_pan_folder + angle + '_surf.vmf'

    # We use a template for the surface, so it can use correct textures.
    if angle == '00':
        # Special case: flat panels use different templates
        temp_data = template_brush.import_template(
            vbsp_options.get(str, 'static_pan_temp_flat'),
            origin=Vec.from_str(ent['origin']),
            angles=Vec.from_str(ent['angles']),
            targetname=ent['targetname'],
            force_type=template_brush.TEMP_TYPES.detail,
        )
        template_brush.retexture_template(
            temp_data,
            origin=Vec.from_str(ent['origin']),
            force_colour=getattr(template_brush.MAT_TYPES, pan_type),
            fixup=ent.fixup,
            use_bullseye=is_bullseye,
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

        temp_data = template_brush.import_template(
            vbsp_options.get(str, 'static_pan_temp_' + pan_type),
            temp_origin,
            temp_angles,
            force_type=template_brush.TEMP_TYPES.detail,
        )
        template_brush.retexture_template(
            temp_data,
            origin=Vec.from_str(ent['origin']),
            force_colour=getattr(template_brush.MAT_TYPES, pan_type),
            fixup=ent.fixup,
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


def change_ents() -> None:
    """Edit misc entities."""
    LOGGER.info("Editing Other Entities...")
    if vbsp_options.get(bool, "remove_info_lighting"):
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


def fix_worldspawn() -> None:
    """Adjust some properties on WorldSpawn."""
    LOGGER.info("Editing WorldSpawn")
    if VMF.spawn['paintinmap'] != '1':
        # If PeTI thinks there should be paint, don't touch it
        # Otherwise set it based on the 'gel' voice attribute
        # If the game is Aperture Tag, it's always forced on
        VMF.spawn['paintinmap'] = srctools.bool_as_int(
            settings['has_attr']['gel'] or
            vbsp_options.get(str, 'game_id') == utils.STEAM_IDS['APTAG']
        )
    VMF.spawn['skyname'] = vbsp_options.get(str, 'skybox')


def make_vrad_config(is_peti: bool) -> None:
    """Generate a config file for VRAD from our configs.

    This way VRAD doesn't need to parse through vbsp_config, or anything else.
    """
    LOGGER.info('Generating VRAD config...')
    conf = Property('Config', [
    ])
    conf['is_peti'] = srctools.bool_as_int(is_peti)

    if is_peti:
        conf['force_full'] = srctools.bool_as_int(
            BEE2_config.get_bool('General', 'vrad_force_full')
        )
        conf['screenshot'] = BEE2_config.get_val(
            'Screenshot', 'loc', ''
        )
        conf['screenshot_type'] = BEE2_config.get_val(
            'Screenshot', 'type', 'PETI'
        ).upper()
        conf['clean_screenshots'] = srctools.bool_as_int(
            BEE2_config.get_bool('Screenshot', 'del_old')
        )
        conf['is_preview'] = srctools.bool_as_int(
            IS_PREVIEW
        )
        conf['game_id'] = vbsp_options.get(str, 'game_id')

        if BEE2_config.get_bool('General', 'packfile_dump_enable'):
            conf['packfile_dump'] = BEE2_config.get_val(
                'General',
                'packfile_dump_dir',
                ''
            )

        # Copy over the voice attributes
        conf['VoiceAttr'] = ';'.join(
            key
            for key, value in
            settings['has_attr'].items()
            if value
        )

        # Copy over music soundscript data so VRAD can generate it..
        if settings['music_conf']:
            # It's a list of prop objects, so it'll become a proper
            # block when written.
            conf['MusicScript'] = settings['music_conf']

        import cubes
        import conditions.piston_platform

        # This generates scripts and might need to tell VRAD.
        cubes.write_vscripts(conf)

    with open('bee2/vrad_config.cfg', 'w', encoding='utf8') as f:
        for line in conf.export():
            f.write(line)


def instance_symlink():
    """On OS X and Linux, Valve broke VBSP's instances/ finding code.

    We need to symlink maps/styled/instances/ -> maps/instances/ to allow
    instances to be found.
    """
    map_root = os.path.abspath(os.path.join(
        os.getcwd(),
        '..', 'sdk_content', 'maps',
    ))
    inst = os.path.join(map_root, 'instances')
    link_loc = os.path.join(map_root, 'styled', 'instances')

    if os.path.islink(link_loc) and os.path.samefile(inst, link_loc):
        LOGGER.info('Symlink already exists..')
        return  # Already done

    LOGGER.info('Creating symlink from "{}" -> "{}"', link_loc, inst)
    os.symlink(inst, link_loc, target_is_directory=True)


def save(path: str) -> None:
    """Save the modified map back to the correct location.
    """
    LOGGER.info("Saving New Map...")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with AtomicWriter(path) as f:
        VMF.export(dest_file=f, inc_version=True)
    LOGGER.info("Complete!")


def run_vbsp(vbsp_args, path, new_path=None) -> None:
    """Execute the original VBSP, copying files around so it works correctly.

    vbsp_args are the arguments to pass.
    path is the original .vmf, new_path is the styled/ name.
    If new_path is passed VBSP will be run on the map in styled/, and we'll
    read through the output to find the entity counts.
    """

    is_peti = new_path is not None

    # We can't overwrite the original vmf, so we run VBSP from a separate
    # location.
    if is_peti:
        # Copy the original log file
        if os.path.isfile(path.replace(".vmf", ".log")):
            shutil.copy(
                path.replace(".vmf", ".log"),
                new_path.replace(".vmf", ".log"),
            )

    # Remove blank args.
    vbsp_args = [x for x in vbsp_args if x and not x.isspace()]

    # Ensure we've fixed the instance/ folder so instances are found.
    if utils.MAC or utils.LINUX and is_peti:
        instance_symlink()

    # Use a special name for VBSP's output..
    vbsp_logger = srctools.logger.get_logger('valve.VBSP', alias='<Valve>')

    # And also save a copy for us to analyse.
    buff = StringIO()
    vbsp_logger.addHandler(logging.StreamHandler(buff))

    code = srctools.run.run_compiler('vbsp', vbsp_args, vbsp_logger)
    if code != 0:
        # VBSP didn't succeed.
        if is_peti:  # Ignore Hammer maps
            process_vbsp_fail(buff.getvalue())

        # Propagate the fail code to Portal 2, and quit.
        sys.exit(code)

    # Print output
    LOGGER.info("VBSP Done!")

    if is_peti:  # Ignore Hammer maps
        process_vbsp_log(buff.getvalue())

    # Copy over the real files so vvis/vrad can read them
        for ext in (".bsp", ".log", ".prt"):
            if os.path.isfile(new_path.replace(".vmf", ext)):
                shutil.copy(
                    new_path.replace(".vmf", ext),
                    path.replace(".vmf", ext),
                )


def process_vbsp_log(output: str) -> None:
    """Read through VBSP's log, extracting entity counts.

    This is then passed back to the main BEE2 application for display.
    """

    # The output is something like this:
    # nummapplanes:     (?? / 65536)
    # nummapbrushes:    (?? / 8192)
    # nummapbrushsides: (?? / 65536)
    # num_map_overlays: (?? / 512)
    # nummodels:        (?? / 1024)
    # num_entities:     (?? / 16384)

    desired_vals = [
        # VBSP values -> config names
        ('nummapbrushes:', 'brush'),
        ('num_map_overlays:', 'overlay'),
        ('num_entities:', 'entity'),
    ]
    # The other options rarely hit the limits, so we don't track them.

    counts = {
        'brush': ('0', '8192'),
        'overlay': ('0', '512'),
        'entity': ('0', '2048'),
    }

    for line in output.splitlines():
        line = line.lstrip(' \t[|')
        for name, conf in desired_vals:
            if not line.startswith(name):
                continue
            # Grab the value from ( onwards
            fraction = line.split('(', 1)[1]
            # Grab the two numbers, convert to ascii and strip
            # whitespace.
            count_num, count_max = fraction.split('/')
            counts[conf] = (
                count_num.strip(' \t\n'),
                # Strip the ending ) off the max. We have the value, so
                # we might as well tell the BEE2 if it changes..
                count_max.strip(') \t\n'),
            )

    LOGGER.info('Retrieved counts: {}', counts)
    count_section = BEE2_config['Counts']
    for count_name, (value, limit) in counts.items():
        count_section[count_name] = value
        count_section['max_' + count_name] = limit
    BEE2_config.save()


def process_vbsp_fail(output: str) -> None:
    """Read through VBSP's logs when failing, to update counts."""
    # VBSP doesn't output the actual entity counts, so set the errorred
    # one to max and the others to zero.
    count_section = BEE2_config['Counts']

    count_section['max_brush'] = '8192'
    count_section['max_entity'] = '2048'
    count_section['max_overlay'] = '512'

    for line in reversed(output.splitlines()):
        if 'MAX_MAP_OVERLAYS' in line:
            count_section['entity'] = '0'
            count_section['brush'] = '0'
            # The line is like 'MAX_MAP_OVER = 512', pull out the number from
            # the end and decode it.
            over_count = line.rsplit('=')[1].strip()
            count_section['overlay'] = over_count
            count_section['max_overlay'] = over_count
            break
        if 'MAX_MAP_BRUSHSIDES' in line or 'MAX_MAP_PLANES' in line:
            count_section['entity'] = '0'
            count_section['overlay'] = '0'
            count_section['brush'] = '8192'
            break
        if 'MAX_MAP_ENTITIES' in line:
            count_section['entity'] = count_section['overlay'] = '0'
            count_section['brush'] = '8192'
            break
    else:
        count_section['entity'] = '0'
        count_section['overlay'] = '0'
        count_section['brush'] = '0'
    BEE2_config.save_check()


def main() -> None:
    """Main program code.

    """
    global MAP_RAND_SEED, IS_PREVIEW, GAME_MODE
    LOGGER.info("BEE{} VBSP hook initiallised.", utils.BEE_VERSION)

    conditions.import_conditions()  # Import all the conditions and
    # register them.

    if 'BEE2_WIKI_OPT_LOC' in os.environ:
        # Special override - generate docs for the BEE2 wiki.
        LOGGER.info('Writing Wiki text...')
        with open(os.environ['BEE2_WIKI_OPT_LOC'], 'w') as f:
            vbsp_options.dump_info(f)
        with open(os.environ['BEE2_WIKI_COND_LOC'], 'a+') as f:
            conditions.dump_conditions(f)
        LOGGER.info('Done. Exiting now!')
        sys.exit()

    # Just in case we fail, overwrite the VRAD config so it doesn't use old
    # data.
    open('bee2/vrad_config.cfg', 'w').close()

    args = " ".join(sys.argv)
    new_args = sys.argv[1:]
    old_args = sys.argv[1:]
    folded_args = [arg.casefold() for arg in old_args]
    path = sys.argv[-1]  # The path is the last argument to vbsp

    if not old_args:
        # No arguments!
        LOGGER.info(
            'No arguments!\n'
            "The BEE2 VBSP takes all the regular VBSP's "
            'arguments, with some extra arguments:\n'
            '-dump_conditions: Print a list of all condition flags,\n'
            '  results, and metaconditions.\n'
            '-bee2_verbose: Print debug messages to the console.\n'
            '-verbose: A default VBSP command, has the same effect as above.\n'
            '-force_peti: Force enabling map conversion. \n'
            "-force_hammer: Don't convert the map at all.\n"
            '-entity_limit: A default VBSP command, this is inspected to'
            'determine if the map is PeTI or not.'
        )
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

    # Clear the list of files we want to inject into the packfile.
    # If we're in a Hammer map, we want to ensure no files are injected.
    LOGGER.info('Clearing inject/ directory..')
    os.makedirs('bee2/inject/', exist_ok=True)
    for file in os.listdir('bee2/inject'):
        os.remove(os.path.join('bee2', 'inject', file))

    if is_hammer:
        LOGGER.warning("Hammer map detected! skipping conversion..")
        run_vbsp(
            vbsp_args=old_args,
            path=path,
        )
    else:
        LOGGER.info("PeTI map detected!")

        LOGGER.info("Loading settings...")
        ant_floor, ant_wall = load_settings()

        load_map(path)
        instance_traits.set_traits(VMF)

        # Requires instance traits!
        connections.calc_connections(
            VMF,
            settings['textures']['overlay.shapeframe'],
            settings['style_vars']['enableshapesignageframe'],
            ant_floor,
            ant_wall,
        )

        MAP_RAND_SEED = calc_rand_seed()

        all_inst = get_map_info()

        brushLoc.POS.read_from_map(VMF, settings['has_attr'])

        fizzler.parse_map(VMF, settings['has_attr'])
        barriers.parse_map(VMF, settings['has_attr'])

        conditions.init(
            seed=MAP_RAND_SEED,
            inst_list=all_inst,
            vmf_file=VMF,
        )

        conditions.check_all()
        add_extra_ents(mode=GAME_MODE)

        change_ents()
        fixup_goo_sides()  # Must be done before change_brush()!
        change_brush()
        change_overlays()
        collapse_goo_trig()
        change_func_brush()
        barriers.make_barriers(VMF, get_tex)
        fix_worldspawn()

        
        # Ensure all VMF outputs use the correct seperator.
        for ent in VMF.entities:
            for out in ent.outputs:
                out.comma_sep = False

        save(new_path)
        run_vbsp(
            vbsp_args=new_args,
            path=path,
            new_path=new_path,
        )

    # We always need to do this - VRAD can't easily determine if the map is
    # a Hammer one.
    make_vrad_config(is_peti=not is_hammer)
    LOGGER.info("BEE2 VBSP hook finished!")


if __name__ == '__main__':
    main()
