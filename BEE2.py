from property_parser import Property
import paletteLoader
import packageLoader
import UI
import utils

global settings
settings={}
with open("config/config.cfg", "r") as f:
    prop=Property.parse(f)
dirs = Property.find_key(prop, 'directories')

settings['pal_dir']=dirs.find_key('palettes', 'palettes\\').value
settings['package_dir']=dirs.find_key('package', 'packages\\').value

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