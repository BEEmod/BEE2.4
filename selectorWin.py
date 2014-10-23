from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS

import tkinter_png as png # png library for TKinter


widgets={} # holds the checkbox or other item used to manipulate the box
labels={} # holds the descriptive labels for each property

propList=[]

values={}

class Item:
    "An item on the panel."
    def __init__(
            self, 
            name, 
            shortName, 
            longName = None,
            icon = None, 
            desc = ""):
        self.name = name
        self.shortName = shortName
        self.longName = shortName if longName is None else longName
        self.icon = None if icon is None else png.loadIcon(icon)
        self.desc = desc

noneItem = None
    
def exit():
    "Quit and cancel."
    win.grab_release()
    win.withdraw()
    callback(None)
    
def confirm():
    "Quit and return the newly-selected item."
    win.grab_release()
    win.withdraw()
    callback(None)

def init(tk, cback):
    global callback, noneItem, win
    callback=cback
    noneItem = Item('NONE','NONE')
    win=Toplevel(tk)
    win.title("BEE2")
    win.resizable(False, False)
    win.iconbitmap(r'BEE2.ico')
    win.protocol("WM_DELETE_WINDOW", exit)
    win.withdraw()

def open(parent, list, title, suggested = "", selected = ""):
    win.title("BEE2 - " + title)
    win.transient(master=parent)
    
    win.deiconify()
    win.lift(parent)
    win.grab_set()
    win.geometry('+'+str(parent.winfo_rootx()-30)+'+'+str(parent.winfo_rooty()-win.winfo_reqheight()-30))

if __name__ == '__main__': # load the window if directly executing this file
    root=Tk()
    png.img_error=png.loadIcon('_error') # If image is not readable, use this instead
    root.geometry("+250+250")
    init(root,print)
    lst = [
        Item(
            "SKY_BTS", 
            "BTS", 
            longName = "Behind The Scenes - Factory", 
            icon = "faithplate_128", 
            desc = 'The dark constuction and office areas of Aperture. Catwalks '
                   'extend between different buildings, with vactubes and cranes '
                   'carrying objects throuout the facility. Abandoned offices can '
                   'often be found here.')
          ]
    print(lst[0].desc)
    open(root, "NONE", "Skybox", lst)
