"""A widget for picking from a specific list of options."""
import attrs
from typing import Tuple
from tkinter import ttk
import tkinter as tk

import srctools.logger

from packages.widgets import DropdownOptions, UpdateFunc
from app import itemconfig


LOGGER = srctools.logger.get_logger(__name__)


@itemconfig.ui_single_wconf(DropdownOptions)
async def dropdown(
    parent: tk.Widget, on_changed: itemconfig.SingleChangeFunc, conf: DropdownOptions,
) -> Tuple[tk.Widget, UpdateFunc]:
    """Dropdowns allow selecting from a few options."""
    async def update_ui(new_value: str) -> None:
        """Update when new values are picked."""
        try:
            index = conf.key_to_index[new_value.casefold()]
        except KeyError:
            LOGGER.warning('Invalid combobox value: "{}"!', new_value)
            return
        combobox.current(index)

    def changed(_: tk.Event) -> None:
        """Called when the combobox changes."""
        on_changed(conf.options[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        state='readonly',
        values=conf.display,
    )
    combobox.bind('<<ComboboxSelected>>', changed)
    return combobox, update_ui
