"""Handler for app.errors."""
from __future__ import annotations
from typing import List, Tuple
from tkinter import ttk
import tkinter as tk
import math

import trio

from app import TK_ROOT
from app.errors import AppError, ErrorUI
from transtoken import TransToken
from ui_tk.wid_transtoken import set_text, set_win_title


ChannelValue = Tuple[TransToken, TransToken, List[AppError], trio.Event]


async def display_errors(
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Always-running task that displays errors."""
    send: trio.abc.SendChannel[ChannelValue]
    receive: trio.abc.ReceiveChannel[ChannelValue]
    send, receive = trio.open_memory_channel(math.inf)

    # Set when the dialog was closed, and the handler can return. Immediately re-assigned.
    close_event = trio.Event()

    async def handler(title: TransToken, desc: TransToken, errors: List[AppError]) -> None:
        """Wait for the error box to display the message."""
        evt = trio.Event()
        await send.send((title, desc, errors, evt))
        await evt.wait()

    window = tk.Toplevel(TK_ROOT, name='errorWin')
    window.withdraw()
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    # Late binding, looks up each time.
    window.wm_protocol("WM_DELETE_WINDOW", lambda: close_event.set())

    bg = ttk.Frame(window, name='frame')
    bg.grid(row=0, column=0, sticky="NSEW")
    bg.columnconfigure(0, weight=1)
    bg.rowconfigure(1, weight=1)

    wid_desc = ttk.Label(bg, name='desc')
    wid_desc.grid(row=0, column=0, sticky="EW")

    wid_errors = ttk.Label(bg, wraplength=200, name='list_lbl')
    wid_errors.grid(row=1, column=0, sticky="NSEW")

    wid_close = ttk.Button(bg, command=lambda: close_event.set(), name='close_btn')
    wid_close.grid(row=2, column=0)
    set_text(wid_close, TransToken.ui("Close"))

    with ErrorUI.install_handler(handler):
        # We're now ready for events.
        task_status.started()
        while True:
            # Alternate between waiting for an error, displaying, then waiting for it to close.
            title, desc, errors, close_event = await receive.receive()
            set_win_title(window, title)
            set_text(wid_desc, desc)
            set_text(wid_errors, TransToken.untranslated("\n").join([
                exc.message for exc in errors
            ]))

            window.deiconify()
            await close_event.wait()
            window.withdraw()
