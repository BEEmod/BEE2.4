from __future__ import annotations

import tkinter as tk
from srctools import Keyvalues
from tkinter import ttk

from app import itemconfig


TYPE = itemconfig.register_no_conf('string', 'str')


@itemconfig.ui_single_no_conf(TYPE)
@itemconfig.WidgetLookup('string', 'str')
async def widget_string(parent: tk.Widget, var: tk.StringVar, conf: Keyvalues) -> tuple[tk.Widget, itemconfig.UpdateFunc]:
    """Simple textbox for entering text."""
    return ttk.Entry(
        parent,
        textvariable=var,
    ), itemconfig.nop_update
