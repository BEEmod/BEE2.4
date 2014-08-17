from tkinter import * # ui library
from tkinter import ttk


Settings=None
win=Tk()
previewImg=PhotoImage(file='menu.gif') #image with the ingame items palette
ItemsBG="#CDD0CE" # Colour of the main background to match the above image

def initMainWind(): # ATM just a mockup, but it sort of works
  # Will probably want to move into a class or something
  win.title("BEE2")
  
  UIbg=Frame(win, bg=ItemsBG)
  UIbg.grid(row=0,column=0, sticky=(N,S,E,W))
  win.columnconfigure(0, weight=1)
  win.rowconfigure(0, weight=1)
  
  topBar=Frame(UIbg, bg=ItemsBG)
  topBar.grid(row=1,column=0,columnspan=2, sticky=(N,E,W))
  UIbg.columnconfigure(1, weight=1)
  
  ttk.Label(topBar, text="Palette Layouts:").grid(row=0, column=0, sticky=(N,E,W))
  UIPalette=ttk.Combobox(topBar)
  UIPalette['values'] = ('Empty','Portal 2', 'Portal 2 Collapsed', 'BEEMOD', 'HMW') # TODO: Fill this from the *.Bee2Palette files
  UIPalette.grid(row=0, column=1, sticky=(W,N,E))
  topBar.columnconfigure(1, weight=1)
  
  ttk.Label(topBar, text="Style:").grid(row=0, column=2, sticky=(N,E,W))
  UIStyle=ttk.Combobox(topBar)
  UIStyle['values'] = ('Clean', '1950s', '1960s', '1970s', '1980s', 'Portal 1', 'Art Therapy', 'Overgrown') # TODO: Fill this from the *.Bee2Item files
  UIStyle.grid(row=0, column=3, sticky=(W,N,E))
  topBar.columnconfigure(3, weight=1) # make the boxes scale with window size
  
  ttk.Label(topBar, text="Filter:").grid(row=0, column=4, sticky=(N,E,W))
  UIFilter=ttk.Combobox(topBar)
  UIFilter['values'] = ('All Items', 'BEEMOD', 'BEE2', 'HMW', 'Stylemod', 'FGEmod') # TODO: Fill this from the *.Bee2Item files
  UIFilter.grid(row=0, column=5, sticky=(W,N,E))
  topBar.columnconfigure(5, weight=1)  
  
  previewFrame=ttk.Frame(UIbg, padding=(0,0,0,0))
  previewFrame.grid(row=2, column=0, rowspan=2, sticky=(N,W), padx=5,pady=5)
  UIbg.rowconfigure(1, weight=1)
  
  previewBG = ttk.Label(previewFrame)
  previewBG['image'] = previewImg
  previewBG.grid(row=0,column=0)
  
  itemsBox=ttk.Frame(UIbg, borderwidth=2, relief="sunken")
  itemsBox.grid(row=2, column=1, sticky=(S, E))
  UIbg.columnconfigure(1, weight=1)
  UIbg.rowconfigure(2, weight=1)
  
  ttk.Label(itemsBox,text="HI").grid(row=0, column=0)
  
  recentBox=ttk.Frame(UIbg, borderwidth=4, relief="sunken", padding=5, width="330", height="132")
  recentBox.grid(row=3, column=1)

initMainWind()
win.mainloop()