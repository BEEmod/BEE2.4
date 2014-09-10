from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from tkinter import font, messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc
import tkinter_png as png # png library for TKinter
import random
import math
    
win=Tk()
win.withdraw() # hide the main window while everything is loading, so you don't see the bits appearing

png.img_error=png.loadIcon('_error') # If image is not readable, use this instead

testImg  = (png.loadIcon('portal_button'), # test palette images,remove when item loading done
          png.loadIcon('stairs'),
          png.loadIcon('flipper'),
          png.loadIcon('faithplate'),
          png.loadIcon('goo'),
          png.loadIcon('frankenturret'),
          png.loadIcon('item_dropper'),
          png.loadIcon('turret'),
          png.loadIcon('hard_light_emitter'),
          png.loadIcon('laser_receptacle'),
          png.loadIcon('light_panel'),
          png.loadIcon('paintsplat_water'),
          png.loadIcon('paintsplat_speed'),
          png.loadIcon('paintsplat_portal'),
          png.loadIcon('tbeam'),
          png.loadIcon('companion_cube'),
          png.loadIcon('airlock'))
  
win.iconbitmap(r'BEE2.ico')# set the window icon

windows={}
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

# UI vars, TODO: most should be generated on startup
palettes=('Portal 2','Empty','Palette 1', 'Portal 2 Collapsed')
paletteReadOnly=('Empty','Portal 2') # Don't let the user edit these, they're special
paletteText = StringVar(value=palettes)
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files
skyboxText = ('[Default]','None','Overgrown Sunlight', 'Darkness', 'Reactor Fires', 'Clean BTS', 'Wheatley BTS', 'Factory BTS', 'Portal 1 BTS', 'Art Therapy BTS', 'Test Shaft', 'Test Sphere')
voiceText = ('[Default]', 'None', "50's Cave","60's Cave", "70's Cave", "80's Cave", "Cave", "Cave and GLaDOS", "GLaDOS", "Portal 1 GLaDOS (ported)", "Portal 1 GLaDOS", "Rexaura GLaDOS", "Art Therapy GLaDOS", "BTS GLaDOS", "Apocalypse GLaDOS", "Apocalypse Announcer", "Announcer", "BTS Announcer")
musicText = ('[Default]','None', 'Random PeTI', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3', 'Robot Waiting Room 4', 'Robot Waiting Room 5', 'Robot Waiting Room 6', 'You are Not Part of the Control Group', 'Vitrification Order', 'The Reunion', 'Music of the Spheres 1', 'Music of the Spheres 2', 'The Future Starts With You')
gooText = ('[Default]','[Bottomless Pit]','Regular', 'Overgrown', 'Portal 1')
authorText = ('BenVlodgi & Rantis','HMW','Carl Kenner', 'Felix Griffin', 'Bisqwit', 'TeamSpen210')
packageText = ('BEEMOD', 'BEE2', 'HMW', 'Stylemod', 'FGEmod')
tagText = ('Test Elements', 'Panels', 'Geometry', 'Logic', 'Custom')
# Examples, we want to set some in styles
games = ('common/portal2', 'common/aperturetag')
gamesDisplay = ('Portal 2', 'Aperture Tag') #TODO: We probably want to have the user navigate to gameinfo.txt / find it from the exe to get these names

styleOptions = [('MultiverseCave','Multiverse Cave', True),
                ('FixPortalBump','Prevent Portal Bump  (glass)', False), 
                ('FixFizzlerBump','Prevent Portal Bump  (fizzler)', False), # these five should be hardcoded (part of Portal 2 basically), other settings should be extracted from style file and put into cats
                ('UnlockMandatory','Unlock Default Items', False),
                ('NoMidVoices','Suppress Mid-Chamber Dialogue', False)]

def demoMusic():
  messagebox.showinfo(message='This would play the track selected for a few seconds.')

def setGame():
  global selectedGame
  selectedGame = selectedGame_radio.get()
  print("Game: [" + str(selectedGame) + "] = " + gamesDisplay[selectedGame])
  win.title('BEE2 - '+gamesDisplay[selectedGame])

def setPalette():
  print("Palette chosen: ["+ str(selectedPalette) + "] = " + palettes[selectedPalette])
  # TODO: Update the listbox/menu to match, and reload the new palette.

def setStyleOpt(key):
  print("Toggle style option: " + key)
  return
  
def menu_quit():
  win.destroy()
                
def showProps(e):
  print("Showing properties at: " + str(e.x_root) + ', ' + str(e.y_root))
  propWin.deiconify()
  propWin.lift(win)
  loc_x=e.widget.winfo_rootx() + propWin.winfo_rootx() - UI['prop_sub_2'].winfo_rootx()
#The pixel offset between the window and the subitem in the properties dialog - change sub_2 to move it.
  loc_y=e.widget.winfo_rooty() + propWin.winfo_rooty() - UI['prop_sub_0'].winfo_rooty()
  propWin.geometry('+'+str(loc_x)+'+'+str(loc_y))

def hideProps(e):
  propWin.withdraw()
  

def showDrag(e):
  dragWin.deiconify()
  dragWin.lift(win)
  dragWin.grab_set_global() # grab makes this window the only one to recieve mouse events, so we guarentee that it'll drop when the mouse is released.
  moveDrag(e) # move to correct position
  UI['drag_lbl']['image']=e.widget.img
  dragWin.bind("<B1-Motion>", moveDrag)
  dragWin.bind("<ButtonRelease-1>", hideDrag)

def hideDrag(e):
  dragWin.withdraw()
  dragWin.unbind("<B1-Motion>")
  dragWin.grab_release()
  # we should actually change the picker menu here (if applies) to add the dropped item.

def moveDrag(e):
  dragWin.geometry('+'+str(e.x_root-32)+'+'+str(e.y_root-32))
  if e.x_root > UI['pre_bg_img'].winfo_rootx() and e.y_root > UI['pre_bg_img'].winfo_rooty() and e.x_root < UI['pre_bg_img'].winfo_rootx() + UI['pre_bg_img'].winfo_width() and e.y_root < UI['pre_bg_img'].winfo_rooty() + UI['pre_bg_img'].winfo_height():
    dragWin.configure(cursor='plus')
  else:
    dragWin.configure(cursor='no')

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
  
def pal_remTempText(e):
  if PalEntry.get() == PalEntry_TempText:
    PalEntry.set("")

def pal_addTempText(e):
  if PalEntry.get() == "":
    PalEntry.set(PalEntry_TempText)
  
def saveAs():
  name=""
  while True:
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
    
def toggleWin(button, window):
  if window.vis:
    window.vis=False
    window.withdraw()
    UI['tool_win_'+button].state(['!pressed'])
  else:
    window.vis=True
    window.deiconify()
    UI['tool_win_'+button].state(['pressed'])
  
def hideWin(button, window):
  window.withdraw()
  window.vis=False
  UI['tool_win_'+button].state(['!pressed'])
  
def menu_newPal():
  newPal(simpledialog.askstring("BEE2 - New Palette", "Enter a name:"))

def newPal_textbox(e):
  newPal(PalEntry.get())

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
        FilterVars_all[cat].set(True) # force it to be true so when clicked it'll blank out all the   checkboxes
        FilterBoxes_all[cat].state(['alternate']) # make it the half-selected state, since they don't match
        no_alt=False
        break
    if no_alt:
      FilterBoxes_all[cat].state(['!alternate']) # no alternate if they are all the same
      FilterVars_all[cat].set(value)
    
#TODO: This should check all the filter checkboxes, and change what is actually shown in the list of items.

def filterAllCallback(col): 
  "sets all items in a category to true/false, then updates the item list."
  val = FilterVars_all[col].get()
  for i in FilterVars[col]:
    FilterVars[col][i].set(val)
  updateFilters()

# UI functions, each accepts the parent frame to place everything in. initMainWind generates the main frames that hold all the panes to make it easy to move them around if needed
def initPalette(f):

  palFrame=ttk.Frame(f)
  palFrame.grid(row=0, column=0, sticky="NSEW")
  palFrame.rowconfigure(0, weight=1)
  palFrame.columnconfigure(0, weight=1)
  f.rowconfigure(2, weight=1)

  UI['palette']=Listbox(palFrame, listvariable=paletteText, width=10)
  UI['palette'].grid(row=0,column=0, sticky="NSEW")
  UI['palette'].bind("<<ListboxSelect>>", setPal_listbox)
  UI['palette'].selection_set(0)

  palScroll=ttk.Scrollbar(palFrame, orient=VERTICAL, command=UI['palette'].yview)
  palScroll.grid(row=0,column=1, sticky="NS")
  UI['palette']['yscrollcommand']=palScroll.set

  UI['newBox']=ttk.Entry(f, textvariable=PalEntry)
  UI['newBox'].grid(row=1, column=0, sticky=S) # User types in and presses enter to create
  UI['newBox'].bind("<Return>", newPal_textbox)
  UI['newBox'].bind("<FocusIn>", pal_remTempText)
  UI['newBox'].bind("<FocusOut>", pal_addTempText)
  ttk.Button(f, text=" - ").grid(row=2, column=0, sticky="EWS") # Delete (we probably don't want to allow deleting "None" or "Portal 2")

def initOption(f):
  ttk.Button(f, width=10, text="Save", command=save).grid(row=0, column=0)
  ttk.Button(f, width=10, text="Save as", command=saveAs).grid(row=1, column=0)
  ttk.Button(f, width=10, text="Export...").grid(row=2, column=0, pady=(0, 10))  

  ttk.Label(f, text="Properties").grid(row=3,column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=4, column=0, sticky="EW", pady=5)
  props=ttk.Frame(f)
  props.grid(row=5, column=0)

  ttk.Label(props, text="Style: ").grid(row=0, column=0)
  UIStyle=ttk.Combobox(props, values=styleText)
  UIStyle.current(5)
  UIStyle.grid(row=0, column=1, columnspan=2, sticky="EW")

  ttk.Label(props, text="Music: ").grid(row=1, column=0)
  UIMusic=ttk.Combobox(props, values = musicText)
  UIMusic.grid(row=1, column=1)
  UIMusic.current(0)
  ttk.Button(props, text=">", command=demoMusic, width='4pt').grid(row=1,column=2)

  ttk.Label(props, text="Voice: ").grid(row=2, column=0)
  UIVoice=ttk.Combobox(props, values=voiceText)
  UIVoice.current(0)
  UIVoice.grid(row=2, column=1, columnspan=2, sticky="EW")

  ttk.Label(props, text="Skybox: ").grid(row=3, column=0)
  UISky=ttk.Combobox(props, values=skyboxText)
  UISky.current(0)
  UISky.grid(row=3, column=1, columnspan=2, sticky="EW")


  ttk.Label(props, text="Goo: ").grid(row=4, column=0)
  UI['goo']=ttk.Combobox(props, values=gooText)
  UI['goo'].current(0)
  UI['goo'].grid(row=4, column=1, columnspan=2, sticky="EW")

def initStyleOpt(f):
  global styleCheck, styleOptVars

  can=Canvas(f)
  can.grid(row=0, column=0, sticky="NSEW") # need to use a canvas to allow scrolling
  f.rowconfigure(0, weight=1)

  scroll = ttk.Scrollbar(f, orient=VERTICAL, command=can.yview)
  scroll.grid(column=1, row=0, sticky="NS")
  can['yscrollcommand'] = scroll.set
  canFrame=ttk.Frame(can)

  #This should automatically switch to match different styles
  frmAll=ttk.Labelframe(canFrame, text="All")
  frmAll.grid(row=0, column=0, sticky="EW")

  frmOld=ttk.Labelframe(canFrame, text="Old Aperture")
  frmOld.grid(row=1, column=0, sticky="EW")

  frm80s=ttk.Labelframe(canFrame, text="80s")
  frm80s.grid(row=2, column=0, sticky="EW")

  frmOver=ttk.Labelframe(canFrame, text="Overgrown")
  frmOver.grid(row=3, column=0, sticky="EW")
   
  pos=0
  styleCheck={}
  styleOptVars={
    "HepDestCube" : BooleanVar(value=False),
    "RealObs" : BooleanVar(value=False),
    "GelFaith" : BooleanVar(value=True),
    "OpenSphere" : BooleanVar(value=True),
    "OverEntryPuzzles" : BooleanVar(value=True)}
  for key in styleOptions:
    styleOptVars[styleOptions[pos][0]]=BooleanVar(value=styleOptions[pos][2])
    styleCheck[pos]=ttk.Checkbutton(frmAll, variable=styleOptVars[styleOptions[pos][0]],   text=styleOptions[pos][1], command=lambda key=styleOptions[pos][0]: setStyleOpt(key)) # the key argument forces lambda to remember the string
    styleCheck[pos].grid(row=pos, column=0, sticky="W", padx=3)
    pos=pos+1

  # TODO: These should be generated by a similar loop to above.
  ttk.Checkbutton(frmAll, text="HEPs destroy cubes (Rexaura)", variable=styleOptVars["HepDestCube"], command=lambda: setStyleOpt("HepDestCube")).grid(row=5, column=0, sticky="W", padx=3) 

  ttk.Checkbutton(frmOld, text="Real Observation Rooms", variable=styleOptVars["RealObs"], command=lambda: setStyleOpt("RealObs")).grid(row=0, column=0, sticky="W", padx=3)
  ttk.Checkbutton(frmOld, text="Gel-Faith-Plates", variable=styleOptVars["GelFaith"], command=lambda: setStyleOpt("GelFaith")).grid(row=1, column=0, sticky="W", padx=3)

  ttk.Checkbutton(frm80s, text="Opened Sphere", variable=styleOptVars["OpenSphere"], command=lambda: setStyleOpt("OpenSphere")).grid(row=0, column=0, sticky="W", padx=3)
  ttk.Checkbutton(frmOver, text="Have entry/exit puzzles", variable=styleOptVars["OverEntryPuzzles"], command=lambda: setStyleOpt("OverEntryPuzzles")).grid(row=0, column=0, sticky="W", padx=3)

  can.create_window(0, 0, window=canFrame, anchor="nw")
  can.update_idletasks()
  can['width']=canFrame.winfo_reqwidth()
  
def initTool(f):
  UI['tool_delete']=ttk.Button(f)
  UI['tool_delete'].img = png.loadPng('icons/tool_delete')
  UI['tool_delete']['image'] = UI['tool_delete'].img
  UI['tool_delete'].grid(row=0, column=0, padx=2)
  
  UI['tool_subitem']=ttk.Button(f)
  UI['tool_subitem'].img = png.loadPng('icons/tool_sub')
  UI['tool_subitem']['image'] = UI['tool_subitem'].img
  UI['tool_subitem'].grid(row=0, column=1, padx=(2,5))
  
  UI['tool_win_pal']=ttk.Button(f, command=lambda:toggleWin('pal',windows['palette']))
  UI['tool_win_pal'].img = png.loadPng('icons/win_pal')
  UI['tool_win_pal']['image'] = UI['tool_win_pal'].img
  UI['tool_win_pal'].state(["pressed"])
  UI['tool_win_pal'].grid(row=0, column=3, padx=(5,2))
  
  UI['tool_win_opt']=ttk.Button(f, command=lambda:toggleWin('opt',windows['option']))
  UI['tool_win_opt'].img = png.loadPng('icons/win_opt')
  UI['tool_win_opt']['image'] = UI['tool_win_opt'].img
  UI['tool_win_opt'].state(["pressed"])
  UI['tool_win_opt'].grid(row=0, column=4, padx=2)
  
  UI['tool_win_style']=ttk.Button(f, command=lambda:toggleWin('style',windows['styleOpt']))
  UI['tool_win_style'].img = png.loadPng('icons/win_style')
  UI['tool_win_style']['image'] = UI['tool_win_style'].img
  UI['tool_win_style'].state(["pressed"])
  UI['tool_win_style'].grid(row=0, column=5, padx=2)

def initPreview(f):
  UI['pre_bg_img']=Label(f, bg=ItemsBG)
  previewImg  = png.loadPng('menu')
  UI['pre_bg_img']['image'] = previewImg
  UI['pre_bg_img'].imgsave=previewImg #image with the ingame items palette, needs to be saved to stop garbage collection
  UI['pre_bg_img'].grid(row=0,column=0)

  ttk.Label(f, text="Item: Button").place(x=10,y=552)
  
  for x in range(0,4):
    pal_picked[x]={}
    for y in range(0,8):
      img=random.choice(testImg)
      pal_picked[x][y]=ttk.Label(f, image=img)
      pal_picked[x][y].img=img
      pal_picked[x][y].bind("<Button-3>",showProps)
      pal_picked[x][y].bind("<Button-1>",showDrag)
      pal_picked[x][y].gr_x=x
      pal_picked[x][y].gr_y=y # these can be referred to to figure out where it is
      pal_picked[x][y].place(x=(x*65+4),y=(y*65+32))

def initPicker(f):
  global frmScroll, pal_canvas, pal_items_fake
  ttk.Label(f, text="All Items: ", anchor="center").grid(row=0, column=0, sticky="EW")
  UI['picker_empty_img']=png.loadIcon('_blank')
  cframe=ttk.Frame(f,borderwidth=4, relief="sunken")
  cframe.grid(row=1, column=0, sticky="NSEW")
  f.rowconfigure(1, weight=1)
  f.columnconfigure(0, weight=1)

  pal_canvas=Canvas(cframe)
  pal_canvas.grid(row=0, column=0, sticky="NSEW") # need to use a canvas to allow scrolling
  cframe.rowconfigure(0, weight=1)
  cframe.columnconfigure(0, weight=1)

  scroll = ttk.Scrollbar(cframe, orient=VERTICAL, command=pal_canvas.yview)
  scroll.grid(column=1, row=0, sticky="NS")
  pal_canvas['yscrollcommand'] = scroll.set

  frmScroll=ttk.Frame(pal_canvas) # add another frame inside to place labels on
  pal_canvas.create_window(1, 1, window=frmScroll, anchor="nw")

  for num in range(0,len(testImg)*10):
    lbl=ttk.Label(frmScroll) 
    lbl.img=testImg[num%len(testImg)]# init with test objects
    lbl['image']=lbl.img
    lbl.bind("<Button-3>",showProps)
    lbl.bind("<Button-1>",showDrag)
    pal_items.append(lbl)
  pal_items_fake=[]
  for i in range(0, 50): # NOTE - this will fail silently if someone has a monitor that can fit 51 columns or more (3250+ pixels just for the icons)
    pal_items_fake.append(ttk.Label(frmScroll, image=UI['picker_empty_img']))
  f.bind("<Configure>",flowPicker)

def flowPicker(e):
  global frmScroll, pal_items_fake
  frmScroll.update_idletasks()
  frmScroll['width']=pal_canvas.winfo_width()
  width=(pal_canvas.winfo_width()-10) // 65
  if width <1:
    width=1 # we got way too small, prevent division by zero
  itemNum=len(pal_items)
  pal_canvas['scrollregion'] = (0, 0, width*65, math.ceil(itemNum/width)*65+2) 
  frmScroll['height']=(math.ceil(itemNum/width)*65+2)
  for i in range(0,itemNum):
      pal_items[i].place(x=((i%width) *65+1),y=((i//width)*65+1))
    
  # this adds extra blank items on the end to finish the grid nicely.
  for i in range(0,len(pal_items_fake)):
    if i>=(itemNum%width) and i<width:
      pal_items_fake[i].place(x=((i%width)*65+1),y=(itemNum//width)*65+1)
    else:
      pal_items_fake[i].place_forget()  
    
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

def initProperties(win):
  global propWin
  propWin=Toplevel(win)
  propWin.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
  propWin.resizable(False, False)
  propWin.transient(master=win)
  propWin.withdraw() # starts hidden

  win.bind("<Button-1>",hideProps)

  f=ttk.Frame(propWin, relief="raised", borderwidth="4")
  f.grid(row=0, column=0)

  ttk.Label(f, text="Properties:", anchor="center").grid(row=0, column=0, columnspan=3, sticky="EW")
  entSpr=png.loadSpr('gear_ent')

  UI['prop_name']=ttk.Label(f, text="Weighted Button", anchor="center")
  UI['prop_name'].grid(row=1, column=0, columnspan=3, sticky="EW")

  UI['prop_ent_count']=ttk.Label(f, text="2", anchor="e", compound="left", image=entSpr)
  UI['prop_ent_count'].img=entSpr
  UI['prop_ent_count'].grid(row=0, column=2, rowspan=2, sticky=E)

  UI['prop_author']=ttk.Label(f, text=" Valve, Carl Kenner ", anchor="center", relief="sunken")
  UI['prop_author'].grid(row=2, column=0, columnspan=3, sticky="EW")

  sub_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
  sub_frame.grid(column=0, columnspan=3, row=3)
  img=('_blank','portal_button','box_socket','ball_socket','_blank') # for now always show 'properties' for the ITEM_BUTTON_FLOOR
  for i in range(0,5):
    ico=png.loadIcon(img[i])
    UI['prop_sub_'+str(i)]=ttk.Label(sub_frame, image=ico)
    UI['prop_sub_'+str(i)].grid(row=0, column=i)
    if i==2:
      UI['prop_sub_'+str(i)]['relief']='raised' #hardcode this to be selected
    UI['prop_sub_'+str(i)].img=ico # save here to prevent python from garbage collecting
  ttk.Label(f, text="Description:", anchor="sw").grid(row=4, column=0, sticky="SW")
  spr_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
  spr_frame.grid(column=1, columnspan=2, row=4, sticky=W)
  img=('in_none','out_norm','rot_0','space_occupy','surf_wall_floor_ceil','ap_black') # in order: inputs, outputs, rotation handle, occupied/embed state, desiredFacing, is a Valve item (+ other authors in future)
  for i in range(0,6):
    spr=png.loadSpr(img[i])
    UI['prop_spr_'+str(i)]=ttk.Label(spr_frame, image=spr, relief="raised")
    UI['prop_spr_'+str(i)].grid(row=0, column=i)
    UI['prop_spr_'+str(i)].img=spr
  desc_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
  desc_frame.grid(row=5, column=0, columnspan=3, sticky="EW")
  UI['prop_desc']=Text(desc_frame, width=40, height=8, wrap="word")
  UI['prop_desc'].grid(row=0, column=0, sticky="EW")

  desc_scroll=ttk.Scrollbar(desc_frame, orient=VERTICAL, command=UI['prop_desc'].yview)
  UI['prop_desc']['yscrollcommand']=desc_scroll.set
  desc_scroll.grid(row=0, column=1, sticky="NS")
  UI['prop_desc'].insert("end", "Big pressure buttons activated by players or cubes. Cube buttons are only activated by cubes, sphere buttons only by spheres.")
  UI['prop_desc']['state']="disabled" # need to set this to normal when editing text, then swap back

  UI['prop_more']=ttk.Button(f, text="More Info>>")
  UI['prop_more'].grid(row=6, column=2, sticky=E)

  UI['prop_alternate']=ttk.Checkbutton(f, text="Use Recessed Button")
  UI['prop_alternate'].grid(row=6, column=0, sticky=W)

def initDragIcon(win):
  global dragWin
  dragWin=Toplevel(win)
  dragWin.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
  dragWin.resizable(False, False)
  dragWin.withdraw()
  dragWin.transient(master=win)
  dragWin.withdraw() # starts hidden
  UI['drag_lbl']=Label(dragWin, image=png.loadIcon('_blank'))
  UI['drag_lbl'].grid(row=0, column=0)

def initMenuBar(win):
  bar=Menu(win)
  win['menu']=bar
  win.option_add('*tearOff', False) #Suppress ability to make each menu a separate window - weird old TK behaviour

  menuFile=Menu(bar, name='apple') #Name is used to make this the special 'BEE2' menu item on Mac
  bar.add_cascade(menu=menuFile, label='File')
  menuFile.add_command(label="Export")
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

def initMain():
  "Initialise all windows and panes."
  
  initMenuBar(win)
  win.maxsize(width=2000, height=2000)
  UIbg=Frame(win, bg=ItemsBG)
  UIbg.grid(row=0,column=0, sticky=(N,S,E,W))
  win.columnconfigure(0, weight=1)
  win.rowconfigure(0, weight=1)

  UIbg.rowconfigure(0, weight=1)
  
  frames['preview']=Frame(UIbg, bg=ItemsBG)
  frames['preview'].grid(row=0, column=3, sticky="NW", padx=(2,5),pady=5)
  initPreview(frames['preview'])
  
  frames['toolMenu']=Frame(frames['preview'], bg=ItemsBG, width=192, height=26)
  frames['toolMenu'].place(x=75, y=2)
  initTool(frames['toolMenu'])
  
  ttk.Separator(UIbg, orient=VERTICAL).grid(row=0, column=4, sticky="NS", padx=10, pady=10)

  pickSplitFrame=Frame(UIbg, bg=ItemsBG)
  pickSplitFrame.grid(row=0, column=5, sticky="NSEW", padx=5, pady=5)
  UIbg.columnconfigure(5, weight=1)

  frames['filter']=ttk.Frame(pickSplitFrame, padding=5, borderwidth=0, relief="raised")
  frames['filter'].place(x=0,y=0, relwidth=1) # This will sit on top of the palette section, spanning from left to right
  initFilter(frames['filter'])

  frames['picker']=ttk.Frame(pickSplitFrame, padding=(5,40,5,5), borderwidth=4, relief="raised")
  frames['picker'].grid(row=0, column=0, sticky="NSEW")
  pickSplitFrame.rowconfigure(0, weight=1)
  pickSplitFrame.columnconfigure(0, weight=1)
  initPicker(frames['picker'])
  
  win.bind("<MouseWheel>", lambda e: pal_canvas.yview_scroll(int(-1*(e.delta/120)), "units")) # make scrollbar work globally
  win.bind("<Button-4>", lambda e: pal_canvas.yview_scroll(1, "units")) # needed for linux
  win.bind("<Button-5>", lambda e: pal_canvas.yview_scroll(-1, "units"))

  frames['filter']=ttk.Frame(pickSplitFrame, padding=5, borderwidth=0, relief="raised")
  frames['filter'].place(x=0,y=0, relwidth=1) # This will sit on top of the palette section, spanning from left to right
  initFilter(frames['filter'])

  frames['filter'].lift()
  
  windows['palette']=Toplevel(win)
  windows['palette'].transient(master=win)
  windows['palette'].resizable(False, True)
  windows['palette'].title("Palettes")
  windows['palette'].protocol("WM_DELETE_WINDOW", lambda: hideWin('pal', windows['palette']))
  windows['palette'].vis=True
  initPalette(windows['palette'])

  windows['option']=Toplevel(win)
  windows['option'].transient(master=win)
  windows['option'].resizable(False, False)
  windows['option'].title("Options")
  windows['option'].protocol("WM_DELETE_WINDOW", lambda: hideWin('opt', windows['option']))
  windows['option'].vis=True
  initOption(windows['option'])

  windows['styleOpt']=Toplevel(win)
  windows['styleOpt'].transient(master=win)
  windows['styleOpt'].resizable(False, True)
  windows['styleOpt'].title("Style Properties")
  windows['styleOpt'].protocol("WM_DELETE_WINDOW", lambda: hideWin('style', windows['styleOpt']))
  windows['styleOpt'].vis=True
  initStyleOpt(windows['styleOpt'])

  initProperties(win)
  initDragIcon(win)
  
  win.deiconify() # show it once we've loaded everything
  
  win.update_idletasks()
  windows['styleOpt'].update_idletasks()
  windows['option'].update_idletasks()
  windows['palette'].update_idletasks()
  
  # move windows around to make it look nice on startup
  if(win.winfo_rootx() < windows['palette'].winfo_reqwidth() + 50): # move the main window if needed to allow room for palette
    win.geometry('+' + str(win.winfo_rootx() - windows['palette'].winfo_reqwidth() - 50) + '+' + str(win.winfo_rooty()))
  windows['palette'].geometry('+' + str(windows['palette'].winfo_width() + 50) + '+' + str(win.winfo_rooty()))
  xpos = '+' + str(min(win.winfo_screenwidth() - windows['styleOpt'].winfo_reqwidth(),win.winfo_rootx() + win.winfo_width() + 10 )) + '+'
  windows['option'].geometry(xpos + str(win.winfo_rooty()))
  windows['styleOpt'].geometry(xpos + str(win.winfo_rooty()+windows['option'].winfo_reqheight()))
  
  
  win.mainloop()
  
initMain()