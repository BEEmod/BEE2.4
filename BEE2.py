from configparser import ConfigParser

from property_parser import Property
import paletteLoader
import packageLoader
import loadScreen
import gameMan
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
        }
}

settings = ConfigParser()

def save_settings():
    with open('config/config.cfg', 'w') as conf:
        settings.write(conf)
        
settings.save = save_settings
        
try:
    with open("config/config.cfg", "r") as conf:
        settings.read_file(conf)
except FileNotFoundError:
    print("Config not found! Using defaults...")
    # If we fail, just continue - we just use the default values
    
# Set the default values if the settings file has no values defined
for sect, values in default_settings.items():
    if sect not in settings:
        settings[sect] = {}
    for set, default in values.items():
        if set not in settings[sect]:
            settings[sect][set] = default
settings.save()

gameMan.load_config()
gameMan.load()

print('Loading Packages...')
package_data = packageLoader.loadAll(settings['Directories']['package'], settings['General']['preserve_BEE2_resource_dir'])
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