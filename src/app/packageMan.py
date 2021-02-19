"""Allows enabling and disabling individual packages.
"""
from typing import Iterable
from tkinter import ttk
from tkinter import messagebox
import tkinter as tk
from app import TK_ROOT

from app.CheckDetails import CheckDetails, Item as CheckItem
from BEE2_config import ConfigFile
import packages
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
    window.update()
    UI['details'].refresh()


def make_packitems() -> Iterable[CheckItem]:
    """Make the checkitems used in the details view."""
    pack_items.clear()
    for pack in packages.packages.values():  # type: packages.Package
        pack_items[pack.id] = item = CheckItem(
            pack.disp_name,
            hover_text=pack.desc or 'No description!',
            # The clean package can't be disabled!
            lock_check=(pack.id == packages.CLEAN_PACKAGE),
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
        window.grab_release()
        return

    if messagebox.askokcancel(
            title=_('BEE2 - Restart Required!'),
            message=_('Changing enabled packages requires a restart.\nContinue?'),
            master=window,
            ):
        window.withdraw()
        window.grab_release()
        for item in UI['details'].items:
            pack = item.package
            if pack.id != packages.CLEAN_PACKAGE:
                pack.enabled = item.state
        PACK_CONFIG.save_check()
        utils.restart_app()


def cancel():
    window.withdraw()
    window.grab_release()
    UI['details'].remove_all()
    UI['details'].add_items(*make_packitems())


def make_window():
    """Initialise the window."""
    window.transient(TK_ROOT)
    window.title(_('BEE2 - Manage Packages'))

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
        text=_('OK'),
        command=apply_changes,
    ).grid(row=1, column=0, sticky='W')

    ttk.Button(
        frame,
        text=_('Cancel'),
        command=cancel,
    ).grid(row=1, column=1, sticky='E')
