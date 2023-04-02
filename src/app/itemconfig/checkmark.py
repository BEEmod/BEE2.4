from __future__ import annotations

from typing import AsyncIterator, Iterable, Tuple
from tkinter import ttk
import tkinter as tk

from srctools import conv_bool

import packages.widgets
from app import itemconfig
from app.tooltip import add_tooltip
from packages.widgets import KIND_CHECKMARK


@itemconfig.ui_single_no_conf(KIND_CHECKMARK)
async def widget_checkmark(
    parent: tk.Widget, on_changed: itemconfig.SingleChangeFunc,
) -> Tuple[tk.Widget, packages.widgets.UpdateFunc]:
    """Allows ticking a box."""
    var = tk.BooleanVar(parent)

    def command() -> None:
        """Called when the checkmark is edited."""
        itemconfig.widget_sfx()
        on_changed('1' if var.get() else '0')

    async def update(value: str) -> None:
        """Update the checkmark from stored values."""
        var.set(conv_bool(value))

    check = ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
        command=command,
    )

    return check, update


@itemconfig.ui_multi_no_conf(KIND_CHECKMARK)
async def widget_checkmark_multi(
    parent: tk.Widget,
    values: Iterable[itemconfig.TimerNum],
    get_on_changed: itemconfig.MultiChangeFunc,
) -> AsyncIterator[Tuple[itemconfig.TimerNum, packages.widgets.UpdateFunc]]:
    """For checkmarks, display in a more compact form."""
    for row, column, tim_val, tim_text in itemconfig.multi_grid(values):
        checkbox, update = await widget_checkmark(parent, get_on_changed(tim_val))
        checkbox.grid(row=row, column=column)
        add_tooltip(checkbox, tim_text, delay=0)
        yield tim_val, update
