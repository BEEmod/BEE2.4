"""Backup and restore P2C maps.

"""
import tkinter as tk
from tkinter import ttk
from tk_tools import TK_ROOT

import time
from zipfile import ZipFile

from property_parser import Property
from CheckDetails import CheckDetails, Item as CheckItem
import utils
import tk_tools
import gameMan

window = None  # type: tk.Toplevel

UI = {}

menus = {}  # For standalone application, generate menu bars

HEADERS = ['Name', 'Mode', 'Date', 'Description']

# The game subfolder where puzzles are located
PUZZLE_FOLDERS = {
    utils.STEAM_IDS['PORTAL2']: 'portal2',
    utils.STEAM_IDS['APTAG']: 'aperturetag',
    utils.STEAM_IDS['TWTM']: 'TWTM',
}


class P2C:
    """A PeTI map."""
    def __init__(self, path, props):
        props = Property.parse(props)

        self.path = path
        self.title = props['title', '<Untitled>']
        self.desc = props['description', '...']
        self.is_coop = utils.conv_bool(props['coop', '0'])
        self.create_time = read_time(props['timestamp_created', ''])
        self.mod_time = read_time(props['timestamp_modified', ''])


def read_time(hex_time):
    """Convert the time format in P2C files into a readable string."""
    try:
        val = int(hex_time, 16)
    except ValueError:
        return '??'
    date = time.localtime(val)
    return time.strftime(
        '%d %b %Y, %I:%M%p',
        date,
    )


def init():
    """Initialise all widgets in the given window."""
    for cat, btn_text in [
            ('back_', 'Restore:'),
            ('game_', 'Backup:'),
            ]:
        UI[cat + 'frame'] = frame = ttk.Frame(
            window,
        )

        UI[cat + 'title'] = ttk.Label(
            frame,
        )
        UI[cat + 'title'].grid(row=0, column=0, sticky='EW')
        UI[cat + 'details'] = CheckDetails(
            frame,
            headers=HEADERS,
        )
        UI[cat + 'details'].grid(row=1, column=0, sticky='NSEW')
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        button_frame = ttk.Frame(
            frame,
        )
        button_frame.grid(column=0, row=2)
        ttk.Label(button_frame, text=btn_text).grid(row=0, column=0)
        UI[cat + 'btn_all'] = ttk.Button(
            button_frame,
            text='All',
            width=3,
        )
        UI[cat + 'btn_sel'] = ttk.Button(
            button_frame,
            text='Selected',
            width=8,
        )
        UI[cat + 'btn_all'].grid(row=0, column=1)
        UI[cat + 'btn_sel'].grid(row=0, column=2)

        UI[cat + 'btn_del'] = ttk.Button(
            button_frame,
            text='Delete Selected',
            width=14,
        )
        UI[cat + 'btn_del'].grid(row=1, column=0, columnspan=3)

        utils.add_mousewheel(
            UI[cat + 'details'].wid_canvas,
            UI[cat + 'frame'],
        )

    UI['back_frame'].grid(row=1, column=0, sticky='NSEW')
    ttk.Separator(orient=tk.VERTICAL).grid(
        row=1, column=1, sticky='NS', padx=5,
    )
    UI['game_frame'].grid(row=1, column=2, sticky='NSEW')

    window.rowconfigure(1, weight=1)
    window.columnconfigure(0, weight=1)
    window.columnconfigure(2, weight=1)


def init_application():
    """Initialise the standalone application."""
    global window
    window = TK_ROOT
    init()

    UI['bar'] = bar = tk.Menu(TK_ROOT)
    window.option_add('*tearOff', False)

    gameMan.load()

    if utils.MAC:
        # Name is used to make this the special 'BEE2' menu item
        file_menu = menus['file'] = tk.Menu(bar, name='apple')
    else:
        file_menu = menus['file'] = tk.Menu(bar)
    file_menu.add_command(label='New Backup')
    file_menu.add_command(label='Open Backup')
    file_menu.add_command(label='Save Backup')
    file_menu.add_command(label='Save Backup As')

    bar.add_cascade(menu=file_menu, label='File')

    game_menu = menus['game'] = tk.Menu(bar)

    game_menu.add_command(label='Add Game', command=gameMan.add_game)
    game_menu.add_command(label='Remove Game', command=gameMan.remove_game)
    game_menu.add_separator()

    bar.add_cascade(menu=game_menu, label='Game')
    window['menu'] = bar

    gameMan.add_menu_opts(game_menu)
    gameMan.game_menu = game_menu


def init_toplevel():
    """Initialise the window as part of the BEE2."""
    global window
    window = tk.Toplevel(TK_ROOT)
    window.transient(TK_ROOT)

    init()


if __name__ == '__main__':
    # Run this standalone.
    init_application()

    TK_ROOT.deiconify()
    TK_ROOT.mainloop()