"""A widget for picking from a specific list of options."""
from typing import Tuple, List, Dict
from tkinter import ttk
import tkinter as tk

import srctools.logger
from srctools import Property

from app.itemconfig import UpdateFunc, WidgetLookup


LOGGER = srctools.logger.get_logger(__name__)


@WidgetLookup('dropdown')
async def dropdown(parent: tk.Widget, var: tk.StringVar, conf: Property) -> Tuple[tk.Widget, UpdateFunc]:
    """Dropdowns allow selecting from a few options."""
    options: List[str] = []
    display: List[str] = []
    key_to_index: Dict[str, int] = {}

    for ind, prop in enumerate(conf.find_children('Options')):
        options.append(prop.real_name)
        display.append(prop.value)
        key_to_index[prop.name] = ind

    async def update_ui(new_value: str) -> None:
        """Update when new values are picked."""
        try:
            index = key_to_index[new_value.casefold()]
        except KeyError:
            LOGGER.warning('Invalid combobox value: "{}"!', new_value)
            return
        combobox.current(index)

    def on_changed(_: tk.Event) -> None:
        """Called when the combobox changes."""
        var.set(options[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        state='readonly',
        values=display,
    )
    combobox.bind('<<ComboboxSelected>>', on_changed)
    await update_ui(var.get())
    return combobox, update_ui
