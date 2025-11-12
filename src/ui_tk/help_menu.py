"""Tkinter-specific help menu implementation."""
from typing import override

from tkinter import ttk
import tkinter as tk
from contextlib import aclosing
import functools

import trio

from app.helpMenu import (
    ICONS, SEPERATOR, TRANS_CLOSE_BUTTON, TRANS_CREDITS_BUTTON,
    TRANS_CREDITS_TITLE, WEB_RESOURCES, CreditsWindowBase, open_url, splash_btn_task
)
from app.mdown import MarkdownData
import utils
from async_util import EdgeTrigger
from transtoken import TransToken

from . import TK_ROOT, tk_tools
from .dialogs import DIALOG
from .img import TKImages
from .rich_textbox import RichText
from .wid_transtoken import set_menu_text, set_text, set_win_title


class CreditsWindow(CreditsWindowBase):
    """Tk-specific implementation."""

    def __init__(self) -> None:
        super().__init__()
        self.win = win = tk.Toplevel(TK_ROOT, name='credits')
        win.withdraw()
        set_win_title(win, TRANS_CREDITS_TITLE)
        win.transient(master=TK_ROOT)
        win.resizable(width=True, height=True)
        if utils.LINUX:
            win.wm_attributes('-type', 'dialog')
        tk_tools.set_window_icon(win)

        # Hide when the exit button is pressed, or Escape
        # on the keyboard.
        close_cmd = win.register(self._close)
        win.wm_protocol("WM_DELETE_WINDOW", close_cmd)
        win.bind("<Escape>", close_cmd)

        frame = tk.Frame(win, background='white')
        frame.grid(row=0, column=0, sticky='nsew')
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)

        self._textbox = RichText(frame, name='message', width=80, height=24)
        self._textbox.configure(background='white', relief='flat')
        self._textbox.grid(row=0, column=0, sticky='nsew')
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        scrollbox = tk_tools.HidingScroll(
            frame,
            orient='vertical',
            command=self._textbox.yview,
        )
        scrollbox.grid(row=0, column=1, sticky='ns')
        self._textbox['yscrollcommand'] = scrollbox.set

        set_text(
            ttk.Button(frame, command=close_cmd),
            TRANS_CLOSE_BUTTON,
        ).grid(row=1, column=0)

    @override
    async def _ui_apply_text(self, text: MarkdownData) -> None:
        """Apply the credits text to the window."""
        self._textbox.set_text(text)

    @override
    async def _ui_show_window(self) -> None:
        """Show the window, and center it."""
        self.win.deiconify()
        await tk_tools.wait_eventloop()
        tk_tools.center_win(self.win, TK_ROOT)

    @override
    async def _ui_hide_window(self) -> None:
        """Hide the window."""
        self.win.withdraw()


async def create(
    menu: tk.Menu, tk_img: TKImages,
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create and operate the application 'Help' menu."""
    credit_window = CreditsWindow()
    open_splash_map: EdgeTrigger[()] = EdgeTrigger()

    async with trio.open_nursery() as nursery:
        for res in WEB_RESOURCES:
            if res is SEPERATOR:
                menu.add_separator()
            else:
                menu.add_command(
                    command=functools.partial(nursery.start_soon, open_url, DIALOG, res.url_key),
                    compound='left',
                )
                tk_img.menu_set_icon(menu, utils.not_none(menu.index('end')), ICONS[res.icon])
                set_menu_text(menu, res.name)

        menu.add_separator()
        menu.add_command(command=open_splash_map.trigger)
        splash_ind = menu.index('end')
        assert splash_ind is not None

        menu.add_command(command=credit_window.open.trigger)
        credit_ind = menu.index('end')
        assert credit_ind is not None
        set_menu_text(menu, TRANS_CREDITS_BUTTON, credit_ind)

        def set_splash(text: TransToken, enabled: bool) -> None:
            """Set the state of the splash credits option."""
            set_menu_text(menu, text, splash_ind)
            menu.entryconfigure(splash_ind, state='normal' if enabled else 'disabled')

        nursery.start_soon(credit_window.display_task)
        nursery.start_soon(splash_btn_task,DIALOG, set_splash, open_splash_map)
        async with aclosing(credit_window.open.ready.eventual_values()) as agen:
            task_status.started()
            async for enabled in agen:
                menu.entryconfigure(credit_ind, state='normal' if enabled else 'disabled')
