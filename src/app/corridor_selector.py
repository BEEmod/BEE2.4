"""Implements UI for selecting corridors."""
from typing import Callable
from tkinter import ttk
import tkinter as tk

from app import TK_ROOT, config, BEE2


class Selector:
    def __init__(self) -> None:
        self.win = tk.Toplevel(TK_ROOT)
        self.win.wm_protocol("WM_DELETE_WINDOW", self.hide)

        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)

        frm_left = ttk.Frame(self.win, relief="sunken")
        frm_left.rowconfigure(0, weight=1)
        frm_left.columnconfigure(0, weight=1)
        frm_left.grid(row=0, column=0, sticky='nsew')

        frm_right = ttk.Frame(self.win)
        frm_right.rowconfigure(0, weight=1)
        frm_right.columnconfigure(0, weight=1)
        frm_right.grid(row=0, column=1, sticky='ns')

        self.wid_sel_title = ttk.Label(frm_right, text='Corridor')
        self.wid_sel_title.grid(row=1, column=0, sticky='ew')

    def show(self) -> None:
        self.win.deiconify()

    def hide(self) -> None:
        self.win.withdraw()

