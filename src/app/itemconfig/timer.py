from __future__ import annotations

from functools import lru_cache
from typing import AsyncIterator, List, Tuple

import tkinter as tk
from srctools import Keyvalues, conv_int, logger

from app.itemconfig import UpdateFunc, WidgetLookup, WidgetLookupMulti, multi_grid
from app.tooltip import add_tooltip


LOGGER = logger.get_logger('itemconfig.timer')


@lru_cache(maxsize=20)
def timer_values(min_value: int, max_value: int) -> List[str]:
    """Return 0:38-like strings up to the max value."""
    return [
        '{}:{:02}'.format(i//60, i % 60)
        for i in range(min_value, max_value + 1)
    ]


@WidgetLookupMulti('Timer', 'MinuteSeconds')
async def widget_minute_seconds_multi(
        parent: tk.Widget,
        values: List[Tuple[str, tk.StringVar]], conf: Keyvalues
) -> AsyncIterator[Tuple[str, UpdateFunc]]:
    """For timers, display in a more compact form."""
    for row, column, tim_val, tim_text, var in multi_grid(values, columns=5):
        timer, update = await widget_minute_seconds(parent, var, conf)
        timer.grid(row=row, column=column)
        add_tooltip(timer, tim_text, delay=0)
        yield tim_val, update


@WidgetLookup('Timer', 'MinuteSeconds')
async def widget_minute_seconds(parent: tk.Widget, var: tk.StringVar, conf: Keyvalues) -> Tuple[tk.Widget, UpdateFunc]:
    """A widget for specifying times - minutes and seconds.

    The value is saved as seconds.
    Max specifies the largest amount.
    """
    max_value = conf.int('max', 60)
    min_value = conf.int('min', 0)
    if min_value > max_value:
        raise ValueError('Bad min and max values!')

    values = timer_values(min_value, max_value)

    # Stores the 'pretty' value in the actual textbox.
    disp_var = tk.StringVar()

    existing_value = var.get()

    async def update_disp(new_val: str) -> None:
        """Whenever the string changes, update the displayed text."""
        seconds = conv_int(new_val, -1)
        if min_value <= seconds <= max_value:
            disp_var.set('{}:{:02}'.format(seconds // 60, seconds % 60))
        else:
            LOGGER.warning('Bad timer value "{}" for "{}"!', new_val, conf['id'])
            # Recurse, with a known safe value.
            var.set(values[0])

    def set_var() -> None:
        """Set the variable to the current value."""
        try:
            minutes, seconds = disp_var.get().split(':')
            var.set(str(int(minutes) * 60 + int(seconds)))
        except (ValueError, TypeError):
            pass

    def validate(reason: str, operation_type: str, cur_value: str, new_char: str, new_value: str):
        """Validate the values for the text.

        This is called when the textbox is modified, to allow cancelling bad
        inputs.

        Reason is the reason this was fired: 'key', 'focusin', 'focusout', 'forced'.
        operation_type is '1' for insert, '0' for delete', '-1' for programmatic changes.
        cur_val is the value before the change occurs.
        new_char is the added/removed text.
        new_value is the value after the change, if accepted.
        """
        if operation_type == '0' or reason == 'forced':
            # Deleting or done by the program, allow that always.
            return True

        if operation_type == '1':  # Inserted text.
            # Disallow non number and colons
            if new_char not in '0123456789:':
                return False
            # Only one colon.
            if ':' in cur_value and new_char == ':':
                return False

            # Don't allow more values if it has more than 2 numbers after
            # the colon - if there is one, and it's not in the last 3 characters.
            if ':' in new_value and ':' not in new_value[-3:]:
                return False

        if reason == 'focusout':
            # When leaving focus, apply range limits and set the var.
            try:
                str_min, str_sec = new_value.split(':')
                seconds = int(str_min) * 60 + int(str_sec)
            except (ValueError, TypeError):
                seconds = min_value
            else:
                if seconds < min_value:
                    seconds = min_value
                if seconds > max_value:
                    seconds = max_value
            var.set(str(seconds))  # This then re-writes the textbox.
        return True

    validate_cmd = parent.register(validate)

    # Unfortunately we can't use ttk.Spinbox() here, it doesn't support
    # the validation options.
    # TODO: Update when possible.
    spinbox = tk.Spinbox(
        parent,
        exportselection=False,
        textvariable=disp_var,
        command=set_var,
        wrap=True,
        values=values,
        width=5,

        validate='all',
        # These define which of the possible values will be passed along.
        # http://tcl.tk/man/tcl8.6/TkCmd/spinbox.htm#M26
        validatecommand=(validate_cmd, '%V', '%d', '%s', '%S', '%P'),
    )
    # We need to set this after, it gets reset to the first one.
    var.set(existing_value)
    await update_disp(existing_value)
    return spinbox, update_disp
