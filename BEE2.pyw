from config import ConfigFile

import UI
import loadScreen
import paletteLoader
import packageLoader
import gameMan

loadScreen.init(UI.win)
loadScreen.length('UI', 8)

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

settings = ConfigFile('config.cfg')
settings.set_defaults(DEFAULT_SETTINGS)

UI.load_settings(settings)

# If we have no games, gameMan will quit the app entirely.
gameMan.load(UI.quit_application, loadScreen.win)

gameMan.set_game_by_name(
    settings.get_val('Last_Selected', 'Game', ''),
    )

print('Loading Packages...')
UI.load_packages(
    packageLoader.load_packages(
        settings['Directories']['package'],
        not settings.get_bool('General', 'preserve_BEE2_resource_dir'),
        )
    )
print('Done!')

print('Loading Palettes...')
UI.load_palette(
    paletteLoader.load_palettes(settings['Directories']['palette']),
    )
print('Done!')

print('Initialising UI...')
UI.initMain()  # create all windows
print('Done!')

loadScreen.close_window()
UI.event_loop()
