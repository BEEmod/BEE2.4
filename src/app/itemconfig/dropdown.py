"""A widget for picking from a specific list of options."""
from typing import Tuple
from tkinter import ttk
import tkinter as tk

import srctools.logger

from packages.widgets import DropdownOptions, UpdateFunc
from app import itemconfig, localisation
from ui_tk.img import TKImages


LOGGER = srctools.logger.get_logger(__name__)


@itemconfig.ui_single_wconf(DropdownOptions)
async def dropdown(
    parent: tk.Widget, tk_img: TKImages,
    on_changed: itemconfig.SingleChangeFunc, conf: DropdownOptions,
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
    )

    @localisation.add_callback(call=True)
    def update_combo_values() -> None:
        """Update the combo box when translations change."""
        index = combobox.current()
        combobox['values'] = [str(token) for token in conf.display]
        if index >= 0:  # -1 if empty.
            combobox.current(index)  # Update display.

    combobox.bind('<<ComboboxSelected>>', changed)
    return combobox, update_ui
