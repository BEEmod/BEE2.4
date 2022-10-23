"""Allows enabling and disabling individual packages.
"""
from __future__ import annotations
from typing import Iterable
from tkinter import ttk, messagebox
import tkinter as tk
from app import TK_ROOT, tk_tools

from app.CheckDetails import CheckDetails, Item as CheckItem
from localisation import TransToken, gettext
import packages
import utils

window = tk.Toplevel(TK_ROOT)
window.withdraw()

list_widget: CheckDetails
pack_items: list[tuple[packages.Package, CheckItem]] = []


def show() -> None:
    """Show the manager window."""
    window.deiconify()
    window.lift(TK_ROOT)
    window.grab_set()
    tk_tools.center_win(window, TK_ROOT)
    window.update()
    list_widget.refresh()


def make_packitems() -> Iterable[CheckItem]:
    """Make the checkitems used in the details view."""
    pack_items.clear()
    for pack in packages.LOADED.packages.values():
        item = CheckItem(
            pack.disp_name,
            hover_text=pack.desc,
            # The clean package can't be disabled!
            lock_check=(pack.id.casefold() == packages.CLEAN_PACKAGE),
            state=pack.enabled
        )
        pack_items.append((pack, item))
        yield item


def apply_changes() -> None:
    """Enable/disable the new packages."""
    values_changed = any(
        pack.enabled != item.state
        for pack, item in
        pack_items
    )
    if not values_changed:
        # We don't need to do anything!
        window.withdraw()
        window.grab_release()
        return

    if messagebox.askokcancel(
        title=gettext('BEE2 - Restart Required!'),
        message=gettext('Changing enabled packages requires a restart.\nContinue?'),
        master=window,
    ):
        window.withdraw()
        window.grab_release()
        for pack, item in pack_items:
            if pack.id.casefold() != packages.CLEAN_PACKAGE:
                pack.enabled = item.state
        packages.PACK_CONFIG.save_check()
        utils.restart_app()


def cancel() -> None:
    """Abort enabling/disabling packages."""
    window.withdraw()
    window.grab_release()
    list_widget.remove_all()
    list_widget.add_items(*make_packitems())


def make_window() -> None:
    """Initialise the window."""
    global list_widget
    window.transient(TK_ROOT)
    window.title(gettext('BEE2 - Manage Packages'))

    # Don't destroy window when quit!
    window.protocol("WM_DELETE_WINDOW", cancel)

    frame = ttk.Frame(window)
    frame.grid(row=0, column=0, sticky='NSEW')
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)

    list_widget = CheckDetails(
        frame,
        headers=[TransToken.ui('Name')],
        items=make_packitems(),
    )

    list_widget.grid(row=0, column=0, columnspan=2, sticky='NSEW')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    ttk.Button(
        frame,
        text=gettext('OK'),
        command=apply_changes,
    ).grid(row=1, column=0, sticky='W')

    ttk.Button(
        frame,
        text=gettext('Cancel'),
        command=cancel,
    ).grid(row=1, column=1, sticky='E')
