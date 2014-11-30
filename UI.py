from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from tkinter import font, messagebox # simple, standard modal dialogs
from tkinter import filedialog # open/save as dialog creator
from tkinter import simpledialog # Premade windows for asking for strings/ints/etc
import tkinter_png as png # png library for TKinter
import random
import math
import webbrowser

from property_parser import Property
from paletteLoader import Palette
from packageLoader import Style as palStyle, Item as palItem, Voice as palVoice, Skybox as palSkybox
import itemPropWin
from selectorWin import selWin
from selectorWin import Item as selWinItem
import sound as snd

win=Tk()
win.withdraw() # hide the main window while everything is loading, so you don't see the bits appearing

png.img_error=png.loadIcon('_error') # If image is not readable, use this instead


testImg  = [ # test palette images,remove when item loading done
            ('Weighted Button',      'ITEM_BUTTON',                     0, png.loadIcon('portal_button')),
            ('Cube Button',          'ITEM_BUTTON',                     1, png.loadIcon('box_socket')),
            ('Sphere Button',        'ITEM_BUTTON',                     2, png.loadIcon('ball_socket')),
            ('Pedestal Button',      'ITEM_PEDESTAL_BUTTON',            0, png.loadIcon('pedestal_button')),
            ('Stairs',               'ITEM_STAIRS',                     0, png.loadIcon('stairs')),
            ('Flip Panel',           'ITEM_FLIP_PANEL',                 0, png.loadIcon('panel_flip')),
            ('Faith Plate',          'ITEM_CATAPULT',                   0, png.loadIcon('faithplate')),
            ('Track Platform',       'ITEM_TRACK_PLATFORM',             0, png.loadIcon('arm_motionplatform')),
            ('Deadly Goo',           'ITEM_GOO',                        0, png.loadIcon('goo')),
            ('Storage Cube',         'ITEM_CUBE',                       0, png.loadIcon('cube')),
            ('Companion Cube',       'ITEM_CUBE',                       1, png.loadIcon('companion_cube')),
            ('Reflection Cube',      'ITEM_CUBE',                       2, png.loadIcon('reflection_cube')),
            ('Safety Cube',          'ITEM_CUBE',                       3, png.loadIcon('edgeless_safety_cube')),
            ('FrankenTurret',        'ITEM_CUBE',                       4, png.loadIcon('frankenturret')),
            ('Cube Dropper',         'ITEM_CUBE_DROPPER',               0, png.loadIcon('item_dropper')),
            ('Sentry Turret',        'ITEM_TURRET',                     0, png.loadIcon('turret')),
            ('Hard Light Bridge',    'ITEM_LIGHT_BRIDGE',               0, png.loadIcon('hard_light_emitter')),
            ('Laser Catcher',        'ITEM_LASER_CATCHER_CENTER',       0, png.loadIcon('laser_catcher')),
            ('Light Strip',          'ITEM_LIGHTSTRIP',                 0, png.loadIcon('light_panel')),
            ('Piston Platform',      'ITEM_PISTON_PLATFORM',            0, png.loadIcon('arm_paneltop')),
            ('Large Faith Plate',    'ITEM_CATAPULT_LARGE',             0, png.loadIcon('faithplate_128')),
            ('AutoPortal',           'ITEM_AUTOPORTAL',                 0, png.loadIcon('fixed_portal_door')),
            ('Fizzler',              'ITEM_BARRIERHAZARD',              0, png.loadIcon('fizzler')),
            ('Discouragement Field', 'ITEM_BARRIERHAZARD',              1, png.loadIcon('deathfield')),
            ('Laser Relay',          'ITEM_LASER_RELAY_CENTER',         0, png.loadIcon('laser_receptacle')),
            ('Laser Emitter',        'ITEM_LASER_EMITTER_CENTER',       0, png.loadIcon('laser_emitter')),
            ('Repulsion Gel',        'ITEM_PAINT_SPLAT',                0, png.loadIcon('paintsplat_bounce')),
            ('Propulsion Gel',       'ITEM_PAINT_SPLAT',                2, png.loadIcon('paintsplat_speed')),
            ('Conversion Gel',       'ITEM_PAINT_SPLAT',                3, png.loadIcon('paintsplat_portal')),
            ('Cleansing Gel',        'ITEM_PAINT_SPLAT',                4, png.loadIcon('paintsplat_water')),
            ('Excursion Funnel',     'ITEM_TBEAM',                      0, png.loadIcon('tbeam')),
            ('Glass Panel',          'ITEM_GLASS_PANEL',                0, png.loadIcon('airlock')),
            ('Glass',                'ITEM_BARRIER',                    0, png.loadIcon('glass')),
            ('Observation Room',     'ITEM_SECONDARY_OBSERVATION_ROOM', 0, png.loadIcon('observation_room')),
            ('Angled Panel',         'ITEM_ANGLED_PANEL',               0, png.loadIcon('panel_flap'))
           ]
           
item_list = []

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
selectedGame_radio = IntVar(value=0)
selectedPalette_radio = IntVar(value=0) # fake value the menu radio buttons set
shouldSnap=True # Should we update the relative positions of windows?
muted = IntVar(value=0) # Is the sound fx muted?

# UI vars, TODO: most should be generated on startup
paletteReadOnly=('Empty','Portal 2') # Don't let the user edit these, they're special
palettes=[]
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files

skybox_list = [
    selWinItem(
        "SKY_BLACK", 
        "Black", 
        longName = "Darkness", 
        icon = "pal_test/faithplate_128",
        author = "Valve",
        desc = 'Pure black darkness. Nothing to see here.'),
    selWinItem(
        "SKY_OVERGROWN",
        "Sunlight",
        longName = "Overgrown Sunlight",
        author = "Valve",
        desc = 'Sunlight peaking through crevices in the ground. Mostly pure white.'),
    selWinItem(
        "SKY_WHEATLEY",
        'Fire',
        longName = 'Reactor Fires',
        author = 'Valve',
        desc = 'An orange glow from the malfunctioning reactor core '
               'beginning to self-destruct. Seen in the last few '
               'Wheatley maps.'),
    selWinItem(
        "SKY_BTS", 
        "BTS", 
        longName="Behind The Scenes - Factory", 
        icon= "pal_test/faithplate_128",
        author="TeamSpen210",
        desc='The dark constuction and office areas of Aperture. Catwalks '
             'extend between different buildings, with vactubes and cranes '
             'carrying objects throughout the facility. Abandoned offices can '
             'often be found here.')
    ]
      
voice_list = [
    selWinItem(
        "VOICE_CAVE_50",
        "50s Cave",
        longName="1950s Cave",
        icon="pal_test/observation_room",
        author="Carl Kenner, TeamSpen210",
        desc="Cave"),
    selWinItem(
        "VOICE_CAVE_60",
        "60s Cave",
        longName="1960s Cave",
        icon="pal_test/observation_room",
        author="Carl Kenner, TeamSpen210",
        desc="Cave"),
    selWinItem(
        "VOICE_CAVE_70",
        "70s Cave",
        longName="1960s Cave",
        icon="pal_test/observation_room",
        author="Carl Kenner, TeamSpen210",
        desc="Cave"),
    selWinItem(
        "VOICE_CAVE_80",
        "80s Cave",
        longName="1980s Cave",
        icon="pal_test/observation_room",
        author="Carl Kenner, TeamSpen210",
        desc="Cave"),
    ]
    
music_list = [
    selWinItem(
        "VALVE_PETI",
        "Random PeTI",
        longName="Random PeTI (Robot Waiting Room)",
        icon="music/peti",
        author="Valve",
        desc="The original PeTI music. Randomly chooses between the 7 different tracks."),
    selWinItem(
        "VALVE_CONTROL_GROUP",
        "50s Chamber",
        longName="You are Not Part of the Control Group",
        icon="music/control_group",
        author="Valve",
        desc="Cave"),
    selWinItem(
        "MUSIC_FUTURE_STARTER",
        "Future Starter",
        longName="The Future Starts With You",
        icon="music/future_starter",
        author="Valve",
        desc="Cave"),
    ]
    
goo_list = [   
    selWinItem(
        "GOO_NORM",
        "Regular",
        icon="pal_test/goo",
        author="Valve",
        desc="The standard normal Toxic Goo."),
        
    selWinItem(
        "GOO_NORM",
        "Overgrown",
        icon="pal_test/goo",
        author="Valve",
        desc="A version of goo which is more reflective, and less polluted."),
    ]
    
selected_style = "clean"
    
skyboxText = ('[Default]','None','Overgrown Sunlight', 'Darkness', 'Reactor Fires', 'Clean BTS', 'Wheatley BTS', 'Factory BTS', 'Portal 1 BTS', 'Art Therapy BTS', 'Test Shaft', 'Test Sphere')
voiceText = ('[Default]', 'None', "50's Cave","60's Cave", "70's Cave", "80's Cave", "Cave", "Cave and GLaDOS", "GLaDOS", "Portal 1 GLaDOS (ported)", "Portal 1 GLaDOS", "Rexaura GLaDOS", "Art Therapy GLaDOS", "BTS GLaDOS", "Apocalypse GLaDOS", "Apocalypse Announcer", "Announcer", "BTS Announcer")
musicText = ('[Default]','None', 'Random PeTI', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3', 'Robot Waiting Room 4', 'Robot Waiting Room 5', 'Robot Waiting Room 6', 'You are Not Part of the Control Group', 'Vitrification Order', 'The Reunion', 'Music of the Spheres 1', 'Music of the Spheres 2', 'The Future Starts With You')

skybox_win = selWin(win, skybox_list, title='Skyboxes', has_none=False)
voice_win = selWin(win, voice_list, title='Voice Lines', has_none=True, none_desc='Add no extra voice lines.')
music_win = selWin(win, music_list, title='Background Music', has_none=True, none_desc='Add no music to the map at all.')
goo_win = selWin(win, goo_list, title='Goo Appearence', has_none=True, none_desc='Use a Bottomless Pit instead. This changes appearance depending on the skybox that is chosen.')

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
    def __init__(self, item):
        self.ver = 0
        self.item = item
        self.data=item.versions[self.ver]['styles'][selected_style]
        self.num_sub = len(list(Property.find_all(self.data['editor'], "Item", "Editor", "Subtype")))
        self.description = self.data['desc']
        self.id = item.id
        
    def get_icon(self, subKey):
        return png.loadIcon(self.data['icons'][str(subKey)])
               
class PalItem(ttk.Label):
    def __init__(self, frame, item, sub):
        "Create a label to show an item onscreen."
        self.item = item
        self.subKey = sub
        print(item.data['icons'].keys())
        self.img = item.get_icon(self.subKey)
        self.name = list(Property.find_all(item.data['editor'], "Item", "Editor", "Subtype", "Name"))
        self.name=self.name[self.subKey].value
        super().__init__(frame, image=self.img)
        self.dispName='Null'#data['name']
        self.bind("<Button-3>",showProps)
        self.bind("<Button-1>", showDrag)
        self.bind("<Shift-Button-1>", fastDrag)
        self.bind("<Enter>", lambda e, n=self.name: setDispName(n))
        self.bind("<Leave>", clearDispName)

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
    
def demoMusic():
    messagebox.showinfo(message='This would play the track selected for a few seconds.')
    
def load_palette(data):
    global palettes
    print("loading data!")
    palettes=sorted(data,key=Palette.getName) # sort by name
    
def load_packages(data):
    '''Import in the list of items and styles from the packages.'''
    global item_list
    for item in data['Item']:
        item_list.append(Item(item))
    
    
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

def setGame():
    global selectedGame
    selectedGame = selectedGame_radio.get()
    print("Game: [" + str(selectedGame) + "] = " + gamesDisplay[selectedGame])
    win.title('BEE2 - '+gamesDisplay[selectedGame])

def setPalette():
    print("Palette chosen: ["+ str(selectedPalette) + "] = " + palettes[selectedPalette].name)
    # TODO: Update the listbox/menu to match, and reload the new palette.

def setStyleOpt(key):
    print("Toggle style option: " + key)
    return

def setDispName(name):
    UI['pre_disp_name'].configure(text='Item: '+name)

def clearDispName(e):
    UI['pre_disp_name'].configure(text='')

def showProps(e):
    snd.fx('expand')
    windows['props'].deiconify()
    windows['props'].vis=True
    windows['props'].lift(win)
    
    sub_item = e.widget
    item = e.widget.item
    icon_widget = UI['prop_sub_' + str(sub_item.subKey)]
    
    loc_x=e.widget.winfo_rootx() + windows['props'].winfo_rootx() - icon_widget.winfo_rootx()
        #The pixel offset between the window and the subitem in the properties dialog
    loc_y=e.widget.winfo_rooty() + windows['props'].winfo_rooty() - UI['prop_sub_0'].winfo_rooty()
    
    if loc_x<15: # adjust to fit inside the screen, + small boundary to not obstruct taskbars, menus etc
        loc_x=0
    if loc_y<45:
        loc_y=0
    if loc_x > windows['props'].winfo_screenwidth()-windows['props'].winfo_reqwidth()-15:
        loc_x=windows['props'].winfo_screenwidth()-windows['props'].winfo_reqwidth()-15
    if loc_y > windows['props'].winfo_screenheight()-windows['props'].winfo_reqheight()-45:
        loc_y=windows['props'].winfo_screenheight()-windows['props'].winfo_reqheight()-45
    windows['props'].geometry('+'+str(loc_x)+'+'+str(loc_y))
    windows['props'].relX=loc_x-win.winfo_x()
    windows['props'].relY=loc_y-win.winfo_y()
    for pos in range(5):
        if pos >= item.num_sub:
            UI['prop_sub_' + str(pos)]['image'] = png.loadIcon('_blank')
        else:
            UI['prop_sub_' + str(pos)]['image']=item.get_icon(pos)
        UI['prop_sub_' + str(pos)]['relief'] = 'flat'
    UI['prop_sub_' + str(sub_item.subKey)]['relief'] = 'raised'
    UI['prop_author']['text'] = ', '.join(item.data['auth'])
    UI['prop_name']['text'] = sub_item.dispName

def hideProps(e):
    if windows['props'].vis:
        snd.fx('contract')
        windows['props'].withdraw()
        windows['props'].vis=False

def showItemProps():
    snd.fx('expand')
    itemPropWin.open(['ButtonType', 'TimerDelay', 'StartEnabled', 'StartReversed'], UI['prop_itemProps'], "ItemNameHere") # TODO: add real values for first/last args

def hideItemProps(vals):
    snd.fx('contract')
    print(vals)

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

def showMoreInfo(url):
    try:
        webbrowser.open(url, new=2, autoraise=True) # 2 = open in tab if possible
    except webbrowser.Error:
        if messagebox.askyesno(icon="error", title="BEE2 - Error", message="Failed to open a web browser. Do you wish for the URL to be copied to the clipboard instead?", detail="'" + str(url) + "'", parent=windows['props']):
            print("saving " +url+ "to clipboard")
            win.clipboard_clear()
            win.clipboard_append(url)
    hideProps(None) # either the webbrowser or the messagebox could cause the properties to move behind the main window, so hide it so it doesn't appear there

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
    for name in('pal','style','opt', 'props'):
        windows[name].geometry('+'+str(win.winfo_x()+windows[name].relX)+'+'+str(win.winfo_y()+windows[name].relY))
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

    props=ttk.LabelFrame(f, text="Properties")
    props.columnconfigure(1,weight=1)
    props.grid(row=3, column=0, sticky="EW")
    ttk.Sizegrip(props,cursor='sb_h_double_arrow').grid(row=1,column=3, sticky="NS")

    ttk.Label(props, text="Style: ").grid(row=0, column=0)
    UIStyle=ttk.Combobox(props, values=styleText)
    UIStyle.current(5)
    UIStyle.grid(row=0, column=1, columnspan=2, sticky="EW")

    ttk.Label(props, text="Music: ").grid(row=1, column=0)
    music_win.init_display(props, row=1, column=1)
    ttk.Button(props, text=">", command=demoMusic, width='4pt').grid(row=1,column=2)

    ttk.Label(props, text="Voice: ").grid(row=2, column=0)
    ttk.Label(props, text="Skybox: ").grid(row=3, column=0)
    ttk.Label(props, text="Goo: ").grid(row=4, column=0)
    
    voice_win.init_display(props, row=2, column=1, colspan=2)
    skybox_win.init_display(props, row=3, column=1, colspan=2)
    goo_win.init_display(props, row=4, column=1, colspan=2)

def initStyleOpt(f):
    global styleCheck, styleOptVars

    UI['style_can']=Canvas(f)
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
    previewImg  = png.loadPng('menu')
    UI['pre_bg_img']=Label(f, bg=ItemsBG, image=previewImg)
    UI['pre_bg_img'].imgsave=previewImg #image with the ingame items palette, needs to be saved to stop garbage collection
    UI['pre_bg_img'].grid(row=0,column=0)

    UI['pre_disp_name']=ttk.Label(f, text="Item: Button", style='BG.TLabel')
    UI['pre_disp_name'].place(x=10,y=552)

    selImg=png.loadPng('sel_bar')
    UI['pre_sel_line']=Label(f, bg="#F0F0F0", image=selImg, borderwidth=0, relief="solid")
    UI['pre_sel_line'].imgsave=selImg

    #for i in range(0,32):
    #    img=random.choice(testImg)
    #    pal_picked.append(PalItem(frames['preview'], img[0], img[1], img[2], img[3]))
    flowPreview()

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
    for item in item_list:
        #num_subitems = len(list(Property.find_all(item.versions[0]['styles'][selected_style]['editor'], "Item", "Editor", "Subtype")))
        print("sub", item.num_sub)
        for i in range(0,item.num_sub):
            pal_items.append(PalItem(frmScroll, item, i))
    #for num in range(0,len(testImg)*10):
    #    img=testImg[num%len(testImg)] # init with test objects
    #    pal_items.append(PalItem(frmScroll, img[0], img[1], img[2], img[3]))
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

def initProperties(win):
    windows['props']=Toplevel(win)
    windows['props'].overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
    windows['props'].resizable(False, False)
    windows['props'].transient(master=win)
    windows['props'].vis=False
    windows['props'].relX=0
    windows['props'].relY=0
    windows['props'].withdraw() # starts hidden


    f=ttk.Frame(windows['props'], relief="raised", borderwidth="4")
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
    for i, ico in enumerate(img):
        ico=png.loadIcon(ico)
        UI['prop_sub_'+str(i)]=ttk.Label(sub_frame, image=ico)
        UI['prop_sub_'+str(i)].grid(row=0, column=i)
        if i==2:
            UI['prop_sub_'+str(i)]['relief']='raised' #hardcode this to be selected
        UI['prop_sub_'+str(i)].img=ico # save here to prevent python from garbage collecting
    ttk.Label(f, text="Description:", anchor="sw").grid(row=4, column=0, sticky="SW")
    spr_frame=ttk.Frame(f, borderwidth=4, relief="sunken")
    spr_frame.grid(column=1, columnspan=2, row=4, sticky=W)
    img=('in_none','out_norm','rot_0','space_occupy','surf_wall_floor_ceil','ap_black') # in order: inputs, outputs, rotation handle, occupied/embed state, desiredFacing, is a Valve item (+ other authors in future)
    for i, spr in enumerate(img):
        spr=png.loadSpr(spr)
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

    UI['prop_more']=ttk.Button(f, text="More Info>>", command=lambda u='https://developer.valvesoftware.com/wiki/Portal_2_Puzzle_Maker/Button': showMoreInfo(u))
    UI['prop_more'].grid(row=6, column=2, sticky=E)

    UI['prop_itemProps']=ttk.Button(f, text="Change Defaults...", command=showItemProps)
    UI['prop_itemProps'].grid(row=6, column=1)

    UI['prop_variant']=ttk.Combobox(f, values=("Recessed","Compat (On Top)"))
    UI['prop_variant'].current(0)
    UI['prop_variant'].grid(row=6, column=0, sticky=W)


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

    menus['file']=Menu(bar, name='apple') #Name is used to make this the special 'BEE2' menu item on Mac
    bar.add_cascade(menu=menus['file'], label='File')
    menus['file'].add_command(label="Export")
    menus['file'].add_command(label="Find Game")
    menus['file'].add_command(label="Remove Game")
    menus['file'].add_separator()
    val=0
    for name in gamesDisplay: # Add a set of options to pick the palette into the menu system
        menus['file'].add_radiobutton(label=name, variable=selectedGame_radio, value=val, command=setGame)
        val+=1

    menus['file'].add_separator()
    if snd.initiallised:
        menus['file'].add_checkbutton(label="Mute Sounds", variable=muted, command=lambda: snd.setMute(muted.get()))
    menus['file'].add_command(label="Quit", command=win.destroy)
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

    setGame()

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

    win.bind("<Button-1>",hideProps)
    windows['style'].bind("<Button-1>",hideProps)
    windows['opt'].bind("<Button-1>",hideProps)
    windows['pal'].bind("<Button-1>",hideProps)

    initProperties(win)
    initDragIcon(win)
    itemPropWin.init(win, hideItemProps)

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
    windows['opt'].geometry(xpos + str(win.winfo_rooty()-40))
    windows['style'].geometry(xpos + str(win.winfo_rooty()+windows['opt'].winfo_reqheight()+50))

    win.bind("<Configure>",moveMain)
    windows['style'].bind("<Configure>", lambda e: snapWin('style'))
    windows['opt'].  bind("<Configure>", lambda e: snapWin('opt'))
    windows['pal'].  bind("<Configure>", lambda e: snapWin('pal'))

    loadPalUI()
def event_loop():
    win.mainloop()

if __name__ == '__main__': # load the window if directly executing this file
    initMain()
