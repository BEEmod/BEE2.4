from BEE2_config import GEN_OPTS

import UI
import loadScreen
import paletteLoader
import packageLoader
import gameMan

loadScreen.length('UI', 9)

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
    }

UI.load_settings(GEN_OPTS)

# If we have no games, gameMan will quit the app entirely.
gameMan.load(UI.quit_application, loadScreen.win)

gameMan.set_game_by_name(
    GEN_OPTS.get_val('Last_Selected', 'Game', ''),
    )

print('Loading Packages...')
UI.load_packages(
    packageLoader.load_packages(
        GEN_OPTS['Directories']['package'],
        not GEN_OPTS.get_bool('General', 'preserve_BEE2_resource_dir'),
        )
    )
print('Done!')

print('Loading Palettes...')
UI.load_palette(
    paletteLoader.load_palettes(GEN_OPTS['Directories']['palette']),
    )
print('Done!')

print('Initialising UI...')
UI.init_windows()  # create all windows
print('Done!')

loadScreen.close_window()
UI.event_loop()
