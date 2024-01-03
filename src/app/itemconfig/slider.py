from __future__ import annotations

import math

import tkinter as tk
from tkinter import ttk

from packages.widgets import SliderOptions, UpdateFunc
from app import itemconfig
from transtoken import TransToken
from ui_tk.img import TKImages
from ui_tk.wid_transtoken import set_text


# If enabled, optionally override text to this when set to 0. This is for options where zero turns
# it off.
TRANS_OFF = TransToken.ui('Off')


def decimal_points(num: float) -> int:
    """Count the number of decimal points required to display a number."""
    str_num = format(num, 'g')
    if '.' in str_num:
        whole, frac = str_num.split('.')
        return len(frac)
    else:
        return 0


@itemconfig.ui_single_wconf(SliderOptions)
async def widget_slider(
    parent: tk.Widget, tk_img: TKImages,
    on_changed: itemconfig.SingleChangeFunc, conf: SliderOptions,
) -> tuple[tk.Widget, UpdateFunc]:
    """Provides a slider for setting a number in a range."""

    # We have to manually translate the UI position to a value.
    ui_min = 0
    ui_max = abs(math.ceil((conf.max - conf.min) / conf.step))
    ui_var = tk.DoubleVar()

    # The formatting of the text display is a little complex.
    # We want to keep the same number of decimal points for all values.
    points = max(
        decimal_points(conf.min + conf.step * offset)
        for offset in range(ui_min, int(ui_max) + 1)
    )
    txt_format = f'.{points}f'
    # Then we want to figure out the longest value with this format to set
    # the widget width
    widget_width = max(
        len(format(conf.min + conf.step * offset, txt_format))
        for offset in range(ui_min, int(ui_max) + 1)
    )

    last_value = ''

    def change_cmd(value: str) -> None:
        """Called when the slider is changed."""
        nonlocal last_value
        value_num = float(value)
        new_pos = format(conf.min + conf.step * round(value_num), txt_format)
        # Only trigger sounds when moving each step.
        if last_value != new_pos:
            itemconfig.widget_sfx()
            if conf.zero_off and math.isclose(value_num, 0.0):
                set_text(disp, TRANS_OFF)
            else:
                set_text(disp, TransToken.untranslated(new_pos))
            last_value = new_pos
            on_changed(new_pos)

    async def update_ui(new_value: str) -> None:
        """Apply the configured value to the UI."""
        value_num = float(new_value)
        if conf.zero_off and math.isclose(value_num, 0.0):
            set_text(disp, TRANS_OFF)
        else:
            set_text(disp, TransToken.untranslated(format(value_num, txt_format)))

        off = (value_num - conf.min) / conf.step
        ui_var.set(round(off, points))

    frame = ttk.Frame(parent)
    frame.columnconfigure(1, weight=1)

    disp = ttk.Label(
        frame,
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
