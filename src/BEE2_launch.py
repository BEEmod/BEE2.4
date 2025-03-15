"""Run the BEE2 application."""
from multiprocessing import freeze_support, set_start_method
import os
import sys

# We need to add dummy files if these are None - multiprocessing tries to flush
# them.
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf8')
if sys.stdin is None:
    sys.stdin = open(os.devnull, encoding='utf8')

freeze_support()
if __name__ == '__main__':
    # Forking doesn't really work right, stick to spawning a fresh process.
    set_start_method('spawn')

if sys.platform == "darwin":
    # Disable here, can't get this to work.
    sys.modules['pyglet'] = None  # type: ignore


DEFAULT_SETTINGS = {
    'Directories': {
        'package': 'packages/',
    },
    'General': {
        # A token used to indicate the time the current cache/ was extracted.
        # This tells us whether to copy it to the game folder.
        'cache_time': '0',
        # We need this value to detect just removing a package.
        'cache_pack_count': '0',
    },
}

import srctools.logger
from app import localisation, on_error
from pathlib import Path
import utils

if __name__ == '__main__':
    if len(sys.argv) > 1:
        app_name = sys.argv[1].lower()
    else:
        app_name = Path(sys.argv[0]).stem.casefold()
        if 'python' in app_name:
            # Running from source, by default.
            app_name = 'bee2'
    log_name = app_name

    if app_name not in ('backup', 'compiler_settings'):
        log_name = 'bee2'

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

    import app
    from BEE2_config import GEN_OPTS
    import config
    from config.gen_opts import GenOptions

    GEN_OPTS.load()
    GEN_OPTS.set_defaults(DEFAULT_SETTINGS)
    config.APP.read_file(config.APP_LOC)
    conf = config.APP.get_cur_conf(GenOptions)

    # Special case, load in this early, so it applies.
    utils.DEV_MODE = conf.dev_mode
    app.DEV_MODE.value = conf.dev_mode

    localisation.setup(conf.language)
    from app import backup, CompilerPane

    if utils.USE_WX:
        from ui_wx.core import start_main
        test_mod = 'ui_wx.demo'
    else:
        from ui_tk.core import start_main
        test_mod = 'ui_tk.demo'

    if app_name == 'bee2':
        start_main()
    elif app_name == 'backup':
        start_main(backup.init_application)
    elif app_name == 'compiler_settings':
        start_main(CompilerPane.init_application)
    elif app_name.startswith('test_'):
        import importlib
        mod = importlib.import_module(f'{test_mod}.{sys.argv[1].removeprefix('test_')}')
        if utils.USE_WX:
            from wx.lib.inspection import InspectionTool

            inspection = InspectionTool()
            inspection.Show()
        start_main(mod.test)
    else:
        raise ValueError(f'Invalid component name "{app_name}"!')
    # noinspection PyProtectedMember
    if app._WANTS_RESTART:
        # A restart was desired, we're quit completely. Switch to that.
        utils.restart_app(app_name)
