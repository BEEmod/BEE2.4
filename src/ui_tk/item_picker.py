"""Tk implementation of the item picker."""
from tkinter import ttk
import tkinter as tk

from app.img import PETI_ITEM_BG_HEX
from app.paletteLoader import COORDS
from transtoken import TransToken
from trio_util import AsyncValue

from app.item_picker import ItemPickerBase, ItemSlot, IMG_MENU, TRANS_ITEMS_TITLE
from packages.item import SubItemRef
import utils

from . import TK_ROOT, tk_tools, wid_transtoken
from .img import TK_IMG
from .dragdrop import CanvasPositioner, DragDrop

ItemsBG = "#CDD0CE"  # Colour of the main background to match the menu image


class ItemPicker(ItemPickerBase[tk.Misc]):
    """Tk implementation of the item picker."""
    __slots__ = ['drag_man']  # Use a slot to override the superclass' property.
    drag_man: DragDrop[SubItemRef]

    def __init__(
        self,
        pal_frame: tk.Frame,
        picker_frame: ttk.Frame,
        selected_style: AsyncValue[utils.SpecialID],
    ) -> None:
        super().__init__(selected_style)
        self.drag_man = DragDrop(
            TK_ROOT,
            info_cb=self._drag_info,
            config_icon=True,
        )

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

        # Place the slots.
        for x, y in COORDS:
            slot = self.drag_man.slot_target(pal_frame, desc=f'{x}-{y}')
            self.slots_pal[slot] = (x, y)
            self.drag_man.slot_place(
                slot,
                x=x * 65 + 4,
                y=y * 65 + 32,
            )

        # Now the picker pane.
        wid_transtoken.set_text(
            ttk.Label(picker_frame, anchor="center"),
            TRANS_ITEMS_TITLE,
        ).grid(row=0, column=0, sticky="EW")
        picker_wrap = ttk.Frame(picker_frame, borderwidth=4, relief="sunken")
        picker_wrap.grid(row=1, column=0, sticky="NSEW")
        picker_frame.rowconfigure(1, weight=1)
        picker_frame.columnconfigure(0, weight=1)

        self.picker_canv = canvas = tk.Canvas(picker_wrap)
        # need to use a canvas to allow scrolling
        canvas.grid(row=0, column=0, sticky="NSEW")
        picker_wrap.rowconfigure(0, weight=1)
        picker_wrap.columnconfigure(0, weight=1)

        scroll = tk_tools.HidingScroll(
            picker_wrap,
            orient=tk.VERTICAL,
            command=canvas.yview,
        )
        scroll.grid(column=1, row=0, sticky="NS")
        canvas['yscrollcommand'] = scroll.set
        canvas.bind("<Configure>", self.evt_window_resized)

        # Make scrollbar work globally
        tk_tools.add_mousewheel(canvas, TK_ROOT)

        self.canv_pos = CanvasPositioner(
            self.drag_man.slot_canvas, canvas,
            self.drag_man.width, self.drag_man.height,
            spacing=1,
        )

    def evt_window_resized(self, event: object) -> None:
        super().evt_window_resized(event)

    async def _ui_task(self) -> None:
        pass

    def _ui_picker_create(self, index: int) -> ItemSlot:
        """Create a source slot, likely by calling dragdrop.slot_source."""
        return self.drag_man.slot_source(self.picker_canv)

    def _ui_picker_hide(self, slot: ItemSlot) -> None:
        """Hide the specified slot widget."""
        slot.contents = None
        self.drag_man.slot_hide(slot)

    def _ui_calc_columns(self) -> int:
        return self.canv_pos.calc_columns()

    def _ui_set_sel_name(self, name: TransToken) -> None:
        wid_transtoken.set_text(self.pal_name, name)

    async def _ui_reposition_items(self) -> None:
        """Position all the items."""
        self.picker_canv.delete("real_slots", "fake_slots")
        self.canv_pos.reset(yoff=1)
        self.canv_pos.place_slots(self.slots_picker.placed, "real_slots", xoff=1)
        for x, y in self.canv_pos.remainder(xoff=1):
            self.picker_canv.create_rectangle(
                x, y,
                x + 64, y + 64,
                fill=PETI_ITEM_BG_HEX,
                width=0,
                tags="fake_slots",
            )
        self.canv_pos.resize_canvas()
