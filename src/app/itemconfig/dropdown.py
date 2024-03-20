"""A widget for picking from a specific list of options."""
from tkinter import ttk
import tkinter as tk

from trio_util import AsyncValue
import srctools.logger
import trio

from packages.widgets import DropdownOptions
from app import itemconfig
from transtoken import CURRENT_LANG
from ui_tk.img import TKImages


LOGGER = srctools.logger.get_logger(__name__)


@itemconfig.ui_single_wconf(DropdownOptions)
async def dropdown(
    parent: tk.Widget, tk_img: TKImages,
    holder: AsyncValue[str],
    conf: DropdownOptions,
    /, *, task_status: trio.TaskStatus[tk.Widget] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Dropdowns allow selecting from a few options."""

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        state='readonly',
        values=[str(token) for token in conf.display],
    )

    async def update_ui() -> None:
        """Update when new values are picked."""
        async for value in holder.eventual_values():
            try:
                index = conf.key_to_index[value.casefold()]
            except KeyError:
                LOGGER.warning('Invalid combobox value: "{}"!', value)
                return
            combobox.current(index)

    async def update_combo_values() -> None:
        """Update the combo box when translations change."""
        while True:
            await CURRENT_LANG.wait_transition()
            index = combobox.current()
            combobox['values'] = [str(token) for token in conf.display]
            if index >= 0:  # -1 if empty.
                combobox.current(index)  # Update display.

    def changed(_: tk.Event) -> None:
        """Called when the combobox changes."""
        holder.value = conf.options[combobox.current()]

    async with trio.open_nursery() as nursery:
        nursery.start_soon(update_ui)
        nursery.start_soon(update_combo_values)

        combobox.bind('<<ComboboxSelected>>', changed)
        task_status.started(combobox)
