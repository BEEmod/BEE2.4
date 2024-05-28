"""A widget for picking from a specific list of options."""
import tkinter as tk

from trio_util import AsyncValue
import srctools.logger
import trio

from packages.widgets import DropdownOptions
from app import itemconfig
from ui_tk import tk_tools
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

    combobox = tk_tools.ComboBoxMap(
        parent,
        name='',  # Auto-generate.
        current=holder,
        values=conf.options,
    )

    async with trio.open_nursery() as nursery:
        nursery.start_soon(combobox.task)
        task_status.started(combobox.widget)
