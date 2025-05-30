"""Implements the BEE2 VBSP compiler replacement."""
from typing import Any, NamedTuple, TypedDict
from collections.abc import Iterable
from collections import defaultdict, Counter
from operator import itemgetter
from io import StringIO
import os
import sys
import shutil
import logging
import pickle


from aioresult import ResultCapture
from srctools import AtomicWriter, Keyvalues, Vec, FrozenVec, Angle
from srctools.dmx import Element
from srctools.game import Game
from srctools.vmf import VMF, Entity, Output
import async_util
import attrs
import srctools
import srctools.logger
import srctools.run
import trio

from BEE2_config import ConfigFile
import utils
from precomp.collisions import Collisions
from quote_pack import QuoteInfo
from precomp import (
    instance_traits,
    brushLoc,
    bottomlessPit,
    instanceLocs,
    corridor,
    template_brush,
    texturing,
    tiling,
    tiling_gen,
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
    rand,
    cubes,
    errors,
)
import config
import consts
import editoritems
import user_errors


LOGGER = srctools.logger.get_logger()


class _Settings(TypedDict):
    """Configuration data extracted from VBSP_config. TODO: Eliminate and make local vars."""
    textures: dict[str, Any]
    fog: dict[str, Any]
    elevator: dict[str, str]
    music_conf: Keyvalues

    style_vars: dict[str, bool]


settings: _Settings = {
    "textures":       {},
    "fog":            {},
    "elevator":       {},
    'music_conf':     Keyvalues('', []),

    "style_vars":     defaultdict(bool),
}

COND_MOD_NAME = 'VBSP'
BEE2_config = ConfigFile('compile.cfg')

# These are overlays which have been modified by
# conditions, and shouldn't be restyled or modified later.
IGNORED_OVERLAYS: set[Entity] = set()


async def load_settings() -> tuple[
    antlines.IndicatorStyle,
    dict[utils.ObjectID, editoritems.Item],
    corridor.ExportedConf,
]:
    """Load in all our settings from vbsp_config."""
    # Do all our file parsing concurrently.
    def load_pickle(filename: str) -> object:
        """Open then load a pickle file. Typed as object to force manual checks below."""
        with open(filename, 'rb') as f:
            return pickle.load(f)

    def load_keyvalues(filename: str) -> Keyvalues:
        """Open then load a keyvalues1 file."""
        with open(filename, encoding='utf8') as f:
            return Keyvalues.parse(f, filename)

    def load_dmx_config(filename: str) -> config.Config:
        """Load our main DMX config."""
        with open(filename, 'rb') as f:
            dmx, fmt_name, fmt_ver = Element.parse(f)
        conf, upgrade, extra = config.COMPILER.parse_dmx(dmx, fmt_name, fmt_ver)
        # We're never changing the file, no point upgrading it. The app will do so next
        # export anyway. The parse function has already logged, so we can ignore those.
        return conf

    try:
        async with trio.open_nursery() as nursery:
            res_vconf = async_util.sync_result(nursery, load_keyvalues, "bee2/vbsp_config.cfg")
            res_packlist = async_util.sync_result(nursery, load_keyvalues, 'bee2/pack_list.cfg')
            res_editor = async_util.sync_result(nursery, load_pickle, 'bee2/editor.bin')
            res_corr = async_util.sync_result(nursery, load_pickle, 'bee2/corridors.bin')
            res_dmx_conf = async_util.sync_result(nursery, load_dmx_config, 'bee2/config.dmx')
            # Load in templates locations.
            nursery.start_soon(template_brush.load_templates, 'bee2/templates.lst')
    except* OSError:
        LOGGER.exception(
            'Failed to parse required config file. Recompile the compiler '
            'and/or export the palette.'
            if utils.DEV_MODE else
            'Failed to parse required config file. Re-export BEE2.'
        )
        sys.exit(1)

    vconf = res_vconf.result()
    tex_block = Keyvalues('Textures', list(vconf.find_children('textures')))

    texturing.load_config(tex_block)

    # Load in our main configs...
    options.load(vconf.find_all('Options'))
    config.COMPILER.merge_conf(res_dmx_conf.result())
    utils.DEV_MODE = options.DEV_MODE()

    # Configuration properties for styles.
    for stylevar_block in vconf.find_all('stylevars'):
        for var in stylevar_block:
            settings['style_vars'][var.name.casefold()] = srctools.conv_bool(var.value)

    # Load out a copy of the item configuration, checking types as we go.
    # The pickle could have produced anything.
    id_to_item: dict[utils.ObjectID, editoritems.Item] = {}

    editor_list = res_editor.result()
    if not isinstance(editor_list, list):
        raise ValueError(f'Invalid list of editor items, got: {editor_list!r}')
    for item in editor_list:
        if isinstance(item, editoritems.Item):
            id_to_item[item.id] = item
        else:
            raise ValueError(f'Invalid editor item, got: {item!r}')

    # Send that data to the relevant modules.
    instanceLocs.load_conf(id_to_item.values())
    connections.read_configs(id_to_item.values())

    # Antline texturing settings.
    indicators = antlines.IndicatorStyle.parse(
        # Collect all blocks, since they may be in separate blocks for antlines/checkmarks/timers.
        Keyvalues('Antlines', list(tex_block.find_children('antlines'))),
        'the main antline configuration',
        antlines.IndicatorStyle.from_legacy(id_to_item),
    )
    if indicators.toggle_var:
        LOGGER.warning('A custom toggle var is nonsensical on the default antline definition. Removing.')
        indicators = attrs.evolve(indicators, toggle_var='')

    # Parse packlist data.
    packing.parse_packlists(res_packlist.result())

    # Parse all the conditions.
    for cond in vconf.find_all('conditions', 'condition'):
        conditions.add(cond)

    cubes.parse_conf(vconf)
    fizzler.read_configs(vconf)
    barriers.parse_conf(vconf)

    # Selected corridors.
    corridor_conf = res_corr.result()
    if not isinstance(corridor_conf, corridor.ExportedConf):
        raise ValueError(f'Invalid corridor config, got {corridor_conf!r}')

    # Signage items
    from precomp.conditions.signage import load_signs
    load_signs(vconf)

    # Get configuration for the elevator, defaulting to ''.
    elev = vconf.find_block('elevator', or_blank=True)
    settings['elevator'] = {
        key: elev[key, '']
        for key in
        (
            'type', 'horiz', 'vert',
            'scr_rand', 'scr_force', 'scr_bsod',
        )
    }

    settings['music_conf'] = vconf.find_block('MusicScript', or_blank=True)

    # Bottomless pit configuration
    bottomlessPit.load_settings(vconf.find_block("bottomless_pit", or_blank=True))

    # Fog settings - from the skybox (env_fog_controller, env_tonemap_controller)
    fog_config = vconf.find_block("fog", or_blank=True)
    # Update inplace so imports get the settings
    settings['fog'].update({
        # These defaults are from Clean Style.
        'start': fog_config['start', '128'],
        'end': fog_config['end', '5000'],
        'density': fog_config['density', '0.95'],
        'primary': fog_config['primaryColor', '40 53 64'],
        'secondary': fog_config['secondaryColor', ''],
        'direction': fog_config['direction', '0 0 0'],
        # These appear to be always the same.
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
    return indicators, id_to_item, corridor_conf


def load_map(map_path: str) -> VMF:
    """Load in the VMF file."""
    with open(map_path, encoding='utf8') as file:
        LOGGER.info("Parsing Map...")
        kv = Keyvalues.parse(file, map_path)
    LOGGER.info('Reading Map...')
    vmf = VMF.parse(kv)
    LOGGER.info("Loading complete!")
    return vmf


@conditions.MetaCond.VoiceLine.register
def add_voice(vmf: VMF, coll: Collisions, info: corridor.Info, voice: QuoteInfo) -> None:
    """Add voice lines to the map."""
    voice_line.add_voice(
        style_vars=settings['style_vars'],
        coll=coll,
        vmf=vmf,
        info=info,
        voice=voice,
        use_priority=BEE2_config.get_bool('General', 'voiceline_priority', False),
    )


FIZZ_BUMPER_WIDTH = 32  # The width of bumper brushes
FIZZ_NOPORTAL_WIDTH = 16  # Width of noportal_volumes


@conditions.MetaCond.AntiFizzBump.register
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
            fizz_name = fizz_name.removesuffix('_brush') + '-br_brush'

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


@conditions.MetaCond.PlayerModel.register
def set_player_model(vmf: VMF, info: corridor.Info) -> None:
    """Set the player model in SinglePlayer."""

    # Add the model changer instance.
    # We don't change the player model in Coop, or if Bendy is selected.

    if info.is_coop:  # Not in coop..
        return

    loc = options.GLOBAL_ENTS_LOC()
    assert loc is not None
    model_id = BEE2_config.get_val(
        'General', 'player_model_id',
        consts.DEFAULT_PLAYER,
    )
    try:
        chosen_model = utils.obj_id(model_id)
    except ValueError:
        LOGGER.warning('Invalid player model ID "{}"!', model_id)
        return

    if chosen_model == consts.DEFAULT_PLAYER:
        # The default model..
        return

    try:
        player = config.COMPILER.get_cur_conf(config.player.ExportPlayer, chosen_model, LookupError)
    except LookupError:
        LOGGER.warning('Unknown player model ID "{}"!', chosen_model)
        return

    # Precache the model, so we can switch to it.
    vmf.create_ent(
        classname='comp_precache_model',
        origin=loc,
        model=f'models/{player.model}.mdl',
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
        f'setmodel {player.model}',
        delay=0.1,
    ))

    # We need to redo this whenever a saved game is loaded..
    auto.add_out(Output(
        'OnLoadGame',
        '@command',
        'Command',
        f'setmodel {player.model}',
        delay=0.1,
    ))

    if player.pgun_skin and options.GAME_ID() == utils.STEAM_IDS['PORTAL2']:
        # Only change portalgun skins in Portal 2 - this is the vanilla
        # portalgun weapon/viewmodel.
        auto.add_out(Output(
            'OnMapSpawn',
            'viewmodel',  # Classname of the viewmodel.
            'Skin',
            player.pgun_skin,
            delay=0.1,
        ))
        auto.add_out(Output(
            'OnMapSpawn',
            # Classname of the portalgun.
            # This will also change pedestals and the like,
            # but that's fine.
            'weapon_portalgun',
            'Skin',
            player.pgun_skin,
            delay=0,
        ))


@conditions.MetaCond.PlayerPortalGun.register
def set_player_portalgun(vmf: VMF, info: corridor.Info) -> None:
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

    if options.GAME_ID() == utils.STEAM_IDS['TAG']:
        return  # Aperture Tag doesn't have Portal Guns!

    LOGGER.info('Setting Portalgun:')

    blue_portal = not info.has_attr('blueportal')
    oran_portal = not info.has_attr('orangeportal')
    has_btn_onoff = info.has_attr('portalgunonoff')
    force_portal_man = has_btn_onoff or info.has_attr('needsportalman')

    LOGGER.info(
        'Blue: {}, Orange: {}, On/Off: {}, Portal Manager: {}',
        'Y' if blue_portal else 'N',
        'Y' if oran_portal else 'N',
        'Y' if has_btn_onoff else 'N',
        'Y' if force_portal_man else 'N',
    )

    if blue_portal and oran_portal:
        info.set_attr('spawn_dual')
    elif blue_portal or oran_portal:
        info.set_attr('spawn_single')
    else:
        info.set_attr('spawn_nogun')

    ent_pos = options.GLOBAL_PTI_ENTS_LOC()
    assert ent_pos is not None

    logic_auto = vmf.create_ent('logic_auto', origin=ent_pos, flags='1')

    if not blue_portal or not oran_portal or force_portal_man:
        pgun_script = vmf.create_ent(
            classname='point_template',
            targetname='@portalgun',
            vscripts='bee2/portal_man.nut',
            origin=ent_pos,
        )

        if info.is_sp:
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
        port_ids: Iterable[int]
        if info.is_coop:
            port_ids = (0, 1, 2)
        else:
            port_ids = (0, )

        for port_id in port_ids:
            trigger_portal = vmf.create_ent(
                targetname=f'__pgun_port_detect_{port_id}',
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
                    f'__pgun_port_id <- {port_id}; '
                    '__pgun_active <- 1'
                ),
                Output(
                    'OnStartTouchPortal2',
                    '!activator',
                    'RunScriptCode',
                    '__pgun_is_oran <- 1; '
                    f'__pgun_port_id <- {port_id}; '
                    '__pgun_active <- 1'
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

        if info.is_sp:
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


@conditions.MetaCond.Screenshot.register
def add_screenshot_logic(vmf: VMF, info: corridor.Info) -> None:
    """If the screenshot type is 'auto', add in the needed ents."""
    if BEE2_config.get_val(
        'Screenshot', 'type', 'PETI'
    ).upper() == 'AUTO' and info.is_preview:
        SSHOT_FNAME = 'instances/bee2/logic/screenshot_logic.vmf'
        vmf.create_ent(
            classname='func_instance',
            file=SSHOT_FNAME,
            origin=options.GLOBAL_ENTS_LOC(),
            angles='0 0 0',
        )
        conditions.ALL_INST.add(SSHOT_FNAME)
        LOGGER.info('Added Screenshot Logic')


@conditions.MetaCond.FogEnts.register
def add_fog_ents(vmf: VMF, info: corridor.Info) -> None:
    """Add the tonemap and fog controllers, based on the skybox."""
    pos = options.GLOBAL_ENTS_LOC()
    vmf.create_ent(
        classname='env_tonemap_controller',
        targetname='@tonemapper',
        origin=pos + (-16, 0, 0),
    )

    fog_opt = settings['fog']

    rng = rand.seed(b'shadow_angle')
    vmf.create_ent(
        classname='shadow_control',
        # Slight variations around downward direction.
        angles=Angle(rng.randrange(85, 90), rng.randrange(0, 360), 0),
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

    logic_auto = vmf.create_ent(classname='logic_auto', origin=pos, flags='0')

    logic_auto.add_out(
        Output(
            'OnMapSpawn',
            '@clientcommand',
            'Command',
            'r_flashlightbrightness 3',
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

    if info.is_sp:
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

    if options.SKY_DRAW_FIRST():
        logic_auto.add_out(Output(
            'OnMapSpawn',
            '@broadcastcommand',
            'Command',
            'r_skybox_draw_last 0',
        ), Output(
            'OnLoadGame',
            '@broadcastcommand',
            'Command',
            'r_skybox_draw_last 0',
        ))


@conditions.MetaCond.ElevatorVideos.register
def set_elev_videos(vmf: VMF, info: corridor.Info) -> None:
    """Add the scripts and options for customisable elevator videos to the map."""
    vid_type = settings['elevator']['type'].casefold()

    LOGGER.info('Elevator type: {}', vid_type.upper())

    if vid_type == 'none' or info.is_coop:
        # No elevator exists!
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
        LOGGER.warning('Invalid elevator video type: {!r}', vid_type)
        return

    transition_ents = instanceLocs.resolve_filter('[transitionents]')
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


def add_goo_mist(vmf: VMF, sides: Iterable[FrozenVec]) -> None:
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
    sides: Iterable[FrozenVec],
    needs_mist: set[FrozenVec],
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
            if (pos + (x, y, 0.0)) not in needs_mist:
                break  # Doesn't match
        else:
            vmf.create_ent(
                classname='info_particle_system',
                targetname='@goo_mist',
                start_active='1',
                effect_name=particle,
                origin=pos.thaw() + (grid_x/2 - 64, grid_y/2 - 64, 48.0),
                angles=angles,
            )
            for (x, y) in utils.iter_grid(grid_x, grid_y, stride=128):
                needs_mist.remove(pos + (x, y, 0.0))


def change_brush(vmf: VMF) -> None:
    """Alter all world/detail brush textures to use the configured ones."""
    LOGGER.info("Editing Brushes...")

    goo_scale = options.GOO_SCALE()

    # Goo mist must be enabled by both the style and the user.
    make_goo_mist = options.GOO_MIST() and srctools.conv_bool(
        settings['style_vars'].get('AllowGooMist', '1')
    )
    mist_solids: set[FrozenVec] = set()

    make_bottomless = bottomlessPit.pits_allowed()
    LOGGER.info('Make Bottomless Pit: {}', make_bottomless)

    highest_brush = 0.0

    # Calculate the z-level with the largest number of goo brushes,
    # so we can ensure the 'fancy' pit is the largest one.
    # Valve just does it semi-randomly.
    goo_heights: Counter[float] = Counter()
    for pos, block in brushLoc.POS.items():
        if block.is_goo and block.is_top:
            # Block position is the center,
            # save at the height of the top face
            goo_heights[brushLoc.g2w(pos).z + 32] += 1
    # Find key with the highest value = z-level with highest brush.
    try:
        best_goo = max(goo_heights.items(), key=itemgetter(1))[0]
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
                    mist_solids.add(solid.get_origin().freeze())
                # Apply goo scaling
                face.scale = goo_scale
                # Use fancy goo on the level with the
                # highest number of blocks.
                # All plane z are the same.
                texturing.SPECIAL.get(
                    face.get_origin(), (
                        'goo' if
                        face.planes[0].z == best_goo
                        else 'goo_cheap'
                    ),
                ).apply(face)

    if make_bottomless:
        LOGGER.info('Creating Bottomless Pits...')
        bottomlessPit.make_bottomless_pit(vmf, highest_brush)
        LOGGER.info('Done!')

    if make_goo_mist:
        LOGGER.info('Adding Goo Mist...')
        add_goo_mist(vmf, mist_solids)
        LOGGER.info('Done!')


class Clump(NamedTuple):
    """Additional clumps set by conditions. TODO: Not functional."""
    min_pos: Vec
    max_pos: Vec
    tex: dict[str, str]


PRESET_CLUMPS: list[Clump] = []


@conditions.make_result('SetAreaTex')
def cond_force_clump(res: Keyvalues) -> conditions.ResultCallable:
    """Force an area to use certain textures.

    This only works in styles using the clumping texture algorithm.
    """
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

    def set_tex(inst: Entity) -> None:
        """Store off the new textures."""
        origin = Vec.from_str(inst['origin'])
        angles = Angle.from_str(inst['angles'])

        min_pos, max_pos = Vec.bbox(point1 @ angles + origin, point2 @ angles + origin)

        PRESET_CLUMPS.append(Clump(
            min_pos,
            max_pos,
            tex_data
        ))
    return set_tex


@conditions.MetaCond.ExitSigns.register
def position_exit_signs(vmf: VMF) -> None:
    """Configure exit signage.

    If "remove_exit_signs" is set, then delete them. Otherwise, if "signExitInst"
    is set, overlay the specified instance on top of the sign pair.
    """
    exit_sign: Entity | None
    exit_arrow: Entity | None
    try:
        [exit_sign] = vmf.by_target['exitdoor_stickman']
    except ValueError:
        exit_sign = None
    try:
        [exit_arrow] = vmf.by_target['exitdoor_arrow']
    except ValueError:
        exit_arrow = None

    # If turned off, user requested removal of signs entirely.
    enable_signs = options.get_itemconf(('VALVE_MANDATORY', 'ExitSignage'), True)

    if not enable_signs or options.REMOVE_EXIT_SIGNS():
        if exit_sign is not None:
            exit_sign.remove()
        if exit_arrow is not None:
            exit_arrow.remove()

    inst_filename = options.SIGN_EXIT_INST()
    if not enable_signs or inst_filename is None or exit_sign is None or exit_arrow is None:
        return

    sign_pos = Vec.from_str(exit_sign['origin'])
    arrow_pos = Vec.from_str(exit_arrow['origin'])
    arrow_norm = Vec.from_str(exit_arrow['basisnormal'])
    sign_norm = Vec.from_str(exit_sign['basisnormal'])
    offset = arrow_pos - sign_pos

    if round(offset.mag()) != 32 or arrow_norm != sign_norm:
        LOGGER.warning('Exit sign overlays are not aligned!')
        return

    arrow_dir = -Vec.from_str(exit_arrow['basisv'])  # Texture points down.
    u = Vec.from_str(exit_sign['basisu'])
    v = Vec.from_str(exit_sign['basisv'])
    angles = Angle.from_basis(x=u, y=v, z=sign_norm)

    if arrow_dir == u:
        sign_dir = 'east'
    elif arrow_dir == v:
        sign_dir = 'north'
    elif arrow_dir == -u:
        sign_dir = 'west'
    elif arrow_dir == -v:
        sign_dir = 'south'
    else:
        LOGGER.warning(
            'Could not match exit sign norm of ({}) to u=({}), v=({})',
            arrow_dir, u, v,
        )
        return
    if abs(Vec.dot(offset, u)) > 0.5:
        orient = 'horizontal'
    elif abs(Vec.dot(offset, v)) > 0.5:
        orient = 'vertical'
    else:
        LOGGER.warning('Exit signs stacked on each other????')
        return

    inst = vmf.create_ent(
        'func_instance',
        targetname='exitdoor_sign',
        origin=round((sign_pos + arrow_pos) / 2, 0),  # Center
        angles=angles,
        file=inst_filename,
        fixup_style='0',  # Prefix
    )
    conditions.ALL_INST.add(inst_filename.casefold())
    inst.fixup['$arrow'] = sign_dir
    inst.fixup['$orient'] = orient
    if options.REMOVE_EXIT_SIGNS_DUAL():
        exit_sign.remove()
        exit_arrow.remove()
    else:
        # Indicate the singular instances shouldn't be placed.
        exit_sign['bee_noframe'] = exit_arrow['bee_noframe'] = '1'


def change_overlays(vmf: VMF) -> None:
    """Alter the overlays."""
    LOGGER.info("Editing Overlays...")

    # A frame instance to add around all the 32x32 signs
    sign_inst = options.SIGN_INST()
    # Resize the signs to this size. 4 vertexes are saved relative
    # to the origin, so we must divide by 2.
    sign_size = options.SIGN_SIZE() / 2

    # A packlist associated with the sign_inst.
    sign_inst_pack = options.SIGN_PACK()

    # Grab all the textures we're using...
    for over in vmf.by_class['info_overlay']:
        if over in IGNORED_OVERLAYS:
            # Overlays added by us, or conditions. These are styled already,
            # don't touch them.
            continue

        try:
            sign_type = consts.Signage(over['material'].casefold())
        except ValueError:
            continue

        if sign_inst is not None and 'bee_noframe' not in over:
            new_inst = vmf.create_ent(
                classname='func_instance',
                origin=over['origin'],
                angles=over['angles', '0 0 0'],
                file=sign_inst,
            )
            conditions.ALL_INST.add(sign_inst.casefold())
            if sign_inst_pack:
                packing.pack_list(vmf, sign_inst_pack)
            new_inst.fixup['mat'] = sign_type.name.lower()

        # Delete the overlay's targetname - signs aren't ever dynamic.
        # This also means items set to signage only won't get toggle
        # instances.
        del over['targetname']
        del over['bee_noframe']  # Not needed anymore.

        texturing.OVERLAYS.get(over.get_origin(), sign_type).apply_over(over)
        if not over['material']:
            over.remove()
        if sign_size != 16:
            # Resize the signage overlays
            # These are the 4 vertex locations
            # Each axis is set to -16, 16 or 0 by default
            for key in ('uv0', 'uv1', 'uv2', 'uv3'):
                val = Vec.from_str(over[key])
                val /= 16
                val *= sign_size
                over[key] = val.join(' ')


def add_extra_ents(vmf: VMF, info: corridor.Info) -> None:
    """Add the various extra instances to the map."""
    LOGGER.info('Adding global ents...')

    global_ents_pos = options.GLOBAL_ENTS_LOC()
    pti_file = options.GLOBAL_PTI_ENTS()
    pti_loc = options.GLOBAL_PTI_ENTS_LOC()

    # Add a nodraw box around the global entity location, to seal it.
    vmf.add_brushes(vmf.make_hollow(
        global_ents_pos + (128, 128, 128),
        global_ents_pos - (128, 128, 64),
    ))

    # Add a cubemap into the map, so materials get a blank one generated.
    # If none are present this doesn't happen...
    vmf.create_ent(
        classname='env_cubemap',
        cubemapsize=1,  # Make as small as possible.
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

    music.add(vmf, global_ents_pos, settings['music_conf'], info)

    if info.has_attr('bridge') or info.has_attr('lightbridge'):
        # If we have light bridges, make sure we precache the particle.
        vmf.create_ent(
            classname='info_particle_system',
            origin=global_ents_pos,
            effect_name='projected_wall_impact',
            start_active=0,
        )

    if pti_file:
        # Add the global_pti_ents instance automatically, with disable_pti_audio set.
        LOGGER.info('Adding Global PTI Ents')
        global_pti_ents = vmf.create_ent(
            classname='func_instance',
            targetname='global_pti_ents',
            angles='0 0 0',
            origin=pti_loc,
            file=pti_file,
            fixup_style='0',
            )
        conditions.ALL_INST.add(pti_file.casefold())

        has_cave = srctools.conv_bool(
            settings['style_vars'].get('multiversecave', '1')
        )
        global_pti_ents.fixup['disable_pti_audio'] = not has_cave
        global_pti_ents.fixup['glados_script'] = 'choreo/glados.nut'  # Implements Multiverse Cave..


def change_ents(vmf: VMF) -> None:
    """Edit misc entities."""
    LOGGER.info("Editing Other Entities...")
    for auto in vmf.by_class['logic_auto']:
        # Remove all the logic_autos that set attachments, we can
        # replicate this in the instance
        for out in auto.outputs:
            if 'panel_top' in out.target:
                vmf.remove_ent(auto)


def write_itemid_list(vmf: VMF, used_items: Iterable[str]) -> None:
    """To aid debugging, include info about the items in the map."""
    # Number of keyvalues per ent to add.
    per_ent = 16

    used_item_list = sorted(used_items)
    LOGGER.debug('Used items: \n{}', '\n'.join(used_item_list))
    global_ents_loc = options.GLOBAL_ENTS_LOC()
    for offset in range(0, len(used_item_list), per_ent):
        lst_ent = vmf.create_ent(
            'bee2_item_list',
            origin=global_ents_loc,
        )
        for j, item_id in enumerate(used_item_list[offset:offset+per_ent]):
            lst_ent[f'itemid{j:02}'] = item_id


def fix_worldspawn(vmf: VMF, info: conditions.MapInfo) -> None:
    """Adjust some properties on WorldSpawn."""
    LOGGER.info("Editing WorldSpawn")
    if vmf.spawn['paintinmap'] != '1':
        # If PeTI thinks there should be paint, don't touch it
        # Otherwise set it based on the 'gel' voice attribute
        # If the game is Aperture Tag, it's always forced on
        vmf.spawn['paintinmap'] = (
            info.has_attr('gel') or
            options.GAME_ID() == utils.STEAM_IDS['APTAG']
        )
    vmf.spawn['skyname'] = options.SKYBOX()


async def find_missing_instances(game: Game, vmf: VMF) -> list[Vec]:
    """Go through the map, and check for missing instances.

    We don't raise an error immediately, because it could be possible that VBSP checks differently
    and can find them anyway. In that case just let it continue successfully.
    """
    missing: list[Vec] = []
    sdk_content = await trio.Path(game.path / '..' / 'sdk_content' / 'maps').absolute()

    async def check(inst: Entity) -> None:
        """See if this file exists."""
        filename = inst['file']
        if not await (sdk_content / filename).exists():
            missing.append(Vec.from_str(inst['origin']))

    async with trio.open_nursery() as nursery:
        for instance in vmf.by_class['func_instance']:
            nursery.start_soon(check, instance)

    return missing


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


def run_vbsp(
    vbsp_args: list[str],
    path: str,
    new_path: str | None = None,
    is_error_map: bool = False,
    maybe_missing_inst: Iterable[Vec] = (),
) -> None:
    """Execute the original VBSP, copying files around to make it work correctly.

    vbsp_args are the arguments to pass.
    path is the original .vmf, new_path is the styled/ name.
    If new_path is passed VBSP will be run on the map in styled/, and we'll
    read through the output to find the entity counts.
    """
    is_peti = new_path is not None

    # We can't overwrite the original vmf, so we run VBSP from a separate
    # location.
    if new_path is not None:
        # Copy the original log file
        if os.path.isfile(path.replace(".vmf", ".log")):
            shutil.copy(
                path.replace(".vmf", ".log"),
                new_path.replace(".vmf", ".log"),
            )

    # Remove blank args.
    vbsp_args = [x for x in vbsp_args if x and not x.isspace()]

    # Ensure we've fixed the instance/ folder so instances are found.
    if (utils.MAC or utils.LINUX) and is_peti:
        instance_symlink()

    # Use a special name for VBSP's output...
    vbsp_logger = srctools.logger.get_logger('valve.VBSP', alias='<Valve>')

    # And also save a copy for us to analyse.
    buff = StringIO()
    vbsp_logger.addHandler(logging.StreamHandler(buff))

    code = srctools.run.run_compiler(
        'linux32/vbsp' if utils.LINUX else 'vbsp',
        vbsp_args, vbsp_logger,
    )

    # Check for leaks!
    if new_path is not None and not is_error_map:
        pointfile = new_path.replace(".vmf", ".lin")
        LOGGER.info('Files present: {}', os.listdir(os.path.dirname(new_path)))
        if os.path.isfile(pointfile):  # We leaked!
            points = []
            with open(pointfile, encoding='ascii') as f:
                for line in f:
                    points.append(Vec.from_str(line.strip()))
            # Preserve this, rename to match the error map we generate.
            os.replace(pointfile, pointfile[:-4] + ".error.lin")
            raise errors.UserError(errors.TOK_VBSP_LEAK, leakpoints=points)

    if code != 0:
        # VBSP didn't succeed.
        if is_peti:  # Ignore Hammer maps
            process_vbsp_fail(buff.getvalue(), maybe_missing_inst)

        # Propagate the fail code to Portal 2, and quit.
        sys.exit(code)

    # Print output
    LOGGER.info("VBSP Done!")

    if new_path is not None:  # Ignore Hammer maps
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


def process_vbsp_fail(output: str, missing_locs: Iterable[Vec]) -> None:
    """Read through VBSP's logs when failing, to update counts."""
    # VBSP doesn't output the actual entity counts, so set the errorred
    # one to max and the others to zero.
    count_section = BEE2_config['Counts']

    count_section['max_brush'] = '8192'
    count_section['max_entity'] = '2048'
    count_section['max_overlay'] = '512'

    for line in reversed(output.splitlines()):
        if 'Could not open instance file' in line:
            filename = line.split('file', 1)[1].strip()
            raise user_errors.UserError(
                user_errors.TOK_VBSP_MISSING_INSTANCE.format(inst=filename),
                points=missing_locs,
            )
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


async def main(argv: list[str]) -> None:
    """Main program code.

    """
    LOGGER.info("BEE{} VBSP hook initiallised, srctools v{}.", utils.BEE_VERSION, srctools.__version__)
    await trio.lowlevel.checkpoint()

    # Warn if srctools Cython code isn't installed.
    utils.check_cython(LOGGER.warning)
    conditions.import_conditions()  # Import all the conditions and
    # register them.

    if 'BEE2_WIKI_OPT_LOC' in os.environ:
        # Special override - generate docs for the BEE2 wiki.
        LOGGER.info('Writing Wiki text...')
        async with trio.open_nursery() as nursery:
            nursery.start_soon(options.dump_info, trio.Path(os.environ['BEE2_WIKI_OPT_LOC']))
            nursery.start_soon(conditions.dump_conditions, trio.Path(os.environ['BEE2_WIKI_COND_LOC']))
        LOGGER.info('Done. Exiting now!')
        sys.exit()

    args = " ".join(argv)
    new_args = argv[1:]
    old_args = argv[1:]
    path = argv[-1]  # The path is the last argument to vbsp

    if not old_args:
        # No arguments!
        LOGGER.info(
            'No arguments!\n'
            "The BEE2 VBSP takes all the regular VBSP's "
            'arguments, with some extra arguments:\n'
            '-dump_conditions: Print a list of all condition tests,\n'
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
    game_dir = ''

    skip_vbsp = False
    for i, a in enumerate(new_args):
        # We need to strip these out, otherwise VBSP will get confused.
        if a == '-force_peti' or a == '-force_hammer':
            new_args[i] = ''
            old_args[i] = ''
        elif a == '-skip_vbsp':  # Debug command, for skipping.
            skip_vbsp = True
        # Strip the entity limit, and the following number
        elif a == '-entity_limit':
            new_args[i] = ''
            if len(new_args) > i+1 and new_args[i+1] == '1750':
                new_args[i+1] = ''
        elif a == '-game':
            game_dir = new_args[i+1]

    LOGGER.info('Map path is "{}"', path)
    LOGGER.info('New path: "{}"', new_path)
    if not path:
        raise Exception("No map passed!")
    if not game_dir:
        raise Exception("No game directory passed!")

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
        await trio.lowlevel.checkpoint()
        run_vbsp(
            vbsp_args=old_args,
            path=path,
        )
        return

    is_publishing = False
    vmf: VMF | None = None
    try:
        LOGGER.info("PeTI map detected!")

        LOGGER.info("Loading settings...")
        async with trio.open_nursery() as nursery:
            res_game = async_util.sync_result(nursery, Game, game_dir)
            res_settings = ResultCapture.start_soon(nursery, load_settings)
            vmf_res = async_util.sync_result(nursery, load_map, path)
            voice_data_res = ResultCapture.start_soon(nursery, voice_line.load)

        ind_style, id_to_item, corridor_conf = res_settings.result()
        vmf = vmf_res.result()

        coll = Collisions()

        used_inst = instance_traits.set_traits(vmf, id_to_item, coll)
        # Must be before corridors!
        initial_voice_attrs = brushLoc.POS.read_from_map(vmf, id_to_item)

        rand.init_seed(vmf)

        info = corridor.analyse_and_modify(
            vmf, corridor_conf,
            elev_override=BEE2_config.get_bool('General', 'spawn_elev'),
        )
        is_publishing = info.is_publishing
        info.set_attr(*initial_voice_attrs)

        ant, side_to_antline = antlines.parse_antlines(vmf)

        write_itemid_list(vmf, used_inst)

        # Requires instance traits!
        connections.calc_connections(
            vmf, ant,
            shape_frame_mat=texturing.OVERLAYS.get_all('shapeframe', False),
            enable_shape_frame=settings['style_vars']['enableshapesignageframe'],
            ind_style=ind_style,
        )
        change_ents(vmf)

        fizzler.parse_map(vmf, info)
        barriers.parse_map(vmf, connections.ITEMS)
        # We have barriers, pass to our error display.
        errors.load_barriers(barriers.BARRIERS)

        tiling.gen_tile_temp()
        tiling.analyse_map(vmf, side_to_antline)

        del side_to_antline
        # We have tiles, pass to our error display.
        errors.load_tiledefs(tiling.TILES.values(), brushLoc.POS)

        await texturing.setup(res_game.result(), vmf, list(tiling.TILES.values()))

        conditions.check_all(vmf, coll, info, voice_data_res.result())
        add_extra_ents(vmf, info)

        LOGGER.info('Generating tiles...')
        if texturing.NEW_TILE_GEN:
            tiling_gen.generate_brushes(vmf)
        else:
            tiling.generate_brushes(vmf)
        LOGGER.info('Generating goop...')
        tiling.generate_goo(vmf)
        tiling.bind_overlays()

        faithplate.gen_faithplates(vmf, info.has_attr('superposition'))
        change_overlays(vmf)
        fix_worldspawn(vmf, info)

        if utils.DEV_MODE:
            coll.export_debug(vmf, vis_name='collisions')
        coll.export_vscript(vmf)

        # Ensure all VMF outputs use the correct separator.
        for ent in vmf.entities:
            for out in ent.outputs:
                out.comma_sep = False
        # Set this so VRAD can know.
        vmf.spawn['BEE2_is_preview'] = info.is_preview
        # Ensure VRAD knows that the map is PeTI, it can't figure that out
        # from parameters.
        vmf.spawn['BEE2_is_peti'] = True

        # Save and run VBSP. If this leaks, this will raise UserError, and we'll compile again.
        save(vmf, new_path)
        if not skip_vbsp:
            run_vbsp(
                vbsp_args=new_args,
                path=path,
                new_path=new_path,
                maybe_missing_inst=await find_missing_instances(res_game.result(), vmf),
            )
    except errors.UserError as error:
        # The user did something wrong, so the map is invalid.
        # In preview, compile a special map which displays the message.
        if is_publishing:  # But force an error to prevent publishing.
            raise
        LOGGER.error('"User" error detected, aborting compile: ', exc_info=True)

        error.info = attrs.evolve(error.info, vmf_fname_orig=path)

        # Try to preserve the current map.
        if vmf is not None:
            error_fname = new_path[:-4] + '.error.vmf'
            try:
                save(vmf, error_fname)  # noqa
            except Exception:
                pass
            else:
                error.info = attrs.evolve(error.info, vmf_fname_new=error_fname)

        vmf = errors.make_map(error)

        # Flag as preview and errored for VRAD.
        vmf.spawn['BEE2_is_preview'] = True
        vmf.spawn['BEE2_is_error'] = True
        vmf.spawn['BEE2_is_peti'] = True

        if not skip_vbsp:
            save(vmf, new_path)
            run_vbsp(
                vbsp_args=new_args,
                path=path,
                new_path=new_path,
                is_error_map=True,
            )

    LOGGER.info("BEE2 VBSP hook finished!")
