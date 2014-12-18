from property_parser import Property
import paletteLoader
import packageLoader
import loadScreen
import gameMan
import UI
import utils

loadScreen.init(UI.win)
loadScreen.length('UI', 8)

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
bee2 = Property.find_key(prop, 'BEE2')

settings['pal_dir']=dirs['palettes', 'palettes\\']
settings['package_dir']=dirs['package', 'packages\\']
settings['load_resources'] = bee2['preserve_BEE2_resource_dir', '1'] == '0'

gameMan.load(Property.find_all(prop, 'games', 'game'))

print('Loading Packages...')
package_data = packageLoader.loadAll(settings['package_dir'], settings)
UI.load_packages(package_data, settings)
print('Done!')

print('Loading Palettes...')
pal=paletteLoader.loadAll(settings['pal_dir'])
UI.load_palette(pal)
print('Done!')

print('Initialising UI...')
UI.initMain() # create all windows

loadScreen.quit()
UI.event_loop()