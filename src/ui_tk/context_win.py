"""Tk-specific code for the window that shows item information."""
from app.contextWin import ContextWinBase
from ui_tk import TK_ROOT


class ContextWin(ContextWinBase):
    """Tk-specific item context window."""
    def __init__(self) -> None:
        super().__init__()

        # When the main window moves, move the context window also.
        TK_ROOT.bind("<Configure>", self.adjust_position, add='+')
