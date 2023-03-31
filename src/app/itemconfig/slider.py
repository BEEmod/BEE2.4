from __future__ import annotations

import attr
import math

import tkinter as tk
from srctools import Keyvalues
from tkinter import ttk
from typing_extensions import Self

from app.itemconfig import UpdateFunc, WidgetLookup, widget_sfx


@attr.frozen
class SliderOptions:
    """Options for a slider widget."""
    min: float
    max: float
    step: float

    @classmethod
    def parse(cls, conf: Keyvalues) -> Self:
        """Parse from keyvalues options."""
        return cls(
            min=conf.float('min', 0),
            max=conf.float('max', 100),
            step=conf.float('step', 1),
        )


def decimal_points(num: float) -> int:
    """Count the number of decimal points required to display a number."""
    str_num = format(num, 'g')
    if '.' in str_num:
        whole, frac = str_num.split('.')
        return len(frac)
    else:
        return 0


@WidgetLookup('range', 'slider', wide=True)
async def widget_slider(parent: tk.Widget, var: tk.StringVar, kv: Keyvalues) -> tuple[tk.Widget, UpdateFunc]:
    """Provides a slider for setting a number in a range."""
    conf = SliderOptions.parse(kv)

    # We have to manually translate the UI position to a value.
    ui_min = 0
    ui_max = abs(math.ceil((conf.max - conf.min) / conf.step))
    ui_var = tk.DoubleVar()

    # The formatting of the text display is a little complex.
    # We want to keep the same number of decimal points for all values.
    points = max(
        decimal_points(conf.min + conf.step * offset)
        for offset in range(0, int(ui_max) + 1)
    )
    txt_format = f'.{points}f'
    # Then we want to figure out the longest value with this format to set
    # the widget width
    widget_width = max(
        len(format(conf.min + conf.step * offset, txt_format))
        for offset in range(0, int(ui_max) + 1)
    )

    def change_cmd(*args) -> None:
        new_pos = format(conf.min + conf.step * round(scale.get(), points), txt_format)
        if var.get() != new_pos:
            widget_sfx()
            var.set(new_pos)

    async def update_ui(new_value: str) -> None:
        """Apply the configured value to the UI."""
        off = (float(new_value) - conf.min) / conf.step
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
