from tkinter import messagebox

import traceback
import time
# BEE2_config creates this config file to allow easy cross-module access
from BEE2_config import GEN_OPTS

from tk_root import TK_ROOT
import UI
import loadScreen
import paletteLoader
import packageLoader
import gameMan

ERR_FORMAT = '''
--------------

{time!s}
{underline}
{exception!s}
'''
loadScreen.main_loader.set_length('UI', 9)

DEFAULT_SETTINGS = {
    'Directories': {
        'palette': 'palettes\\',
        'package': 'packages\\',
    },
    'General': {
        'preserve_BEE2_resource_dir': '0',
        'allow_any_folder_as_game': '0',
        'mute_sounds': '0',
    },
    'Debug': {
        # Show execptions in dialog box when crash occurs
        'show_errors': '0',
        # Log whenever items fallback to the parent style
        'log_item_fallbacks': '0',
        # Print message for items that have no match for a style
        'log_missing_styles': '0',
        # Print message for items that are missing ent_count values
        'log_missing_ent_count': '0',
    },
}
GEN_OPTS.set_defaults(DEFAULT_SETTINGS)

show_errors = False

try:

    UI.load_settings(GEN_OPTS)

    show_errors = GEN_OPTS.get_bool('Debug', 'show_errors')

    # If we have no games, gameMan will quit the app entirely.
    gameMan.load(UI.quit_application, loadScreen.main_loader)

    gameMan.set_game_by_name(
        GEN_OPTS.get_val('Last_Selected', 'Game', ''),
        )

    print('Loading Packages...')
    UI.load_packages(
        packageLoader.load_packages(
            GEN_OPTS['Directories']['package'],
            load_res=not GEN_OPTS.get_bool(
                'General', 'preserve_BEE2_resource_dir'
            ),
            log_item_fallbacks=GEN_OPTS.get_bool(
                'Debug', 'log_item_fallbacks'),
            log_missing_styles=GEN_OPTS.get_bool(
                'Debug', 'log_missing_styles'),
            log_missing_ent_count=GEN_OPTS.get_bool(
                'Debug', 'log_missing_ent_count'),
            )
        )
    print('Done!')

    print('Loading Palettes...')
    UI.load_palette(
        paletteLoader.load_palettes(GEN_OPTS['Directories']['palette']),
        )
    print('Done!')

    print('Loading Item Translations...', end='')
    gameMan.init_trans()
    print('Done')

    print('Initialising UI...')
    UI.init_windows()  # create all windows
    print('Done!')

    loadScreen.main_loader.destroy()
    UI.event_loop()

except Exception as e:
    # Grab Python's traceback, and record it
    # This way we have a log.
    loadScreen.main_loader.destroy()

    err = traceback.format_exc()
    if show_errors:
        # Put it onscreen
        messagebox.showinfo(
            title='BEE2 Error!',
            message=str(e).strip('".')+'!',
            icon=messagebox.ERROR,
            parent=TK_ROOT,
            )

    # Weekday Date Month Year HH:MM:SS AM/PM
    cur_time = time.strftime('%A %d %B %Y %I:%M:%S%p') + ':'

    print('Logging ' + repr(e) + '!')

    # Always log the exception into a file.
    with open('../config/BEE2-error.log', 'a') as log:
        log.write(ERR_FORMAT.format(
            time=cur_time,
            underline='=' * len(cur_time),
            exception=err,
        ))
    # We still want to crash!
    raise
