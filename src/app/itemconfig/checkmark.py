from __future__ import annotations
from typing import List, Tuple
from tkinter import ttk
import tkinter as tk

from srctools import Property, conv_bool

from app.itemconfig import WidgetLookup, WidgetLookupMulti, multi_grid, widget_sfx
from app.tooltip import add_tooltip


@WidgetLookup('boolean', 'bool', 'checkbox')
def widget_checkmark(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Widget:
    """Allows ticking a box."""
    # Ensure it's a bool value.
    if conv_bool(var.get()):
        var.set('1')
    else:
        var.set('0')

    return ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
        command=widget_sfx,
    )


@WidgetLookupMulti('boolean', 'bool', 'checkbox')
def widget_checkmark_multi(
    parent: tk.Frame,
    values: List[Tuple[str, tk.StringVar]],
    conf: Property,
) -> tk.Widget:
    """For checkmarks, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values):
        checkbox = widget_checkmark(parent, var, conf)
        checkbox.grid(row=row, column=column)
        add_tooltip(checkbox, tim_text, delay=0)
    return parent
