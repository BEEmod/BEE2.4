# Fix a bug with multiprocessing, where it tries to flush stdout
import sys, io
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

from multiprocessing import freeze_support

if __name__ == '__main__':
    freeze_support()  # Make multiprocessing work correctly when frozen

    import utils
    if utils.MAC or utils.LINUX:
        import os
        # Change directory to the location of the executable
        # Otherwise we can't find our files!
        # The Windows executable does this automatically.
        os.chdir(os.path.dirname(sys.argv[0]))

    from tkinter import messagebox

    import traceback
    import time
    # BEE2_config creates this config file to allow easy cross-module access
    from BEE2_config import GEN_OPTS

    from tk_tools import TK_ROOT
    import UI
    import loadScreen
    import paletteLoader
    import packageLoader
    import gameMan
    import extract_packages
    ERR_FORMAT = '''
    --------------

    {time!s}
    {underline}
    {exception!s}
    '''

    DEFAULT_SETTINGS = {
        'Directories': {
            'palette': 'palettes/',
            'package': 'packages/',
        },
        'General': {
            'preserve_BEE2_resource_dir': '0',
            'allow_any_folder_as_game': '0',
            'mute_sounds': '0',
            'show_wip_items': '0',
        },
        'Debug': {
            # Show exceptions in dialog box when crash occurs
            'show_errors': '0',
            # Log whenever items fallback to the parent style
            'log_item_fallbacks': '0',
            # Print message for items that have no match for a style
            'log_missing_styles': '0',
            # Print message for items that are missing ent_count values
            'log_missing_ent_count': '0',
        },
    }
    loadScreen.main_loader.set_length('UI', 14)
    loadScreen.main_loader.show()

    if utils.MAC:
        TK_ROOT.lift()

    GEN_OPTS.load()
    GEN_OPTS.set_defaults(DEFAULT_SETTINGS)

    show_errors = False
    try:

        UI.load_settings()

        show_errors = GEN_OPTS.get_bool('Debug', 'show_errors')

        gameMan.load()
        gameMan.set_game_by_name(
            GEN_OPTS.get_val('Last_Selected', 'Game', ''),
            )

        print('Loading Packages...')
        pack_data = packageLoader.load_packages(
            GEN_OPTS['Directories']['package'],
            log_item_fallbacks=GEN_OPTS.get_bool(
                'Debug', 'log_item_fallbacks'),
            log_missing_styles=GEN_OPTS.get_bool(
                'Debug', 'log_missing_styles'),
            log_missing_ent_count=GEN_OPTS.get_bool(
                'Debug', 'log_missing_ent_count'),
        )
        UI.load_packages(pack_data)
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

        if GEN_OPTS.get_bool('General', 'preserve_BEE2_resource_dir'):
            extract_packages.done_callback()
        else:
            extract_packages.start_copying(pack_data['zips'])

        TK_ROOT.mainloop()

    except Exception as e:
        # Grab Python's traceback, and record it.
        # This way we have a log.
        loadScreen.main_loader.destroy()

        err = traceback.format_exc()
        if show_errors:
            # Put it onscreen
            messagebox.showinfo(
                title='BEE2 Error!',
                message=str(e).strip('".')+'!',
                icon=messagebox.ERROR,
                )

        # Weekday Date Month Year HH:MM:SS AM/PM
        cur_time = time.strftime('%A %d %B %Y %I:%M:%S%p') + ':'

        print('Logging ' + repr(e) + '!')

        # Always log the exception into a file.
        with open('../BEE2-error.log', 'a') as log:
            log.write(ERR_FORMAT.format(
                time=cur_time,
                underline='=' * len(cur_time),
                exception=err,
            ))
        # We still want to crash!
        raise
