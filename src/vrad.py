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

CONF = Property('Config')
SCREENSHOT_DIR = os.path.join(
    '..',
    'portal2',  # This is hardcoded into P2, it won't change for mods.
    'puzzles',
    # Then the <random numbers> folder
)
# Locations of resources we need to pack
RES_ROOT = os.path.join(
    '..',
    'bee2_dev',
)


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
    utils.con_log('Loading Settings...')
    try:
        with open("bee2/vrad_config.cfg") as config:
            CONF = Property.parse(config, 'bee2/vrad_config.cfg').find_key(
                'Config', []
            )
    except FileNotFoundError:
        pass
    utils.con_log('Config Loaded!')


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
        utils.con_log('No files to pack!')
        return

    utils.con_log('Files to pack:')
    for file in sorted(files):
        utils.con_log(' # "' + file + '"')

    utils.con_log("Packing Files!")
    bsp_file = BSP(path)
    utils.con_log(' - Header read')
    bsp_file.read_header()

    # Manipulate the zip entirely in memory
    zip_data = BytesIO()
    zip_data.write(bsp_file.get_lump(BSP_LUMPS.PAKFILE))
    zipfile = ZipFile(zip_data, mode='a')
    utils.con_log(' - Existing zip read')

    for file in files:
        full_path = os.path.normpath(
            os.path.join(RES_ROOT, file)
        )
        if os.path.isfile(full_path):
            zipfile.write(
                filename=full_path,
                arcname=file,
            )
        else:
            utils.con_log('"' + full_path + '" not found!')
    utils.con_log(' - Added files')

    zipfile.close()  # Finalise the zip modification

    # Copy the zipfile into the BSP file, and adjust the headers
    bsp_file.replace_lump(
        path,
        BSP_LUMPS.PAKFILE,
        zip_data.getvalue(),  # Get the binary data we need
    )
    utils.con_log(' - BSP written!')

    utils.con_log("Packing complete!")


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
        utils.con_log('Using custom screenshot!')
        scr_loc = CONF['screenshot', '']
    elif mod_type == 'auto':
        utils.con_log('Using automatic screenshot!')
        scr_loc = None
        # The automatic screenshots are found at this location:
        auto_path = os.path.join(
            '..',
            'portal2',
            'screenshots'
        )
        # We need to find the most recent one. If it's named
        # "previewcomplete", we want to ignore it - it's a flag
        # to indicate the map was playtested correctly.
        screens = [
            os.path.join(auto_path, path)
            for path in
            os.listdir(auto_path)
        ]
        screens.sort(
            key=os.path.getmtime,
            reverse=True,
            # Go from most recent to least
        )
        playtested = False
        for scr_shot in screens:
            utils.con_log(scr_shot)
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
                utils.con_log('Screenshot "{scr}" too old ({diff!s})'.format(
                    scr=scr_shot, diff=diff
                ))
                continue

            # If we got here, it's a good screenshot!
            utils.con_log('Chosen "{}"'.format(scr_shot))
            utils.con_log('Map Playtested:', playtested)
            scr_loc = scr_shot
            break
        else:
            # If we get to the end, we failed to find an automatic
            # screenshot!
            utils.con_log('No Auto Screenshot found!')
            mod_type = 'peti'  # Suppress the "None not found" error

        if utils.conv_bool(CONF['clean_screenshots', '0']):
            utils.con_log('Cleaning up screenshots...')
            # Clean up this folder - otherwise users will get thousands of
            # pics in there!
            for screen in screens:
                if screen != scr_loc:
                    os.remove(screen)
            utils.con_log('Done!')
    else:
        # PeTI type, or something else
        scr_loc = None

    if scr_loc is not None and os.path.isfile(scr_loc):
        # We should use a screenshot!
        for screen in find_screenshots():
            utils.con_log('Replacing "{}"...'.format(screen))
            # Allow us to edit the file...
            unset_readonly(screen)
            shutil.copy(scr_loc, screen)
            # Make the screenshot readonly, so P2 can't replace it.
            # Then it'll use our own
            set_readonly(screen)

    else:
        if mod_type != 'peti':
            # Error if the screenshot doesn't exist
            utils.con_log('"{}" not found!'.format(scr_loc))
        utils.con_log('Using PeTI screenshot!')
        for screen in find_screenshots():
            # Make the screenshot writeable, so P2 will replace it
            utils.con_log('Making "{}" replaceable...'.format(screen))
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
    utils.con_log("Calling original VRAD...")
    utils.con_log(joined_args)
    code = subprocess.call(
        joined_args,
        stdout=None,
        stderr=subprocess.PIPE,
        shell=True,
    )
    if code == 0:
        utils.con_log("Done!")
    else:
        utils.con_log("VRAD failed! (" + str(code) + ")")
        sys.exit(code)


def main(argv):
    utils.con_log('BEE2 VRAD hook started!')
    args = " ".join(argv)
    fast_args = argv[1:]
    full_args = argv[1:]

    path = argv[-1]  # The path is the last argument to vrad
    fast_args[-1] = os.path.normpath(path)

    utils.con_log("Map path is " + path)
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
            utils.con_log('OVERRIDE: Applying cheap lighting!')
            is_peti = True
        else:
            utils.con_log('OVERRIDE: Preserving args!')
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
        utils.con_log("Forcing Cheap Lighting!")
        run_vrad(fast_args)
    else:
        utils.con_log("Hammer map detected! Not forcing cheap lighting..")
        run_vrad(full_args)

    if '-no_pack' not in args:
        pack_content(path)
    else:
        utils.con_log("No items to pack!")
    utils.con_log("BEE2 VRAD hook finished!")

if __name__ == '__main__':
    main(sys.argv)