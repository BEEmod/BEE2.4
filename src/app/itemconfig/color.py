"""A Widget for allowing selecting a colour."""
from __future__ import annotations
from typing import List, Tuple
from tkinter import ttk
from tkinter.colorchooser import askcolor
import tkinter as tk

from srctools import Property

from app import img, tk_tools
from app.itemconfig import WidgetLookup, WidgetLookupMulti, multi_grid, parse_color, widget_sfx
from app.tooltip import add_tooltip
from localisation import gettext


@WidgetLookup('color', 'colour', 'rgb')
def widget_color_single(
    parent: tk.Frame,
    var: tk.StringVar,
    conf: Property,
) -> tk.Widget:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """
    # Isolates the swatch so it doesn't resize.
    frame = ttk.Frame(parent)
    swatch = make_color_swatch(frame, var, 24)
    swatch.grid(row=0, column=0, sticky='w')
    return frame


@WidgetLookupMulti('color', 'colour', 'rgb')
def widget_color_multi(parent: tk.Frame, values: List[Tuple[str, tk.StringVar]], conf: Property):
    """For color swatches, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values):
        swatch = make_color_swatch(parent, var, 16)
        swatch.grid(row=row, column=column)
        add_tooltip(swatch, tim_text, delay=0)


def make_color_swatch(parent: tk.Frame, var: tk.StringVar, size: int) -> ttk.Label:
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
            var.set('{} {} {}'.format(int(r), int(g), int(b)))

    swatch = ttk.Label(parent)

    def update_image(var_name: str, var_index: str, operation: str):
        img.apply(swatch, img.Handle.color(parse_color(var.get()), size, size))

    update_image('', '', '')

    # Register a function to be called whenever this variable is changed.
    var.trace_add('write', update_image)

    tk_tools.bind_leftclick(swatch, open_win)

    return swatch
