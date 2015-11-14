"""
General code used for tkinter portions.

"""
from tkinter import ttk
import tkinter as tk

from idlelib.WidgetRedirector import WidgetRedirector

import utils

# Put this in a module so it's a singleton, and we can always import the same
# object.
TK_ROOT = tk.Tk()

if utils.WIN:
    # Ensure everything has our icon (including dialogs)
    TK_ROOT.wm_iconbitmap(default='../BEE2.ico')
TK_ROOT.withdraw()  # Hide the window until everything is loaded.


def event_cancel(*args, **kwargs):
    """Bind to an event to cancel it, and prevent it from propagating."""
    return 'break'


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


class ReadOnlyEntry(ttk.Entry):
    """A modified Entry widget which prevents editing the text.

    See http://tkinter.unpythonic.net/wiki/ReadOnlyText
    """
    def __init__(self, master, **opt):

        opt['exportselection'] = 0 # Don't let it write to clipboard
        opt['takefocus'] = 0 # Ignore when tabbing
        super().__init__(master, **opt)

        self.redirector = redir = WidgetRedirector(self)
        # These two TK commands are used for all text operations,
        # so cancelling them stops anything from happening.
        self.insert = redir.register('insert', event_cancel)
        self.delete = redir.register('delete', event_cancel)