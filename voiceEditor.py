from tkinter import *
from tkinter import ttk
from tkinter import font

import os
import itertools
import functools
import operator

from property_parser import Property
from config import ConfigFile
import tkinter_png as png
import utils

voice_item = None

UI = {}
coop_selected = False

TABS_SP = {}
TABS_COOP = {}

def quote_sort_func(quote):
    '''The quotes will be sorted by their priority value.'''
    try:
        return float(quote['priority', '0'])
    except ValueError:
        return 0.0
            
def modeswitch_sp():
    global coop_selected
    coop_selected = False
    UI['mode_SP'].state(['disabled'])
    UI['mode_COOP'].state(['!disabled'])
    refresh()
    
def modeswitch_coop():
    global coop_selected
    coop_selected = True
    UI['mode_SP'].state(['!disabled'])
    UI['mode_COOP'].state(['disabled'])
    refresh()
    
def show_trans(e):
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, END)
    text.insert('end', e.widget.transcript)
    text['state'] = 'disabled'
    
def check_toggled(var, config_section, quote_id):
    '''Update the config file to match the checkbox.'''
    config_section[quote_id] = utils.bool_as_int(var.get())
    
def configure_canv(e):
    canvas = e.widget
    frame = canvas.frame
    canvas['scrollregion'] = (
        0,
        0,
        canvas.winfo_reqwidth(),
        frame.winfo_reqheight(),
        )
    frame['width'] = canvas.winfo_reqwidth()
    
def save():
    print('Saving Configs!')
    config_sp.save_check()
    config_coop.save_check()
    config_mid_sp.save_check()
    config_mid_coop.save_check()
    win.withdraw()
    
def refresh(e=None):
    notebook = UI['tabs']
    is_coop = coop_selected
    
    # Save the current tab index so we can restore it after.
    current_tab = notebook.index(notebook.select())
    
    # Add or remove tabs so only the correct mode is visible.
    for name, tab in sorted(TABS_SP.items()):
        if is_coop:
            notebook.forget(tab)
        else:
            notebook.add(tab)
            if tab.nb_is_mid:
                # For the midpoint tabs, we use a special image to make
                # sure they are well-distinguished from the other groups.
                notebook.tab(
                    tab,
                    compound='image',
                    image=png.loadPng('icons/mid_quote'),
                    )
            else:
                notebook.tab(tab, text=tab.nb_text)
            
    for name, tab in sorted(TABS_COOP.items()):
        if is_coop:
            notebook.add(tab)
            if tab.nb_is_mid:
                notebook.tab(
                    tab, 
                    compound='image',
                    image=png.loadPng('icons/mid_quote'),
                    )
            else:
                notebook.tab(tab, text=tab.nb_text)

        else:
            notebook.forget(tab)
    notebook.select(current_tab)

def init(root):
    '''Initialise all the widgets.'''
    global win, QUOTE_FONT
    
    QUOTE_FONT = font.nametofont('TkHeadingFont').copy()
    QUOTE_FONT['weight'] = 'bold'
    
    win = Toplevel(root, name='voiceEditor')
    win.columnconfigure(0, weight=1)
    win.transient(master=root)
    win.withdraw()
    
    btn_frame = ttk.Frame(win)
    btn_frame.grid(row=0, column=0, sticky='EW')
    btn_frame.columnconfigure(0, weight=1)
    btn_frame.columnconfigure(1, weight=1)
    
    UI['mode_SP'] = ttk.Button(
        btn_frame, 
        text='Single-Player',
        state=['disabled'],
        command=modeswitch_sp,
        )
    UI['mode_SP'].grid(row=0, column=0, sticky=E)
    
    UI['mode_COOP'] = ttk.Button(
        btn_frame, 
        text='Coop',
        command=modeswitch_coop,
        )
    UI['mode_COOP'].grid(row=0, column=1, sticky=W)

    
    pane = ttk.PanedWindow(
        win,
        orient=VERTICAL,
        )
    UI['pane'] = pane
    pane.grid(row=1, column=0, sticky='NSEW')
    win.rowconfigure(1, weight=1)
    
    UI['tabs'] = ttk.Notebook(pane)
    UI['tabs'].enable_traversal() # Add keyboard shortcuts
    pane.add(UI['tabs'], weight=2)
    
    trans_frame = ttk.Frame(pane)
    trans_frame.rowconfigure(0, weight=1)
    trans_frame.columnconfigure(0, weight=1)
    pane.add(trans_frame, weight=1)
    
    ttk.Label(
        trans_frame,
        text='Transcript:',
        ).grid(
            row=0,
            column=0, 
            sticky=W,
            )
    
    trans_inner_frame = ttk.Frame(trans_frame, borderwidth=2, relief='sunken')
    trans_inner_frame.grid(row=1, column=0, sticky='NSEW')
    trans_inner_frame.rowconfigure(0, weight=1)
    trans_inner_frame.columnconfigure(0, weight=1)
    
    UI['trans'] = Text(
        trans_inner_frame,
        width=10, 
        height=10,
        wrap='word',
        relief='flat',
        state='disabled',
        font=('Helvectia', 10),
        )
    UI['trans_scroll'] = ttk.Scrollbar(
        trans_inner_frame,
        orient=VERTICAL,
        command=UI['trans'].yview,
        )
    UI['trans']['yscrollcommand'] = UI['trans_scroll'].set
    UI['trans_scroll'].grid(row=0, column=1, sticky='NS')
    UI['trans'].grid(row=0, column=0, sticky='NSEW')
    
    ttk.Button(
        win,
        text='Save',
        command=save,
        ).grid(row=2, column=0)
        
    pane.rowconfigure(0, minsize=100)
    pane.rowconfigure(1, minsize=100)
    
def show(quote_pack):
    '''Display the editing window.'''
    global voice_item, config_sp, config_coop, config_mid_sp, config_mid_coop
    voice_item = quote_pack
    
    notebook = UI['tabs']
    
    quote_data = quote_pack.config
    
    os.makedirs('config/voice', exist_ok=True)
    config_sp = ConfigFile('voice/SP_' + quote_pack.id + '.cfg')
    config_coop = ConfigFile('voice/COOP_' + quote_pack.id + '.cfg')
    config_mid_sp = ConfigFile('voice/MID_SP_' + quote_pack.id + '.cfg')
    config_mid_coop = ConfigFile('voice/MID_COOP_' + quote_pack.id + '.cfg')
    
    # Destroy all the old tabs
    for tab in itertools.chain(
            TABS_SP.values(),
            TABS_COOP.values(),
            ):
        try:
            notebook.forget(tab)
        except TclError:
            pass
        tab.destroy()
        
    TABS_SP.clear()
    TABS_COOP.clear()
    
    add_tabs(quote_data, 'quotes_sp', TABS_SP, config_sp)
    add_tabs(quote_data, 'quotes_coop', TABS_COOP, config_coop)
    
    config_sp.save()
    config_coop.save()
    config_mid_sp.save()
    config_mid_coop.save()
    
    refresh()
    win.deiconify()
    win.lift(win.winfo_parent())
    utils.center_win(win) # Center inside the parent
    
def add_tabs(quote_data, section, tab_dict, config):
    '''Add all the tabs for one of the game modes.'''
    for group in quote_data.find_all(section, 'group'):
        frame = make_tab(
            group,
            tab_dict,
            config,
            is_mid=False,
            )
    
    mid_quotes = list(quote_data.find_all(section, 'midchamber'))
    if len(mid_quotes) > 0:
        frame = make_tab(
            mid_quotes[0],
            tab_dict,
            config,
            is_mid=True,
            )
        frame.nb_text = ''

def make_tab(group, tab_dict, config, is_mid=False):
    '''Create all the widgets for a tab.'''
    group_name = group['name', 'No Name!']
    group_desc = group['desc', '']
    # This is just to hold the canvas and scrollbar
    outer_frame = ttk.Frame(UI['tabs'])
    outer_frame.columnconfigure(0, weight=1)
    outer_frame.rowconfigure(0, weight=1)
    
    tab_dict[group_name] = outer_frame
    # We add this attribute so the refresh() method knows all the 
    # tab names
    outer_frame.nb_text = group_name
    outer_frame.nb_is_mid = is_mid
    
    # We need a canvas to make the list scrollable.
    canv = Canvas(
        outer_frame, 
        highlightthickness=0,
        )
    scroll = ttk.Scrollbar(
    outer_frame,
    orient=VERTICAL,
    command=canv.yview,
    )
    canv['yscrollcommand'] = scroll.set
    canv.grid(row=0, column=0, sticky='NSEW')
    scroll.grid(row=0, column=1, sticky='NS')
    
    UI['tabs'].add(outer_frame)
    
    # This holds the actual elements
    frame = ttk.Frame(
        canv,
        )
    frame.columnconfigure(0, weight=1)
    canv.create_window(0, 0, window=frame, anchor="nw")
    
    # We do this so we can adjust the scrollregion later in 
    # <Configure>.
    canv.frame = frame
    
    if is_mid:
        group_name = 'Mid - Chamber'
        group_desc = 'Lines played during normal gameplay'
        
    ttk.Label(
        frame,
        text=group_name,
        anchor='center',
        font='tkHeadingFont',
        ).grid(
            row=0, 
            column=0, 
            sticky='EW',
            )
    
    ttk.Label(
        frame,
        text=group_desc + ':',
        ).grid(
            row=1, 
            column=0, 
            sticky='EW',
            )
            
    ttk.Separator(frame, orient=HORIZONTAL).grid(
        row=2,
        column=0,
        sticky='EW',
        )
            
    sorted_quotes = sorted(
        group.find_all('Quote'),
        key = quote_sort_func,
        reverse=True,
        )
        
    for quote in sorted_quotes:
        ttk.Label(
            frame, 
            text=quote['name', 'No Name!'],
            font=QUOTE_FONT,
            ).grid(
                column=0,
                sticky=W,
                )
        
        for line in quote.find_all('Instance'):
            line_id = line['id', line['name']]
            check = ttk.Checkbutton(    
                frame,
                text=line['name'],
                )
            check.quote_var = IntVar(
                value=config.get_bool(group_name, line_id, True),
                )
            check['variable'] = check.quote_var
            
            check['command'] = functools.partial(
                check_toggled,
                check.quote_var,
                config[group_name],
                line_id,
                )
                
            check.transcript = '\n\n'.join(
                ['"' + trans.value + '"'
                for trans in
                line.find_all('trans')
                ])  
            check.grid(
                column=0,
                padx=(10, 0),
                sticky=W,
                )
            check.bind("<Enter>", show_trans)
    canv.bind('<Configure>', configure_canv)
    
    return outer_frame


if __name__ == '__main__':
    import packageLoader
    data = packageLoader.load_packages('packages\\', False)

    root = Tk()
    lab = ttk.Label(root, text='Root Window')
    lab.bind('<Button-1>', lambda e: show(d['BEE2_CAVE_50s']))
    lab.grid()
    init(root)
    d = {quote.id: quote for quote in data['QuotePack']}
    print(d)
    show(d['BEE2_CAVE_50s'])