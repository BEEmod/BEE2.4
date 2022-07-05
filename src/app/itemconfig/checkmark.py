from __future__ import annotations
from typing import AsyncIterator, List, Tuple
from tkinter import ttk
import tkinter as tk

from srctools import Property, conv_bool

from app.itemconfig import (
    UpdateFunc, WidgetLookup, WidgetLookupMulti,
    multi_grid, widget_sfx, nop_update,
)
from app.tooltip import add_tooltip


@WidgetLookup('boolean', 'bool', 'checkbox')
async def widget_checkmark(parent: tk.Widget, var: tk.StringVar, conf: Property) -> Tuple[tk.Widget, UpdateFunc]:
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
    ), nop_update


@WidgetLookupMulti('boolean', 'bool', 'checkbox')
async def widget_checkmark_multi(
    parent: tk.Widget,
    values: List[Tuple[str, tk.StringVar]],
    conf: Property,
) -> AsyncIterator[Tuple[str, UpdateFunc]]:
    """For checkmarks, display in a more compact form."""
    for row, column, _, tim_text, var in multi_grid(values):
        checkbox, _ = await widget_checkmark(parent, var, conf)
        checkbox.grid(row=row, column=column)
        add_tooltip(checkbox, tim_text, delay=0)
    # noinspection PyUnreachableCode
    if False:
        yield ('', nop_update)
