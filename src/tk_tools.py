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
