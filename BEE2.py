from tkinter import * # ui library
import UI

#Loading commands, will load/reload the items/styles/palettes/etc
def load_settings():
  pass

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

UI.initMain() # create all windows