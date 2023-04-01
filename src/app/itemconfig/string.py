from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app import itemconfig


TYPE = itemconfig.register_no_conf('string', 'str')


@itemconfig.ui_single_no_conf(TYPE)
async def widget_string(
    parent: tk.Widget, on_changed: itemconfig.SingleChangeFunc, _: None,
) -> tuple[tk.Widget, itemconfig.UpdateFunc]:
    """Simple textbox for entering text."""
    var = tk.StringVar()
    entry = ttk.Entry(
        parent,
        textvariable=var,
    )
    # When changed, fire the callback.
    var.trace_add('write', lambda *args: on_changed(var.get()))

    async def update_ui(value: str) -> None:
        """Called to update the UI."""
        var.set(value)

    return entry, update_ui
