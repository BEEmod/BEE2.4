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

window = None  # type: tk.Toplevel

UI = {}


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


def init_toplevel():
    """Initialise the window as part of the BEE2."""
    global window
    window = tk.Toplevel(TK_ROOT)
    init()


if __name__ == '__main__':
    # Run this standalone.
    init_toplevel()
    TK_ROOT.deiconify()
    TK_ROOT.mainloop()