"""Handler for app.errors."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
import math

import trio

from app.errors import ErrorUI
from app import quit_app
from transtoken import AppError, TransToken

from . import TK_ROOT, tk_tools
from .wid_transtoken import set_text, set_win_title


type ChannelValue = tuple[TransToken, TransToken, list[AppError], trio.Event]


async def display_errors(
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Always-running task that displays errors."""
    send: trio.abc.SendChannel[ChannelValue]
    receive: trio.abc.ReceiveChannel[ChannelValue]
    send, receive = trio.open_memory_channel(math.inf)

    # Set when the dialog was closed, and the handler can return. Immediately re-assigned.
    close_event = trio.Event()

    async def handler(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
        """Wait for the error box to display the message."""
        evt = trio.Event()
        await send.send((title, desc, errors, evt))
        await evt.wait()

    window = tk.Toplevel(TK_ROOT, name='errorWin')
    window.wm_attributes('-topmost', 1)
    window.withdraw()
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    # Late binding, looks up each time.
    window.wm_protocol("WM_DELETE_WINDOW", lambda: close_event.set())

    await trio.lowlevel.checkpoint()

    bg = ttk.Frame(window, name='bg')  # Required for correct background.
    bg.grid(row=0, column=0, sticky="NSEW")
    bg.columnconfigure(0, weight=1)
    bg.rowconfigure(1, weight=1)

    frame = ttk.Frame(window, name='frame')
    frame.grid(row=0, column=0, sticky='NSEW', padx=16, pady=16)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)

    wid_desc = ttk.Label(frame, name='desc')
    wid_desc.grid(row=0, column=0, sticky='EW', padx=4, pady=2)

    wid_error_border = tk.Frame(frame, name='border', relief='sunken', bg='white', borderwidth=2)
    wid_error_border.grid(row=1, column=0, sticky='NSEW', padx=4, pady=2)
    wid_error_border.columnconfigure(0, weight=1)
    wid_error_border.rowconfigure(0, weight=1)

    wid_error_canv = tk.Canvas(
        wid_error_border,
        name='scroll_canv', bg='white',
        borderwidth=0, highlightthickness=0,
    )
    wid_error_canv.grid(row=0, column=0, sticky='NSEW', padx=(2, 0), pady=2)

    await trio.lowlevel.checkpoint()

    wid_error_frm = tk.Frame(wid_error_canv, name='errors', bg='white')
    wid_error_frm.columnconfigure(0, weight=1)
    wid_error_canv.create_window(0, 0, anchor='nw', window=wid_error_frm)

    scrollbar = tk_tools.HidingScroll(
        wid_error_border, orient='vertical',
        command=wid_error_canv.yview,
    )
    scrollbar.grid(row=0, column=1, sticky='NS')
    wid_error_canv['yscrollcommand'] = scrollbar.set
    tk_tools.add_mousewheel(wid_error_canv, window)

    await trio.lowlevel.checkpoint()

    btn_frame = ttk.Frame(frame)
    btn_frame.grid(row=2, column=0, pady=2)

    wid_quit = ttk.Button(btn_frame, command=quit_app, name='quit_btn')
    wid_quit.grid(row=0, column=0, padx=4)
    set_text(wid_quit, TransToken.ui("Quit"))

    wid_close = ttk.Button(btn_frame, command=lambda: close_event.set(), name='close_btn')
    wid_close.grid(row=0, column=1, padx=4)
    set_text(wid_close, TransToken.ui("Continue"))

    # Cache the labels and separators.
    error_widgets: list[tuple[tk.Label, ttk.Separator]] = []

    def on_resize(e: object) -> None:
        """Resize labels when the window does."""
        wid_desc['wraplength'] = frame.winfo_width() - 10
        canv_width = wid_error_canv.winfo_width()
        wid_error_canv['scrollregion'] = (0, 0, canv_width, wid_error_frm.winfo_reqheight())
        for label, sep in error_widgets:
            label['wraplength'] = canv_width - 15

    window.bind('<Configure>', on_resize)

    with ErrorUI.install_handler(handler):
        # We're now ready for events.
        task_status.started()
        while True:
            # Alternate between waiting for an error, displaying, then waiting for it to close.
            title, desc, errors, close_event = await receive.receive()
            set_win_title(window, title)
            set_text(wid_desc, desc)

            # Create enough for this set of errors.
            while len(error_widgets) < len(errors):
                error_widgets.append((
                    tk.Label(wid_error_frm, bg='white', justify='left'),
                    ttk.Separator(wid_error_frm, orient='horizontal'),
                ))
            error_wid_iter = iter(error_widgets)
            for i, (error, (label, sep)) in enumerate(zip(errors, error_wid_iter, strict=False)):
                set_text(label, error.message)
                label.grid(row=2 * i, column=0, pady=(4, 4), sticky='EW')
                if i != 0:
                    # Place behind for all except the first, so it goes in between.
                    # The first separator is unused, but that isn't important.
                    sep.grid(row=2 * i - 1, column=0, padx=2, sticky='EW')
            for label, sep in error_wid_iter:
                set_text(label, TransToken.BLANK)
                label.grid_remove()
                sep.grid_remove()

            window.deiconify()
            window.lift()
            tk_tools.center_onscreen(window)
            window.bell()
            await close_event.wait()
            window.withdraw()
