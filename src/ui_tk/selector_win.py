"""Tk-specific implementation of the selector window."""
from app.selector_win import SelectorWinBase, AttrDef


__all__ = [
    'AttrDef',  # Re-export
    'SelectorWin',
]


class SelectorWin(SelectorWinBase):
    """Tk implementation of the selector window."""
