from tkinter import *
from tkinter import ttk

import os

from property_parser import Property
from config import ConfigFile
import utils

voice_item = None

UI = {}
coop_selected = False

TABS_SP = {}
TABS_COOP = {}

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
    pass
    
def refresh(e=None):
    notebook = UI['pane']
    is_coop = coop_selected
    
    # Save the current tab index so we can restore it after.
    current_tab = notebook.index(notebook.select())
    
    # Add or remove tabs so only the correct mode is visible.
    for name, tab in sorted(TABS_SP.items()):
        if is_coop:
            notebook.forget(tab)
        else:
            notebook.add(tab)
            notebook.tab(tab, text=tab.nb_text)
            
    for name, tab in sorted(TABS_COOP.items()):
        if is_coop:
            notebook.add(tab)
            notebook.tab(tab, text=tab.nb_text)
        else:
            notebook.forget(tab)
    notebook.select(current_tab)

def init(root):
    global win
    win = Toplevel(root, name='voiceEditor')
    win.columnconfigure(0, weight=1)
    
    mode_frame = ttk.Frame(win)
    mode_frame.grid(row=0, column=0, sticky="EW")
    
    UI['mode_SP'] = ttk.Button(
        mode_frame, 
        text='SP',
        state=['disabled'],
        command=modeswitch_sp,
        )
    UI['mode_SP'].grid(row=0, column=0, sticky=W)
    
    UI['mode_COOP'] = ttk.Button(
        mode_frame, 
        text='COOP',
        command=modeswitch_coop,
        )
    UI['mode_COOP'].grid(row=0, column=1, sticky=E)
    
    UI['pane'] = ttk.Notebook(win, name='notebook')
    UI['pane'].grid(row=1, column=0, sticky='NSEW')

        
    #UI['pane'].bind('<<NotebookTabChanged>>', test)
    
def show(quote_pack):
    '''Display the editing window.'''
    global voice_item, config_sp, config_coop
    voice_item = quote_pack
    
    notebook = UI['pane']
    
    quote_data = quote_pack.config
    
    os.makedirs('config/voice', exist_ok=True)
    config_sp = ConfigFile('voice/SP_' + quote_pack.id + '.cfg')
    config_coop = ConfigFile('voice/COOP_' + quote_pack.id + '.cfg')
    print(config_sp, config_coop)
    
    for tab in TABS_SP.values():
        notebook.forget(tab)
        tab.destroy()
    for tab in TABS_COOP.values():
        notebook.forget(tab)
        tab.destroy()
    TABS_SP.clear()
    TABS_COOP.clear()
    
    make_tabs(quote_data.find_key('quotes_sp'), TABS_SP, config_sp, 'sp')
    make_tabs(quote_data.find_key('quotes_coop'), TABS_COOP, config_coop, 'coop')
    config_sp.save()
    refresh()
    win.deiconify()
    win.lift()

def make_tabs(props, tab_dict, config, mode):
    '''Create all the widgets for a tab.'''
    for group in props.find_all('Group'):
        group_name = group['name']
        group_desc = group['desc', '']
        print(group_name, group_desc)
        tab = ttk.Frame(
            UI['pane'], 
            name=mode + '_' + group_name,
            )
        tab_dict[group_name] = tab
        
        tab.nb_text = group_name
        ttk.Label(
            tab,
            text=group_name,
            anchor='center',
            font='tkHeadingFont',
            ).grid(
                row=0, 
                column=0, 
                sticky='EW',
                )
                
        ttk.Label(
            tab,
            text=group_desc + ':',
            ).grid(
                row=1, 
                column=0, 
                sticky='EW',
                )
                
        ttk.Separator(tab, orient=HORIZONTAL).grid(
            row=2,
            column=0,
            sticky='EW',
            )
            
        for quote in group.find_all('Quote'):
            ttk.Label(
                tab, 
                text=quote['name', ''],
                ).grid(
                    column=0,
                    sticky=W,
                    )
            
            for line in quote.find_all('Instance'):
                line_name = line['Name']
                check = ttk.Checkbutton(    
                    tab,
                    text=line_name,
                    )
                check.quote_var = IntVar(
                    value=config.get_bool(group_name, line_name, True),
                    )
                check['variable'] = check.quote_var
                check.grid(
                    column=0,
                    padx=(10, 0),
                    sticky=W,
                    )

        UI['pane'].add(tab)

if __name__ == '__main__':
    import packageLoader
    data = packageLoader.load_packages('packages\\', False)

    root = Tk()
    ttk.Label(root, text='Root Window').grid()
    init(root)
    d = {quote.id: quote for quote in data['QuotePack']}
    print(d)
    show(d['BEE2_CAVE_50s'])