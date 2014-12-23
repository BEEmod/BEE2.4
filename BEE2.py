from property_parser import Property
from config import ConfigFile

import paletteLoader
import packageLoader
import gameMan

import loadScreen
import UI

import utils

loadScreen.init(UI.win)
loadScreen.length('UI', 8)

default_settings = {
    'Directories' : {
        'palette' : 'palettes\\',
        'package' : 'packages\\',
        },
    'General' : {
        'preserve_BEE2_resource_dir' : '0',
        'allow_any_folder_as_game' : '0',
        },
}

settings = ConfigFile('config.cfg')
settings.set_defaults(default_settings)

UI.load_settings(settings)
gameMan.load()
gameMan.set_game_by_name(settings.get_val('Last_Selected','Game', ''))

print('Loading Packages...')
package_data = packageLoader.loadAll(
    settings['Directories']['package'],
    not settings.get_bool('General','preserve_BEE2_resource_dir'))
UI.load_packages(package_data)
print('Done!')

print('Loading Palettes...')
pal=paletteLoader.loadAll(settings['Directories']['palette'])
UI.load_palette(pal)
print('Done!')

print('Initialising UI...')
UI.initMain() # create all windows

loadScreen.quit()
UI.event_loop()