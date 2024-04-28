from __future__ import annotations

from typing import Mapping
from tkinter import ttk
import tkinter as tk

from srctools import conv_bool
from trio_util import AsyncValue
import trio

from app import itemconfig
from ui_tk.tooltip import add_tooltip
from packages.widgets import KIND_CHECKMARK
from ui_tk.img import TKImages
import utils


@itemconfig.ui_single_no_conf(KIND_CHECKMARK)
async def widget_checkmark(
    parent: tk.Widget, tk_img: TKImages,
    holder: AsyncValue[str],
    /, *, task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Allows ticking a box."""
    var = tk.BooleanVar(parent)

    def command() -> None:
        """Called when the checkmark is edited."""
        itemconfig.widget_sfx()
        holder.value = '1' if var.get() else '0'

    check = ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
        command=command,
    )
    task_status.started(check)
    async with utils.aclosing(holder.eventual_values()) as agen:
        async for value in agen:
            var.set(conv_bool(value))


@itemconfig.ui_multi_no_conf(KIND_CHECKMARK)
async def widget_checkmark_multi(
    parent: tk.Widget, tk_img: TKImages,
    holders: Mapping[itemconfig.TimerNum, AsyncValue[str]],
    /, *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """For checkmarks, display in a more compact form."""
    async with trio.open_nursery() as nursery:
        for row, column, tim_val, tim_text, holder in itemconfig.multi_grid(holders):
            checkbox = await nursery.start(widget_checkmark, parent, tk_img, holder)
            checkbox.grid(row=row, column=column)
            add_tooltip(checkbox, tim_text, delay=0)
        task_status.started()
