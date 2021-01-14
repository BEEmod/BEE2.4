"""Implements the BEE2 VBSP compiler replacement."""
# Do this very early, so we log the startup sequence.
from srctools.logger import init_logging

LOGGER = init_logging('bee2/vbsp.log')

import os
import sys
import shutil
import random
import logging
from io import StringIO
from collections import defaultdict, namedtuple, Counter

from srctools import Property, Vec, AtomicWriter, Vec_tuple
from srctools.vmf import VMF, Entity, Output
from BEE2_config import ConfigFile
import utils
import srctools.run
import srctools.logger
from precomp import (
    instance_traits,
    brushLoc,
    bottomlessPit,
    instanceLocs,
    cubes,
    template_brush,
    texturing,
    tiling,
    barriers,
    connections,
    options,
    faithplate,
    antlines,
    packing,
    conditions,
    fizzler,
    voice_line,
    music,
)
import consts

from typing import Any, Dict, Tuple, List, Set, Iterable


COND_MOD_NAME = 'VBSP'

# Configuration data extracted from VBSP_config
settings: Dict[str, Dict[str, Any]] = {
    "textures":       {},
    "options":        {},
    "fog":            {},
    "elevator":       {},
    'music_conf':     None,

    "style_vars":     defaultdict(bool),
    "has_attr":       defaultdict(bool),
    "packtrigger":    defaultdict(list),
}

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

BEE2_config = ConfigFile('compile.cfg')

GAME_MODE = 'ERR'  # SP or COOP?
# Are we in preview mode? (Spawn in entry door instead of elevator)
IS_PREVIEW = 'ERR'  # type: bool

# A seed value for randomness, based on the general map layout.
# This stops patterns from repeating in different maps, but keeps it the same
# when recompiling.
MAP_RAND_SEED = ''

# These are overlays which have been modified by
# conditions, and shouldn't be restyled or modified later.
IGNORED_OVERLAYS = set()

PRESET_CLUMPS = []  # Additional clumps set by conditions, for certain areas.


def load_settings() -> Tuple[antlines.AntType, antlines.AntType]:
    """Load in all our settings from vbsp_config."""
    try:
        with open("bee2/vbsp_config.cfg", encoding='utf8') as config:
            conf = Property.parse(config, 'bee2/vbsp_config.cfg')
    except FileNotFoundError:
        LOGGER.warning('Error: No vbsp_config file!')
        conf = Property(None, [])
        # All the find_all commands will fail, and we will use the defaults.

    texturing.load_config(conf.find_key('textures', []))

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
    options.load(conf.find_all('Options'))

    # The voice line property block
    for quote_block in conf.find_all("quotes"):
        voice_line.QUOTE_DATA += quote_block.copy()

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

    # Signage items
    from precomp.conditions.signage import load_signs
    load_signs(conf)

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

    settings['music_conf'] = conf.find_key('MusicScript', [])

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

    LOGGER.info("Settings Loaded!")
    return ant_floor, ant_wall


def load_map(map_path: str) -> VMF:
    """Load in the VMF file."""
    with open(map_path) as file:
        LOGGER.info("Parsing Map...")
        props = Property.parse(file, map_path)
    LOGGER.info('Reading Map...')
    vmf = VMF.parse(props)
    LOGGER.info("Loading complete!")
    return vmf


@conditions.meta_cond(priority=100)
def add_voice(vmf: VMF):
    """Add voice lines to the map."""
    voice_line.add_voice(
        has_items=settings['has_attr'],
        style_vars_=settings['style_vars'],
        vmf_file_=vmf,
        map_seed=MAP_RAND_SEED,
        use_priority=BEE2_config.get_bool('General', 'use_voice_priority', True),
    )


FIZZ_BUMPER_WIDTH = 32  # The width of bumper brushes
FIZZ_NOPORTAL_WIDTH = 16  # Width of noportal_volumes


@conditions.meta_cond(priority=200, only_once=True)
def anti_fizz_bump(vmf: VMF) -> None:
    """Create portal_bumpers and noportal_volumes surrounding fizzlers.

    This makes it more difficult to portal-bump through an active fizzler.
    It is only applied to trigger_portal_cleansers with the Client flag
    checked.
    """
    # Subtract 2 for the fizzler width, and divide
    # to get the difference for each face.

    if not srctools.conv_bool(settings['style_vars']['fixfizzlerbump']):
        return

    # Only use 1 bumper entity for each fizzler, since we can.
    bumpers = {}

    LOGGER.info('Adding Portal Bumpers to fizzlers...')
    for cleanser in vmf.by_class['trigger_portal_cleanser']:
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
            bumper = bumpers[fizz_name] = vmf.create_ent(
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
        noportal = vmf.create_ent(
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
def set_player_model(vmf: VMF) -> None:
    """Set the player model in SinglePlayer."""

    # Add the model changer instance.
    # We don't change the player model in Coop, or if Bendy is selected.

    if GAME_MODE == 'COOP':  # Not in coop..
        return

    loc = options.get(Vec, 'global_ents_loc')
    chosen_model = BEE2_config.get_val('General', 'player_model', 'PETI').casefold()

    if chosen_model == 'peti':
        # The default model..
        return

    model_path, pgun_skin = PLAYER_MODELS[chosen_model]

    # Precache the model, so we can switch to it.
    vmf.create_ent(
        classname='comp_precache_model',
        origin=loc,
        model='models/' + model_path + '.mdl',
    )

    auto = vmf.create_ent(
        classname='logic_auto',
        spawnflags=0,  # Don't remove on fire.
        origin=loc,
    )

    # The delay is required to ensure the portalgun parents properly
    # to the player's hand.
    auto.add_out(Output(
        'OnMapSpawn',
        '@command',
        'Command',
        'setmodel ' + model_path,
        delay=0.1,
    ))

    # We need to redo this whenever a saved game is loaded..
    auto.add_out(Output(
        'OnLoadGame',
        '@command',
        'Command',
        'setmodel ' + model_path,
        delay=0.1,
    ))

    if pgun_skin and options.get(str, 'game_id') == utils.STEAM_IDS['PORTAL2']:
        # Only change portalgun skins in Portal 2 - this is the vanilla
        # portalgun weapon/viewmodel.
        auto.add_out(Output(
            'OnMapSpawn',
            'viewmodel',  # Classname of the viewmodel.
            'Skin',
            str(pgun_skin),
            delay=0.1,
        ))
        auto.add_out(Output(
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
def set_player_portalgun(vmf: VMF) -> None:
    """Controls which portalgun the player will be given.

    This does not apply to coop. It checks the 'blueportal' and
    'orangeportal' attributes to see what are in the map.

    - If there are no spawners in the map, the player gets a dual portal
      device.
    - If there are only blue portal spawners, the player gets a orange-only
      gun.
    - If there are only orange portal spawners, the player gets a blue-
      only gun (Regular single portal device).
    - If there are both spawner types, the player doesn't get a gun.
    - If the attribute `PortalGunOnOff` is present, special logic is added for that.
    - If the attribute `NeedsPortalMan` is present, or the player has a non-dual
      device the `@portalgun` manager script is added to enable these features.
      `NeedsPortalMan` still works to add this in Coop.
    """

    if options.get(str, 'game_id') == utils.STEAM_IDS['TAG']:
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

    ent_pos = options.get(Vec, 'global_pti_ents_loc')
    
    logic_auto = vmf.create_ent('logic_auto', origin=ent_pos, flags='1')

    if not blue_portal or not oran_portal or force_portal_man:
        pgun_script = vmf.create_ent(
            classname='point_template',
            targetname='@portalgun',
            vscripts='bee2/portal_man.nut',
            origin=ent_pos,
        )

        if GAME_MODE == 'SP':
            vmf.create_ent(
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
            cleanser = vmf.create_ent(
                classname='trigger_portal_cleanser',
                targetname='__pgun_cleanser',
                parentname=pgun_script['targetname'],
                origin=ent_pos,
                startdisabled=0,
                visible=0,
                spawnflags=1,  # Clients only.
            )
            cleanser.solids.append(vmf.make_prism(
                ent_pos - 4, ent_pos + 4,
                mat=consts.Tools.TRIGGER,
            ).solid)

        # For removing portalguns from players.
        trig_stripper = vmf.create_ent(
            targetname='__pgun_weapon_strip',
            classname='trigger_weapon_strip',
            origin=ent_pos,
            startdisabled=1,
            spawnflags=1,  # Players
            KillWeapons=1,
        )
        # Max map size is +-16384, for some reason we can't have a brush bigger than
        # that in any dimension?
        whole_map = vmf.make_prism(
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
            trigger_portal = vmf.create_ent(
                targetname='__pgun_port_detect_{}'.format(port_id),
                classname='func_portal_detector',
                origin=ent_pos,
                CheckAllIDs=0,
                LinkageGroupID=port_id,
            )
            trigger_portal.solids = [whole_map.copy()]
            trigger_portal.add_out(
                Output(
                    'OnStartTouchPortal1',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_is_oran <- 0; '
                    '__pgun_port_id <- {}; '
                    '__pgun_active <- 1'.format(port_id),
                ),
                Output(
                    'OnStartTouchPortal2',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_is_oran <- 1; '
                    '__pgun_port_id <- {}; '
                    '__pgun_active <- 1'.format(port_id),
                ),
                Output(
                    'OnEndTouchPortal',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_active <- 0',
                ),
            )

        # Checking for held cubes, for pgun buttons.
        if has_btn_onoff:
            trig_cube = vmf.create_ent(
                targetname='__pgun_held_trig',
                classname='trigger_multiple',
                origin=ent_pos,
                filtername='@filter_held',
                startdisabled=1,
                spawnflags=8,  # Physics
                wait=0.01,
            )
            trig_cube.solids = [whole_map.copy()]
            trig_cube.add_out(Output(
                'OnStartTouch',
                '@portalgun',
                'RunScriptCode',
                '_mark_held_cube()',
            ))

        if GAME_MODE == 'SP':
            logic_auto.add_out(Output(
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
        import precomp.conditions.instances
        precomp.conditions.instances.global_input(vmf, ent_pos, Output(
            'OnTrigger',
            '@portalgun',
            'RunScriptCode',
            'map_won()',
        ), relay_name='@map_won')

    if blue_portal:
        logic_auto.add_out(Output(
            'OnMapSpawn',
            '@player_has_blue',
            'Trigger',
            only_once=True,
        ))
    if oran_portal:
        logic_auto.add_out(Output(
            'OnMapSpawn',
            '@player_has_oran',
            'Trigger',
            only_once=True,
        ))

    LOGGER.info('Done!')


@conditions.meta_cond(priority=750, only_once=True)
def add_screenshot_logic(vmf: VMF) -> None:
    """If the screenshot type is 'auto', add in the needed ents."""
    if BEE2_config.get_val(
        'Screenshot', 'type', 'PETI'
    ).upper() == 'AUTO' and IS_PREVIEW:
        vmf.create_ent(
            classname='func_instance',
            file='instances/bee2/logic/screenshot_logic.vmf',
            origin=options.get(Vec, 'global_ents_loc'),
            angles='0 0 0',
        )
        LOGGER.info('Added Screenshot Logic')


@conditions.meta_cond(priority=100, only_once=True)
def add_fog_ents(vmf: VMF) -> None:
    """Add the tonemap and fog controllers, based on the skybox."""
    pos = options.get(Vec, 'global_ents_loc')
    vmf.create_ent(
        classname='env_tonemap_controller',
        targetname='@tonemapper',
        origin=pos + (-16, 0, 0),
    )

    fog_opt = settings['fog']

    random.seed(MAP_RAND_SEED + '_shadow_angle')
    vmf.create_ent(
        classname='shadow_control',
        # Slight variations around downward direction.
        angles=Vec(random.randrange(85, 90), random.randrange(0, 360), 0),
        origin=pos + (0, 16, 0),
        distance=100,
        color=fog_opt['shadow'],
        disableallshadows=0,
        enableshadowsfromlocallights=1,
    )

    fog_controller = vmf.create_ent(
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

    logic_auto = vmf.create_ent(classname='logic_auto', origin=pos, flags='1')

    logic_auto.add_out(
        Output(
            'OnMapSpawn',
            '@clientcommand',
            'Command',
            'r_flashlightbrightness 1',
        ),

        Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetTonemapPercentBrightPixels',
            fog_opt['tonemap_brightpixels'],
            only_once=True,
        ),
        Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetTonemapRate',
            fog_opt['tonemap_rate'],
            only_once=True,
        ),
        Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetAutoExposureMin',
            fog_opt['tonemap_exp_min'],
            only_once=True,
        ),
        Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetAutoExposureMax',
            fog_opt['tonemap_exp_max'],
            only_once=True,
        ),
    )

    if fog_opt['tonemap_bloom_scale']:
        logic_auto.add_out(Output(
            'OnMapSpawn',
            '@tonemapper',
            'SetBloomScale',
            fog_opt['tonemap_bloom_scale'],
            only_once=True,
        ))

    if GAME_MODE == 'SP':
        logic_auto.add_out(Output(
            'OnMapSpawn',
            '!player',
            'SetFogController',
            '@fog_controller',
            only_once=True,
        ))
    else:
        logic_auto.add_out(Output(
            'OnMapSpawn',
            '!player_blue',
            'SetFogController',
            '@fog_controller',
            only_once=True,
        ), Output(
            'OnMapSpawn',
            '!player_orange',
            'SetFogController',
            '@fog_controller',
            only_once=True,
        ))


@conditions.meta_cond(priority=50, only_once=True)
def set_elev_videos(vmf: VMF) -> None:
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
    for inst in vmf.by_class['func_instance']:
        if inst['file'].casefold() not in transition_ents:
            continue
        if vert_vid:
            inst.fixup[consts.FixupVars.BEE_ELEV_VERT] = 'media/' + vert_vid + '.bik'
        if horiz_vid:
            inst.fixup[consts.FixupVars.BEE_ELEV_HORIZ] = 'media/' + horiz_vid + '.bik'

        # Create the video script
        vmf.create_ent(
            classname='logic_script',
            targetname='@video_splitter',
            vscripts=script,
            origin=inst['origin'],
        )


def get_map_info(vmf: VMF) -> Set[str]:
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

    for item in vmf.by_class['func_instance']:
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
    inst: Entity,
    resolve_name: str,
    pretty_name: str,
    elev_override: bool = False,
    override_corr: int = -1,
    is_exit: bool = False,
) -> str:
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
        return '0'  # There aren't any variants (coop spawn room)

    if override_corr == 0:
        index = files.index(inst['file'].casefold())
        inst.fixup[consts.FixupVars.BEE_CORR_INDEX] = index + 1
        LOGGER.info(
            'Using random {} ({})',
            pretty_name,
            index + 1,
        )
        return str(index)
    else:
        LOGGER.info(
            'Setting {} to {}',
            pretty_name,
            override_corr,
        )
        inst.fixup[consts.FixupVars.BEE_CORR_INDEX] = override_corr
        inst['file'] = files[override_corr - 1]
        return str(override_corr - 1)


def mod_doorframe(inst: Entity, corr_id, corr_type, corr_name):
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


def calc_rand_seed(vmf: VMF) -> str:
    """Use the ambient light entities to create a map seed.

     This ensures textures remain the same when the map is recompiled.
    """
    amb_light = instanceLocs.resolve('<ITEM_POINT_LIGHT>')
    lst = [
        inst['targetname'] or '-'  # If no targ
        for inst in
        vmf.by_class['func_instance']
        if inst['file'].casefold() in amb_light
        ]
    if len(lst) == 0:
        # Very small maps won't have any ambient light entities at all.
        return 'SEED'
    else:
        return '|'.join(lst)


def add_goo_mist(vmf, sides: Iterable[Vec_tuple]):
    """Add water_mist* particle systems to goo.

    This uses larger particles when needed to save ents.
    """
    needs_mist = set(sides)  # Locations that still need mist
    ordered_sides = sorted(sides)
    fit_goo_mist(
        vmf, ordered_sides, needs_mist,
        grid_x=1024,
        grid_y=512,
        particle='water_mist_1024_512',
    )

    fit_goo_mist(
        vmf, ordered_sides, needs_mist,
        grid_x=512,
        grid_y=1024,
        particle='water_mist_1024_512',
        angles='0 90 0',
    )

    fit_goo_mist(
        vmf, ordered_sides, needs_mist,
        grid_x=512,
        grid_y=512,
        particle='water_mist_512',
    )

    fit_goo_mist(
        vmf, sides, needs_mist,
        grid_x=256,
        grid_y=256,
        particle='water_mist_256',
    )

    # There isn't a 128 particle so use 256 centered
    fit_goo_mist(
        vmf, ordered_sides, needs_mist,
        grid_x=128,
        grid_y=128,
        particle='water_mist_256',
    )


def fit_goo_mist(
    vmf: VMF,
    sides: Iterable[Vec_tuple],
    needs_mist: Set[Vec_tuple],
    grid_x: int,
    grid_y: int,
    particle: str,
    angles: str = '0 0 0',
) -> None:
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
            vmf.create_ent(
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


@conditions.meta_cond(priority=-50)
def set_barrier_frame_type(vmf: VMF) -> None:
    """Set a $type instvar on glass frame.

    This allows using different instances on glass and grating.
    """
    barrier_types = {}  # origin, normal -> 'glass' / 'grating'
    barrier_pos: List[Tuple[Vec, str]] = []

    # Find glass and grating brushes..
    for brush in vmf.iter_wbrushes(world=False, detail=True):
        for side in brush:
            if side.mat == consts.Special.GLASS:
                break
        else:
            # Not glass..
            continue
        barrier_pos.append((brush.get_origin(), 'glass'))

    for brush_ent in vmf.by_class['func_brush']:
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
    for inst in vmf.by_class['func_instance']:
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


def change_brush(vmf: VMF) -> None:
    """Alter all world/detail brush textures to use the configured ones."""
    LOGGER.info("Editing Brushes...")

    goo_scale = options.get(float, 'goo_scale')

    # Goo mist must be enabled by both the style and the user.
    make_goo_mist = options.get(bool, 'goo_mist') and srctools.conv_bool(
        settings['style_vars'].get('AllowGooMist', '1')
    )
    mist_solids = set()

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

    for solid in vmf.iter_wbrushes(world=True, detail=True):
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
                face.mat = texturing.SPECIAL.get(
                    face.get_origin(), (
                        'goo' if
                        face.planes[0].z == best_goo
                        else 'goo_cheap'
                    ),
                )

    if make_bottomless:
        LOGGER.info('Creating Bottomless Pits...')
        bottomlessPit.make_bottomless_pit(vmf, highest_brush)
        LOGGER.info('Done!')

    if make_goo_mist:
        LOGGER.info('Adding Goo Mist...')
        add_goo_mist(vmf, mist_solids)
        LOGGER.info('Done!')


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


def change_overlays(vmf: VMF) -> None:
    """Alter the overlays."""
    LOGGER.info("Editing Overlays...")

    # A frame instance to add around all the 32x32 signs
    sign_inst = options.get(str, 'signInst')
    # Resize the signs to this size. 4 vertexes are saved relative
    # to the origin, so we must divide by 2.
    sign_size = options.get(int, 'signSize') / 2

    # A packlist associated with the sign_inst.
    sign_inst_pack = options.get(str, 'signPack')

    # Grab all the textures we're using...
    for over in vmf.by_class['info_overlay']:
        if over in IGNORED_OVERLAYS:
            # Overlays added by us, or conditions. These are styled already,
            # don't touch them.
            continue

        if (over['targetname'] == 'exitdoor_stickman' or
                over['targetname'] == 'exitdoor_arrow'):
            if options.get(bool, "remove_exit_signs"):
                # Some styles have instance-based ones, remove the
                # originals if needed to ensure it looks nice.
                over.remove()
                continue  # Break out, to make sure the instance isn't added
            else:
                # blank the targetname, so we don't get the
                # useless info_overlay_accessors for these signs.
                del over['targetname']

        case_mat = over['material'].casefold()

        try:
            sign_type = consts.Signage(case_mat)
        except ValueError:
            continue

        if sign_inst is not None:
            new_inst = vmf.create_ent(
                classname='func_instance',
                origin=over['origin'],
                angles=over['angles', '0 0 0'],
                file=sign_inst,
            )
            if sign_inst_pack:
                packing.pack_list(vmf, sign_inst_pack)
            new_inst.fixup['mat'] = sign_type.name.lower()

        # Delete the overlay's targetname - signs aren't ever dynamic.
        # This also means items set to signage only won't get toggle
        # instances.
        del over['targetname']

        over['material'] = texturing.OVERLAYS.get(over.get_origin(), sign_type)
        if sign_size != 16:
            # Resize the signage overlays
            # These are the 4 vertex locations
            # Each axis is set to -16, 16 or 0 by default
            for prop in ('uv0', 'uv1', 'uv2', 'uv3'):
                val = Vec.from_str(over[prop])
                val /= 16
                val *= sign_size
                over[prop] = val.join(' ')


def add_extra_ents(vmf: VMF, game_mode: str) -> None:
    """Add the various extra instances to the map."""
    loc = options.get(Vec, 'global_ents_loc')

    music.add(
        vmf,
        loc,
        settings['music_conf'],
        settings['has_attr'],
        game_mode == 'SP',
    )

    LOGGER.info('Adding global ents...')

    # Add the global_pti_ents instance automatically, with disable_pti_audio
    # set.
    global_ents_pos = options.get(Vec, 'global_ents_loc')
    pti_file = options.get(str, 'global_pti_ents')
    pti_loc = options.get(Vec, 'global_pti_ents_loc')

    # Add a nodraw box around the global entity location, to seal it.
    vmf.add_brushes(vmf.make_hollow(
        global_ents_pos + (128, 128, 128),
        global_ents_pos - (128, 128, 64),
    ))

    # Add a cubemap into the map, so materials get a blank one generated.
    # If none are present this doesn't happen...
    vmf.create_ent(
        classname='env_cubemap',
        cubemapsize=1,  # Make as small as possible..
        origin=global_ents_pos,
    )

    # So we have one in the map.
    vmf.create_ent(
        classname='info_node',
        origin=global_ents_pos - (0, 0, 64),
        nodeid=1,
        spawnflags=0,
        angles='0 0 0',
    )

    if settings['has_attr']['bridge'] or settings['has_attr']['lightbridge']:
        # If we have light bridges, make sure we precache the particle.
        vmf.create_ent(
            classname='info_particle_system',
            origin=global_ents_pos,
            effect_name='projected_wall_impact',
            start_active=0,
        )

    if pti_file:
        LOGGER.info('Adding Global PTI Ents')
        global_pti_ents = vmf.create_ent(
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

        global_pti_ents.fixup['glados_script'] = 'choreo/glados.nut'  # Implements Multiverse Cave..


def change_ents(vmf: VMF) -> None:
    """Edit misc entities."""
    LOGGER.info("Editing Other Entities...")
    if options.get(bool, "remove_info_lighting"):
        # Styles with brush-based glass edges don't need the info_lighting,
        # delete it to save ents.
        for ent in vmf.by_class['info_lighting']:
            ent.remove()
    for auto in vmf.by_class['logic_auto']:
        # Remove all the logic_autos that set attachments, we can
        # replicate this in the instance
        for out in auto.outputs:
            if 'panel_top' in out.target:
                vmf.remove_ent(auto)


def fix_worldspawn(vmf: VMF) -> None:
    """Adjust some properties on WorldSpawn."""
    LOGGER.info("Editing WorldSpawn")
    if vmf.spawn['paintinmap'] != '1':
        # If PeTI thinks there should be paint, don't touch it
        # Otherwise set it based on the 'gel' voice attribute
        # If the game is Aperture Tag, it's always forced on
        vmf.spawn['paintinmap'] = srctools.bool_as_int(
            settings['has_attr']['gel'] or
            options.get(str, 'game_id') == utils.STEAM_IDS['APTAG']
        )
    vmf.spawn['skyname'] = options.get(str, 'skybox')


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
        conf['screenshot_type'] = BEE2_config.get_val(
            'Screenshot', 'type', 'PETI'
        ).upper()
        conf['clean_screenshots'] = srctools.bool_as_int(
            BEE2_config.get_bool('Screenshot', 'del_old')
        )
        conf['is_preview'] = srctools.bool_as_int(
            IS_PREVIEW
        )
        conf['game_id'] = options.get(str, 'game_id')

        if BEE2_config.get_bool('General', 'packfile_dump_enable'):
            conf['packfile_dump'] = BEE2_config.get_val(
                'General',
                'packfile_dump_dir',
                ''
            )

        # This generates scripts and might need to tell VRAD.
        cubes.write_vscripts(conf)

    with open('bee2/vrad_config.cfg', 'w', encoding='utf8') as f:
        for line in conf.export():
            f.write(line)


def instance_symlink() -> None:
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


def save(vmf: VMF, path: str) -> None:
    """Save the modified map back to the correct location.
    """
    LOGGER.info("Saving New Map...")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with AtomicWriter(path) as f:
        vmf.export(dest_file=f, inc_version=True)
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
    global MAP_RAND_SEED
    LOGGER.info("BEE{} VBSP hook initiallised.", utils.BEE_VERSION)

    conditions.import_conditions()  # Import all the conditions and
    # register them.

    if 'BEE2_WIKI_OPT_LOC' in os.environ:
        # Special override - generate docs for the BEE2 wiki.
        LOGGER.info('Writing Wiki text...')
        with open(os.environ['BEE2_WIKI_OPT_LOC'], 'w') as f:
            options.dump_info(f)
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

        vmf = load_map(path)
        instance_traits.set_traits(vmf)

        ant, side_to_antline = antlines.parse_antlines(vmf)

        # Requires instance traits!
        connections.calc_connections(
            vmf,
            ant,
            texturing.OVERLAYS.get_all('shapeframe'),
            settings['style_vars']['enableshapesignageframe'],
            antline_wall=ant_wall,
            antline_floor=ant_floor,
        )

        MAP_RAND_SEED = calc_rand_seed(vmf)

        all_inst = get_map_info(vmf)

        brushLoc.POS.read_from_map(vmf, settings['has_attr'])

        fizzler.parse_map(vmf, settings['has_attr'])
        barriers.parse_map(vmf, settings['has_attr'])

        conditions.init(
            seed=MAP_RAND_SEED,
            inst_list=all_inst,
            vmf_file=vmf,
        )

        tiling.gen_tile_temp()
        tiling.analyse_map(vmf, side_to_antline)

        del side_to_antline

        texturing.setup(vmf, MAP_RAND_SEED, list(tiling.TILES.values()))

        conditions.check_all(vmf)
        add_extra_ents(vmf, GAME_MODE)

        change_ents(vmf)
        tiling.generate_brushes(vmf)
        faithplate.gen_faithplates(vmf)
        change_overlays(vmf)
        barriers.make_barriers(vmf)
        fix_worldspawn(vmf)

        # Ensure all VMF outputs use the correct separator.
        for ent in vmf.entities:
            for out in ent.outputs:
                out.comma_sep = False

        save(vmf, new_path)
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
