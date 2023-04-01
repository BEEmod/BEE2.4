"""A widget for picking from a specific list of options."""
import attrs
from typing import Tuple, List, Dict
from tkinter import ttk
import tkinter as tk

import srctools.logger
from srctools import Keyvalues
from typing_extensions import Self

from app import itemconfig


LOGGER = srctools.logger.get_logger(__name__)


@itemconfig.register('dropdown')
@attrs.define
class DropdownOptions:
    """Options defined for a widget."""
    options: List[str]
    display: List[str]
    key_to_index: Dict[str, int]

    @classmethod
    def parse(cls, conf: Keyvalues) -> Self:
        """Parse configuration."""
        result = cls([], [], {})
        for ind, prop in enumerate(conf.find_children('Options')):
            result.options.append(prop.real_name)
            result.display.append(prop.value)
            result.key_to_index[prop.name] = ind
        return result


@itemconfig.ui_single_wconf(DropdownOptions)
async def dropdown(parent: tk.Widget, var: tk.StringVar, conf: DropdownOptions) -> Tuple[tk.Widget, itemconfig.UpdateFunc]:
    """Dropdowns allow selecting from a few options."""
    async def update_ui(new_value: str) -> None:
        """Update when new values are picked."""
        try:
            index = conf.key_to_index[new_value.casefold()]
        except KeyError:
            LOGGER.warning('Invalid combobox value: "{}"!', new_value)
            return
        combobox.current(index)

    def on_changed(_: tk.Event) -> None:
        """Called when the combobox changes."""
        var.set(conf.options[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        state='readonly',
        values=conf.display,
    )
    combobox.bind('<<ComboboxSelected>>', on_changed)
    await update_ui(var.get())
    return combobox, update_ui
