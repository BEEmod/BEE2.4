"""A Widget for allowing selecting a colour."""
from __future__ import annotations
from typing import AsyncIterator, Iterable

from tkinter import ttk
from tkinter.colorchooser import askcolor
import tkinter as tk

from config.widgets import TimerNum
from packages.widgets import UpdateFunc, KIND_COLOR, parse_color
from app import img, tk_tools
from app import itemconfig
from app.tooltip import add_tooltip
from app.localisation import TransToken
from ui_tk.img import TKImages


TRANS_SELECT_TITLE = TransToken.ui('Choose a Color')


@itemconfig.ui_single_no_conf(KIND_COLOR)
async def widget_color_single(
    parent: tk.Widget, tk_img: TKImages,
    on_changed: itemconfig.SingleChangeFunc,
) -> tuple[tk.Widget, UpdateFunc]:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """
    # Isolates the swatch so it doesn't resize.
    frame = ttk.Frame(parent)
    swatch, update = make_color_swatch(frame, tk_img, on_changed, 24)
    swatch.grid(row=0, column=0, sticky='w')
    return frame, update


@itemconfig.ui_multi_no_conf(KIND_COLOR)
async def widget_color_multi(
    parent: tk.Widget, tk_img: TKImages,
    timers: Iterable[itemconfig.TimerNum],
    get_on_changed: itemconfig.MultiChangeFunc,
) -> AsyncIterator[tuple[TimerNum, UpdateFunc]]:
    """For color swatches, display in a more compact form."""
    for row, column, tim_val, tim_text in itemconfig.multi_grid(timers):
        swatch, update = make_color_swatch(parent, tk_img,get_on_changed(tim_val), 16)
        swatch.grid(row=row, column=column)
        add_tooltip(swatch, tim_text, delay=0)
        yield tim_val, update


def make_color_swatch(
    parent: tk.Widget, tk_img: TKImages,
    on_changed: itemconfig.SingleChangeFunc, size: int,
) -> tuple[tk.Widget, UpdateFunc]:
    """Make a single swatch."""
    r = g = b = 128

    swatch = ttk.Label(parent)

    # Note: tkinter requires RGB as ints, not float!
    def open_win(e: tk.Event) -> None:
        """Display the color selection window."""
        nonlocal r, g, b
        itemconfig.widget_sfx()
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
            on_changed(f'{r} {g} {b}')

    tk_tools.bind_leftclick(swatch, open_win)

    async def update_image(value: str) -> None:
        """Update the image when changed."""
        nonlocal r, g, b
        r, g, b = parsed = parse_color(value)
        tk_img.apply(swatch, img.Handle.color(parsed, size, size))

    return swatch, update_image
