"""Run the BEE2 application."""
from multiprocessing import freeze_support, set_start_method
import os
import sys

# We need to add dummy files if these are None - multiprocessing tries to flush
# them.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')
if sys.stdin is None:
    sys.stdin = open(os.devnull, 'r')

freeze_support()

if sys.platform == "darwin":
    # Disable here, can't get this to work.
    sys.modules['pyglet'] = None  # type: ignore


import srctools.logger
from app import on_error, TK_ROOT
import utils

if __name__ == '__main__':
    # Forking doesn't really work right, stick to spawning a fresh process.
    set_start_method('spawn')

    if len(sys.argv) > 1:
        log_name = app_name = sys.argv[1].lower()
        if app_name not in ('backup', 'compilepane'):
            log_name = 'bee2'
    else:
        log_name = app_name = 'bee2'

    # We need to initialise logging as early as possible - that way
    # it can record any errors in the initialisation of modules.
    utils.fix_cur_directory()
    LOGGER = srctools.logger.init_logging(
        str(utils.install_path(f'logs/{log_name}.log')),
        __name__,
        on_error=on_error,
    )
    LOGGER.info('Arguments: {}', sys.argv)
    LOGGER.info('Running "{}", version {}:', app_name, utils.BEE_VERSION)

    # Warn if srctools Cython code isn't installed.
    utils.check_cython(LOGGER.warning)

    import localisation
    localisation.setup()

    # Check early on for a common mistake - putting the BEE2 folder directly in Portal 2 means
    # when we export we'll try and overwrite ourselves. Use Steam's appid file as a marker.
    if utils.install_path('../steam_appid.txt').exists() and utils.install_path('.').name.casefold() == 'bee2':
        from app import gameMan
        gameMan.app_in_game_error()
        sys.exit()

    elif app_name == 'bee2':
        from app import BEE2
        BEE2.start_main()
    elif app_name == 'backup':
        from app import backup
        backup.init_application()
        TK_ROOT.mainloop()
    elif app_name == 'compilepane':
        from app import CompilerPane
        CompilerPane.init_application()
        TK_ROOT.mainloop()
    elif app_name.startswith('test_'):
        from app import BEE2
        import importlib
        mod = importlib.import_module('app.' + sys.argv[1][5:])
        BEE2.start_main(getattr(mod, 'test'))
    else:
        raise ValueError(f'Invalid component name "{app_name}"!')
