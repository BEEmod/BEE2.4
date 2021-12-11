from __future__ import annotations

import tkinter as tk
from srctools import Property
from tkinter import ttk

from app.itemconfig import WidgetLookup


@WidgetLookup('string', 'str')
def widget_string(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Widget:
    """Simple textbox for entering text."""
    return ttk.Entry(
        parent,
        textvariable=var,
    )
