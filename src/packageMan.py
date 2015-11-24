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

window = tk.Toplevel(TK_ROOT)
window.withdraw()

UI = {}

PACK_CONFIG = ConfigFile('packages.cfg')

pack_items = {}

HEADERS = ['Name']


def show():
    """Show the manager window."""
    window.deiconify()
    window.lift(TK_ROOT)
    window.grab_set()
    utils.center_win(window, TK_ROOT)
    window.after(100, UI['details'].refresh)


def make_packitems():
    """Make the checkitems used in the details view."""
    pack_items.clear()
    for pack in packageLoader.packages.values():  # type: packageLoader.Package
        pack_items[pack.id] = item = CheckItem(
            pack.disp_name,
            hover_text=pack.desc or 'No description!',
            # The clean package can't be disabled!
            lock_check=(pack.id == packageLoader.CLEAN_PACKAGE),
            state=pack.enabled
        )
        item.package = pack
    return pack_items.values()


def apply_changes():
    values_changed = any(
        item.package.enabled != item.state
        for item in
        pack_items.values()
    )
    if not values_changed:
        # We don't need to do anything!
        window.withdraw()
        return

    if messagebox.askokcancel(
            title='BEE2 - Restart Required!',
            message='Changing enabled packages requires a restart.\n'
                    'Continue?',
            master=window,
            ):
        window.withdraw()
        for item in UI['details'].items:
            pack = item.package
            if pack.id != packageLoader.CLEAN_PACKAGE:
                pack.enabled = item.state
        PACK_CONFIG.save_check()
        utils.restart_app()


def cancel():
    window.withdraw()
    UI['details'].remove_all()
    UI['details'].add_items(*make_packitems())


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

    UI['details'].grid(row=0, column=0, columnspan=2, sticky='NSEW')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    ttk.Button(
        frame,
        text='Ok',
        command=apply_changes,
    ).grid(row=1, column=0, sticky='W')

    ttk.Button(
        frame,
        text='Cancel',
        command=cancel,
    ).grid(row=1, column=1, sticky='E')