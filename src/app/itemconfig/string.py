from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from contextlib import aclosing

from trio_util import AsyncValue
import trio

from packages.widgets import KIND_STRING
from app import itemconfig
from ui_tk.img import TKImages


@itemconfig.TK_IMPL.register_ui_single_no_conf(KIND_STRING)
async def widget_string(
    parent: tk.Widget, tk_img: TKImages,
    holder: AsyncValue[str],
    /, *, task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Simple textbox for entering text."""
    var = tk.StringVar(parent, holder.value)
    entry = ttk.Entry(parent, textvariable=var)

    def on_changed(*args: object) -> None:
        """When changed, propagate."""
        holder.value = var.get()

    var.trace_add('write', on_changed)

    task_status.started(entry)

    async with aclosing(holder.eventual_values(held_for=0.125)) as agen:
        async for value in agen:
            var.set(value)
