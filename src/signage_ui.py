"""Configures which signs are defined for the Signage item."""
from typing import Optional

import dragdrop
from packageLoader import Signage
import tkinter as tk
from tkinter import ttk
from tk_tools import TK_ROOT

window = tk.Toplevel(TK_ROOT)
window.withdraw()


def init_widgets(master: ttk.Frame) -> Optional[tk.Misc]:
    """Construct the widgets, returning the configuration button.

    If no signages are defined, this returns None.
    """
    if not any(Signage.all()):
        return None

    window.protocol("WM_DELETE_WINDOW", window.withdraw)
    window.resizable(True, True)


    return ttk.Button(
        master,
        text=_('Configure Signage'),
        command=window.deiconify
    )
