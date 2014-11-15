from tkinter import * # ui library
from tkinter import ttk # themed ui components that match the OS
import math

import tkinter_png as png # png library for TKinter

class Item:
    "An item on the panel."
    __slots__ = ('name', 'shortName', 'longName', 'icon', 'desc', 'author', 'button', 'win')
    def __init__(
            self,
            name, 
            shortName, 
            longName = None,
            icon = None, 
            author = '',
            desc = ""):
        self.name = name
        self.shortName = shortName
        self.longName = shortName if longName is None else longName
        self.icon = None if icon is None else png.loadIcon(icon)
        self.desc = desc
        self.author = author


class selWin: 
    "The selection window for skyboxes, music, goo and voice packs."
    def exit(self):
        "Quit and cancel."
        self.win.grab_release()
        self.win.withdraw()
        self.callback(None)
        
    def confirm(self):
        "Quit and return the newly-selected item."
        self.win.grab_release()
        self.win.withdraw()
        if self.item_list[self.selected] == self.noneItem:
            self.callback(None)
        else:
            self.callback(self.item_list[self.selected].name)
        
    def sel_item(self, item):
        self.prop_author['text'] = item.longName
        self.prop_name['text'] = item.author
        self.prop_icon['image'] = item.icon
        
        self.prop_desc['state']="normal"
        self.prop_desc.delete(1.0, END)
        self.prop_desc.insert("end", item.desc) 
        self.prop_desc['state']="disabled"
        
        self.item_list[self.selected].button.state(('!alternate',))
        
        self.selected = self.item_list.index(item)
        item.button.state(('alternate',))
    
    def flow_items(self, e):
        self.pal_frame.update_idletasks()
        self.pal_frame['width']=self.wid_canvas.winfo_width()
        width=(self.wid_canvas.winfo_width()-10) // 80
        if width <1:
            width=1 # we got way too small, prevent division by zero
        itemNum=len(self.item_list)
        self.wid_canvas['scrollregion'] = (0, 0, width*80, math.ceil(itemNum/width)*100+2)
        self.pal_frame['height']=(math.ceil(itemNum/width)*100+2)
        for i,item in enumerate(self.item_list):
            item.button.place(x=((i%width) *80+1),y=((i//width)*100+1))
            item.button.lift()

    def __init__(self, tk, lst, cback):
        self.callback=cback
        self.noneItem = Item('NONE','<None>')
        self.noneItem.icon = png.loadPng('none')
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

        self.pal_frame=ttk.Frame(self.wid_canvas) # add another frame inside to place labels on
        self.wid_canvas.create_window(1, 1, window=self.pal_frame, anchor="nw")
        
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
        self.prop_desc['state']="disabled"
        
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
        
        for item in self.item_list:
            item.button = ttk.Button(self.pal_frame, text=item.shortName, image=item.icon, compound='top')
            item.win = self.win
            item.button.bind("<Button-1>",lambda e, s=self, i=item: s.sel_item(i))
        self.flow_items(None)
        self.wid_canvas.bind("<Configure>",lambda e, s=self: s.flow_items(e))
        

    def open(self, parent, title, suggested = "", selected = ""):
        self.win.title("BEE2 - " + title)
        self.win.transient(master=parent)
        self.selected = 0
        self.parent = parent
        
        self.win.deiconify()
        self.win.lift(parent)
        self.win.grab_set()
        self.win.geometry('+'+str(parent.winfo_rootx()-30)+'+'+str(parent.winfo_rooty()-self.win.winfo_reqheight()-30))
        self.sel_item(self.item_list[self.selected])

if __name__ == '__main__': # load the window if directly executing this file
    root=Tk()
    lbl = ttk.Label(root, text="I am a demo window.")
    lbl.grid()
    png.img_error=png.loadIcon('_error') # If image is not readable, use this instead
    root.geometry("+500+500")
    lst = [
        Item(
            "SKY_BTS", 
            "BTS", 
            longName = "Behind The Scenes - Factory", 
            icon = "faithplate_128",
            author = "TeamSpen210",
            desc = 'The dark constuction and office areas of Aperture. Catwalks '
                   'extend between different buildings, with vactubes and cranes '
                   'carrying objects throughout the facility. Abandoned offices can '
                   'often be found here.'),
        Item(
            "SKY_BLACK", 
            "Black", 
            longName = "Darkness", 
            icon = "faithplate_128",
            author = "Valve",
            desc = 'Pure black darkness. Nothing to see here.')
          ]
    def done(x):
        print(x)
        root.withdraw()
    window = selWin(root, lst, done)
    window.open(root, "Skybox", suggested = "NONE")
