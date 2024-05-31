"""A widget for allowing selecting a colour."""
from contextlib import aclosing
from collections.abc import Mapping

from tkinter import ttk
from tkinter.colorchooser import askcolor
import tkinter as tk

from trio_util import AsyncValue
import trio

from packages.widgets import KIND_COLOR, parse_color
from app import img
from ui_tk import tk_tools
from app import itemconfig
from ui_tk.tooltip import add_tooltip
from app.localisation import TransToken
from ui_tk.img import TKImages


TRANS_SELECT_TITLE = TransToken.ui('Choose a Color')


@itemconfig.ui_single_no_conf(KIND_COLOR)
async def widget_color_single(
    parent: tk.Widget, tk_img: TKImages,
    holder: AsyncValue[str],
    /, *, task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """
    # The frame isolates the swatch so that it doesn't resize.
    frame = ttk.Frame(parent)
    async with trio.open_nursery() as nursery:
        swatch = await nursery.start(make_color_swatch, frame, tk_img, holder, 24)
        swatch.grid(row=0, column=0, sticky='w')
        task_status.started(swatch)


@itemconfig.ui_multi_no_conf(KIND_COLOR)
async def widget_color_multi(
    parent: tk.Widget, tk_img: TKImages,
    holders: Mapping[itemconfig.TimerNum, AsyncValue[str]],
    /, *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """For color swatches, display in a more compact form."""
    async with trio.open_nursery() as nursery:
        for row, column, tim_val, tim_text, holder in itemconfig.multi_grid(holders):
            swatch = await nursery.start(make_color_swatch, parent, tk_img, holder, 16)
            swatch.grid(row=row, column=column)
            add_tooltip(swatch, tim_text, delay=0)
        task_status.started()


async def make_color_swatch(
    parent: tk.Widget, tk_img: TKImages,
    holder: AsyncValue[str],
    size: int,
    /, *, task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Make a single swatch."""
    swatch = ttk.Label(parent)

    # Note: tkinter requires RGB as ints, not float!
    def open_win(e: tk.Event) -> None:
        """Display the color selection window."""
        itemconfig.widget_sfx()
        r, g, b = parse_color(holder.value)
        new_color, tk_color = askcolor(
            color=f"#{r:02x}{g:02x}{b:02x}",
            parent=parent.winfo_toplevel(),
            title=str(TRANS_SELECT_TITLE),
        )
        if new_color is not None:
            # On 3.8, these are floats.
            rf, gf, bf = new_color
            r, g, b = parsed = int(rf), int(gf), int(bf)
            tk_img.apply(swatch, img.Handle.color(parsed, size, size))
            holder.value = f'{r} {g} {b}'

    tk_tools.bind_leftclick(swatch, open_win)

    task_status.started(swatch)
    async with aclosing(holder.eventual_values()) as agen:
        async for value in agen:
            tk_img.apply(swatch, img.Handle.color(parse_color(value), size, size))
