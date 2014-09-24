import property_parser
import UI

#Loading commands, will load/reload the items/styles/palettes/etc
def load_settings():
  global settings
  with open("bin/config.cfg", "r") as f:
    settings=property_parser.parse(f)
  print(settings)

def load_palettes():
  pass

def load_styles():
  pass
  
def load_items():
  pass


def newPal(name): # TODO: make a new palette based on a name
  print("Make palette:",name)
  pass
    
def savePal(name):
  print('We should save the palette as ' + name)
  # TODO: actually load
  load_palettes() # reload to make it show up

#load_settings()
load_palettes()
UI.initMain() # create all windows