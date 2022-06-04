from __future__ import annotations

import math

import tkinter as tk
from srctools import Property
from tkinter import ttk

from app.itemconfig import UpdateFunc, WidgetLookup, widget_sfx


def decimal_points(num: float) -> int:
    """Count the number of decimal points required to display a number."""
    str_num = format(num, 'g')
    if '.' in str_num:
        whole, frac = str_num.split('.')
        return len(frac)
    else:
        return 0


@WidgetLookup('range', 'slider')
async def widget_slider(parent: ttk.Frame, var: tk.StringVar, conf: Property) -> tuple[tk.Widget, UpdateFunc]:
    """Provides a slider for setting a number in a range."""
    limit_min = conf.float('min', 0)
    limit_max = conf.float('max', 100)
    step = conf.float('step', 1)

    # We have to manually translate the UI position to a value.
    ui_min = 0
    ui_max = abs(math.ceil((limit_max - limit_min) / step))
    ui_var = tk.DoubleVar()

    # The formatting of the text display is a little complex.
    # We want to keep the same number of decimal points for all values.
    points = max(
        decimal_points(limit_min + step * offset)
        for offset in range(0, int(ui_max) + 1)
    )
    txt_format = f'.{points}f'
    # Then we want to figure out the longest value with this format to set
    # the widget width
    widget_width = max(
        len(format(limit_min + step * offset, txt_format))
        for offset in range(0, int(ui_max) + 1)
    )

    def change_cmd(*args) -> None:
        new_pos = format(limit_min + step * round(scale.get(), points), txt_format)
        if var.get() != new_pos:
            widget_sfx()
            var.set(new_pos)

    async def update_ui(new_value: str) -> None:
        """Apply the configured value to the UI."""
        off = (float(new_value) - limit_min) / step
        ui_var.set(round(off, points))

    await update_ui(var.get())

    frame = ttk.Frame(parent)
    frame.columnconfigure(1, weight=1)

    disp = ttk.Label(
        frame,
        textvariable=var,
        width=widget_width,
        justify='right'
    )
    scale = ttk.Scale(
        frame,
        orient='horizontal',
        from_=ui_min,
        to=ui_max,
        variable=ui_var,
        command=change_cmd,
    )

    disp.grid(row=0, column=0)
    scale.grid(row=0, column=1, sticky='ew')

    return frame, update_ui
