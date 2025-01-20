"""Allows enabling and disabling individual packages.
"""
from collections.abc import Iterable
from tkinter import ttk
import tkinter as tk

from app import background_run
from app.dialogs import Dialogs
from transtoken import TransToken
from ui_tk import TK_ROOT, tk_tools
from ui_tk.check_table import CheckDetails, Item as CheckItem
from ui_tk.dialogs import TkDialogs
from ui_tk.wid_transtoken import set_text, set_win_title
import packages
import utils


window = tk.Toplevel(TK_ROOT, name='packagesWin')
window.withdraw()

list_widget: CheckDetails[None]
pack_items: list[tuple[packages.Package, CheckItem[None]]] = []


def show() -> None:
    """Show the manager window."""
    window.deiconify()
    window.lift(TK_ROOT)
    window.grab_set()
    tk_tools.center_win(window, TK_ROOT)
    window.update()
    list_widget.refresh()


def make_packitems() -> Iterable[CheckItem[None]]:
    """Make the checkitems used in the details view."""
    pack_items.clear()
    for pack in packages.get_loaded_packages().packages.values():
        item = CheckItem(
            pack.disp_name,
            hover_text=pack.desc,
            # These packages can't be disabled!
            lock_check=pack.id in packages.MANDATORY_PACKAGES,
            state=pack.enabled,
        )
        pack_items.append((pack, item))
        yield item


async def apply_changes(dialog: Dialogs) -> None:
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

    if await dialog.ask_ok_cancel(
        title=TransToken.ui('BEE2 - Restart Required!'),
        message=TransToken.ui('Changing enabled packages requires a restart.\nContinue?'),
    ):
        window.withdraw()
        window.grab_release()
        for pack, item in pack_items:
            if pack.id not in packages.MANDATORY_PACKAGES:
                pack.enabled = item.state
        packages.PACK_CONFIG.save_check()
        utils.restart_app()


def cancel() -> None:
    """Abort enabling/disabling packages."""
    window.withdraw()
    window.grab_release()
    list_widget.remove_all()
    list_widget.add_items(make_packitems())


def make_window() -> None:
    """Initialise the window."""
    global list_widget
    dialog = TkDialogs(window)
    window.transient(TK_ROOT)
    set_win_title(window, TransToken.ui('BEE2 - Manage Packages'))

    # Don't destroy window when quit!
    window.protocol("WM_DELETE_WINDOW", cancel)

    frame = ttk.Frame(window)
    frame.grid(row=0, column=0, sticky='NSEW')
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)

    list_widget = CheckDetails(
        frame,
        headers=[TransToken.ui('Name')],
    )
    list_widget.add_items(make_packitems())

    list_widget.grid(row=0, column=0, columnspan=2, sticky='NSEW')
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)

    set_text(
        ttk.Button(frame, command=lambda: background_run(apply_changes, dialog)),
        TransToken.ui('OK'),
    ).grid(row=1, column=0, sticky='W')

    set_text(
        ttk.Button(frame, command=cancel),
        TransToken.ui('Cancel'),
    ).grid(row=1, column=1, sticky='E')
