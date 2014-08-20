from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from tkinter import messagebox
from tkinter import filedialog
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc

window=Tk()
frames={} #Holds frames that we need to deal with later
UI={} # Other ui elements we need to access
FilterBoxes={} # the various checkboxes for the filters
Settings=None
ItemsBG="#CDD0CE" # Colour of the main background to match the above image
selectedPalette = 1
selectedPalette_radio = 0 # fake value the menu radio buttons set

# UI vars, most should be generated on startup
palettes=('Palette 1','Empty','Portal 2', 'Portal 2 Collapsed')
paletteReadOnly=('Empty','Portal 2') # Don't let the user edit these, they're special
paletteText = StringVar(value=palettes)
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files
skyboxText = ('[Default]','None','Overgrown Sunlight', 'Darkness', 'Reactor Fires', 'Clean BTS', 'Wheatley BTS', 'Factory BTS', 'Portal 1 BTS', 'Art Therapy BTS', 'Test Shaft', 'Test Sphere')
voiceText = ('[Default]', 'None', "50's Cave","60's Cave", "70's Cave", "80's Cave", "Cave", "Cave and GLaDOS", "GLaDOS", "Portal 1 GLaDOS (ported)", "Portal 1 GLaDOS", "Art Therapy GLaDOS", "Apocalypse GLaDOS", "Apocalypse Announcer", "Announcer", "BTS Announcer")
musicText = ('[Default]','None', 'Random PeTI', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3', 'Robot Waiting Room 4', 'Robot Waiting Room 5', 'Robot Waiting Room 6', 'You are Not Part of the Control Group', 'Vitrification Order', 'The Reunion', 'Music of the Spheres 1', 'Music of the Spheres 2', 'The Future Starts With You')
authorText = ('BenVlodgi & Rantis','HMW','Carl Kenner', 'Felix Griffin', 'Bisqit', 'TeamSpen210')
packageText = ('BEEMOD', 'BEE2', 'HMW', 'Stylemod', 'FGEmod')
tagText = ('Test Elements', 'Panels', 'Geometry', 'Logic', 'Custom')
# Examples, we want to set some in styles
games = ('common/portal2', 'common/aperturetag')
gamesDisplay = ('Portal 2', 'Aperture Tag') # We probably want to have the user navigate to gameinfo.txt / find it from the exe to get these names

def menu_quit():
  window.destroy()

def menu_newPal():
  newPal(simpledialog.askstring("BEE2 - New Palette", "Enter a name:"))

def newPal(t):
  pass


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
    saveAs() # If it's readonly, prompt for a name
  else:
    savePal(pal) # overwrite it
    
def savePal(name):
  messagebox.showinfo(message = 'We should save the palette into "' + name + '".')
  
def demoMusic():
  messagebox.showinfo(message='This would play the track selected for a few seconds.')
  
def setPal_listbox(e):
  global selectedPalette
  selectedPalette = UI['palette'].curselection()[0]
  setPalette()
  
def setPal_radio():
  #selectedPalette = selectedPalette_radio
  setPalette()

def setPalette():
  print(selectedPalette)
  #messagebox.showinfo(message='Update the listbox/menu to match, and reload the new palette.')

def filterExpand(ignore):
  frames['filter_expanded'].grid(row=2, column=0, columnspan=3)

def filterContract(ignore):
  frames['filter_expanded'].grid_remove()
  
def updateFilters():
  pass # This should check all the filter checkboxes, and change what is shown in the list of items.

# UI functions, each accepts the parent frame to place everything in. initMainWind generates the main frames that hold all the panes to make it easy to move them around if needed
def initGameOpt(f):
  ttk.Label(f, text="Selected Game", anchor="center").grid(row=0, column=0, columnspan=2, sticky="EW")
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, columnspan=2, sticky="EW", pady=5)
  gamesUI=ttk.Combobox(f, values=gamesDisplay, width=13)
  gamesUI.grid(row=3, column=0, rowspan=2, sticky="EW")
  gamesUI.current(0)
  ttk.Button(f, text="+", width=3).grid(row=3, column=1)
  ttk.Button(f, text="-", width=3).grid(row=4, column=1)

def initPalette(f):
  ttk.Label(f, text="Palettes", anchor="center").grid(row=0, column=0, sticky="EW")
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, sticky="EW", pady=5)
  UI['palette']=Listbox(f, listvariable=paletteText, width=10)
  UI['palette'].grid(row=2,column=0, sticky="NSEW")
  UI['palette'].bind("<<ListboxSelect>>", setPal_listbox)
  
  UI['newBox']=ttk.Entry(f, text="Create New")
  UI['newBox'].grid(row=3, column=0) # User types in and presses enter to create
  UI['newBox'].bind("<Return>", newPal)
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
  global previewImg
  previewImg  = PhotoImage(file='images/menu.gif')
  #image with the ingame items palette, needs to be global to stop garbage collection
  f['image'] = previewImg
  ttk.Label(f, text="Item: Button").place(x=30,y=557)
  
def initPicker(f):
  ttk.Label(f, text="Items: ").grid(row=0, column=0)
  
def initFilterCol(f, names):
  arr={}
  val=1
  for name in names:
    c=ttk.Checkbutton(f, text=name, command=updateFilters)
    c.grid(row=val, column=0, sticky=W)
    val+=1
  return arr
  
def initFilter(f):

  ttk.Label(f, text="Filters:", anchor="center").grid(row=0, column=0, columnspan=3, sticky="EW")
  
  f2=ttk.Frame(f)
  frames['filter_expanded']=f2
  # Not added to window, we add it below the others to expand the lists
  
  f.bind("<Enter>", filterExpand)
  f.bind("<Leave>", filterContract)
  
  cat=ttk.Labelframe(f2, text="Categories")
  cat.grid(row=1, column=0, sticky="NS")
  pack=ttk.Labelframe(f2, text="Packages")
  pack.grid(row=1, column=1, sticky="NS")
  tags=ttk.Labelframe(f2, text="Tags")
  tags.grid(row=1, column=2, sticky="NS")
  
  FilterBoxes['author']  = initFilterCol(cat, authorText)
  FilterBoxes['package'] = initFilterCol(pack, packageText)
  FilterBoxes['tags']    = initFilterCol(tags, tagText)

def initMenuBar(win):
  bar=Menu(win)
  win['menu']=bar
  win.option_add('*tearOff', False) #Suppress ability to make each menu a separate window - old TK behaviour
  
  menuFile=Menu(bar, name='apple') #Name is used to make this the special 'BEE2' menu item on Mac
  bar.add_cascade(menu=menuFile, label='File')
  menuFile.add_command(label='New...', command=menu_newPal)
  menuFile.add_command(label='Clear')
  menuFile.add_separator()
  val=0
  for name in palettes: # Add a set of options to pick the palette into the menu system
    menuFile.add_radiobutton(label=name, variable=selectedPalette_radio, value=val, command=setPal_radio)
    val+=1
 
  menuFile.add_separator()
  menuFile.add_command(label="Quit", command=menu_quit)
  
  menuHelp=Menu(bar, name='help') # Name for Mac-specific stuff
  bar.add_cascade(menu=menuHelp, label='Help')
  menuHelp.add_command(label='About') # Authors etc
  menuHelp.add_command(label='Quotes') # show the list of quotes

def initMainWind(win): # Generate the main window frames
  # Will probably want to move into a class or something
  win.title("BEE 2")
  initMenuBar(win)
  
  UIbg=Frame(win, bg=ItemsBG)
  UIbg.grid(row=0,column=0, sticky=(N,S,E,W))
  win.columnconfigure(0, weight=1)
  win.rowconfigure(0, weight=1)
  
  UIbg.rowconfigure(0, weight=1)
  
  palSplitFrame=Frame(UIbg, bg=ItemsBG)
  palSplitFrame.grid(row=0, column=0, sticky="NS", padx=2, pady=5)
  palSplitFrame.columnconfigure(0, weight=1)
  
  paletteFrame=ttk.Frame(palSplitFrame, borderwidth=4, relief="raised", padding=5)
  paletteFrame.grid(row=0, column=0, sticky=N)
  paletteFrame.columnconfigure(0, weight=1)
  palSplitFrame.rowconfigure(0, weight=1)
  initPalette(paletteFrame)
  
  gameFrame=ttk.Frame(palSplitFrame, borderwidth=4, relief="raised", padding=5)
  gameFrame.grid(row=1, column=0, sticky=N)
  palSplitFrame.rowconfigure(1, weight=1)
  initGameOpt(gameFrame)
  
  optSplitFrame=Frame(UIbg, bg=ItemsBG)
  optSplitFrame.grid(row=0, column=1, sticky="NS", padx=2, pady=5)
  
  optionFrame=ttk.Frame(optSplitFrame, padding=5, borderwidth=4, relief="raised")
  optionFrame.grid(row=0, column=0, sticky=N)
  initOption(optionFrame)
  
  frames['styleOpt']=ttk.Frame(optSplitFrame, padding=5, borderwidth=4, relief="raised")
  frames['styleOpt'].grid(row=1, column=0, sticky=N, pady=(10,0))
  initStyleOpt(frames['styleOpt'])
  
  previewFrame=ttk.Label(UIbg)
  previewFrame.grid(row=0, column=3, sticky=(N,W), padx=(2,5),pady=5)
  UIbg.rowconfigure(1, weight=1)
  initPreview(previewFrame)
  
  ttk.Separator(UIbg, orient=VERTICAL).grid(row=0, column=4, sticky="NS", padx=10, pady=10)
  
  pickSplitFrame=Frame(UIbg, bg=ItemsBG)
  pickSplitFrame.grid(row=0, column=5, sticky="NS", padx=5, pady=5)
  
  frames['picker']=ttk.Frame(pickSplitFrame, padding=5, borderwidth=4, relief="raised")
  frames['picker'].grid(row=0, column=0, sticky="NSEW")
  initPicker(frames['picker'])
  
  frames['filter']=ttk.Frame(pickSplitFrame, padding=5, borderwidth=4, relief="raised")
  frames['filter'].grid(row=1, column=0, sticky=S)
  initFilter(frames['filter'])

initMainWind(window)
window.mainloop()