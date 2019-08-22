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
from srctools import sndscript as snd


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

# Opvar name used to sync tracks.
MUSIC_SYNC_OPVAR = 'bee2_music_start'

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
    has_funnel = bool(funnel) and (
        'funnel' in voice_attr or
        'excursionfunnel' in voice_attr
    )
    has_bounce = bool(bounce) and (
        'bouncegel' in voice_attr or
        'bluegel' in voice_attr
    )
    # Speed-gel sounds also play when flinging, so keep it always.
    has_speed = bool(speed)

    sound_base = snd.Sound(
        "music.BEE2_base",
        ['#*' + wav for wav in base.as_array()],
        channel=snd.Channel.BACKGROUND,
        level=snd.Level.SNDLVL_NONE,
    )
    sound_start = snd.Sound(
        "music.BEE2_start",
        ['common/null.wav'],
    )
    sound_stop = snd.Sound(
        "music.BEE2_stop",
        ['common/null.wav']
    )

    sounds = [sound_start, sound_stop, sound_base]
    sounds_synch = []

    # A pair of proxy tracks starting and stopping the music.
    with sound_start.stack_start.build() as builder:
        builder.import_stack("P2_null_player_start")
        with builder.play_entry:
            builder.entry_name("music.BEE2_base")

    # We need to stop the sub-tracks after the main track stops
    with sound_stop.stack_start.build() as builder:
        builder.import_stack("P2_null_player_start")
        with builder.stop_entry:
            builder.operator("sys_stop_entries")
            builder.input_max_entries("0")
            builder.match_entity("false")
            builder.match_substring("true")
            builder.match_entry("music.BEE2_")

    with sound_base.stack_update.build() as builder:
        builder.import_stack("update_music_stereo")
        with builder.volume_fade_in:
            builder.input_max("0.5")
        with builder.volume_fade_out:
            builder.input_max("1.5")

        # Add the operators to play the auxiliary sounds..
        if has_funnel:
            builder.import_stack("p2_update_music_play_tbeam")
            with builder.play_entry:
                builder.entry_name("music.BEE2_funnel")
            with builder.stop_entry:
                builder.match_entry("music.BEE2_funnel")

        if has_bounce:
            builder.import_stack("p2_update_music_play_gel")
            with builder.gel_play_entry:
                builder.entry_name("music.BEE2_gel_bounce")
            with builder.gel_stop_entry:
                builder.match_entry("music.BEE2_gel_bounce")

        if has_speed:
            builder.import_stack("p2_update_music_play_speed_gel")
            with builder.speed_velocity_trigger:
                builder.input2("250")
            with builder.speed_play_entry:
                builder.entry_name("music.BEE2_gel_speed")
            with builder.speed_stop_entry:
                builder.match_entry("music.BEE2_gel_speed")

    if has_funnel:
        sound_funnel = snd.Sound(
            "music.BEE2_funnel",
            ['*' + wav for wav in funnel.as_array()],
            channel=snd.Channel.BACKGROUND,
            level=snd.Level.SNDLVL_NONE,
        )
        sounds.append(sound_funnel)

        # Some tracks want the funnel music to sync with the normal
        # track, others randomly choose a start.
        if sync_funnel:
            sounds_synch.append(sound_funnel)
            # The base then needs to resync with itself.
            sounds_synch.append(sound_base)
        else:
            # Randomly choose a start.
            with sound_funnel.stack_start.build() as builder:
                with builder.random_offset:
                    builder.operator("math_random")
                    builder.input_min("-300")
                    builder.input_max("0")
                with builder.delay_output:
                    builder.operator("sys_output")
                    builder.input_float("@random_offset.output")
                    builder.output("delay")

        with sound_funnel.stack_update.build() as builder:
            builder.import_stack("update_music_stereo")
            with builder.mixer:
                builder.mixgroup("unduckedMusic")
            with builder.volume_fade_in:
                builder.input_max("3.0")
                builder.input_map_min("0.05")
            with builder.volume_fade_out:
                builder.input_max("0.75")
                builder.input_map_min("0.05")
            with builder.volume_lfo_time_scale:
                builder.input2("0.3")
            with builder.volume_lfo_scale:
                builder.input2("0.4")

        # Restart base to sync properly
        if sync_funnel:
            with sound_funnel.stack_stop.build() as builder:
                with builder.restart_main:
                    builder.operator("sys_start_entry")
                    builder.entry_name("music.BEE2_base")

            # Stop existing bases when we restart the base.
            with sound_base.stack_start.build() as builder:
                with builder.stop_existing:
                    builder.operator("sys_stop_entries")
                    builder.input_max_entries("0")
                    builder.match_entity("false")
                    builder.match_substring("true")
                    builder.match_entry("music.BEE2_")

    if has_bounce:
        sound_bounce = snd.Sound(
            "music.BEE2_gel_bounce",
            ['*' + wav for wav in bounce.as_array()],
            channel=snd.Channel.BACKGROUND,
            level=snd.Level.SNDLVL_NONE,
        )
        sounds.append(sound_bounce)
        sounds_synch.append(sound_bounce)

        # Fade in fast (we never get false positives), but fade out slow
        # since this disables when falling back..
        with sound_bounce.stack_update.build() as builder:
            builder.import_stack("update_music_stereo")
            with builder.volume_fade_in:
                builder.input_max("0.25")
            with builder.volume_fade_out:
                builder.input_max("1.5")

    if has_speed:
        sound_speed = snd.Sound(
            "music.BEE2_gel_speed",
            ['*' + wav for wav in speed.as_array()],
            channel=snd.Channel.BACKGROUND,
            level=snd.Level.SNDLVL_NONE,
        )
        sounds.append(sound_speed)
        sounds_synch.append(sound_speed)

        # We need to shut off the sound fast, so portals don't confuse it.
        # Fade in slow so it doesn't make much sound (and also as we get
        # up to speed). We stop almost immediately on gel too.
        with sound_speed.stack_update.build() as builder:
            builder.import_stack("update_music_stereo")
            with builder.volume_fade_in:
                builder.input_max("0.5")
            with builder.volume_fade_out:
                builder.input_max("0.1")

    # If we want synchronisation, do that using opvars to keep it even when
    # the base track is paused by the funnel.
    # We sync to the base track if the funnel isn't synced, otherwise the main.

    if sounds_synch:
        if sync_funnel:
            sync_point = sound_base
        else:
            sync_point = sound_start

        with sync_point.stack_start.build() as builder:
            with builder.sys_time:
                builder.operator("get_sys_time")
            with builder.sync_time:
                builder.operator("set_opvar_float")
                builder.opvar(MUSIC_SYNC_OPVAR)
                builder.input("@sys_time.output_client_time")

    # The more complicated syncing logic.
    for script in sounds_synch:
        with script.stack_start.build() as builder:
            # Get the time, subtract from now.
            with builder.sys_time:
                builder.operator("get_sys_time")
            with builder.sync_time:
                builder.operator("get_opvar_float")
                builder.opvar(MUSIC_SYNC_OPVAR)
            with builder.sync_delta:
                builder.operator("math_float")
                builder.apply("sub")
                builder.input1("@sys_time.output_client_time")
                builder.input2("@sync_time.output")
            # Invert.
            with builder.sync_negative_delay:
                builder.operator("math_float")
                builder.apply("mult")
                builder.input1("@sync_delta.output")
                builder.input2("-1.0")
            # Apply the delay.
            with builder.delay_output:
                builder.operator("sys_output")
                builder.input_float("@sync_negative_delay.output")
                builder.output("delay")

    file = StringIO()

    for script in sounds:
        for wav in script.sounds:
            pack_list.pack_file('sound/' + wav.lstrip(snd.SND_CHARS))

        script.export(file)
        file.write('\n')

    return file.getvalue().rstrip().encode('utf8')


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
