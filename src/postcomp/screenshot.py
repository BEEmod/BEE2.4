"""Handles modification of the editor screenshot."""
import os
import shutil
from datetime import datetime
from typing import Iterator

import srctools.logger
import utils
from srctools import Property


LOGGER = srctools.logger.get_logger(__name__)

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


def find() -> Iterator[str]:
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


def modify(conf: Property) -> None:
    """Modify the map's screenshot."""
    mod_type = conf['screenshot_type', 'PETI'].lower()

    if mod_type == 'cust':
        LOGGER.info('Using custom screenshot!')
        scr_loc = str(utils.conf_location('screenshot.jpg'))
    elif mod_type == 'auto':
        LOGGER.info('Using automatic screenshot!')
        scr_loc = None
        # The automatic screenshots are found at this location:
        auto_path = os.path.join(
            '..',
            GAME_FOLDER.get(conf['game_id', ''], 'portal2'),
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

        if srctools.conv_bool(conf['clean_screenshots', '0']):
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
        for screen in find():
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
        for screen in find():
            # Make the screenshot writeable, so P2 will replace it
            LOGGER.info('Making "{}" replaceable...', screen)
            utils.unset_readonly(screen)
