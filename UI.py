from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from tkinter import font, messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc
import tkinter_png as png # png library for TKinter
import random
import math

from property_parser import Property
from paletteLoader import Palette
from packageLoader import Style as palStyle, Item as palItem, Voice as palVoice, Skybox as palSkybox
import contextWin
import gameMan
from selectorWin import selWin
from selectorWin import Item as selWinItem
import sound as snd

win=Tk()
win.withdraw() # hide the main window while everything is loading, so you don't see the bits appearing
gameMan.root=win

png.img_error=png.loadPng('BEE2/error') # If image is not readable, use this instead
           
item_list = {}

win.iconbitmap('BEE2.ico')# set the window icon

windows={}
frames={} #Holds frames that we need to deal with later
UI={} # Other ui elements we need to access
menus={} # The menu items for the main window
pal_picked=[] # array of the picker icons
pal_items=[] # array of the "all items" icons
drag_item=-1 # the item currently being moved
drag_orig_pos=-1
drag_onPal=False # are we dragging a palette item?
drag_passedPal=False # has the cursor passed over the palette
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
selectedPalette_radio = IntVar(value=0) # fake value the menu radio buttons set
shouldSnap=True # Should we update the relative positions of windows?
muted = IntVar(value=0) # Is the sound fx muted?

# UI vars, TODO: most should be generated on startup
paletteReadOnly=('Empty','Portal 2') # Don't let the user edit these, they're special
palettes=[]
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files

skyboxes = {}
voices = {}
    
music_list = [
    selWinItem(
        "VALVE_PETI",
        "Random PeTI",
        longName="Random PeTI (Robot Waiting Room)",
        icon="music/peti",
        authors=["Valve"],
        desc="The original PeTI music. Randomly chooses between the 7 different tracks."),
    selWinItem(
        "VALVE_CONTROL_GROUP",
        "50s Chamber",
        longName="You are Not Part of the Control Group",
        icon="music/control_group",
        authors=["Valve"],
        desc="The music played in some of the first 50s chambers. Has additional Repulsion Gel beats that mix in dynamically."),
    selWinItem(
        "MUSIC_FUTURE_STARTER",
        "Future Starter",
        longName="The Future Starts With You",
        icon="music/future_starter",
        authors=["Valve"],
        desc="Cave"),
    ]
    
goo_list = [   
    selWinItem(
        "GOO_NORM",
        "Regular",
        icon="goo/clean",
        authors=["Valve"],
        desc="The standard normal Toxic Goo."),
        
    selWinItem(
        "GOO_OVERGROWN",
        "Overgrown",
        icon="goo/overgrown",
        authors=["Valve"],
        desc="A version of goo which is more murky, and reflective."),
    ]
    
style_list = [
    selWinItem(
        "CLEAN",
        "Clean",
        authors=["Valve", "Carl Kenner"],
        desc="Portal 2 Clean style, like after GLaDOS has been awoken and finished cleaning the facility, or in a parallel world where it was never destroyed. Similar to the default PeTI style but with more variety of wall panels and automatic security cameras."),
    selWinItem(
        "Portal1",
        "Portal 1",
        authors=["Carl Kenner"],
        desc="Portal 1 style test chamber. Portal 1 style elevators, the brown metal walls, white concrete walls, floor tiles, security cameras (unless the Sentient Cloud has taken over), Unstationary Scaffolds, Complementary Victory Lifts, Vital Apparatus Vents, Portal 1 Fizzlers, etc. There's an orange glow coming from behind panels.")
]
    
selected_style = "clean"
    
skyboxText = ('[Default]','None','Overgrown Sunlight', 'Darkness', 'Reactor Fires', 'Clean BTS', 'Wheatley BTS', 'Factory BTS', 'Portal 1 BTS', 'Art Therapy BTS', 'Test Shaft', 'Test Sphere')
voiceText = ('[Default]', 'None', "50's Cave","60's Cave", "70's Cave", "80's Cave", "Cave", "Cave and GLaDOS", "GLaDOS", "Portal 1 GLaDOS (ported)", "Portal 1 GLaDOS", "Rexaura GLaDOS", "Art Therapy GLaDOS", "BTS GLaDOS", "Apocalypse GLaDOS", "Apocalypse Announcer", "Announcer", "BTS Announcer")
musicText = ('[Default]','None', 'Random PeTI', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3', 'Robot Waiting Room 4', 'Robot Waiting Room 5', 'Robot Waiting Room 6', 'You are Not Part of the Control Group', 'Vitrification Order', 'The Reunion', 'Music of the Spheres 1', 'Music of the Spheres 2', 'The Future Starts With You')

authorText = ('BenVlodgi & Rantis','HMW','Carl Kenner', 'Felix Griffin', 'Bisqwit', 'TeamSpen210')
packageText = ('BEEMOD', 'BEE2', 'HMW', 'Stylemod', 'FGEmod')
tagText = ('Test Elements', 'Panels', 'Geometry', 'Logic', 'Custom')

styleOptions = [('MultiverseCave','Multiverse Cave', True),
                ('FixPortalBump','Prevent Portal Bump  (glass)', False),
                ('FixFizzlerBump','Prevent Portal Bump  (fizzler)', False), # these five should be hardcoded (part of Portal 2 basically), other settings should be extracted from style file and put into cats
                ('UnlockMandatory','Unlock Default Items', False),
                ('NoMidVoices','Suppress Mid-Chamber Dialogue', False)
               ]
               # These should come from the styles/items.
styleOptMain = [('HepDestCube', 'HEPs destroy cubes (Rexaura)', True),
                ('RealObs', 'Real Observation Rooms', False)
               ]
styleOptOther= [
                ('GelFaith', 'Gel-Faith-Plates', True),
                ('OpenSphere', 'Opened Sphere', True),
                ('OverEntryPuzzles', 'Have entry/exit puzzles', True)
               ]
               
class Item():
    '''Represents an item that can appear on the list.'''
    def __init__(self, item):
        self.ver = 0
        self.item = item
        self.data=item.versions[self.ver]['styles'][selected_style]
        self.num_sub = len(list(Property.find_all(self.data['editor'], "Item", "Editor", "Subtype")))
        self.id = item.id
        self.url = self.data['url']
        if self.url == 'NONE':
            self.url = None
        
    def get_icon(self, subKey):
        return png.loadIcon(self.data['icons'][str(subKey)])
        
    def get_properties(self):
        props = []
        for part in Property.find_all(self.data['editor'], "Item", "Properties"):
            props.extend([prop.name for prop in part])
        return props
               
class PalItem(ttk.Label):
    '''The icon and associated data for a single subitem.'''
    def __init__(self, frame, item, sub):
        "Create a label to show an item onscreen."
        super().__init__(frame)
        self.item = item
        self.subKey = sub
        self.load_data(sub)
        self.bind("<Button-3>", contextWin.showProps)
        self.bind("<Button-1>", showDrag)
        self.bind("<Shift-Button-1>", fastDrag)
        self.bind("<Enter>", lambda e, n=self.name: setDispName(n))
        self.bind("<Leave>", clearDispName)
        
    def load_data(self, sub):
        self.img = self.item.get_icon(self.subKey)
        self.name = list(Property.find_all(self.item.data['editor'], "Item", "Editor", "Subtype", "Name"))
        self.name=self.name[self.subKey].value
        self['image'] = self.img
        self.dispName='Null'#data['name']
        
    def clear(self):
        "Remove any items matching the passed label from the palette, to prevent adding two copies."
        toRem=[]
        found=False
        for i,item in enumerate(pal_picked): # remove the item off of the palette if it's on there, this lets you delete items and prevents having the same item twice.
            if self==item:
                item.place_forget()
                toRem.append(i)
                found=True
        for i in reversed(toRem):
            del pal_picked[i] # we have to loop in reverse to stop indexes changing on us and messing up enumerate()
        return found

    def onPal(self):
        '''Determine if this item is on the palette.'''
        for item in pal_picked:
            if self==item:
                return True
        return False
        
    def __eq__(self, other):
        '''Two items are equal if they have the same overall item and sub-item index.'''
        return self.item.id == other.item.id and self.subKey == other.subKey
        
    def copy(self, frame):
        return PalItem(frame, self.item, self.subKey)
    
def load_palette(data):
    global palettes
    print("loading data!")
    palettes=sorted(data,key=Palette.getName) # sort by name
    
def load_packages(data):
    '''Import in the list of items and styles from the packages.'''
    global item_list, skybox_win, voice_win, music_win, goo_win, style_win
    for item in sorted(data['Item'], key=lambda i: i.id):
        it = Item(item)
        item_list[it.id] = it
    sky_list = []
    for sky in sorted(data['Skybox'], key=lambda q: q.name):
        sky_list.append(selWinItem(
                sky.id, 
                sky.short_name,
                longName = sky.name,
                icon=sky.icon, 
                authors=sky.auth, 
                desc=sky.desc))
        skyboxes[sky.id] = sky
        
    voice_list = []
    for voice in sorted(data['QuotePack'], key=lambda q: q.name):
        voice_list.append(selWinItem(
                voice.id,
                voice.short_name,
                longName = voice.name,
                icon=voice.icon,
                authors=voice.auth,
                desc=voice.desc))
        voices[voice.id] = voice
        
    skybox_win = selWin(win, sky_list, title='Skyboxes', has_none=False)
    voice_win = selWin(win, voice_list, title='Voice Lines', has_none=True, none_desc='Add no extra voice lines.')
    music_win = selWin(win, music_list, title='Background Music', has_none=True, none_desc='Add no music to the map at all.')
    goo_win = selWin(win, goo_list, title='Goo Appearence', has_none=True, none_desc='Use a Bottomless Pit instead. This changes appearance depending on the skybox that is chosen.')
    style_win = selWin(win, style_list, title='Style', has_none=False, has_def=False)
    
def loadPalUI():
    "Update the UI to show the correct palettes."
    print(palettes)
    UI['palette'].delete(0, END)
    for i,pal in enumerate(palettes):
        print(pal.name)
        UI['palette'].insert(i,pal.name)
    if menus['pal'].item_len>0:
        menus['pal'].delete(3, menus['pal'].item_len)
    menus['pal'].item_len=0
    for val,pal in enumerate(palettes): # Add a set of options to pick the palette into the menu system
        menus['pal'].add_radiobutton(label=pal.name, variable=selectedPalette_radio, value=val, command=setPal_radio)
        menus['pal'].item_len+=1

def setGame(game):
    global selectedGame
    selectedGame = selectedGame_radio.get()
    print("Game: [" + str(selectedGame) + "] = " + gamesDisplay[selectedGame])
    win.title('BEE2 - '+gamesDisplay[selectedGame])

def setPalette():
    print("Palette chosen: ["+ str(selectedPalette) + "] = " + palettes[selectedPalette].name)
    # TODO: Update the listbox/menu to match, and reload the new palette.
    for item in pal_picked:
        item.place_forget()
    pal_picked.clear()
    print(*item_list.keys())
    for item, sub in palettes[selectedPalette].pos:
        if item in item_list.keys():
            pal_picked.append(PalItem(frames['preview'], item_list[item], sub))
        else:
            print('Unknown item "' + item + '"!')
    flowPreview()

def setStyleOpt(key):
    print("Toggle style option: " + key)
    return

def setDispName(name):
    UI['pre_disp_name'].configure(text='Item: '+name)

def clearDispName(e):
    UI['pre_disp_name'].configure(text='')

def convScrToGrid(x,y):
    "Returns the location of the item hovered over on the preview pane."
    return ((x-UI['pre_bg_img'].winfo_rootx()-8)//65,
           (y-UI['pre_bg_img'].winfo_rooty()-32)//65)

def convScrToPos(x,y):
    "Returns the index of the item hovered over on the preview pane."
    return ((y-UI['pre_bg_img'].winfo_rooty()-32)//65)*4 +\
           ((x-UI['pre_bg_img'].winfo_rootx()-8)//65)

def showDrag(e):
    "Start dragging a palette item."
    global drag_onPal,drag_item, drag_passedPal
    drag_item=e.widget
    setDispName(drag_item.dispName)
    snd.fx('config')
    drag_passedPal=False

    if e.widget.is_pre: # is the cursor over the preview pane?
        ind=e.widget.pre_x+e.widget.pre_y*4
        pal_picked[ind].place_forget()
        del pal_picked[ind]
        drag_onPal=True
    else:
        drag_onPal=e.widget.onPal()
    dragWin.deiconify()
    dragWin.lift(win)
    dragWin.grab_set_global() # grab makes this window the only one to receive mouse events, so it is guaranteed that it'll drop when the mouse is released.
    # NOTE: _global means no other programs can interact, make sure it's released eventually or you won't be able to quit!
    moveDrag(e) # move to correct position
    UI['drag_lbl']['image']=e.widget.img
    dragWin.bind("<B1-Motion>", moveDrag)
    dragWin.bind("<ButtonRelease-1>", hideDrag)
    UI['pre_sel_line'].lift()

def hideDrag(e):
    "User released the mouse button, complete the drag."
    dragWin.withdraw()
    dragWin.unbind("<B1-Motion>")
    dragWin.grab_release()
    clearDispName(None)
    UI['pre_sel_line'].place_forget()
    snd.fx('config')

    pos_x,pos_y=convScrToGrid(e.x_root,e.y_root)
    ind=pos_x+pos_y*4

    if drag_passedPal: #this prevents a single click on the picker from clearing items off the palette
        drag_item.clear() # wipe duplicates off the palette first

        if pos_x>=0 and pos_y>=0 and pos_x<4 and pos_y<8: # is the cursor over the preview pane?
            newItem=drag_item.copy(frames['preview'])
            if ind>=len(pal_picked):
                pal_picked.append(newItem)
            else:
                pal_picked.insert(ind,newItem)
            if len(pal_picked) > 32: # delete the item - it's fallen off the palette
                pal_picked.pop().place_forget()
        else: # drop the item
            snd.fx('delete')
        flowPreview() # always refresh

def moveDrag(e):
    "Update the position of dragged items as they move around."
    global drag_passedPal
    setDispName(drag_item.dispName)
    dragWin.geometry('+'+str(e.x_root-32)+'+'+str(e.y_root-32))
    pos_x,pos_y=convScrToGrid(e.x_root,e.y_root)
    if pos_x>=0 and pos_y>=0 and pos_x<4 and pos_y<8:
        drag_passedPal=True
        dragWin.configure(cursor='plus')
        UI['pre_sel_line'].place(x=pos_x*65+3, y=pos_y*65+33)
    else:
        if drag_onPal and drag_passedPal:
            dragWin.configure(cursor='x_cursor')
        else:
            dragWin.configure(cursor='no')
        UI['pre_sel_line'].place_forget()

def fastDrag(e):
    "When shift-clicking an item will be immediately moved to the palette or deleted from it."
    pos_x,pos_y=convScrToGrid(e.x_root,e.y_root)
    e.widget.clear()
    if pos_x>=0 and pos_y>=0 and pos_x<4 and pos_y<9: # is the cursor over the preview pane?
        snd.fx('delete')
        e.widget.place_forget() # remove the clicked item
    else: # over the picker
        if len(pal_picked) < 32: # can't copy if there isn't room
            snd.fx('config')
            newItem=e.widget.copy(frames['preview'])
            pal_picked.append(newItem)
        else:
            snd.fx('error')
    flowPreview()

def setPal_listbox(e):
    global selectedPalette
    selectedPalette = int(UI['palette'].curselection()[0])
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
            messagebox.showinfo(icon="error", title="BEE2", message='The palette \"'+name+'\" cannot be overwritten. Choose another name.')
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

def toggleWin(name):
    snd.fx('config')
    if windows[name].vis:
        windows[name].vis=False
        windows[name].withdraw()
        UI['tool_win_'+name].state(['!pressed'])
    else:
        windows[name].vis=True
        windows[name].deiconify()
        win.focus() # return focus back to main window so it doesn't flicker between if you press the various buttons
        UI['tool_win_'+name].state(['pressed'])

def hideWin(name):
    "Hide a window, effectively closes it without deleting the contents"
    snd.fx('config')
    windows[name].withdraw()
    windows[name].vis=False
    UI['tool_win_'+name].state(['!pressed'])

def snapWin(name):
    "Callback for window movement, allows it to snap to the edge of the main window."
    # TODO: Actually snap to edges of main window
    if shouldSnap:
        windows[name].relX=windows[name].winfo_x()-win.winfo_x()
        windows[name].relY=windows[name].winfo_y()-win.winfo_y()
        windows[name].update_idletasks()

def moveMain(e):
    "When the main window moves, sub-windows should move with it."
    shouldSnap=False
    for name in('pal','style','opt'):
        windows[name].geometry('+'+str(win.winfo_x()+windows[name].relX)+'+'+str(win.winfo_y()+windows[name].relY))
    contextWin.follow_main()
    win.focus()
    shouldSnap=True

def menu_newPal():
    newPal(simpledialog.askstring("BEE2 - New Palette", "Enter a name:"))

def newPal_textbox(e):
    newPal(PalEntry.get())

def filterExpand(e):
    frames['filter_expanded'].grid(row=2, column=0, columnspan=3)
    frames['filter']['borderwidth']=4
    snd.fx('expand')

def filterContract(e):
    frames['filter_expanded'].grid_remove()
    frames['filter']['borderwidth']=0
    snd.fx('contract')

def updateFilters():
    # First update the 'all' checkboxes to make half-selected if not fully selected.
    for cat in FILTER_CATS: # do for each
        no_alt=True
        value=FilterVars[cat][0].get() # compare to the first one, this will check if they are all the same
        for i in FilterVars[cat]:
            if FilterVars[cat][i].get() != value:
                FilterVars_all[cat].set(True) # force it to be true so when clicked it'll blank out all the checkboxes
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
    f.rowconfigure(0, weight=1)

    UI['palette']=Listbox(palFrame, width=10)
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
    ttk.Sizegrip(f, cursor="sb_v_double_arrow").grid(row=3, column=0)

def initOption(f):
    f.columnconfigure(0,weight=1)
    ttk.Button(f, width=10, text="Save...", command=save).grid(row=0, column=0)
    ttk.Button(f, width=10, text="Save as...", command=saveAs).grid(row=1, column=0)
    ttk.Button(f, width=10, text="Export...").grid(row=2, column=0, pady=(0, 10))

    props=ttk.LabelFrame(f, text="Properties", width="50")
    props.columnconfigure(1,weight=1)
    props.grid(row=3, column=0, sticky="EW")
    ttk.Sizegrip(props,cursor='sb_h_double_arrow').grid(row=1,column=3, sticky="NS")

    ttk.Label(props, text="Style: ").grid(row=0, column=0)
    ttk.Label(props, text="Music: ").grid(row=1, column=0)
    ttk.Label(props, text="Voice: ").grid(row=2, column=0)
    ttk.Label(props, text="Skybox: ").grid(row=3, column=0)
    ttk.Label(props, text="Goo: ").grid(row=4, column=0)
    
    style_win.init_display(props, row=0, column=1)
    music_win.init_display(props, row=1, column=1)
    voice_win.init_display(props, row=2, column=1)
    skybox_win.init_display(props, row=3, column=1)
    goo_win.init_display(props, row=4, column=1)

def initStyleOpt(f):
    global styleCheck, styleOptVars

    UI['style_can']=Canvas(f, highlightthickness=0)
    UI['style_can'].grid(row=0, column=0, sticky="NSEW") # need to use a canvas to allow scrolling
    f.rowconfigure(0, weight=1)

    scroll = ttk.Scrollbar(f, orient=VERTICAL, command=UI['style_can'].yview)
    scroll.grid(column=1, row=0, rowspan=2, sticky="NS")
    UI['style_can']['yscrollcommand'] = scroll.set
    canFrame=ttk.Frame(UI['style_can'])

    #This should automatically switch to match different styles
    frmAll=ttk.Labelframe(canFrame, text="All:")
    frmAll.grid(row=0, column=0, sticky="EW")

    frmChosen=ttk.Labelframe(canFrame, text="Selected Style:")
    frmChosen.grid(row=1, column=0, sticky="EW")

    frmOther=ttk.Labelframe(canFrame, text="Other Styles:")
    frmOther.grid(row=2, column=0, sticky="EW")


    styleCheck={}
    styleOptVars={}
    cats =[
          (frmAll, styleOptions), 
          (frmChosen, styleOptMain),
           (frmOther, styleOptOther)
          ]
    for frm, lst in cats:
        for pos,key in enumerate(lst):
            styleOptVars[key[0]]=BooleanVar(value=key[2])
            styleCheck[key[0]]=ttk.Checkbutton(frm, variable=styleOptVars[key[0]],   text=key[1], command=lambda key=key[0]: setStyleOpt(key)) # the key argument forces lambda to remember the string
            styleCheck[key[0]].grid(row=pos, column=0, sticky="W", padx=3)

    UI['style_can'].create_window(0, 0, window=canFrame, anchor="nw")
    UI['style_can'].update_idletasks()
    UI['style_can'].config(scrollregion=UI['style_can'].bbox(ALL), width=canFrame.winfo_reqwidth())
    ttk.Sizegrip(f, cursor="sb_v_double_arrow").grid(row=1, column=0)

def initTool(f):
    "Creates the small toolbar above the icons that allows toggling subwindows."
    for i,name in enumerate(('pal','opt','style')):
        UI['tool_win_'+name]=ttk.Button(f, command=lambda n=name:toggleWin(n), style='BG.TButton')
        UI['tool_win_'+name].img = png.loadPng('icons/win_'+name)
        UI['tool_win_'+name]['image'] = UI['tool_win_'+name].img
        UI['tool_win_'+name].state(["pressed"])
        UI['tool_win_'+name].grid(row=0, column=i, padx=(5,2))

def flowPreview():
    "Position all the preview icons based on the array. Run to refresh if items are moved around."
    for i,item in enumerate(pal_picked):
        item.pre_x=i%4
        item.pre_y=i//4 # these can be referred to to figure out where it is
        item.is_pre=True
        item.place(x=(i%4*65+4),y=(i//4*65+32))
    UI['pre_sel_line'].lift()

def initPreview(f):
    "Generate the preview pane which shows the items that will export to the palette."
    previewImg  = png.loadPng('BEE2/menu')
    UI['pre_bg_img']=Label(f, bg=ItemsBG, image=previewImg)
    UI['pre_bg_img'].imgsave=previewImg #image with the ingame items palette, needs to be saved to stop garbage collection
    UI['pre_bg_img'].grid(row=0,column=0)

    UI['pre_disp_name']=ttk.Label(f, text="Item: Button", style='BG.TLabel')
    UI['pre_disp_name'].place(x=10,y=552)

    selImg=png.loadPng('BEE2/sel_bar')
    UI['pre_sel_line']=Label(f, bg="#F0F0F0", image=selImg, borderwidth=0, relief="solid")
    UI['pre_sel_line'].imgsave=selImg
    flowPreview()

def initPicker(f):
    global frmScroll, pal_canvas, pal_items_fake
    ttk.Label(f, text="All Items: ", anchor="center").grid(row=0, column=0, sticky="EW")
    UI['picker_empty_img']=png.loadPng('BEE2/blank')
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
    for item in item_list.values():
        for i in range(0,item.num_sub):
            pal_items.append(PalItem(frmScroll, item, i))

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
    pal_canvas.config(scrollregion = (0, 0, width*65, math.ceil(itemNum/width)*65+2))
    frmScroll['height']=(math.ceil(itemNum/width)*65+2)
    for i,item in enumerate(pal_items):
        item.is_pre=False
        item.place(x=((i%width) *65+1),y=((i//width)*65+1))

    # this adds extra blank items on the end to finish the grid nicely.
    for i,blank in enumerate(pal_items_fake):
        if i>=(itemNum%width) and i<width: # if this space is empty
            blank.place(x=((i%width)*65+1),y=(itemNum//width)*65+1)
        else:
            blank.place_forget() # otherwise hide the fake item

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


def initDragIcon(win):
    global dragWin
    dragWin=Toplevel(win)
    dragWin.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
    dragWin.resizable(False, False)
    dragWin.withdraw()
    dragWin.transient(master=win)
    dragWin.withdraw() # starts hidden
    UI['drag_lbl']=Label(dragWin, image=png.loadPng('BEE2/blank'))
    UI['drag_lbl'].grid(row=0, column=0)

def initMenuBar(win):
    bar=Menu(win)
    win['menu']=bar
    win.option_add('*tearOff', False) #Suppress ability to make each menu a separate window - weird old TK behaviour

    menus['file']=Menu(bar, name='apple') #Name is used to make this the special 'BEE2' menu item on Mac
    bar.add_cascade(menu=menus['file'], label='File')
    menus['file'].add_command(label="Export")
    menus['file'].add_command(label="Find Game")
    menus['file'].add_command(label="Remove Game")
    menus['file'].add_separator()
    if snd.initiallised:
        menus['file'].add_checkbutton(label="Mute Sounds", variable=muted, command=lambda: snd.setMute(muted.get()))
    menus['file'].add_command(label="Quit", command=win.destroy)
    menus['file'].add_separator()
    
    gameMan.add_menu_opts(menus['file']) # Add a set of options to pick the game into the menu system
    
    menus['pal']=Menu(bar)
    bar.add_cascade(menu=menus['pal'], label='Palette')
    menus['pal'].add_command(label='New...', command=menu_newPal)
    menus['pal'].add_command(label='Clear')
    menus['pal'].add_separator()
    menus['pal'].item_len=0 # custom attr used to decide how many items to remove when reloading the menu buttons
    

    menuHelp=Menu(bar, name='help') # Name for Mac-specific stuff
    bar.add_cascade(menu=menuHelp, label='Help')
    menuHelp.add_command(label='About') # Authors etc
    menuHelp.add_command(label='Quotes') # show the list of quotes

def initMain():
    "Initialise all windows and panes."

    initMenuBar(win)
    win.maxsize(width=win.winfo_screenwidth(), height=win.winfo_screenheight())
    UIbg=Frame(win, bg=ItemsBG)
    UIbg.grid(row=0,column=0, sticky=(N,S,E,W))
    win.columnconfigure(0, weight=1)
    win.rowconfigure(0, weight=1)
    UIbg.rowconfigure(0, weight=1)

    style=ttk.Style()
    style.configure('BG.TButton', background=ItemsBG) # Custom button style with correct background
    style.configure('Preview.TLabel', background='#F4F5F5') # Custom label style with correct background

    frames['preview']=Frame(UIbg, bg=ItemsBG)
    frames['preview'].grid(row=0, column=3, sticky="NW", padx=(2,5),pady=5)
    initPreview(frames['preview'])
    frames['preview'].update_idletasks()
    win.minsize(width=frames['preview'].winfo_reqwidth()+200,height=frames['preview'].winfo_reqheight()+5) # Prevent making the window smaller than the preview pane

    frames['toolMenu']=Frame(frames['preview'], bg=ItemsBG, width=192, height=26, borderwidth=0)
    frames['toolMenu'].place(x=73, y=2)
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

    frames['filter']=ttk.Frame(pickSplitFrame, padding=5, borderwidth=0, relief="raised")
    frames['filter'].place(x=0,y=0, relwidth=1) # This will sit on top of the palette section, spanning from left to right
    initFilter(frames['filter'])

    frames['filter'].lift()

    windows['pal']=Toplevel(win)
    windows['pal'].transient(master=win)
    windows['pal'].resizable(False, True)
    windows['pal'].title("BEE2 - Palettes")
    windows['pal'].iconbitmap('BEE2.ico')
    windows['pal'].protocol("WM_DELETE_WINDOW", lambda: hideWin('pal'))
    windows['pal'].vis=True
    initPalette(windows['pal'])

    windows['opt']=Toplevel(win)
    windows['opt'].transient(master=win)
    windows['opt'].resizable(True, False)
    windows['opt'].title("BEE2 - Options")
    windows['opt'].iconbitmap('BEE2.ico')
    windows['opt'].protocol("WM_DELETE_WINDOW", lambda: hideWin('opt'))
    windows['opt'].vis=True
    initOption(windows['opt'])

    windows['style']=Toplevel(win)
    windows['style'].transient(master=win)
    windows['style'].resizable(False, True)
    windows['style'].title("BEE2 - Style Properties")
    windows['style'].iconbitmap('BEE2.ico')
    windows['style'].protocol("WM_DELETE_WINDOW", lambda: hideWin('style'))
    windows['style'].vis=True
    initStyleOpt(windows['style'])

    win.bind("<MouseWheel>", lambda e: pal_canvas.yview_scroll(int(-1*(e.delta/120)), "units")) # make scrollbar work globally
    win.bind("<Button-4>", lambda e: pal_canvas.yview_scroll(1, "units")) # needed for linux
    win.bind("<Button-5>", lambda e: pal_canvas.yview_scroll(-1, "units"))

    windows['style'].bind("<MouseWheel>", lambda e: UI['style_can'].yview_scroll(int(-1*(e.delta/120)), "units")) # make scrollbar work globally
    windows['style'].bind("<Button-4>", lambda e: UI['style_can'].yview_scroll(1, "units")) # needed for linux
    windows['style'].bind("<Button-5>", lambda e: UI['style_can'].yview_scroll(-1, "units"))

    win.bind("<Button-1>",contextWin.hideProps)
    windows['style'].bind("<Button-1>",contextWin.hideProps)
    windows['opt'].bind("<Button-1>",contextWin.hideProps)
    windows['pal'].bind("<Button-1>",contextWin.hideProps)

    contextWin.init(win)
    initDragIcon(win)

    win.deiconify() # show it once we've loaded everything

    win.update_idletasks()
    windows['style'].update_idletasks()
    windows['opt'].update_idletasks()
    windows['pal'].update_idletasks()

    # move windows around to make it look nice on startup
    if(win.winfo_rootx() < windows['pal'].winfo_reqwidth() + 50): # move the main window if needed to allow room for palette
        win.geometry('+' + str(windows['pal'].winfo_reqwidth() + 50) + '+' + str(win.winfo_rooty()) )
    else:
        win.geometry('+' + str(win.winfo_rootx()) + '+' + str(win.winfo_rooty()) )
    win.update_idletasks()
    windows['pal'].geometry( str(windows['pal'].winfo_reqwidth()) + 'x' + str(win.winfo_reqheight()) +
      '+' + str(win.winfo_rootx()-windows['pal'].winfo_reqwidth() - 25) + '+' + str(win.winfo_rooty()-50))
    xpos = '+' + str(min(win.winfo_screenwidth() - windows['style'].winfo_reqwidth(),win.winfo_rootx() + win.winfo_reqwidth() + 25 )) + '+'
    opt_size = str(windows['style'].winfo_reqwidth()) + 'x' + str(windows['opt'].winfo_reqheight())
    windows['opt'].geometry(opt_size + xpos + str(win.winfo_rooty()-40))
    windows['style'].geometry(xpos + str(win.winfo_rooty()+windows['opt'].winfo_reqheight()+50))

    win.bind("<Configure>",moveMain)
    windows['style'].bind("<Configure>", lambda e: snapWin('style'))
    windows['opt'].  bind("<Configure>", lambda e: snapWin('opt'))
    windows['pal'].  bind("<Configure>", lambda e: snapWin('pal'))

    loadPalUI()
def event_loop():
    win.mainloop()
