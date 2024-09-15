"""Tk implementation of the item picker."""
from tkinter import ttk
import tkinter as tk

from app import img
from trio_util import AsyncValue

from app.item_picker import IMG_MENU, ItemPickerBase, ItemSlot
from packages.item import SubItemRef
import utils

from . import TK_ROOT
from .img import TK_IMG
from .dragdrop import DragDrop

ItemsBG = "#CDD0CE"  # Colour of the main background to match the menu image


class ItemPicker(ItemPickerBase[tk.Misc]):
    """Tk implementation of the item picker."""
    __slots__ = ['drag_man']  # Use a slot to override the superclass' property.
    drag_man: DragDrop[SubItemRef]

    def __init__(
        self,
        pal_frame: tk.Frame,
        picker_frame: tk.Frame,
        selected_style: AsyncValue[utils.SpecialID],
    ) -> None:
        super().__init__(selected_style)
        self.drag_man = DragDrop(
            TK_ROOT,
            info_cb=self.drag_info,
            config_icon=True,
        )
        self.picker_frame = picker_frame

        # Create the preview pane.
        pre_bg_img = tk.Label(pal_frame, bg=ItemsBG)
        pre_bg_img.grid(row=0, column=0)
        TK_IMG.apply(pre_bg_img, IMG_MENU)

        self.pal_name = ttk.Label(
            pal_frame,
            text="",
            style='BG.TLabel',
        )
        self.pal_name.place(x=10, y=554)

    async def _ui_task(self) -> None:
        pass

    def ui_picker_create(self, index: int) -> ItemSlot:
        """Create a source slot, likely by calling dragdrop.slot_source."""
        return self.drag_man.slot_source(self.picker_frame)

    def ui_picker_hide(self, slot: ItemSlot) -> None:
        """Hide the specified slot widget."""
        raise NotImplementedError

    def _ui_calc_columns(self) -> int:
        pass

    async def _ui_reposition_items(self) -> None:
        pass
