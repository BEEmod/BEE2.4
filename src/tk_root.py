"""
Special module used to ensure other modules use the same TK instance.

When Tk() is called, a toplevel window is generated for the application.
Putting this in a module ensures only one is ever created.

"""
from tkinter import Tk
import utils


TK_ROOT = Tk()
if utils.WIN:
    # Ensure everything has our icon (including dialogs)
    TK_ROOT.wm_iconbitmap(default='../BEE2.ico')
TK_ROOT.withdraw()  # Hide the window until everything is loaded.
