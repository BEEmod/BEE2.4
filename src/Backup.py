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


class P2C:
    """A PeTI map."""
    def __init__(self, path, props):
        props = Property.parse(props)

        self.path = path
        self.title = props['title', '<Untitled>']
        self.desc = props['description', '...']
        self.is_coop = utils.conv_bool(props['coop', '0'])
        self.create_time = props['Timestamp_Created', '']


def read(hex_time):
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
    pass


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