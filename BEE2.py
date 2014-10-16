from property_parser import Property
import paletteLoader
import UI
import utils

#Loading commands, will load/reload the items/styles/palettes/etc
def load_settings():
  global settings
  settings={}
  with open("config/config.cfg", "r") as f:
    prop=Property.parse(f)
  dirs = Property.find_key(prop, 'directories')
  
  settings['pal_dir']=dirs.find_key('palettes', 'palettes\\').value
  settings['item_dir']=dirs.find_key('items', 'items\\').value
  settings['style_dir']=dirs.find_key('styles', 'styles\\').value

def load_palettes():
  pal=paletteLoader.loadAll(settings['pal_dir'])
  UI.palLoad(pal)

def load_styles():
  pass
  
def load_items(): 
  pass


load_settings()
load_palettes()

UI.initMain() # create all windows
UI.event_loop()