"""Tk implementation of the corridor selector."""
import packages
from app.corridor_selector import Selector
from ui_tk.img import TKImages


class TkSelector(Selector):
    """Corridor selection window."""
    def __init__(self, packset: packages.PackagesSet, tk_img: TKImages) -> None:
        super().__init__(packset, tk_img)
