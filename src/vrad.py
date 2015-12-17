from datetime import datetime
from zipfile import ZipFile
from io import BytesIO

import os
import os.path
import stat
import shutil
import sys
import subprocess

from property_parser import Property
from BSP import BSP, BSP_LUMPS
import utils

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
    # The game's root folder, where screenshots are saved/
    utils.STEAM_IDS['PORTAL2']: 'portal2',
    utils.STEAM_IDS['TWTM']: 'twtm',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
}


def quote(txt):
    return '"' + txt + '"'


def set_readonly(file):
    """Make the given file read-only."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it read-only
    os.chmod(
        file,
        flags & ~
        stat.S_IWUSR & ~
        stat.S_IWGRP & ~
        stat.S_IWOTH
    )


def unset_readonly(file):
    """Set the writeable flag on a file."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it writeable
    os.chmod(
        file,
        flags |
        stat.S_IWUSR |
        stat.S_IWGRP |
        stat.S_IWOTH
    )


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


def pack_file(zipfile, filename):
    """Check multiple locations for a resource file.
    """
    for poss_path in RES_ROOT:
        full_path = os.path.normpath(
            os.path.join(poss_path, filename)
        )
        if os.path.isfile(full_path):
            zipfile.write(
                filename=full_path,
                arcname=filename,
            )
            break
    else:
        LOGGER.warning('"bee2/' + filename + '" not found!')


def pack_content(path):
    """Pack any custom content into the map."""
    files = set()
    try:
        pack_list = open(path[:-4] + '.filelist.txt')
    except (IOError, FileNotFoundError):
        pass
    else:
        with pack_list:
            for line in pack_list:
                files.add(line.strip().lower())

    if '' in files:
        # Allow blank lines in original files
        files.remove('')

    if not files:
        LOGGER.info('No files to pack!')
        return

    LOGGER.info('Files to pack:')
    for file in sorted(files):
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

    for file in files:
        pack_file(zipfile, file)

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

        if utils.conv_bool(CONF['clean_screenshots', '0']):
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
            unset_readonly(screen)
            shutil.copy(scr_loc, screen)
            # Make the screenshot readonly, so P2 can't replace it.
            # Then it'll use our own
            set_readonly(screen)

    else:
        if mod_type != 'peti':
            # Error if we were looking for a screenshot
            LOGGER.warning('"{}" not found!', scr_loc)
        LOGGER.info('Using PeTI screenshot!')
        for screen in find_screenshots():
            # Make the screenshot writeable, so P2 will replace it
            LOGGER.info('Making "{}" replaceable...', screen)
            unset_readonly(screen)


def run_vrad(args):
    "Execute the original VRAD."

    if utils.MAC:
        os_suff = '_osx'
    elif utils.LINUX:
        os_suff = '_linux'
    else:
        os_suff = ''

    joined_args = (
        '"' + os.path.normpath(
            os.path.join(os.getcwd(), "vrad" + os_suff + "_original")
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
            utils.conv_bool(CONF['force_full'], False)
        )

    mod_screenshots()

    if is_peti:
        LOGGER.info("Forcing Cheap Lighting!")
        run_vrad(fast_args)
    else:
        LOGGER.info("Hammer map detected! Not forcing cheap lighting..")
        run_vrad(full_args)

    if '-no_pack' not in args:
        pack_content(path)
    else:
        LOGGER.warning("No items to pack!")
    LOGGER.info("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    try:
        main(sys.argv)
    except Exception as e:
        import logging
        # Log the error, finalise the logs, and then crash.
        LOGGER.exception('Exception Occurred:')
        logging.shutdown()
        raise
