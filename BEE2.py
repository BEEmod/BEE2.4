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
  settings['pal_dir']=Property.find_all(prop, 'directories"palettes')
  if settings['pal_dir']:
    settings['pal_dir']=settings['pal_dir'][0].value
    
  settings['item_dir']=Property.find_all(prop, 'directories"items')
  if settings['item_dir']:
    settings['item_dir']=settings['item_dir'][0].value
     
  settings['style_dir']=Property.find_all(prop, 'directories"styles')
  if settings['style_dir']:
    settings['style_dir']=settings['style_dir'][0].value


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