"""
General code used for tkinter portions.

"""
from tkinter import ttk
import tkinter as tk
import utils

# Put this in a module so it's a singleton, and we can always import the same
# object.
TK_ROOT = tk.Tk()

if utils.WIN:
    # Ensure everything has our icon (including dialogs)
    TK_ROOT.wm_iconbitmap(default='../BEE2.ico')
TK_ROOT.withdraw()  # Hide the window until everything is loaded.


class HidingScroll(ttk.Scrollbar):
    """A scrollbar variant which auto-hides when not needed.

    """
    def set(self, low, high):
        """Set the size needed for the scrollbar, and hide/show if needed."""
        if float(low) <= 0.0 and float(high) >= 1.0:
            # Remove this, but remember gridding options
            self.grid_remove()
        else:
            self.grid()
        super(HidingScroll, self).set(low, high)
