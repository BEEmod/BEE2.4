"""Replacement for Valve's VRAD.

This allows us to change the arguments passed in,
edit the BSP after instances are collapsed, and pack files.
"""
# Run as early as possible to catch errors in imports.
from srctools.logger import init_logging
LOGGER = init_logging('bee2/vrad.log')

import os
import shutil
import subprocess
import sys
from datetime import datetime
from io import BytesIO, StringIO
from zipfile import ZipFile
from typing import Iterator, List, Tuple, Set

import srctools
import utils
from srctools import Property, Vec
from srctools.bsp import BSP, BSP_LUMPS
from srctools.filesys import (
    RawFileSystem, VPKFileSystem, ZipFileSystem,
    FileSystem,
)
from srctools.packlist import PackList, FileType as PackType, load_fgd
from srctools.game import find_gameinfo
from srctools.bsp_transform import run_transformations


CONF = Property('Config', [])

SCREENSHOT_DIR = os.path.join(
    '..',
    'portal2',  # This is hardcoded into P2, it won't change for mods.
    'puzzles',
    # Then the <random numbers> folder
)

GAME_FOLDER = {
    # The game's root folder, where screenshots are saved
    utils.STEAM_IDS['PORTAL2']: 'portal2',
    utils.STEAM_IDS['TWTM']: 'twtm',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
    utils.STEAM_IDS['DEST_AP']: 'portal2',
}

SOUND_MAN_FOLDER = {
    # The folder where game_sounds_manifest is found
    utils.STEAM_IDS['PORTAL2']: 'portal2_dlc2',
    utils.STEAM_IDS['DEST_AP']: 'portal2_dlc2',
    utils.STEAM_IDS['TWTM']: 'twtm',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
}

# Files that VBSP may generate, that we want to insert into the packfile.
# They are all found in bee2/inject/.
INJECT_FILES = {
    # Defines choreo lines used on coop death, taunts, etc.
    'response_data.nut': 'scripts/vscripts/bee2/coop_response_data.nut',

    # The list of soundscripts that the game loads.
    'soundscript_manifest.txt': 'scripts/game_sounds_manifest.txt',

    # The list of particles that the game loads.
    'particles_manifest.txt': 'particles/particles_manifest.txt',

    # A generated soundscript for the current music.
    'music_script.txt': 'scripts/BEE2_generated_music.txt',

    # Applied to @glados's entity scripts.
    'auto_run.nut': 'scripts/vscripts/bee2/auto_run.nut',

    # Commands for monitor items.
    'monitor_args.nut': 'scripts/vscripts/bee2/mon_camera_args.nut',

    # Script for setting model types on cubes.
    'cube_setmodel.nut': 'scripts/vscripts/bee2/cube_setmodel.nut',

    # Plays the tick-tock timer sound.
    'timer_sound.nut': 'scripts/vscripts/bee2/timer_sound.nut',
}

# Additional parts to add if we have a mdl file.
MDL_ADDITIONAL_EXT = [
    '.sw.vtx',
    '.dx80.vtx',
    '.dx90.vtx',
    '.vvd',
    '.phy',
]


# Various parts of the soundscript generated for BG music.

# Things that can appear at the beginning of filenames..
SOUND_CHARS = '*#@><^)}$!?'

# The starting section defining the name and volume.
# SNDLVL_NONE means it's infinite range.
MUSIC_START = """\
"music.BEE2{name}"
{{
"channel" "CHAN_STATIC"
"soundlevel" "SNDLVL_NONE"
"volume" "{vol}"
"""

# The basic operator stack for music without any additional tracks.
MUSIC_BASE = """\
"soundentry_version" "2"
"operator_stacks"
\t{
\t"update_stack"
\t\t{
\t\t"import_stack" "update_music_stereo"
\t\t"volume_fade_in"
\t\t\t{
\t\t\t"input_max" "0.5"
\t\t\t}
\t\t"volume_fade_out"
\t\t\t{
\t\t\t"input_max" "1.5"
\t\t\t}
"""

# We need to stop the sub-tracks after the main track stops...
MUSIC_END = """\
\t\t}
\t"stop_stack"
\t\t{
\t\t"stop_entry"
\t\t\t{
\t\t\t"operator" "sys_stop_entries"
\t\t\t"input_max_entries" "0"
\t\t\t"match_entity" "false"
\t\t\t"match_substring" "true"
\t\t\t"match_entry" "music.BEE2_"
\t\t\t}
\t\t}
\t}
}
"""

# Operator stacks which enable the given gel types.
MUSIC_GEL_BOUNCE_MAIN = """\

\t\t"import_stack" "p2_update_music_play_gel"
\t\t"gel_play_entry"
\t\t\t{
\t\t\t"entry_name" "music.BEE2_gel_bounce"
\t\t\t}
\t\t"gel_stop_entry"
\t\t\t{
\t\t\t"match_entry" "music.BEE2_gel_bounce"
\t\t\t}
"""

MUSIC_GEL_SPEED_MAIN = """\

\t\t"import_stack" "p2_update_music_play_speed_gel"
\t\t"speed_velocity_trigger"
\t\t\t{
\t\t\t"input2" "250"
\t\t\t}
\t\t"speed_play_entry"
\t\t\t{
\t\t\t"entry_name" "music.BEE2_gel_speed"
\t\t\t}
\t\t"speed_stop_entry"
\t\t\t{
\t\t\t"match_entry" "music.BEE2_gel_speed"
\t\t\t}
"""

MUSIC_FUNNEL_MAIN = """\

\t"import_stack" "p2_update_music_play_tbeam"
\t"play_entry"
\t\t{
\t\t"entry_name" "music.BEE2_funnel"
\t\t}
\t"stop_entry"
\t\t{
\t\t"match_entry" "music.BEE2_funnel"
\t\t}
"""

# The gel operator stack syncronises the music with the base track.
MUSIC_GEL_STACK = """\

"soundentry_version" "2"
"operator_stacks"
\t{{
\t"start_stack"
\t\t{{
\t\t"import_stack" "start_sync_to_entry"
\t\t"elapsed_time"
\t\t\t{{
\t\t\t"entry" "music.BEE2"
\t\t\t}}
\t\t"duration_div"
\t\t\t{{
\t\t\t"input2" "1"
\t\t\t}}
\t\t"div_mult"
\t\t\t{{
\t\t\t"input1" "1.0"
\t\t\t}}
\t\t}}
\t"update_stack"
\t\t{{
\t\t"import_stack" "update_music_stereo"
\t\t"volume_fade_in"
\t\t\t{{
\t\t\t"input_max" "{fadein}"
\t\t\t}}
\t\t"volume_fade_out"
\t\t\t{{
\t\t\t"input_max" "{fadeout}"
\t\t\t}}
\t\t}}
\t}}
}}
"""

# This funnel stack makes it start randomly offset into the music.
MUSIC_FUNNEL_RAND_STACK = """\

"soundentry_version" "2"
"operator_stacks"
\t{
\t"start_stack"
\t\t{
\t\t"random_offset"
\t\t\t{
\t\t\t"operator" "math_random"
\t\t\t"input_min" "0.0"
\t\t\t"input_max" "126"
\t\t\t}
\t\t"negative_delay"
\t\t\t{
\t\t\t"operator" "math_float"
\t\t\t"apply" "mult"
\t\t\t"input1" "@random_offset.output"
\t\t\t"input2" "-1.0"
\t\t\t}
\t\t"delay_output"
\t\t\t{
\t\t\t"operator" "sys_output"
\t\t\t"input_float" "@negative_delay.output"
\t\t\t"output" "delay"
\t\t\t}
\t\t}
"""

# This funnel stack makes it synchronise with the main track.
MUSIC_FUNNEL_SYNC_STACK = """\

"soundentry_version" "2"
"operator_stacks"
\t{
\t"start_stack"
\t\t{
\t\t"import_stack" "start_sync_to_entry"
\t\t"elapsed_time"
\t\t\t{
\t\t\t"entry" "music.BEE2"
\t\t\t}
\t\t"duration_div"
\t\t\t{
\t\t\t"input2" "1"
\t\t\t}
\t\t"div_mult"
\t\t\t{
\t\t\t"input1" "1.0"
\t\t\t}
\t\t}
"""

# Both funnel versions share the same update stack.
MUSIC_FUNNEL_UPDATE_STACK = """\
\t"update_stack"
\t\t{
\t\t"import_stack" "update_music_stereo"
\t\t"mixer"
\t\t\t{
\t\t\t"mixgroup" "unduckedMusic"
\t\t\t}
\t\t"volume_fade_in"
\t\t\t{
\t\t\t"input_max" "3.0"
\t\t\t"input_map_min" "0.05"
\t\t\t}
\t\t"volume_fade_out"
\t\t\t{
\t\t\t"input_max" "0.75"
\t\t\t"input_map_min" "0.05"
\t\t\t}
\t\t"volume_lfo_time_scale"
\t\t\t{
\t\t\t"input2" "0.3"
\t\t\t}
\t\t"volume_lfo_scale"
\t\t\t{
\t\t\t"input2" "0.4"
\t\t\t}
\t\t}
\t}
}
"""


def load_config():
    global CONF
    LOGGER.info('Loading Settings...')
    try:
        with open("bee2/vrad_config.cfg", encoding='utf8') as config:
            CONF = Property.parse(config, 'bee2/vrad_config.cfg').find_key(
                'Config', []
            )
    except FileNotFoundError:
        pass
    LOGGER.info('Config Loaded!')


def dump_files(zipfile: ZipFile):
    """Dump packed files to a location.
    """
    dump_folder = CONF['packfile_dump', '']
    if not dump_folder:
        return

    dump_folder = os.path.abspath(dump_folder)

    # Delete files in the folder, but don't delete the folder itself.
    try:
        files = os.listdir(dump_folder)
    except FileNotFoundError:
        return

    for name in files:
        name = os.path.join(dump_folder, name)
        if os.path.isdir(name):
            try:
                shutil.rmtree(name)
            except OSError:
                # It's possible to fail here, if the window is open elsewhere.
                # If so, just skip removal and fill the folder.
                pass
        else:
            os.remove(name)

    for zipinfo in zipfile.infolist():
        zipfile.extract(zipinfo, dump_folder)


def generate_music_script(data: Property, pack_list: PackList) -> bytes:
    """Generate a soundscript file for music."""
    # We also pack the filenames used for the tracks - that way funnel etc
    # only get packed when needed. Stock sounds are in VPKS or in aperturetag/,
    # we don't check there.
    # The voice attrs used in the map - we can skip tracks
    voice_attr = CONF['VoiceAttr', ''].casefold().split(';')

    funnel = data.find_key('tbeam', '')
    bounce = data.find_key('bouncegel', '')
    speed = data.find_key('speedgel', '')

    sync_funnel = data.bool('sync_funnel')

    if 'base' not in data:
        base = Property('base', 'bee2/silent_lp.wav')
        # Don't sync to a 2-second sound.
        sync_funnel = False
    else:
        base = data.find_key('base')

    # The sounds must be present, and the items should be in the map.
    has_funnel = funnel.value and (
        'funnel' in voice_attr or
        'excursionfunnel' in voice_attr
    )
    has_bounce = bounce.value and (
        'bouncegel' in voice_attr or
        'bluegel' in voice_attr
    )
    # Speed-gel sounds also play when flinging, so keep it always.

    file = StringIO()

    # Write the base music track
    file.write(MUSIC_START.format(name='', vol='1'))
    write_sound(file, base, pack_list, snd_prefix='#*')
    file.write(MUSIC_BASE)
    # The 'soundoperators' section is still open now.

    # Add the operators to play the auxilluary sounds..
    if has_funnel:
        file.write(MUSIC_FUNNEL_MAIN)
    if has_bounce:
        file.write(MUSIC_GEL_BOUNCE_MAIN)
    if speed.value:
        file.write(MUSIC_GEL_SPEED_MAIN)

    # End the main sound block
    file.write(MUSIC_END)

    if has_funnel:
        # Write the 'music.BEE2_funnel' sound entry
        file.write('\n')
        file.write(MUSIC_START.format(name='_funnel', vol='1'))
        write_sound(file, funnel, pack_list, snd_prefix='*')
        # Some tracks want the funnel music to sync with the normal
        # track, others randomly choose a start.
        file.write(
            MUSIC_FUNNEL_SYNC_STACK
            if sync_funnel else
            MUSIC_FUNNEL_RAND_STACK
        )
        file.write(MUSIC_FUNNEL_UPDATE_STACK)

    if has_bounce:
        file.write('\n')
        file.write(MUSIC_START.format(name='_gel_bounce', vol='0.5'))
        write_sound(file, bounce, pack_list, snd_prefix='*')
        # Fade in fast (we never get false positives, but fade out slow
        # since this disables when falling back..
        file.write(MUSIC_GEL_STACK.format(fadein=0.25, fadeout=1.5))

    if speed.value:
        file.write('\n')
        file.write(MUSIC_START.format(name='_gel_speed', vol='0.5'))
        write_sound(file, speed, pack_list, snd_prefix='*')
        # We need to shut off the sound fast, so portals don't confuse it.
        # Fade in slow so it doesn't make much sound (and also as we get
        # up to speed). We stop almost immediately on gel too.
        file.write(MUSIC_GEL_STACK.format(fadein=0.5, fadeout=0.1))

    return file.getvalue().encode()


def write_sound(
    file: StringIO,
    snds: Property,
    pack_list: PackList,
    snd_prefix: str='*',
) -> None:
    """Write either a single sound, or multiple rndsound.

    snd_prefix is the prefix for each filename - *, #, @, etc.
    """
    if snds.has_children():
        file.write('"rndwave"\n\t{\n')
        for snd in snds:
            file.write(
                '\t"wave" "{sndchar}{file}"\n'.format(
                    file=snd.value.lstrip(SOUND_CHARS),
                    sndchar=snd_prefix,
                )
            )
            pack_list.pack_file('sound/' + snd.value.casefold())
        file.write('\t}\n')
    else:
        file.write(
            '"wave" "{sndchar}{file}"\n'.format(
                file=snds.value.lstrip(SOUND_CHARS),
                sndchar=snd_prefix,
            )
        )
        pack_list.pack_file('sound/' + snds.value.casefold())


def inject_files() -> Iterator[Tuple[str, str]]:
    """Generate the names of files to inject, if they exist.."""
    for filename, arcname in INJECT_FILES.items():
        filename = os.path.join('bee2', 'inject', filename)
        if os.path.exists(filename):
            yield filename, arcname

    # Additionally add files set in the config.
    for prop in CONF.find_children('InjectFiles'):
        filename = os.path.join('bee2', 'inject', prop.real_name)
        if os.path.exists(filename):
            yield filename, prop.value


def find_screenshots() -> Iterator[str]:
    """Find candidate screenshots to overwrite."""
    # Inside SCREENSHOT_DIR, there should be 1 folder with a
    # random name which contains the user's puzzles. Just
    # attempt to modify a screenshot in each of the directories
    # in the folder.
    for folder in os.listdir(SCREENSHOT_DIR):
        full_path = os.path.join(SCREENSHOT_DIR, folder)
        if os.path.isdir(full_path):
            # The screenshot to modify is untitled.jpg
            screenshot = os.path.join(full_path, 'untitled.jpg')
            if os.path.isfile(screenshot):
                yield screenshot


def mod_screenshots() -> None:
    """Modify the map's screenshot."""
    mod_type = CONF['screenshot_type', 'PETI'].lower()

    if mod_type == 'cust':
        LOGGER.info('Using custom screenshot!')
        scr_loc = CONF['screenshot', '']
    elif mod_type == 'auto':
        LOGGER.info('Using automatic screenshot!')
        scr_loc = None
        # The automatic screenshots are found at this location:
        auto_path = os.path.join(
            '..',
            GAME_FOLDER.get(CONF['game_id', ''], 'portal2'),
            'screenshots'
        )
        # We need to find the most recent one. If it's named
        # "previewcomplete", we want to ignore it - it's a flag
        # to indicate the map was playtested correctly.
        try:
            screens = [
                os.path.join(auto_path, path)
                for path in
                os.listdir(auto_path)
            ]
        except FileNotFoundError:
            # The screenshot folder doesn't exist!
            screens = []
        screens.sort(
            key=os.path.getmtime,
            reverse=True,
            # Go from most recent to least
        )
        playtested = False
        for scr_shot in screens:
            filename = os.path.basename(scr_shot)
            if filename.startswith('bee2_playtest_flag'):
                # Previewcomplete is a flag to indicate the map's
                # been playtested. It must be newer than the screenshot
                playtested = True
                continue
            elif filename.startswith('bee2_screenshot'):
                continue  # Ignore other screenshots

            # We have a screenshot. Check to see if it's
            # not too old. (Old is > 2 hours)
            date = datetime.fromtimestamp(
                os.path.getmtime(scr_shot)
            )
            diff = datetime.now() - date
            if diff.total_seconds() > 2 * 3600:
                LOGGER.info(
                    'Screenshot "{scr}" too old ({diff!s})',
                    scr=scr_shot,
                    diff=diff,
                )
                continue

            # If we got here, it's a good screenshot!
            LOGGER.info('Chosen "{}"', scr_shot)
            LOGGER.info('Map Playtested: {}', playtested)
            scr_loc = scr_shot
            break
        else:
            # If we get to the end, we failed to find an automatic
            # screenshot!
            LOGGER.info('No Auto Screenshot found!')
            mod_type = 'peti'  # Suppress the "None not found" error

        if srctools.conv_bool(CONF['clean_screenshots', '0']):
            LOGGER.info('Cleaning up screenshots...')
            # Clean up this folder - otherwise users will get thousands of
            # pics in there!
            for screen in screens:
                if screen != scr_loc and os.path.isfile(screen):
                    os.remove(screen)
            LOGGER.info('Done!')
    else:
        # PeTI type, or something else
        scr_loc = None

    if scr_loc is not None and os.path.isfile(scr_loc):
        # We should use a screenshot!
        for screen in find_screenshots():
            LOGGER.info('Replacing "{}"...', screen)
            # Allow us to edit the file...
            utils.unset_readonly(screen)
            shutil.copy(scr_loc, screen)
            # Make the screenshot readonly, so P2 can't replace it.
            # Then it'll use our own
            utils.set_readonly(screen)

    else:
        if mod_type != 'peti':
            # Error if we were looking for a screenshot
            LOGGER.warning('"{}" not found!', scr_loc)
        LOGGER.info('Using PeTI screenshot!')
        for screen in find_screenshots():
            # Make the screenshot writeable, so P2 will replace it
            LOGGER.info('Making "{}" replaceable...', screen)
            utils.unset_readonly(screen)


def run_vrad(args: List[str]) -> None:
    """Execute the original VRAD."""

    suffix = ''
    if utils.MAC:
        os_suff = '_osx'
    elif utils.LINUX:
        os_suff = '_linux'
    else:
        os_suff = ''
        suffix = '.exe'

    joined_args = (
        '"' + os.path.normpath(
            os.path.join(os.getcwd(), "vrad" + os_suff + "_original" + suffix)
        ) +
        '" ' +
        " ".join(
            # put quotes around args which contain spaces
            ('"' + x + '"' if " " in x else x)
            for x in args
        )
    )
    LOGGER.info("Calling original VRAD...")
    LOGGER.info(joined_args)
    code = subprocess.call(
        joined_args,
        stdout=None,
        stderr=subprocess.PIPE,
        shell=True,
    )
    if code == 0:
        LOGGER.info("Done!")
    else:
        LOGGER.warning("VRAD failed! (" + str(code) + ")")
        sys.exit(code)


def main(argv: List[str]) -> None:
    LOGGER.info('BEE2 VRAD hook started!')
        
    args = " ".join(argv)
    fast_args = argv[1:]
    full_args = argv[1:]
    
    if not fast_args:
        # No arguments!
        LOGGER.info(
            'No arguments!\n'
            "The BEE2 VRAD takes all the regular VRAD's "
            'arguments, with some extra arguments:\n'
            '-force_peti: Force enabling map conversion. \n'
            "-force_hammer: Don't convert the map at all.\n"
            "If not specified, the map name must be \"preview.bsp\" to be "
            "treated as PeTI."
        )
        sys.exit()

    # The path is the last argument to vrad
    # P2 adds wrong slashes sometimes, so fix that.
    fast_args[-1] = path = os.path.normpath(argv[-1])  # type: str

    LOGGER.info("Map path is " + path)

    load_config()

    for a in fast_args[:]:
        if a.casefold() in (
                "-both",
                "-final",
                "-staticproplighting",
                "-staticproppolys",
                "-textureshadows",
                ):
            # remove final parameters from the modified arguments
            fast_args.remove(a)
        elif a in ('-force_peti', '-force_hammer', '-no_pack'):
            # we need to strip these out, otherwise VRAD will get confused
            fast_args.remove(a)
            full_args.remove(a)

    fast_args = ['-bounce', '2', '-noextra'] + fast_args

    # Fast args: -bounce 2 -noextra -game $gamedir $path\$file
    # Final args: -both -final -staticproplighting -StaticPropPolys
    # -textureshadows  -game $gamedir $path\$file

    if not path.endswith(".bsp"):
        path += ".bsp"

    if not os.path.exists(path):
        raise ValueError('"{}" does not exist!'.format(path))
    if not os.path.isfile(path):
        raise ValueError('"{}" is not a file!'.format(path))

    # If VBSP thinks it's hammer, trust it.
    if CONF.bool('is_hammer', False):
        is_peti = edit_args = False
    else:
        is_peti = True
        # Detect preview via knowing the bsp name. If we are in preview,
        # check the config file to see what was specified there.
        if os.path.basename(path) == "preview.bsp":
            edit_args = not CONF.bool('force_full', False)
        else:
            # publishing - always force full lighting.
            edit_args = False

    if '-force_peti' in args or '-force_hammer' in args:
        # we have override commands!
        if '-force_peti' in args:
            LOGGER.warning('OVERRIDE: Applying cheap lighting!')
            is_peti = edit_args = True
        else:
            LOGGER.warning('OVERRIDE: Preserving args!')
            is_peti = edit_args = False

    LOGGER.info('Final status: is_peti={}, edit_args={}', is_peti, edit_args)

    # Grab the currently mounted filesystems in P2.
    game = find_gameinfo(argv)
    root_folder = game.path.parent
    fsys = game.get_filesystem()

    fsys_tag = fsys_mel = None
    if is_peti and 'mel_vpk' in CONF:
        fsys_mel = VPKFileSystem(CONF['mel_vpk'])
        fsys.add_sys(fsys_mel)
    if is_peti and 'tag_dir' in CONF:
        fsys_tag = RawFileSystem(CONF['tag_dir'])
        fsys.add_sys(fsys_tag)

    LOGGER.info('Reading BSP')
    bsp_file = BSP(path)

    bsp_ents = bsp_file.read_ent_data()

    zip_data = BytesIO()
    zip_data.write(bsp_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data, mode='a')

    # Mount the existing packfile, so the cubemap files are recognised.
    fsys.systems.append((ZipFileSystem('', zipfile), ''))

    fsys.open_ref()

    LOGGER.info('Done!')

    LOGGER.info('Reading our FGD files...')
    fgd = load_fgd()

    packlist = PackList(fsys)
    packlist.load_soundscript_manifest(
        str(root_folder / 'bin/bee2/sndscript_cache.vdf')
    )

    # We nee to add all soundscripts in scripts/bee2_snd/
    # This way we can pack those, if required.
    for soundscript in fsys.walk_folder('scripts/bee2_snd/'):
        if soundscript.path.endswith('.txt'):
            packlist.load_soundscript(soundscript, always_include=False)

    if is_peti:
        LOGGER.info('Adding special packed files:')
        music_data = CONF.find_key('MusicScript', [])
        if music_data:
            packlist.pack_file(
                'scripts/BEE2_generated_music.txt',
                PackType.SOUNDSCRIPT,
                data=generate_music_script(music_data, packlist)
            )

        for filename, arcname in inject_files():
            LOGGER.info('Injecting "{}" into packfile.', arcname)
            with open(filename, 'rb') as f:
                packlist.pack_file(arcname, data=f.read())

    LOGGER.info('Run transformations...')
    run_transformations(bsp_ents, fsys, packlist)

    LOGGER.info('Scanning map for files to pack:')
    packlist.pack_from_bsp(bsp_file)
    packlist.pack_fgd(bsp_ents, fgd)
    packlist.eval_dependencies()
    LOGGER.info('Done!')

    if is_peti:
        packlist.write_manifest()
    else:
        # Write with the map name, so it loads directly.
        packlist.write_manifest(os.path.basename(path)[:-4])

    # We need to disallow Valve folders.
    pack_whitelist = set()  # type: Set[FileSystem]
    pack_blacklist = set()  # type: Set[FileSystem]
    if is_peti:
        pack_blacklist |= {
            RawFileSystem(root_folder / 'portal2_dlc2'),
            RawFileSystem(root_folder / 'portal2_dlc1'),
            RawFileSystem(root_folder / 'portal2'),
            RawFileSystem(root_folder / 'platform'),
            RawFileSystem(root_folder / 'update'),
        }
        if fsys_mel is not None:
            pack_whitelist.add(fsys_mel)
        if fsys_tag is not None:
            pack_whitelist.add(fsys_tag)

    if '-no_pack' not in args:
        # Cubemap files packed into the map already.
        existing = set(zipfile.infolist())

        LOGGER.info('Writing to BSP...')
        packlist.pack_into_zip(
            zipfile,
            ignore_vpk=True,
            whitelist=pack_whitelist,
            blacklist=pack_blacklist,
        )

        LOGGER.info('Packed files:\n{}', '\n'.join([
            zipinfo.filename
            for zipinfo in zipfile.infolist()
            if zipinfo.filename not in existing
        ]))

    dump_files(zipfile)

    zipfile.close()  # Finalise the zip modification

    # Copy the zipfile into the BSP file, and adjust the headers.
    bsp_file.lumps[BSP_LUMPS.PAKFILE].data = zip_data.getvalue()
    # Copy new entity data.
    bsp_file.lumps[BSP_LUMPS.ENTITIES].data = BSP.write_ent_data(bsp_ents)

    bsp_file.save()
    LOGGER.info(' - BSP written!')

    if is_peti:
        mod_screenshots()

    if edit_args:
        LOGGER.info("Forcing Cheap Lighting!")
        run_vrad(fast_args)
    else:
        if is_peti:
            LOGGER.info("Publishing - Full lighting enabled! (or forced to do so)")
        else:
            LOGGER.info("Hammer map detected! Not forcing cheap lighting..")
        run_vrad(full_args)

    LOGGER.info("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    main(sys.argv)
