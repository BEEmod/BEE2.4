"""Allows enabling and disabling individual packages.
"""
from tkinter import ttk
from tkinter import messagebox
import tkinter as tk
from tk_tools import TK_ROOT

from CheckDetails import CheckDetails, Item as CheckItem
from BEE2_config import ConfigFile
import packageLoader
import utils
import tk_tools

window = tk.Toplevel(TK_ROOT)
window.withdraw()

UI = {}

PACK_CONFIG = ConfigFile('packages.cfg')

pack_items = {}

HEADERS = ['Name']


def show():
    """Show the manager window."""
    window.deiconify()
    utils.center_win(window, TK_ROOT)
    window.after(100, UI['details'].refresh)


def make_packitems():
    """Make the checkitems used in the details view."""
    pack_items.clear()
    for pack in packageLoader.packages.values():  # type: packageLoader.Package
        pack_items[pack.id] = item = CheckItem(
            pack.disp_name,
            hover_text=pack.desc or None,
            # The clean package can't be disabled!
            lock_check=(pack.id == packageLoader.CLEAN_PACKAGE),
        )
        item.state = pack.enabled
        item.package = pack
    return pack_items.values()


def make_window():
    """Initialise the window."""
    window.transient(TK_ROOT)
    window.title('BEE2 - Manage Packages')

    # Don't destroy window when quit!
    window.protocol("WM_DELETE_WINDOW", cancel)

    frame = ttk.Frame(window)
    frame.grid(row=0, column=0, sticky='NSEW')
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)

    UI['details'] = CheckDetails(
        frame,
        headers=HEADERS,
        items=make_packitems(),
    )

    UI['details'].grid(row=0, column=0, sticky='NSEW')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=0, column=1, sticky='NSE')

    ttk.Button(
        btn_frame,
        text='Ok',
    ).grid(row=0, column=0)

    ttk.Button(
        btn_frame,
        text='Cancel',
    ).grid(row=1, column=0)