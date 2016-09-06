import os
import os.path
import shutil
import subprocess
import sys
import logging
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile

import srctools
import utils
from srctools import Property
from srctools.bsp import BSP, BSP_LUMPS


LOGGER = utils.init_logging('bee2/VRAD.log')

CONF = Property('Config', [])

SCREENSHOT_DIR = os.path.join(
    '..',
    'portal2',  # This is hardcoded into P2, it won't change for mods.
    'puzzles',
    # Then the <random numbers> folder
)
# Locations of resources we need to pack
RES_ROOT = [
    os.path.join('..', loc)
    for loc in
    ('bee2', 'bee2_dev', 'portal2_dlc2')
]

GAME_FOLDER = {
    # The game's root folder, where screenshots are saved
    utils.STEAM_IDS['PORTAL2']: 'portal2',
    utils.STEAM_IDS['TWTM']: 'twtm',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
}

SOUND_MAN_FOLDER = {
    # The folder where game_sounds_manifest is found
    utils.STEAM_IDS['PORTAL2']: 'portal2_dlc2',
    utils.STEAM_IDS['TWTM']: 'twtm',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
}

# Files that VBSP may generate, that we want to insert into the packfile.
# They are all found in bee2/inject/.
INJECT_FILES = {
    # Defines choreo lines used on coop death, taunts, etc.
    'response_data.nut': 'scripts/vscripts/BEE2/coop_response_data.nut',

    # The list of soundscripts that the game loads.
    'soundscript_manifest.txt': 'scripts/game_sounds_manifest.txt',

    # The list of particles that the game loads.
    'particles_manifest.txt': 'particles/particles_manifest.txt',

    # A generated soundscript for the current music.
    'music_script.txt': 'scripts/BEE2_generated_music.txt',

    # Applied to @glados's entity scripts.
    'auto_run.nut': 'scripts/vscripts/BEE2/auto_run.nut',

    # Commands for monitor items.
    'monitor_args.nut': 'scripts/vscripts/BEE2/mon_camera_args.nut',
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
\t\t\t"input2" "300"
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
\t"update_stack"
\t\t{
\t\t"import_stack" "update_music_stereo"
\t\t"volume_fade_in"
\t\t\t{
\t\t\t"input_max" "0.25"
\t\t\t}
\t\t"volume_fade_out"
\t\t\t{
\t\t\t"input_max" "1.0"
\t\t\t}
\t\t}
\t}
}
"""

# The funnel operator stack makes it start randomly offset into the music..
MUSIC_FUNNEL_STACK = """\

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


def quote(txt):
    return '"' + txt + '"'


def load_config():
    global CONF
    LOGGER.info('Loading Settings...')
    try:
        with open("bee2/vrad_config.cfg") as config:
            CONF = Property.parse(config, 'bee2/vrad_config.cfg').find_key(
                'Config', []
            )
    except FileNotFoundError:
        pass
    LOGGER.info('Config Loaded!')


def get_zip_writer(zipfile: ZipFile):
    """Allow dumping the packed files to a folder.

    Returns a zipfile.write() method.
    """
    dump_folder = CONF['packfile_dump', '']
    if not dump_folder:
        return zipfile.write

    dump_folder = os.path.abspath(dump_folder)

    # Delete files in the folder, but don't delete the folder itself.
    try:
        dump_files = os.listdir(dump_folder)
    except FileNotFoundError:
        pass
    else:
        for name in dump_files:
            name = os.path.join(dump_folder, name)
            if os.path.isdir(name):
                shutil.rmtree(name)
            else:
                os.remove(name)

    def write_to_zip(filename, arcname):
        dump_loc = os.path.join(dump_folder, arcname)
        os.makedirs(os.path.dirname(dump_loc), exist_ok=True)
        shutil.copy(filename, dump_loc)
        zipfile.write(filename, arcname)
    return write_to_zip


def pack_file(zip_write, filename: str, suppress_error=False):
    """Check multiple locations for a resource file.
    """
    if '\t' in filename:
        # We want to rename the file!
        filename, arcname = filename.split('\t')
    else:
        arcname = filename

    if filename[-1] == '*':
        # Pack a whole folder (blah/blah/*)
        directory = filename[:-1]
        file_count = 0
        for poss_path in RES_ROOT:
            dir_path = os.path.normpath(
                os.path.join(poss_path, directory)
            )
            if not os.path.isdir(dir_path):
                continue
            for subfile in os.listdir(dir_path):
                full_path = os.path.join(dir_path, subfile)
                rel_path = os.path.join(directory, subfile)
                zip_write(
                    filename=full_path,
                    arcname=rel_path,
                )
                file_count += 1
        LOGGER.info('Packed {} files from folder "{}"', file_count, directory)
        return

    for poss_path in RES_ROOT:
        full_path = os.path.normpath(
            os.path.join(poss_path, filename)
        )
        if os.path.isfile(full_path):
            zip_write(
                filename=full_path,
                arcname=arcname,
            )
            break
    else:
        if not suppress_error:
            LOGGER.warning(
                '"bee2/' + filename + '" not found! (May be OK if not custom)'
            )


def gen_sound_manifest(additional, excludes):
    """Generate a new game_sounds_manifest.txt file.

    This includes all the current scripts defined, plus any custom ones.
    Excludes is a list of scripts to remove from the listing - this allows
    overriding the sounds without VPK overrides.
    """
    if not additional:
        return  # Don't pack, there aren't any new sounds..

    orig_manifest = os.path.join(
        '..',
        SOUND_MAN_FOLDER.get(CONF['game_id', ''], 'portal2'),
        'scripts',
        'game_sounds_manifest.txt',
    )

    try:
        with open(orig_manifest) as f:
            props = Property.parse(f, orig_manifest).find_key(
                'game_sounds_manifest', [],
            )
    except FileNotFoundError:  # Assume no sounds
        props = Property('game_sounds_manifest', [])

    scripts = [prop.value for prop in props.find_all('precache_file')]

    for script in additional:
        scripts.append(script)

    for script in excludes:
        try:
            scripts.remove(script)
        except ValueError:
            LOGGER.warning(
                '"{}" should be excluded, but it\'s'
                ' not in the manifest already!',
                script,
            )

    # Build and unbuild it to strip other things out - Valve includes a bogus
    # 'new_sound_scripts_must_go_below_here' entry..
    new_props = Property('game_sounds_manifest', [
        Property('precache_file', file)
        for file in scripts
    ])

    inject_loc = os.path.join('bee2', 'inject', 'soundscript_manifest.txt')
    with open(inject_loc, 'w') as f:
        for line in new_props.export():
            f.write(line)
    LOGGER.info('Written new soundscripts_manifest..')


def gen_part_manifest(additional):
    """Generate a new particle system manifest file.

    This includes all the current ones defined, plus any custom ones.
    """
    if not additional:
        return  # Don't pack, there aren't any new particles..

    orig_manifest = os.path.join(
        '..',
        GAME_FOLDER.get(CONF['game_id', ''], 'portal2'),
        'particles',
        'particles_manifest.txt',
    )

    try:
        with open(orig_manifest) as f:
            props = Property.parse(f, orig_manifest).find_key(
                'particles_manifest', [],
            )
    except FileNotFoundError:  # Assume no particles
        props = Property('particles_manifest', [])

    parts = [prop.value for prop in props.find_all('file')]

    for particle in additional:
        parts.append(particle)

    # Build and unbuild it to strip comments and similar lines.
    new_props = Property('particles_manifest', [
        Property('file', file)
        for file in parts
    ])

    inject_loc = os.path.join('bee2', 'inject', 'particles_manifest.txt')
    with open(inject_loc, 'w') as f:
        for line in new_props.export():
            f.write(line)

    LOGGER.info('Written new particles_manifest..')


def generate_music_script(data: Property, pack_list):
    """Generate a soundscript file for music."""
    # We also pack the filenames used for the tracks - that way funnel etc
    # only get packed when needed. Stock sounds are in VPKS or in aperturetag/,
    # we don't check there.
    # The voice attrs used in the map - we can skip tracks
    voice_attr = CONF['VoiceAttr', ''].casefold().split(';')

    funnel = data.find_key('tbeam', '')
    bounce = data.find_key('bouncegel', '')
    speed = data.find_key('speedgel', '')

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

    with open(os.path.join('bee2', 'inject', 'music_script.txt'), 'w') as file:
        # Write the base music track
        file.write(MUSIC_START.format(name='', vol='1'))
        write_sound(file, data.find_key('base'), pack_list, snd_prefix='#*')
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
            file.write(MUSIC_FUNNEL_STACK)

        if has_bounce:
            file.write('\n')
            file.write(MUSIC_START.format(name='_gel_bounce', vol='0.5'))
            write_sound(file, bounce, pack_list, snd_prefix='*')
            file.write(MUSIC_GEL_STACK)

        if speed.value:
            file.write('\n')
            file.write(MUSIC_START.format(name='_gel_speed', vol='0.5'))
            write_sound(file, speed, pack_list, snd_prefix='*')
            file.write(MUSIC_GEL_STACK)


def write_sound(file, snds: Property, pack_list, snd_prefix='*'):
    """Write either a single sound, or multiple rndsound.

    snd_prefix is the prefix for each filename - *, #, @, etc.
    """
    if snds.has_children():
        file.write('"rndwave"\n\t{\n')
        for snd in snds:
            file.write(
                '\t"wave" "{sndchar}{file}"\n'.format(
                    file=snd.value,
                    sndchar=snd_prefix,
                )
            )
            pack_list.add('sound/' + snd.value.casefold())
        file.write('\t}\n')
    else:
        file.write(
            '"wave" "{sndchar}{file}"\n'.format(
                file=snds.value,
                sndchar=snd_prefix,
            )
        )
        pack_list.add('sound/' + snds.value.casefold())


def gen_auto_script(preload, is_peti):
    """Run various commands on spawn.

    This allows precaching specific sounds on demand.
    """
    dest = os.path.join('bee2', 'inject', 'auto_run.nut')
    if not preload and not is_peti:
        return  # Don't add for hammer maps

    with open(dest, 'w') as file:
        if not preload:
            return  # Leave it empty, don't write an empty body.

        file.write('function Precache() {\n')
        for entry in preload:
            if entry.startswith('precache_sound:'):
                file.write('\tself.PrecacheSoundScript("{}");\n'.format(
                    entry[15:],
                ))
        file.write('}\n')


def inject_files():
    """Generate the names of files to inject, if they exist.."""
    for filename, arcname in INJECT_FILES.items():
        filename = os.path.join('bee2', 'inject', filename)
        if os.path.exists(filename):
            yield filename, arcname


def pack_content(path, is_peti):
    """Pack any custom content into the map.

    Filelist format: "[control char]filename[\t packname]"
    Filename is the name of the actual file. If given packname is the
    name to save it into the packfile as. If the first character of the
    filename is '#', the file will be added to the soundscript manifest too.
    """
    files = set()  # Files to pack.
    soundscripts = set()  # Soundscripts need to be added to the manifest too..
    rem_soundscripts = set()  # Soundscripts to exclude, so we can override the sounds.
    particles = set()
    additional_files = set()  # .vvd files etc which also are needed.
    preload_files = set()  # Files we want to force preloading

    try:
        pack_list = open(path[:-4] + '.filelist.txt')
    except (IOError, FileNotFoundError):
        pass  # Assume no files if missing..
        # There might still be things to inject.
    else:
        with pack_list:
            for line in pack_list:
                line = line.strip().lower()
                if not line or line.startswith('//'):
                    continue  # Skip blanks or comments

                if line[:8] == 'precache':
                    preload_files.add(line)
                    continue

                if line[:2] == '-#':
                    rem_soundscripts.add(line[2:])
                    continue

                if line[:1] == '#':
                    line = line[1:]
                    soundscripts.add(line)

                # We need to add particle systems to a manifest.
                if line.startswith('particles/'):
                    particles.add(line)

                if line[-4:] == '.mdl':
                    additional_files.update({
                        line[:-4] + ext
                        for ext in
                        MDL_ADDITIONAL_EXT
                    })

                files.add(line)

    # Remove guessed files not in the original list.
    additional_files -= files

    # Only generate a soundscript for PeTI maps..
    if is_peti:
        music_data = CONF.find_key('MusicScript', [])
        if music_data.value:
            generate_music_script(music_data, files)
            # Add the new script to the manifest file..
            soundscripts.add('scripts/BEE2_generated_music.txt')

    # We still generate these in hammer-mode - it's still useful there.
    # If no files are packed, no manifest will be added either.
    gen_sound_manifest(soundscripts, rem_soundscripts)
    gen_part_manifest(particles)
    gen_auto_script(preload_files, is_peti)

    inject_names = list(inject_files())

    # Abort packing if no packfiles exist, and no injected files exist either.
    if not files and not inject_names:
        LOGGER.info('No files to pack!')
        return

    LOGGER.info('Files to pack:')
    for file in sorted(files):
        # \t seperates the original and in-pack name if used.
        LOGGER.info(' # "' + file.replace('\t', '" as "') + '"')

    if additional_files and LOGGER.isEnabledFor(logging.DEBUG):
        LOGGER.info('Potential additional files:')
        for file in sorted(additional_files):
            LOGGER.debug(' # "' + file + '"')

    LOGGER.info('Injected files:')
    for _, file in inject_names:
        LOGGER.info(' # "' + file + '"')

    LOGGER.info("Packing Files!")
    bsp_file = BSP(path)
    LOGGER.debug(' - Header read')
    bsp_file.read_header()

    # Manipulate the zip entirely in memory
    zip_data = BytesIO()
    zip_data.write(bsp_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data, mode='a')
    LOGGER.debug(' - Existing zip read')

    zip_write = get_zip_writer(zipfile)

    for file in files:
        pack_file(zip_write, file)

    for file in additional_files:
        pack_file(zip_write, file, suppress_error=True)

    for filename, arcname in inject_names:
        LOGGER.info('Injecting "{}" into packfile.', arcname)
        zip_write(filename, arcname)

    LOGGER.debug(' - Added files')

    zipfile.close()  # Finalise the zip modification

    # Copy the zipfile into the BSP file, and adjust the headers
    bsp_file.replace_lump(
        path,
        BSP_LUMPS.PAKFILE,
        zip_data.getvalue(),  # Get the binary data we need
    )
    LOGGER.debug(' - BSP written!')

    LOGGER.info("Packing complete!")


def find_screenshots():
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


def mod_screenshots():
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
                continue # Ignore other screenshots

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
                if screen != scr_loc:
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


def run_vrad(args):
    "Execute the original VRAD."

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
            (quote(x) if " " in x else x)
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


def main(argv):
    LOGGER.info('BEE2 VRAD hook started!')
    args = " ".join(argv)
    fast_args = argv[1:]
    full_args = argv[1:]

    # The path is the last argument to vrad
    # P2 adds wrong slashes sometimes, so fix that.
    fast_args[-1] = path = os.path.normpath(argv[-1])

    LOGGER.info("Map path is " + path)
    if path == "":
        raise Exception("No map passed!")

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
            # we need to strip these out, otherwise VBSP will get confused
            fast_args.remove(a)
            full_args.remove(a)

    fast_args = ['-bounce', '2', '-noextra'] + fast_args

    # Fast args: -bounce 2 -noextra -game $gamedir $path\$file
    # Final args: -both -final -staticproplighting -StaticPropPolys
    # -textureshadows  -game $gamedir $path\$file

    if not path.endswith(".bsp"):
        path += ".bsp"

    if '-force_peti' in args or '-force_hammer' in args:
        # we have override command!
        if '-force_peti' in args:
            LOGGER.warning('OVERRIDE: Applying cheap lighting!')
            is_peti = True
        else:
            LOGGER.warning('OVERRIDE: Preserving args!')
            is_peti = False
    else:
        # If we don't get the special -force args, check for the name
        # equalling preview to determine if we should convert
        # If that is false, check the config file to see what was
        # specified there.
        is_peti = (
            os.path.basename(path) == "preview.bsp" or
            srctools.conv_bool(CONF['force_full'], False)
        )

    if '-no_pack' not in args:
        pack_content(path, is_peti)
    else:
        LOGGER.warning("Packing files is disabled!")

    if is_peti:
        mod_screenshots()

        LOGGER.info("Forcing Cheap Lighting!")
        run_vrad(fast_args)
    else:
        LOGGER.info("Hammer map detected! Not forcing cheap lighting..")
        run_vrad(full_args)

    LOGGER.info("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    main(sys.argv)
