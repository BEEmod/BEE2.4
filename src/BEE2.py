"""Run the BEE2."""

# First do a few things as early as possible.
import utils
import srctools.logger

utils.fix_cur_directory()
# We need to initialise logging as early as possible - that way
# it can record any errors in the initialisation of modules.
import tk_tools
LOGGER = srctools.logger.init_logging(
    str(utils.install_path('logs/BEE2.log')),
    on_error=tk_tools.on_error,
)

utils.setup_localisations(LOGGER)

# BEE2_config creates this config file to allow easy cross-module access
from BEE2_config import GEN_OPTS

from tk_tools import TK_ROOT

import UI
import loadScreen
import paletteLoader
import packageLoader
import gameMan
import logWindow
import img
import music_conf

DEFAULT_SETTINGS = {
    'Directories': {
        'package': 'packages/',
    },
    'General': {
        'preserve_BEE2_resource_dir': '0',
        'allow_any_folder_as_game': '0',
        'play_sounds': '1',
        'show_wip_items': '0',

        # A token used to indicate the time the current cache/ was extracted.
        # This tells us whether to copy it to the game folder.
        'cache_time': '0',
        # We need this value to detect just removing a package.
        'cache_pack_count': '0',
    },
    'Debug': {
        # Log whenever items fallback to the parent style
        'log_item_fallbacks': '0',
        # Print message for items that have no match for a style
        'log_missing_styles': '0',
        # Print message for items that are missing ent_count values
        'log_missing_ent_count': '0',
        # Warn if a file is missing that a packfile refers to
        'log_incorrect_packfile': '0',

        # Show the log window on startup
        'show_log_win': '0',
        # The lowest level which will be shown.
        'window_log_level': 'INFO',
    },
}

GEN_OPTS.load()
GEN_OPTS.set_defaults(DEFAULT_SETTINGS)

loadScreen.main_loader.set_length('UI', 14)
loadScreen.show_main_loader(GEN_OPTS.get_bool('General', 'compact_splash'))

# OS X starts behind other windows, fix that.
if utils.MAC:
    TK_ROOT.lift()

logWindow.init(
    GEN_OPTS.get_bool('Debug', 'show_log_win'),
    GEN_OPTS['Debug']['window_log_level']
)

UI.load_settings()

gameMan.load()
gameMan.set_game_by_name(
    GEN_OPTS.get_val('Last_Selected', 'Game', ''),
    )
gameMan.scan_music_locs()

LOGGER.info('Loading Packages...')
pack_data, package_sys = packageLoader.load_packages(
    GEN_OPTS['Directories']['package'],
    loader=loadScreen.main_loader,
    log_item_fallbacks=GEN_OPTS.get_bool(
        'Debug', 'log_item_fallbacks'),
    log_missing_styles=GEN_OPTS.get_bool(
        'Debug', 'log_missing_styles'),
    log_missing_ent_count=GEN_OPTS.get_bool(
        'Debug', 'log_missing_ent_count'),
    log_incorrect_packfile=GEN_OPTS.get_bool(
        'Debug', 'log_incorrect_packfile'),
    has_tag_music=gameMan.MUSIC_TAG_LOC is not None,
    has_mel_music=gameMan.MUSIC_MEL_VPK is not None,
)

# Load filesystems into various modules
music_conf.load_filesystems(package_sys)
img.load_filesystems(package_sys)
gameMan.load_filesystems(package_sys)

UI.load_packages(pack_data)
LOGGER.info('Done!')

LOGGER.info('Loading Palettes...')
paletteLoader.load_palettes()
LOGGER.info('Done!')

# Check games for Portal 2's basemodui.txt file, so we can translate items.
LOGGER.info('Loading Item Translations...')
for game in gameMan.all_games:
    game.init_trans()

LOGGER.info('Initialising UI...')
UI.init_windows()  # create all windows
LOGGER.info('UI initialised!')

loadScreen.main_loader.destroy()
# Delay this until the loop has actually run.
# Directly run TK_ROOT.lift() in TCL, instead
# of building a callable.
TK_ROOT.tk.call('after', 10, 'raise', TK_ROOT)

TK_ROOT.mainloop()
