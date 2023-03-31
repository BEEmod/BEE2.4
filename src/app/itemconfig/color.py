"""A Widget for allowing selecting a colour."""
from __future__ import annotations
from tkinter import ttk
from tkinter.colorchooser import askcolor
import tkinter as tk

from app import img, tk_tools
from app import itemconfig
from app.tooltip import add_tooltip
from app.localisation import TransToken


TRANS_SELECT_TITLE = TransToken.ui('Choose a Color')
TYPE = itemconfig.register_no_conf('color', 'colour', 'rgb')


@itemconfig.ui_single_no_conf(TYPE)
@itemconfig.WidgetLookup('color', 'colour', 'rgb')
async def widget_color_single(
    parent: tk.Widget,
    var: tk.StringVar,
    *conf,
) -> tuple[tk.Widget, itemconfig.UpdateFunc]:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """
    # Isolates the swatch so it doesn't resize.
    frame = ttk.Frame(parent)
    swatch, update = make_color_swatch(frame, var, 24)
    swatch.grid(row=0, column=0, sticky='w')
    return frame, update


@itemconfig.ui_multi_no_conf(TYPE)
@itemconfig.WidgetLookupMulti('color', 'colour', 'rgb')
async def widget_color_multi(parent: tk.Widget, values: list[tuple[str, tk.StringVar]], *conf):
    """For color swatches, display in a more compact form."""
    for row, column, tim_val, tim_text, var in itemconfig.multi_grid(values):
        swatch, update = make_color_swatch(parent, var, 16)
        swatch.grid(row=row, column=column)
        add_tooltip(swatch, tim_text, delay=0)
        yield tim_val, update


def make_color_swatch(parent: tk.Widget, var: tk.StringVar, size: int) -> tuple[tk.Widget, itemconfig.UpdateFunc]:
    """Make a single swatch."""
    # Note: tkinter requires RGB as ints, not float!
    def open_win(e) -> None:
        """Display the color selection window."""
        itemconfig.widget_sfx()
        r, g, b = itemconfig.parse_color(var.get())
        new_color, tk_color = askcolor(
            color=f"#{r:02x}{g:02x}{b:02x}",
            parent=parent.winfo_toplevel(),
            title=str(TRANS_SELECT_TITLE),
        )
        if new_color is not None:
            # On 3.8, these are floats.
            rf, gf, bf = new_color
            var.set(f'{int(rf)} {int(gf)} {int(bf)}')

    swatch = ttk.Label(parent)
    img.apply(swatch, img.Handle.color(itemconfig.parse_color(var.get()), size, size))
    tk_tools.bind_leftclick(swatch, open_win)

    async def update_image(new_value: str) -> None:
        """Update the image when changed."""
        img.apply(swatch, img.Handle.color(itemconfig.parse_color(new_value), size, size))

    return swatch, update_image
