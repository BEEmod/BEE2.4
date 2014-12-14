'''Displays a loading menu while packages, palettes, etc are being loaded.'''
from tkinter import * # ui library
from tkinter import font
from tkinter import ttk # themed ui components that match the OS

active=True

STAGES = [
    ('PAK', 'Packages'),
    ('OBJ',  'Loading Objects'),
    ('RES', 'Extracting Items'),
    ('IMG',  'Loading Images'),
         ]
widgets = {}
maxes = {}
num_images = 0
active=False
         
def init(root):
    global win, wid_list, active
    active=True
    win=Toplevel(root)
    win.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
    win.resizable(False, False)
    win.attributes('-topmost', 1)
    win.geometry('+200+200')
    win.deiconify()
    
    ttk.Label(win, text='Loading...', font=("Helvetica", 12, "bold")).grid()
    ttk.Separator(win, orient=HORIZONTAL).grid(row=1, sticky="EW")
    
    for ind, (id, stage) in enumerate(STAGES):
        ttk.Label(win, text=stage + ':').grid(row=ind*2+2)
        widgets[id] = ttk.Progressbar(win, length=150, mode='determinate', maximum=1)
        widgets[id].grid(row=ind*2+3)
        maxes[id] = 150
     
    win.update()
    loc_x = (win.winfo_screenwidth()-win.winfo_reqwidth())//2 
    loc_y = (win.winfo_screenheight()-win.winfo_reqheight())//2
    win.geometry('+' + str(loc_x) + '+' + str(loc_y))
    win.update()
    
def length(stage, num):
    if active:
        maxes[stage] = num
            
def step(stage):
    if active:
        bar = widgets[stage]
        bar.step(1/maxes[stage])
        bar.update()
            
def quit():
    '''Shutdown the loading screen, we're done!'''
    global win, widgets, maxes, active
    win.destroy()
    del widgets
    del maxes
    active=False
    
if __name__ == '__main__':
    root=Tk()
    init(root)