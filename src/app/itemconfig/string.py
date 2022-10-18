from __future__ import annotations

import tkinter as tk
from srctools import Property
from tkinter import ttk

from app.itemconfig import UpdateFunc, WidgetLookup, nop_update


@WidgetLookup('string', 'str')
async def widget_string(parent: tk.Widget, var: tk.StringVar, conf: Property) -> tuple[tk.Widget, UpdateFunc]:
    """Simple textbox for entering text."""
    return ttk.Entry(
        parent,
        textvariable=var,
    ), nop_update
