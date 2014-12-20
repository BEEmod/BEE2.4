'''Displays a loading menu while packages, palettes, etc are being loaded.'''
from tkinter import * # ui library
from tkinter import font
from tkinter import ttk # themed ui components that match the OS

active=True

STAGES = [
    ('PAK', 'Packages'),
    ('OBJ',  'Loading Objects'),
    ('RES', 'Extracting Resources'),
    ('IMG',  'Loading Images'),
    ('UI', 'Initialising UI')
         ]
widgets = {}
labels = {}
bar_var = {}
bar_val = {}
maxes = {}
num_images = 0
active=False
         
def init(root):
    global win, wid_list, active, bar_var, bar_val
    active=True
    win=Toplevel(root)
    win.overrideredirect(1) # this prevents stuff like the title bar, normal borders etc from appearing in this window.
    win.resizable(False, False)
    win.attributes('-topmost', 1)
    win.geometry('+200+200')
    win.deiconify()
    
    ttk.Label(win, text='Loading...', font=("Helvetica", 12, "bold")).grid(columnspan=2)
    ttk.Separator(win, orient=HORIZONTAL).grid(row=1, sticky="EW", columnspan=2)
    
    for ind, (id, stage) in enumerate(STAGES):
        ttk.Label(win, text=stage + ':').grid(row=ind*2+2, columnspan=2, sticky="W")
        bar_var[id] = IntVar()
        bar_val[id] = 0
        maxes[id] = 10
        
        widgets[id] = ttk.Progressbar(win, length=210, maximum=1000, variable=bar_var[id])
        labels[id] = ttk.Label(win, text='0/??')
        widgets[id].grid(row=ind*2+3, column=0, columnspan=2)
        labels[id].grid(row=ind*2+2, column=1, sticky="E")
     
    win.update()
    loc_x = (win.winfo_screenwidth()-win.winfo_reqwidth())//2 
    loc_y = (win.winfo_screenheight()-win.winfo_reqheight())//2
    win.geometry('+' + str(loc_x) + '+' + str(loc_y))
    win.update()
    
def length(stage, num):
    if active:
        maxes[stage] = num
        set_nums(stage)
            
def step(stage):
    if active:
        bar = widgets[stage]
        bar_val[stage] += 1
        bar_var[stage].set(1000*bar_val[stage]/maxes[stage])
        bar.update()
        set_nums(stage)
        
def set_nums(stage):
    labels[stage]['text'] = str(bar_val[stage]) + '/' + str(maxes[stage])
    
def skip_stage(stage):
    '''Skip over this stage of the loading process.'''
    labels[stage]['text'] = 'Skipped!'
    bar_var[stage].set(1000)
    widgets[stage].update()

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