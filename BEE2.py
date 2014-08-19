from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
from tkinter import messagebox
from tkinter import filedialog

window=Tk()
Settings=None

# UI vars, most should be generated on startup
previewImg=PhotoImage(file='images/menu.gif') #image with the ingame items palette
ItemsBG="#CDD0CE" # Colour of the main background to match the above image
paletteText = StringVar(value=('Palette 1','Empty','Portal 2', 'Portal 2 Collapsed'))
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files
skyboxText = ('[Default]','None','Overgrown Sunlight', 'Darkness', 'Reactor Fires', 'Clean BTS', 'Wheatley BTS', 'Factory BTS', 'Portal 1 BTS', 'Art Therapy BTS', 'Test Shaft', 'Test Sphere')
voiceText = ('[Default]', 'None', "50's Cave","60's Cave", "70's Cave", "80's Cave", "Cave", "Cave and GLaDOS (refurbished)", "GLaDOS", "Portal 1 GLaDOS (ported)", "Portal 1 GLaDOS", "Art Therapy GLaDOS", "Apocalypse Announcer", "Apocalypse GLaDOS")
musicText = ('[Default]','None', 'Random PeTI', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3', 'Robot Waiting Room 4', 'Robot Waiting Room 5', 'Robot Waiting Room 6', 'You are Not Part of the Control Group', 'Vitrification Order', 'The Reunion', 'Music of the Spheres 1', 'Music of the Spheres 2', 'The Future Starts With You') 
# Examples, we want to set some in styles with the [] to show recommended
games = ('common/portal2', 'common/aperturetag')
gamesDisplay = ('Portal 2', 'Aperture Tag') # We probably want to have the user navigate to gameinfo.txt / find it from the exe to get these names

def saveAs():
  types={}
  types['Palette']='.bee2palette'
  save=filedialog.asksaveasfilename(filetype=types)
  messagebox.showinfo(message='We should save the palette into "'+save+'"')
  
def save():
  types={}
  types['Palette']='.bee2palette'
  save=filedialog.asksaveasfilename(parent=window, filetype=types)
  messagebox.showinfo(message='We should save the palette into "'+save+'"')

def demoMusic():
  messagebox.showinfo(message='This would play the track selected for a few seconds.')
  
  # UI functions, each accepts the parent frame to place everything in. initMainWind generates the main frames that hold all the toolbars to make it easy to move them around
def initGameOpt(f):
  ttk.Label(f, text="Selected Game", anchor="center").grid(row=0, column=0, columnspan=2, sticky="EW")
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, columnspan=2, sticky="EW", pady=5)
  gamesUI=ttk.Combobox(f, values=gamesDisplay)
  gamesUI.grid(row=3, column=0, rowspan=2, sticky="EW")
  gamesUI.current(0)
  ttk.Button(f, text="+", width=3).grid(row=3, column=1)
  ttk.Button(f, text="-", width=3).grid(row=4, column=1)

def initPalette(f):
  ttk.Label(f, text="Palettes", anchor="center").grid(row=0, column=0, columnspan=2, sticky="EW")
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, columnspan=2, sticky="EW", pady=5)
  UIPalette=Listbox(f, listvariable=paletteText, width=10)
  UIPalette.grid(row=2,column=0, columnspan=2, sticky="NSEW")
  ttk.Button(f, text="+").grid(row=3, column=0) # Make new as blank
  ttk.Button(f, text="-").grid(row=3, column=1) # Delete (we probably don't want to allow deleting "None" or "Portal 2")

def initOptions(f):
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

def initPreview(f):
  f['image'] = previewImg
  ttk.Label(f, text="Item: Button").place(x=30,y=557)
  
def initPicker(f):
  ttk.Label(f,text="Items: ").grid(row=0, column=0)

def initMainWind(win): # ATM just a mockup, but it sort of works
  # Will probably want to move into a class or something
  win.title("BEE2")
  
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
  
  optionFrame=ttk.Frame(UIbg, padding=5, borderwidth=4, relief="raised")
  optionFrame.grid(row=0, column=1, sticky=N, padx=2, pady=5)
  initOptions(optionFrame)
  
  previewFrame=ttk.Label(UIbg)
  previewFrame.grid(row=0, column=3, sticky=(N,W), padx=(2,5),pady=5)
  UIbg.rowconfigure(1, weight=1)
  initPreview(previewFrame)
  
  ttk.Separator(UIbg, orient=VERTICAL).grid(row=0, column=4, sticky="NS", padx=10, pady=10)
  
  pickerFrame=ttk.Frame(UIbg, padding=5)
  pickerFrame.grid(row=0, column=5, sticky="NS", padx=5, pady=5)
  initPicker(pickerFrame)
  
  # topBar=Frame(bg=ItemsBG)
  # topBar.grid(row=1,column=0,columnspan=2, sticky=(N,E,W))
  # UIbg.columnconfigure(1, weight=1)
  
  # ttk.Label(topBar, text="Palette Layouts:").grid(row=0, column=0, sticky=(N,E,W))
  # UIPalette=ttk.Combobox(topBar)
  # UIPalette['values'] = ('Empty','Portal 2', 'Portal 2 Collapsed', 'BEEMOD', 'HMW') # TODO: Fill this from the *.Bee2Palette files
  # UIPalette.grid(row=0, column=1, sticky=(W,N,E))
  # topBar.columnconfigure(1, weight=1)
  
  # ttk.Label(topBar, text="Style:").grid(row=0, column=2, sticky=(N,E,W))
  # UIStyle.grid(row=0, column=3, sticky=(W,N,E))
  # topBar.columnconfigure(3, weight=1) # make the boxes scale with window size
  
  # ttk.Label(topBar, text="Filter:").grid(row=0, column=4, sticky=(N,E,W))
  # UIFilter=ttk.Combobox(topBar)
  # UIFilter['values'] = ('All Items', 'BEEMOD', 'BEE2', 'HMW', 'Stylemod', 'FGEmod') # TODO: Fill this from the *.Bee2Item files
  # UIFilter.grid(row=0, column=5, sticky=(W,N,E))
  # topBar.columnconfigure(5, weight=1)  
  
  # itemsBox=ttk.Frame(UIbg, borderwidth=2, relief="sunken")
  # itemsBox.grid(row=2, column=1, sticky=(S, E))
  # UIbg.columnconfigure(1, weight=1)
  # UIbg.rowconfigure(2, weight=1)
  
  # ttk.Label(itemsBox,text="Test").grid(row=0, column=0)
  
  # recentBox=ttk.Frame(UIbg, borderwidth=4, relief="sunken", padding=5, width="330", height="132")
  # recentBox.grid(row=3, column=1)

initMainWind(window)
window.mainloop()