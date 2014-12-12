from property_parser import Property
import paletteLoader
import packageLoader
import gameMan
import UI
import utils

global settings
settings={}

def save_settings():
    new_props = Property('', [
        Property('directories', [ 
            Property('palettes', settings['pal_dir']),
            Property('package', settings['package_dir']),
        ]),
        Property('Games', gameMan.as_props()),
    ])
    with open("config/config.cfg", "w") as conf:
        for prop in new_props:
            for line in prop.to_strings():
                conf.write(line)

with open("config/config.cfg", "r") as conf:
    prop=Property.parse(conf, "config/config.cfg")
dirs = Property.find_key(prop, 'directories')

settings['pal_dir']=dirs['palettes', 'palettes\\']
settings['package_dir']=dirs['package', 'packages\\']

gameMan.load(Property.find_all(prop, 'games', 'game'))

print('Loading Packages...')
package_data = packageLoader.loadAll(settings['package_dir'])
print('Done!')
UI.load_packages(package_data)
print('Loading Palettes...')
pal=paletteLoader.loadAll(settings['pal_dir'])
print('Done!')
UI.load_palette(pal)

UI.initMain() # create all windows
UI.event_loop()