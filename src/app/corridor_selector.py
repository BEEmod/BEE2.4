"""Implements UI for selecting corridors."""
from typing import Callable, Final

from tkinter import ttk
import tkinter as tk

import srctools.logger

from app import TK_ROOT, config, img, sound, tk_tools
from app.richTextBox import tkRichText
from localisation import gettext
from packages import corridor
import consts


LOGGER = srctools.logger.get_logger(__name__)


class Selector:
    """Corridor selection UI."""
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
        frm_right.columnconfigure(0, weight=1)
        frm_right.grid(row=0, column=1, sticky='ns')

        self.wid_image = ttk.Label(frm_right)
        self.wid_image.grid(row=0, column=0, sticky='ew')
        img.apply(self.wid_image, img.Handle.builtin('BEE2/corr_generic', 256, 192))

        self.wid_title = ttk.Label(frm_right, text='Corridor')
        self.wid_title.grid(row=1, column=0, sticky='ew')

        self.wid_desc = tkRichText(frm_right)
        self.wid_desc.grid(row=2, column=0, sticky='nsew')
        frm_right.rowconfigure(2, weight=1)

        button_frm = ttk.Frame(frm_left)
        button_frm.grid(row=0, column=0, columnspan=3)
        self.btn_mode = tk_tools.EnumButton(
            button_frm,
            (corridor.GameMode.SP, gettext('SP')),
            (corridor.GameMode.COOP, gettext('Coop')),
            callback=self._evt_modechange,
        )
        self.btn_direction = tk_tools.EnumButton(
            button_frm,
            (corridor.Direction.ENTRY, gettext('Entry')),
            (corridor.Direction.EXIT, gettext('Exit')),
            callback=self._evt_modechange,
        )
        self.btn_orient = tk_tools.EnumButton(
            button_frm,
            (corridor.CorrOrient.FLAT, gettext('Flat')),
            (corridor.CorrOrient.UP, gettext('Upward')),
            (corridor.CorrOrient.DN, gettext('Downward')),
            callback=self._evt_modechange,
        )
        self.btn_mode.frame.grid(row=0, column=0, padx=8)
        self.btn_direction.frame.grid(row=0, column=1, padx=8)
        self.btn_orient.frame.grid(row=0, column=2, padx=8)

    def show(self) -> None:
        """Display the window."""
        self.win.deiconify()

    def hide(self) -> None:
        """Hide the window."""
        self.win.withdraw()

    def _evt_modechange(self, _):
        """Called when any of the radio pushbuttons are pressed."""
