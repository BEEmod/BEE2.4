from tkinter import * # ui library
from tkinter import font
from tkinter import ttk # themed ui components that match the OS
from functools import partial as func_partial
import math

import tkinter_png as png # png library for TKinter
from richTextBox import tkRichText

ICON_SIZE=96
ITEM_WIDTH=ICON_SIZE+16
ITEM_HEIGHT=ICON_SIZE+51


def _NO_OP(new_id):
    '''The default callback, triggered whenever the chosen item is changed.'''
    pass

class Item:
    '''An item on the panel.
    
    '''
    __slots__ = ('name', 'shortName', 'longName', 'icon', 'desc', 'authors', 'button', 'win', 'context_lbl')
    def __init__(
            self,
            name, 
            shortName, 
            longName = None,
            icon = None, 
            authors = None,
            desc = ""):
        self.name = name
        self.shortName = shortName
        self.longName = shortName if longName is None else longName
        self.context_lbl = self.shortName
        if icon is None:
            self.icon = png.loadPng('BEE2/blank')
        else:
            self.icon = png.loadPng(icon)
        self.desc = desc
        self.authors = [] if authors is None else authors
        
    def __repr__(self):
        return '<Item:' + self.name + '>'

class selWin: 
    "The selection window for skyboxes, music, goo and voice packs."
    def __init__(self, tk, lst, has_none=True, has_def=True, none_desc=[('line', 'Do not add anything.')], title='BEE2', callback=_NO_OP):
        '''Create a window object.
        
        Read from .selected_id to get the currently-chosen Item name, or None if the <none> Item is selected.
        Args:
        - tk must be a Toplevel window, either the tk() root or another window if needed.
        - lst is a list of Item objects, defining the visible items.
        - If has_none is True, a <none> item will be added to the beginning of the list.
        - If has_def is True, the 'Reset to Default' button will appear, which resets to the suggested item.
        - none_desc holds an optional description for the <none> Item, which can be used to describe what it results in.
        - title is the title of the selector window.
        - callback is a function to be called whenever the selected item changes.
        ''' 
        self.noneItem = Item('NONE', '', desc=none_desc)
        self.noneItem.icon = png.loadPng('BEE2/none_96')
        self.disp_label = StringVar()
        self.chosen_id = None
        self.callback = callback
        self.suggested = None
        self.has_def = has_def
        if has_none:
            self.item_list = [self.noneItem] + lst
        else:
            self.item_list = lst
        self.selected = self.item_list[0]
        self.orig_selected = self.selected
        self.parent = tk
        
        self.win=Toplevel(tk)
        self.win.withdraw()
        self.win.title("BEE2 - " + title)
        self.win.transient(master=tk)
        self.win.resizable(True, True)
        self.win.iconbitmap('BEE2.ico')
        self.win.protocol("WM_DELETE_WINDOW", self.exit)
        self.win.bind("<Escape>", self.exit)
        
        self.pane_win = ttk.Panedwindow(self.win, orient=HORIZONTAL)
        self.pane_win.grid(row=0, column=0, sticky="NSEW")
        
        self.wid = {}
        shim = ttk.Frame(self.pane_win, relief="sunken")
        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)
        shim.rowconfigure(0, weight=1)
        shim.columnconfigure(0, weight=1)
        
        
        self.wid_canvas = Canvas(shim, highlightthickness=0)
        self.wid_canvas.grid(row=0, column=0, sticky="NSEW") # need to use a canvas to allow scrolling

        self.pal_frame=ttk.Frame(self.wid_canvas) # add another frame inside to place labels on
        self.wid_canvas.create_window(1, 1, window=self.pal_frame, anchor="nw")
        
        self.wid_scroll = ttk.Scrollbar(shim, orient=VERTICAL, command=self.wid_canvas.yview)
        self.wid_scroll.grid(row=0, column=1, sticky="NS")
        self.wid_canvas['yscrollcommand'] = self.wid_scroll.set
        
        self.sugg_lbl = ttk.LabelFrame(self.pal_frame, text="Suggested", labelanchor=N, height=50)
        
        self.prop_frm = ttk.Frame(self.pane_win, borderwidth=4, relief='raised')
        self.prop_frm.columnconfigure(1, weight=1)
        
        self.prop_icon_frm = ttk.Frame(self.prop_frm, borderwidth=4, relief='raised', width=ICON_SIZE, height=ICON_SIZE)
        self.prop_icon_frm.grid(row=0, column=0, columnspan=4)
        
        self.prop_icon = ttk.Label(self.prop_icon_frm)
        self.prop_icon.img = png.loadPng('BEE2/blank')
        self.prop_icon['image'] = self.prop_icon.img
        self.prop_icon.grid(row=0, column = 0)
        
        self.prop_name = ttk.Label(self.prop_frm, text="Item", justify=CENTER, font=("Helvetica", 12, "bold"))
        self.prop_name.grid(row=1, column = 0, columnspan=4)
        self.prop_author = ttk.Label(self.prop_frm, text="Author")
        self.prop_author.grid(row=2, column = 0, columnspan=4)
        
        self.prop_desc_frm = ttk.Frame(self.prop_frm, relief="sunken")
        self.prop_desc_frm.grid(row=4, column=0, columnspan=4, sticky="NSEW")
        self.prop_desc_frm.rowconfigure(0, weight=1)
        self.prop_desc_frm.columnconfigure(0, weight=1)
        self.prop_frm.rowconfigure(4, weight=1)
        
        self.prop_desc = tkRichText(self.prop_desc_frm, width=40, height=16, font="TkSmallCaptionFont")
        self.prop_desc.grid(row=0, column=0, padx=(2,0), pady=2, sticky="NSEW")
        
        self.prop_scroll = ttk.Scrollbar(self.prop_desc_frm, orient=VERTICAL, command=self.prop_desc.yview)
        self.prop_scroll.grid(row=0, column=1, sticky="NS", padx=(0,2), pady=2)
        self.prop_desc['yscrollcommand'] = self.prop_scroll.set
        
        if self.has_def:
            self.prop_reset = ttk.Button(self.prop_frm, text = "Reset to Default", command=self.reset_sel)
            self.prop_reset.grid(row=5, column=1, sticky = "EW")
        
        self.prop_ok = ttk.Button(self.prop_frm, text = "OK", command=self.save)
        self.prop_cancel = ttk.Button(self.prop_frm, text = "Cancel", command=self.exit)
        
        self.prop_ok.grid(row=5, column=0, padx=(8,8))
        self.prop_cancel.grid(row=5, column=2, padx=(8,8))
        
        self.win.option_add('*tearOff', False)
        self.context_menu = Menu(self.win)
        self.sugg_font = font.nametofont('TkMenuFont')
        self.sugg_font['weight'] = 'bold'
        self.context_var = IntVar()
        
        for ind, item in enumerate(self.item_list):
            if item==self.noneItem:
                item.button = ttk.Button(self.pal_frame, image=item.icon)
                item.context_lbl = '<None>'
            else:
                item.button = ttk.Button(self.pal_frame, text=item.shortName, image=item.icon, compound='top')
            self.context_menu.add_radiobutton(
            label=item.context_lbl, 
            command=func_partial(self.sel_item_id, item.name),
            var = self.context_var, value=ind)
            
            item.win = self.win
            item.button.bind("<Button-1>", func_partial(self.sel_item, item))
            item.button.bind("<Double-Button-1>", self.save)
        self.flow_items(None)
        self.wid_canvas.bind("<Configure>", self.flow_items)
        
        self.pane_win.add(shim, weight=1)
        self.pane_win.add(self.prop_frm)
        
    def init_display(self, frame, row=0, column=0, colspan=1, rowspan=1):
        '''Create and grid() the label used to open the selector window.'''
        
        self.display = ttk.Entry(frame, textvariable=self.disp_label, cursor='arrow')
        self.display.grid(row=row, column=column, columnspan=colspan, rowspan=rowspan, sticky="EW")
        self.display.bind("<Button-1>", self.open_win)
        self.display.bind("<Key>", self.set_disp)
        self.display.bind("<Button-3>", self.open_context)
        
        self.disp_btn = ttk.Button(self.display, text="...", width=1.5, command=self.open_win)
        self.disp_btn.pack(side=RIGHT)
        
        self.save()
        
    def exit(self):
        '''Quit and cancel, choosing the originally-selected item.'''
        self.sel_item(self.orig_selected)
        self.save()
        
    def save(self, e=None):
        "Save the selected item into the textbox."
        self.win.grab_release()
        self.win.withdraw()
        self.set_disp()
        self.callback(self.chosen_id)
        
    def set_disp(self, e=None):
        '''Set the display textbox.'''
        if self.selected == self.noneItem:
            self.disp_label.set("<None>")
            self.chosen_id = None
        else:
            self.disp_label.set(self.selected.shortName)
            self.chosen_id = self.selected.name
        self.context_var.set(self.item_list.index(self.selected))
        return "break" # stop the entry widget from continuing with this event
            
    def open_win(self, e=None):
        self.win.deiconify()
        self.win.lift(self.parent)
        self.win.grab_set()
        self.win.focus_force() # Focus here to deselect the textbox
        self.win.geometry('+'+str(self.parent.winfo_rootx()+30)+'+'+str(self.parent.winfo_rooty()+30))
        self.flow_items()
        self.sel_item(self.selected)
        
    def open_context(self, e):
        self.context_menu.post(
            self.display.winfo_rootx(), 
            self.display.winfo_rooty() + self.display.winfo_height())
        
    def reset_sel(self):
        if self.suggested is not None:
            self.sel_item(self.suggested)
            
    def sel_item_id(self, id):
        '''Select the item with the given ID.'''
        for item in self.item_list:
            if item.name == id:
                self.sel_item(item)
                self.set_disp()
                self.callback(self.chosen_id)
                return True
        return False
        
    def sel_item(self, item, e=None):
        self.prop_name['text'] = item.longName
        if len(item.authors) == 0:
            self.prop_author['text'] = ''
        elif len(item.authors) == 1:
            self.prop_author['text'] = 'Author: ' + item.authors[0]
        else:
            self.prop_author['text'] = 'Authors: ' + ', '.join(item.authors)
        self.prop_icon['image'] = item.icon
        
        self.prop_desc.set_text(item.desc)
        
        self.selected.button.state(('!alternate',))
        self.selected = item
        item.button.state(('alternate',))
        if self.has_def:
            if self.suggested is None or self.selected == self.suggested:
                self.prop_reset.state(('disabled',))
            else:
                self.prop_reset.state(('!disabled',))
    
    def flow_items(self, e=None):
        self.pal_frame.update_idletasks()
        self.pal_frame['width']=self.wid_canvas.winfo_width()
        self.prop_name['wraplength'] = self.prop_desc.winfo_width()
        width=(self.wid_canvas.winfo_width()-10) // ITEM_WIDTH
        if width <1:
            width=1 # we got way too small, prevent division by zero
        itemNum=len(self.item_list)
        self.wid_canvas['scrollregion'] = (0, 0, width*ITEM_WIDTH, math.ceil(itemNum/width)*ITEM_HEIGHT+20)
        self.pal_frame['height']=(math.ceil(itemNum/width)*ITEM_HEIGHT+20)
        for i,item in enumerate(self.item_list):
            if item == self.suggested:
                self.sugg_lbl.place(x=((i%width) *ITEM_WIDTH+1),y=((i//width)*ITEM_HEIGHT))
                self.sugg_lbl['width'] = item.button.winfo_width()
            item.button.place(x=((i%width) *ITEM_WIDTH+1),y=((i//width)*ITEM_HEIGHT+20))
            item.button.lift()
        
    def set_suggested(self, suggested=None):
        '''Set the suggested item to the given ID. 
        
        If the ID is None or does not exist, the suggested item will be cleared.
        If the ID is "<NONE>", it will be set to the None item.
        '''
        
        if self.suggested is not None:
            self.context_menu.entryconfig(
                self.item_list.index(self.suggested),
                font='')
            # Remove the font from the last suggested item
        
        if suggested == None:
            self.suggested = None
        elif suggested == "<NONE>":
            self.suggested = self.noneItem
        else:
            for item in self.item_list:
                if item.name == suggested:
                    self.suggested=item
                    break
            else: # Not found
                self.suggested = None
                
        if self.suggested is not None:
            self.context_menu.entryconfig(
                self.item_list.index(self.suggested),
                font=self.sugg_font)
        self.flow_items() # Refresh

if __name__ == '__main__': # test the window if directly executing this file
    root=Tk()
    lbl = ttk.Label(root, text="I am a demo window.")
    lbl.grid()
    png.img_error=png.loadPng('BEE2/error') # If image is not readable, use this instead
    root.geometry("+500+500")
    lst = [
        Item(
            "SKY_BLACK", 
            "Black", 
            longName = "Darkness", 
            icon = "skies/black",
            authors = ["Valve"],
            desc = [('line', 'Pure black darkness. Nothing to see here.')]),
        Item(
            "SKY_BTS", 
            "BTS", 
            longName = "Behind The Scenes - Factory", 
            icon = "voices/glados",
            authors = ["TeamSpen210"],
            desc = [
                ('line', 'The dark constuction and office areas of Aperture. Catwalks '
                         'extend between different buildings, with vactubes and cranes '
                         'carrying objects throughout the facility.'),
                ('rule', ''),
                ('line', 'Abandoned offices can often be found here.')
                   ])
          ]
        
    def done(x):
        print(x)
        root.withdraw()
    window = selWin(root, lst, has_none=True, has_def=True)
    window.init_display(root, 1, 0)
    window.set_suggested("SKY_BLACK")
