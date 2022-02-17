"""A Widget for allowing selecting a colour."""
from __future__ import annotations
from tkinter import ttk
from tkinter.colorchooser import askcolor
import tkinter as tk

from srctools import Property

from app import img, tk_tools
from app.itemconfig import (
    UpdateFunc, WidgetLookup, WidgetLookupMulti,
    multi_grid, parse_color, widget_sfx,
)
from app.tooltip import add_tooltip
from localisation import gettext


@WidgetLookup('color', 'colour', 'rgb')
async def widget_color_single(
    parent: ttk.Frame,
    var: tk.StringVar,
    conf: Property,
) -> tuple[tk.Widget, UpdateFunc]:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """
    # Isolates the swatch so it doesn't resize.
    frame = ttk.Frame(parent)
    swatch, update = make_color_swatch(frame, var, 24)
    swatch.grid(row=0, column=0, sticky='w')
    return frame, update


@WidgetLookupMulti('color', 'colour', 'rgb')
async def widget_color_multi(parent: ttk.Frame, values: list[tuple[str, tk.StringVar]], conf: Property):
    """For color swatches, display in a more compact form."""
    for row, column, tim_val, tim_text, var in multi_grid(values):
        swatch, update = make_color_swatch(parent, var, 16)
        swatch.grid(row=row, column=column)
        add_tooltip(swatch, tim_text, delay=0)
        yield tim_val, update


def make_color_swatch(parent: ttk.Frame, var: tk.StringVar, size: int) -> tuple[tk.Widget, UpdateFunc]:
    """Make a single swatch."""
    # Note: tkinter requires RGB as ints, not float!
    def open_win(e) -> None:
        """Display the color selection window."""
        widget_sfx()
        r, g, b = parse_color(var.get())
        new_color, tk_color = askcolor(
            color=(r, g, b),
            parent=parent.winfo_toplevel(),
            title=gettext('Choose a Color'),
        )
        if new_color is not None:
            r, g, b = map(int, new_color)  # Returned as floats, which is wrong.
            var.set(f'{int(r)} {int(g)} {int(b)}')

    swatch = ttk.Label(parent)
    img.apply(swatch, img.Handle.color(parse_color(var.get()), size, size))
    tk_tools.bind_leftclick(swatch, open_win)

    async def update_image(new_value: str) -> None:
        """Update the image when changed."""
        img.apply(swatch, img.Handle.color(parse_color(new_value), size, size))

    return swatch, update_image
