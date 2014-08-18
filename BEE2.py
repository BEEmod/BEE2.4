from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS

window=Tk()
Settings=None
previewImg=PhotoImage(file='images/menu.gif') #image with the ingame items palette
ItemsBG="#CDD0CE" # Colour of the main background to match the above image
paletteText = StringVar(value=('Palette 1','Empty','Portal 2', 'Portal 2 Collapsed'))
styleText = ('1950s','1960s','1970s','1980s','Portal 1','Clean','Overgrown','BTS','Art Therapy','Refurbished') # TODO: Fill this from the *.Bee2Item files

def initPalette(f):
  ttk.Label(f, text="Palettes").grid(row=0, column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, sticky="EW", pady=5)
  #BtnNewPalette=ttk.Button(f, text="New Palette").grid(row=3,column=0)
  UIPalette=Listbox(f, listvariable=paletteText)
  UIPalette.grid(row=2,column=0, sticky=(N,S))
  UIPaletteNew=Entry(f)
  UIPaletteNew.grid(row=3,column=0)

def initOptions(f):
  ttk.Label(f, text="Options").grid(row=0, column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=1, column=0, sticky="EW", pady=5)
  ttk.Button(f, text="Save").grid(row=2, column=0, sticky="EW")
  ttk.Button(f, text="Save as").grid(row=3, column=0, sticky="EW")
  ttk.Button(f, text="Export...").grid(row=4, column=0, sticky="EW", pady=(0, 10))  
  
  ttk.Label(f, text="Properties").grid(row=5,column=0)
  ttk.Separator(f, orient=HORIZONTAL).grid(row=6, column=0, sticky="EW", pady=5)
  props=ttk.Frame(f)
  props.grid(row=7, column=0)
  
  ttk.Label(props, text="Style: ").grid(row=0, column=0)
  UIStyle=ttk.Combobox(props)
  UIStyle['values'] = styleText
  UIStyle.grid(row=0, column=1, columnspan=2, sticky="EW")
  
  ttk.Label(props, text="Music: ").grid(row=1, column=0)
  UIMusic=ttk.Combobox(props, values = ('PeTI','Vitrification Order', 'Robot Waiting Room 1', 'Robot Waiting Room 2', 'Robot Waiting Room 3'))
  UIMusic.grid(row=1, column=1)
  ttk.Button(props, text=">").grid(row=1,column=2)
  
  ttk.Label(props, text="Skybox: ").grid(row=2, column=0)
  ttk.Combobox(props, values=('None','BTS','Portal 1','Art Therapy')).grid(row=2, column=1, columnspan=2, sticky="EW")
  
  ttk.Label(props, text="Voice: ").grid(row=3, column=0)
  ttk.Combobox(props, values=('GLaDOS', 'Cave', '70s Cave','Announcer')).grid(row=3, column=1, columnspan=2, sticky="EW")

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
  
  paletteFrame=ttk.Frame(UIbg, borderwidth=4, relief="raised", padding=5, width="330", height="132")
  paletteFrame.grid(row=0, column=0, sticky=(N,S), padx=2, pady=5)
  paletteFrame.columnconfigure(0, weight=1)
  initPalette(paletteFrame)
  
  optionFrame=ttk.Frame(UIbg, padding=5, borderwidth=4, relief="raised", width="330", height="132")
  optionFrame.grid(row=0, column=1, sticky=(N), padx=2, pady=5)
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