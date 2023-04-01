from __future__ import annotations
from typing import AsyncIterator, List, Tuple
from tkinter import ttk
import tkinter as tk

from srctools import conv_bool

from app import itemconfig
from app.tooltip import add_tooltip


TYPE = itemconfig.register_no_conf('boolean', 'bool', 'checkbox')


@itemconfig.ui_single_no_conf(TYPE)
async def widget_checkmark(parent: tk.Widget, var: tk.StringVar, _: None) -> Tuple[tk.Widget, itemconfig.UpdateFunc]:
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
        command=itemconfig.widget_sfx,
    ), itemconfig.nop_update


@itemconfig.ui_multi_no_conf(TYPE)
async def widget_checkmark_multi(
    parent: tk.Widget,
    values: List[Tuple[str, tk.StringVar]],
    _: None,
) -> AsyncIterator[Tuple[str, itemconfig.UpdateFunc]]:
    """For checkmarks, display in a more compact form."""
    for row, column, tim_val, tim_text, var in itemconfig.multi_grid(values):
        checkbox, update = await widget_checkmark(parent, var, None)
        checkbox.grid(row=row, column=column)
        add_tooltip(checkbox, tim_text, delay=0)
        yield tim_val, update
