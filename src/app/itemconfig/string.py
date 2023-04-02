from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from packages.widgets import KIND_STRING, UpdateFunc
from app import itemconfig


@itemconfig.ui_single_no_conf(KIND_STRING)
async def widget_string(
    parent: tk.Widget, on_changed: itemconfig.SingleChangeFunc,
) -> tuple[tk.Widget, UpdateFunc]:
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
