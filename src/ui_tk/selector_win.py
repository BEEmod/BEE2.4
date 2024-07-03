"""Tk-specific implementation of the selector window."""
import tkinter as tk

from app.selector_win import SelectorWinBase, AttrDef, Options


__all__ = [
    'AttrDef',  # Re-export
    'SelectorWin',
    'Options',
]


class SelectorWin(SelectorWinBase):
    """Tk implementation of the selector window."""
    def __init__(self, parent: tk.Tk | tk.Toplevel, opt: Options) -> None:
        super().__init__(parent, opt)
