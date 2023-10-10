"""Tk implementation of the corridor selector."""
import tkinter as tk
from typing import Final, Optional

from tkinter import ttk

import utils
from app import img, tk_tools
from app.corridor_selector import HEIGHT, Icon, Selector, WIDTH
from ui_tk.dragdrop import CanvasPositioner
from ui_tk.img import TKImages
import packages


ICON_CHECK_PADDING: Final = 2 if utils.WIN else 0


class IconUI(Icon):
    """An icon for a corridor."""
    def __init__(self, parent: tk.Canvas) -> None:
        """Create the widgets."""
        self.label = ttk.Label(parent, anchor='center')
        self.var = tk.BooleanVar(parent)
        self.check = ttk.Checkbutton(self.label, variable=self.var)
        self.check.place(
            x=-ICON_CHECK_PADDING,
            y=WIDTH - ICON_CHECK_PADDING,
            anchor='sw',
        )

    @property
    def selected(self) -> bool:
        """If the icon is currently selected."""
        return self.var.get()

    @selected.setter
    def selected(self, value: bool) -> None:
        self.var.set(value)

    def set_highlight(self, enabled: bool) -> None:
        """Change the highlight state."""
        self.label['background'] = tk_tools.LABEL_HIGHLIGHT_BG if enabled else ''


def place_icon(canv: tk.Canvas, icon: IconUI, x: int, y: int, tag: str) -> None:
    """Position an icon on the canvas."""
    canv.create_window(
        x, y,
        width=WIDTH,
        height=HEIGHT,
        anchor='nw',
        window=icon.label,
        tags=(tag,),
    )


class TkSelector(Selector):
    """Corridor selection window."""
    def __init__(self, packset: packages.PackagesSet, tk_img: TKImages) -> None:
        super().__init__(packset, tk_img)
        self.tk_img = tk_img

    async def reflow(self) -> None:
        """Called to reposition the corridors."""
        self.canvas.delete('slots')

        pos = CanvasPositioner(place_icon, self.canvas, WIDTH, HEIGHT)

        self.canvas.itemconfigure(self.help_lbl_win, width=pos.width)
        self.help_lbl['wraplength'] = pos.width

        await tk_tools.wait_eventloop()
        (x1, y1, x2, y2) = self.canvas.bbox(self.help_lbl_win)
        pos.yoff += y2 - y1

        pos.place_slots(self.icons, 'slots')
        pos.resize_canvas()

    def ui_icon_set_img(self, icon: IconUI, handle: Optional[img.Handle]) -> None:
        """Set the image used."""
        self.tk_img.apply(icon.label, handle)
