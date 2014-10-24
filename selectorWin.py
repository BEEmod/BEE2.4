from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS

import tkinter_png as png # png library for TKinter

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



class selWin: 
    "The selection window for skyboxes, music, goo and voice packs."
    noneItem = None
    def exit(self):
        "Quit and cancel."
        self.win.grab_release()
        self.win.withdraw()
        self.callback(None)
        
    def confirm(self):
        "Quit and return the newly-selected item."
        self.win.grab_release()
        self.win.withdraw()
        self.callback(None)

    def __init__(self, tk, lst, cback):
        self.callback=cback
        self.noneItem = Item('NONE','NONE')
        self.item_list = [self.noneItem] + lst
        self.win=Toplevel(tk)
        self.win.title("BEE2")
        self.win.resizable(True, True)
        self.win.iconbitmap('BEE2.ico')
        self.win.protocol("WM_DELETE_WINDOW", exit)
        self.win.withdraw()
        
        self.wid = {}
        shim = ttk.Frame(self.win, relief="sunken")
        shim.grid(row=0, column=0, sticky="NSEW")
        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)
        shim.rowconfigure(0, weight=1)
        shim.columnconfigure(0, weight=1)
        
        self.wid_canvas = Canvas(shim)
        self.wid_canvas.grid(row=0, column=0, sticky="NSEW") # need to use a canvas to allow scrolling

        self.wid_scroll = ttk.Scrollbar(shim, orient=VERTICAL, command=self.wid_canvas.yview)
        self.wid_scroll.grid(row=0, column=1, sticky="NS")
        self.wid_canvas['yscrollcommand'] = self.wid_scroll.set
        
        self.prop_frm = ttk.Frame(self.win, borderwidth=4, relief='raised')
        self.prop_frm.grid(row=0, column=1, sticky="NSEW")
        
        self.prop_icon_frm = ttk.Frame(self.prop_frm, borderwidth=4, relief='raised', width=64, height=64)
        self.prop_icon_frm.grid(row=0, column=0, columnspan=4)
        
        self.prop_icon = ttk.Label(self.prop_icon_frm)
        self.prop_icon.img = png.loadIcon('faithplate_128')
        self.prop_icon['image'] = self.prop_icon.img
        self.prop_icon.grid(row=0, column = 0)
        
        self.prop_name = ttk.Label(self.prop_frm, text="Item")
        self.prop_name.grid(row=1, column = 0, columnspan=4)
        self.prop_author = ttk.Label(self.prop_frm, text="Author")
        self.prop_author.grid(row=2, column = 0, columnspan=4)
        
        self.prop_desc_frm = ttk.Frame(self.prop_frm, relief="sunken")
        self.prop_desc_frm.grid(row=4, column=0, columnspan=4, sticky="NSEW")
        self.prop_desc_frm.rowconfigure(0, weight=1)
        self.prop_desc_frm.columnconfigure(0, weight=1)
        self.prop_frm.rowconfigure(4, weight=1)
        
        self.prop_desc = Text(self.prop_desc_frm, width=19, height=8, wrap="word", font="TkSmallCaptionFont")
        self.prop_desc.grid(row=0, column=0, padx=(2,0), pady=2, sticky="NSEW")
        self.prop_desc.insert("end", self.item_list[1].desc)
        self.prop_desc['state']="disabled" # need to set this to normal when editing text, then swap back
        
        self.prop_scroll = ttk.Scrollbar(self.prop_desc_frm, orient=VERTICAL, command=self.prop_desc.yview)
        self.prop_scroll.grid(row=0, column=1, sticky="NS", padx=(0,2), pady=2)
        self.prop_desc['yscrollcommand'] = self.prop_scroll.set
        
        self.prop_reset = ttk.Button(self.prop_frm, text = "Reset to Default", command = lambda obj=self: obj.reset_sel())
        self.prop_reset.grid(row=5, column=0, columnspan=4, sticky = "EW", padx=8, pady=(8,1))
        
        self.prop_ok = ttk.Button(self.prop_frm, text = "OK", command = lambda obj=self: obj.confirm())
        self.prop_cancel = ttk.Button(self.prop_frm, text = "Cancel", command = lambda obj=self: obj.exit())
        
        self.prop_ok.grid(row=6, column=0, padx=(8,16))
        self.prop_cancel.grid(row=6, column=2, padx=(16,8))
        ttk.Sizegrip(self.prop_frm).grid(row=6, column=3, sticky="SE")
        

    def open(self, parent, title, suggested = "", selected = ""):
        self.win.title("BEE2 - " + title)
        self.win.transient(master=parent)
        
        self.parent = parent
        
        self.win.deiconify()
        self.win.lift(parent)
        self.win.grab_set()
        self.win.geometry('+'+str(parent.winfo_rootx()-30)+'+'+str(parent.winfo_rooty()-self.win.winfo_reqheight()-30))

if __name__ == '__main__': # load the window if directly executing this file
    root=Tk()
    lbl = ttk.Label(root, text="I am a demo window.")
    lbl.grid()
    png.img_error=png.loadIcon('_error') # If image is not readable, use this instead
    root.geometry("+250+250")
    lst = [
        Item(
            "SKY_BTS", 
            "BTS", 
            longName = "Behind The Scenes - Factory", 
            icon = "faithplate_128", 
            desc = 'The dark constuction and office areas of Aperture. Catwalks '
                   'extend between different buildings, with vactubes and cranes '
                   'carrying objects throughout the facility. Abandoned offices can '
                   'often be found here.')
          ]
    window = selWin(root, lst, print)
    window.open(root, "Skybox", suggested = "NONE")
