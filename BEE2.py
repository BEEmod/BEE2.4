from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from tkinter import messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc
from tkinter_png import * # png library for TKinter
import os.path
import random
import math

def loadIcon(name): # load in a palette icon, ensuring the correct size
  name= "images/pal_test/" + name + ".png"
  if not os.path.isfile(name):
    print("ERROR: \"" + name + "\" does not exist!")
    return img_error
  tmp=PngImageTk(name)
  tmp.convert()
  img=tmp.image
  if img.width() != 64 or img.height() != 64:
    print("ERROR: \"" + name + "\" is not 64x64!")
    return img_error
  else:
    return img
window=Tk()
img_error=loadIcon('pal_unknown') # If image is not readable, use this instead
frames={} #Holds frames that we need to deal with later
UI={} # Other ui elements we need to access
pal_picked={} # 2d array of the picker icons
pal_items=[] # array of the "all items" icons
FILTER_CATS=('author','package','tags')
FilterBoxes={} # the various checkboxes for the filters
FilterBoxes_all={}
FilterVars={} # The variables for the checkboxes
FilterVars_all={}
Settings=None
ItemsBG="#CDD0CE" # Colour of the main background to match the menu image
selectedPalette = 0
selectedGame=0
PalEntry_TempText="New Palette>"
PalEntry = StringVar(value=PalEntry_TempText)
selectedGame_radio = IntVar(value=0)
selectedPalette_radio = IntVar(value=0) # fake value the menu radio buttons set

testImg  = (loadIcon('portal_button'), # test palette images
            loadIcon('box_socket'),
            loadIcon('stairs'),
            loadIcon('flipper'),
            loadIcon('faithplate'),
            loadIcon('goo'),
            loadIcon('frankenturret'),
            loadIcon('item_dropper'),
            loadIcon('turret'),
            loadIcon('hard_light_emitter'),
            loadIcon('laser_receptacle'),
            loadIcon('light_panel'),
            loadIcon('paintsplat_water'),
            loadIcon('paintsplat_speed'),
            loadIcon('paintsplat_portal'),
            loadIcon('tbeam'),
            loadIcon('companion_cube'),
            loadIcon('airlock'))

# UI vars, TODO: most should be generated on startup
palettes=('Portal 2','Empty','Palette 1', 'Portal 2 Collapsed')
paletteReadOnly=('Empty','Portal 2') # Don't let the user edit these, they're special
paletteText = StringVar(value=palettes)
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files
skyboxText = ('[Default]','None','Overgrown Sunlight', 'Darkness', 'Reactor Fires', 'Clean BTS', 'Wheatley BTS', 'Factory BTS', 'Portal 1 BTS', 'Art Therapy BTS', 'Test Shaft', 'Test Sphere')
voiceText = ('[Default]', 'None', "50's Cave","60's Cave", "70's Cave", "80's Cave", "Cave", "Cave and GLaDOS", "GLaDOS", "Portal 1 GLaDOS (ported)", "Portal 1 GLaDOS", "Art Therapy GLaDOS", "Apocalypse GLaDOS", "Apocalypse Announcer", "Announcer", "BTS Announcer")
musicText = ('[Default]','None', 'Random PeTI', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3', 'Robot Waiting Room 4', 'Robot Waiting Room 5', 'Robot Waiting Room 6', 'You are Not Part of the Control Group', 'Vitrification Order', 'The Reunion', 'Music of the Spheres 1', 'Music of the Spheres 2', 'The Future Starts With You')
authorText = ('BenVlodgi & Rantis','HMW','Carl Kenner', 'Felix Griffin', 'Bisqwit', 'TeamSpen210')
packageText = ('BEEMOD', 'BEE2', 'HMW', 'Stylemod', 'FGEmod')
tagText = ('Test Elements', 'Panels', 'Geometry', 'Logic', 'Custom')
# Examples, we want to set some in styles
games = ('common/portal2', 'common/aperturetag')
gamesDisplay = ('Portal 2', 'Aperture Tag') #TODO: We probably want to have the user navigate to gameinfo.txt / find it from the exe to get these names

#Loading commands, will load/reload the items/styles/palettes/etc
def load_settings():
  pass

def load_palettes():
  pass

def load_styles():
  pass
  
def load_items():
  pass
  
#------
# Perform the actual export to editoritems
def export():
  pass 
  
#------

def menu_quit():
  window.destroy()

def menu_newPal():
  newPal(simpledialog.askstring("BEE2 - New Palette", "Enter a name:"))
  
def newPal_textbox(e):
  newPal(PalEntry.get())

def newPal(name): # TODO: make a new palette based on a name
  print("Make palette:",name)
  pass
  save()
  
def pal_remTempText(e):
  if PalEntry.get() == PalEntry_TempText:
    PalEntry.set("")

def pal_addTempText(e):
  if PalEntry.get() == "":
    PalEntry.set(PalEntry_TempText) 

def saveAs():
  name=""
  while 1:
    name=simpledialog.askstring("BEE2 - Save Palette", "Enter a name:")
    if name in paletteReadOnly:
      messagebox.showinfo(message='The palette \"'+name+'\" cannot be overwritten. Choose another name.')
    elif name == None:
      return
    else:
      break
  savePal(name)
  
def save():
  pal=palettes[selectedPalette]
  if pal in paletteReadOnly:
    saveAs() # If it's readonly, prompt for a name and save somewhere else
  else:
    savePal(pal) # overwrite it
    
def savePal(name):
  print('We should save the palette as ' + name)
  # TODO: actually load
  load_palettes() # reload to make it show up
  
def demoMusic():
  messagebox.showinfo(message='This would play the track selected for a few seconds.')
  
def setPal_listbox(e):
  global selectedPalette
  selectedPalette = UI['palette'].curselection()[0]
  selectedPalette_radio.set(selectedPalette)
  setPalette()
  
def setPal_radio():
  global selectedPalette
  selectedPalette = selectedPalette_radio.get()
  UI['palette'].selection_clear(0,len(palettes))
  UI['palette'].selection_set(selectedPalette)
  setPalette()

def setGame():
  global selectedGame
  selectedGame = selectedGame_radio.get()
  print(selectedGame)
  window.title('BEE2 - '+gamesDisplay[selectedGame])

def setPalette():
  print("Palette chosen: ["+ str(selectedPalette) + "] = " + palettes[selectedPalette])
  # TODO: Update the listbox/menu to match, and reload the new palette.

def filterExpand(e):
  frames['filter_expanded'].grid(row=2, column=0, columnspan=3)
  frames['filter']['borderwidth']=4

def filterContract(e):
  frames['filter_expanded'].grid_remove()
  frames['filter']['borderwidth']=0
  
def updateFilters():
  # First update the 'all' checkboxes to make half-selected if not fully selected.
  for cat in FILTER_CATS: # do for each
    no_alt=True
    value=FilterVars[cat][0].get() # compare to the first one, this will check if they are all the same
    for i in FilterVars[cat]:
      if FilterVars[cat][i].get() != value:
        FilterBoxes_all[cat].state(['alternate']) # make it the half-selected state, it doesn't match
        no_alt=False
        break
    if no_alt:
      FilterBoxes_all[cat].state(['!alternate']) # no alternate if they are all the same
      FilterVars_all[cat].set(value)
      
  #TODO: This should check all the filter checkboxes, and change what is actually shown in the list of items.

def filterAllCallback(col): # This sets all items in a category to true/false, then updates the item list
  val=FilterVars_all[col].get()
  for i in FilterVars[col]:
    FilterVars[col][i].set(val)
  updateFilters()

# UI functions, each accepts the parent frame to place everything in. initMainWind generates the main frames that hold all the panes to make it easy to move them around if needed
def initPalette(f):
  ttk.Label(f, text="Palettes", anchor="center").grid(row=0, column=0, sticky="EW")
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, sticky="EW", pady=5)
  UI['palette']=Listbox(f, listvariable=paletteText, width=10)
  UI['palette'].grid(row=2,column=0, sticky="NSEW")
  UI['palette'].bind("<<ListboxSelect>>", setPal_listbox)
  UI['palette'].selection_set(0)
  
  UI['newBox']=ttk.Entry(f, textvariable=PalEntry)
  UI['newBox'].grid(row=3, column=0) # User types in and presses enter to create
  UI['newBox'].bind("<Return>", newPal_textbox)
  UI['newBox'].bind("<FocusIn>", pal_remTempText)
  UI['newBox'].bind("<FocusOut>", pal_addTempText)
  ttk.Button(f, text="-").grid(row=4, column=0) # Delete (we probably don't want to allow deleting "None" or "Portal 2")

def initOption(f):
  ttk.Label(f, text="Options").grid(row=0, column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, sticky="EW", pady=5)
  ttk.Button(f, width=10, text="Save", command=save).grid(row=2, column=0)
  ttk.Button(f, width=10, text="Save as", command=saveAs).grid(row=3, column=0)
  ttk.Button(f, width=10, text="Export...").grid(row=4, column=0, pady=(0, 10))  
  
  ttk.Label(f, text="Properties").grid(row=5,column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=6, column=0, sticky="EW", pady=5)
  props=ttk.Frame(f)
  props.grid(row=7, column=0)
  
  ttk.Label(props, text="Style: ").grid(row=0, column=0)
  UIStyle=ttk.Combobox(props, values=styleText)
  UIStyle.current(5)
  UIStyle.grid(row=0, column=1, columnspan=2, sticky="EW")
  
  ttk.Label(props, text="Music: ").grid(row=1, column=0)
  UIMusic=ttk.Combobox(props, values = musicText)
  UIMusic.grid(row=1, column=1)
  UIMusic.current(0)
  ttk.Button(props, text=">", command=demoMusic, width='4pt').grid(row=1,column=2)
  
  ttk.Label(props, text="Skybox: ").grid(row=2, column=0)
  UISky=ttk.Combobox(props, values=skyboxText)
  UISky.current(0)
  UISky.grid(row=2, column=1, columnspan=2, sticky="EW")
  
  ttk.Label(props, text="Voice: ").grid(row=3, column=0)
  UIVoice=ttk.Combobox(props, values=voiceText)
  UIVoice.current(0)
  UIVoice.grid(row=3, column=1, columnspan=2, sticky="EW")
  
def initStyleOpt(f):
  ttk.Label(f, text="Style Options").grid(row=0, column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, sticky="EW", pady=5)
  #This should automatically switch to match different styles
  frmAll=ttk.Labelframe(f, text="All")
  frmAll.grid(row=2, column=0, sticky="EW")
  
  frmOld=ttk.Labelframe(f, text="Old Aperture")
  frmOld.grid(row=3, column=0, sticky="EW")
  
  frm50s=ttk.Labelframe(f, text="50s")
  frm50s.grid(row=4, column=0, sticky="EW")
  
  frm80s=ttk.Labelframe(f, text="80s")
  frm80s.grid(row=5, column=0, sticky="EW")
  
  frmOver=ttk.Labelframe(f, text="Overgrown")
  frmOver.grid(row=5, column=0, sticky="EW")
  
  ttk.Checkbutton(frmAll, text="Multiverse Cave").grid(row=0, column=0, sticky="W")
  
  ttk.Checkbutton(frmOld, text="Real Observation Rooms").grid(row=0, column=0, sticky="W")
  ttk.Checkbutton(frmOld, text="Gel-Faith-Plates").grid(row=1, column=0, sticky="W")
  
  ttk.Checkbutton(frm50s, text="Recessed Buttons").grid(row=0, column=0, sticky="W")  
  ttk.Checkbutton(frm80s, text="Opened Sphere").grid(row=0, column=0, sticky="W")
  ttk.Checkbutton(frmOver, text="Have entry/exit puzzles").grid(row=0, column=0, sticky="W")

def initPreview(f):
  global previewImg, picker_canvas
  tmp=PngImageTk('images/menu.png')
  tmp.convert()
  previewImg  = tmp.image
  #image with the ingame items palette, needs to be global to stop garbage collection
  f['image'] = previewImg
  ttk.Label(f, text="Item: Button").place(x=30,y=557)
  for x in range(0,4):
    pal_picked[x]={}
    for y in range(0,8):
      pal_picked[x][y]=ttk.Label(f, image=random.choice(testImg))
      pal_picked[x][y].place(x=(x*65+27),y=(y*65+37))
  
def initPicker(f):
  global frmScroll, pal_canvas
  ttk.Label(f, text="All Items: ", anchor="center").grid(row=0, column=0, sticky="EW")
  cframe=ttk.Frame(f,borderwidth=4, relief="sunken")
  cframe.grid(row=1, column=0, sticky="NSEW")
  f.rowconfigure(1, weight=1)
  f.columnconfigure(0, weight=1)
  f.columnconfigure(1, weight=1)
  pal_canvas=Canvas(cframe)
  pal_canvas.grid(row=0, column=0, sticky="NSEW") # need to use a canvas to allow scrolling
  cframe.rowconfigure(0, weight=1)
  cframe.columnconfigure(0, weight=1, min=40)
  scroll = ttk.Scrollbar(cframe, orient=VERTICAL, command=pal_canvas.yview)
  scroll.grid(column=1, row=0, sticky="NS")
  pal_canvas['yscrollcommand'] = scroll.set
  frmScroll=ttk.Frame(pal_canvas, width=320, height=1950)
  pal_canvas.create_window(1, 1, window=frmScroll, anchor="nw")
  for unused in range(0,random.randrange(50,150)):
    pal_items.append(ttk.Label(frmScroll, image=random.choice(testImg))) # init with test objects
  f.bind("<Configure>",flowPicker)
  

def flowPicker(e):
  global frmScroll
  frmScroll.update()
  frames['filter']['width']=pal_canvas.winfo_width()
  width=(pal_canvas.winfo_width()-10) // 65
  if width <1:
    width=1 # we got way too small, prevent division by zero
  pal_canvas['scrollregion'] = (0, 0, width*65, math.ceil(len(pal_items)/width)*65+2) 
  for i in range(0,len(pal_items)):
      pal_items[i].place(x=((i%width) *65+1),y=((i//width)*65+1))
  
def initFilterCol(cat, f, names):
  FilterBoxes[cat]={}
  FilterVars[cat]={}
  FilterVars_all[cat]=IntVar(value=1)
  
  FilterBoxes_all[cat]=ttk.Checkbutton(f, text='All', onvalue=1, offvalue=0,  command=lambda: filterAllCallback(cat), variable=FilterVars_all[cat]) # We pass along the name of the category, so the function can figure out what to change.
  FilterBoxes_all[cat].grid(row=1, column=0, sticky=W)
  
  val=0
  for name in names:
    FilterVars[cat][val]=IntVar(value=1)
    FilterBoxes[cat][val]=ttk.Checkbutton(f, text=name, command=updateFilters, variable=FilterVars[cat][val])
    FilterBoxes[cat][val]['variable']=FilterVars[cat][val]
    FilterBoxes[cat][val].grid(row=val+2, column=0, sticky=W, padx=(4,0))
    val+=1
  
def initFilter(f):

  ttk.Label(f, text="Filters:", anchor="center").grid(row=0, column=0, columnspan=3, sticky="EW")
  f.columnconfigure(0, weight=1)
  f.columnconfigure(1, weight=1)
  f.columnconfigure(2, weight=1)
  f2=ttk.Frame(f)
  frames['filter_expanded']=f2
  # Not added to window, we add it below the others to expand the lists
  
  f.bind("<Enter>", filterExpand)
  f.bind("<Leave>", filterContract)
  
  cat=ttk.Labelframe(f2, text="Categories")
  cat.grid(row=2, column=0, sticky="NS")
  pack=ttk.Labelframe(f2, text="Packages")
  pack.grid(row=2, column=1, sticky="NS")
  tags=ttk.Labelframe(f2, text="Tags")
  tags.grid(row=2, column=2, sticky="NS")
  FilterBoxes['author']  = initFilterCol('author', cat, authorText)
  FilterBoxes['package'] = initFilterCol('package', pack, packageText)
  FilterBoxes['tags']    = initFilterCol('tags', tags, tagText)

def initMenuBar(win):
  bar=Menu(win)
  win['menu']=bar
  win.option_add('*tearOff', False) #Suppress ability to make each menu a separate window - old TK behaviour
  
  menuFile=Menu(bar, name='apple') #Name is used to make this the special 'BEE2' menu item on Mac
  bar.add_cascade(menu=menuFile, label='File')
  menuFile.add_command(label="Export", command=export)
  menuFile.add_command(label="Find Game")
  menuFile.add_command(label="Remove Game")
  menuFile.add_separator()
  val=0
  for name in gamesDisplay: # Add a set of options to pick the palette into the menu system
    menuFile.add_radiobutton(label=name, variable=selectedGame_radio, value=val, command=setGame)
    val+=1
  
  menuFile.add_separator()
  menuFile.add_command(label="Quit", command=menu_quit) 
  
  menuPal=Menu(bar)
  
  bar.add_cascade(menu=menuPal, label='Palette')
  menuPal.add_command(label='New...', command=menu_newPal)
  menuPal.add_command(label='Clear')
  menuPal.add_separator()
  val=0
  for name in palettes: # Add a set of options to pick the palette into the menu system
    menuPal.add_radiobutton(label=name, variable=selectedPalette_radio, value=val, command=setPal_radio)
    val+=1
  
  menuHelp=Menu(bar, name='help') # Name for Mac-specific stuff
  bar.add_cascade(menu=menuHelp, label='Help')
  menuHelp.add_command(label='About') # Authors etc
  menuHelp.add_command(label='Quotes') # show the list of quotes

  setGame()

def initMainWind(win): # Generate the main window frames
  # Will probably want to move into a class or something
  window.call('wm', 'iconbitmap', window._w, '-default', 'BEE2.ico') # set the window icon
  
  initMenuBar(win)
  
  UIbg=Frame(win, bg=ItemsBG)
  UIbg.grid(row=0,column=0, sticky=(N,S,E,W))
  win.columnconfigure(0, weight=1)
  win.rowconfigure(0, weight=1)
  
  UIbg.rowconfigure(0, weight=1)
  
  splitFrame=Frame(UIbg, bg=ItemsBG)
  splitFrame.grid(row=0, column=0, sticky="NSEW", padx=2, pady=5)
  
  paletteFrame=ttk.Frame(splitFrame, borderwidth=4, relief="raised", padding=5)
  paletteFrame.grid(row=0, column=0, sticky="NW", padx=2, pady=5)
  paletteFrame.columnconfigure(0, weight=1)
  splitFrame.rowconfigure(0, weight=1)
  initPalette(paletteFrame)
  
  optionFrame=ttk.Frame(splitFrame, padding=5, borderwidth=4, relief="raised")
  optionFrame.grid(row=1, column=0, columnspan=2, sticky=S)
  initOption(optionFrame)
  
  frames['styleOpt']=ttk.Frame(splitFrame, padding=5, borderwidth=4, relief="raised")
  frames['styleOpt'].grid(row=0, column=1, sticky="NE", pady=(10,0))
  initStyleOpt(frames['styleOpt'])
  
  previewFrame=ttk.Label(UIbg)
  previewFrame.grid(row=0, column=3, sticky=(N,W), padx=(2,5),pady=5)
  UIbg.rowconfigure(1, weight=1)
  initPreview(previewFrame)
  
  ttk.Separator(UIbg, orient=VERTICAL).grid(row=0, column=4, sticky="NS", padx=10, pady=10)
  
  pickSplitFrame=Frame(UIbg, bg=ItemsBG)
  pickSplitFrame.grid(row=0, column=5, sticky="NS", padx=5, pady=5)
  UIbg.columnconfigure(5, weight=1)
  
  frames['filter']=ttk.Frame(pickSplitFrame, padding=5, borderwidth=0, relief="raised")
  frames['filter'].place(x=0,y=0, relwidth=1) # This will sit on top of the palette section, spanning from left to right
  initFilter(frames['filter'])
  
  frames['picker']=ttk.Frame(pickSplitFrame, padding=(5,40,5,5), borderwidth=4, relief="raised")
  frames['picker'].grid(row=0, column=0, sticky="NSEW")
  initPicker(frames['picker'])
  pickSplitFrame.columnconfigure(0, weight=1)
  pickSplitFrame.rowconfigure(0, weight=1)
  
  frames['filter'].lift()


initMainWind(window)
window.mainloop()