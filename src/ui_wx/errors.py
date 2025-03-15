"""Handler for app.errors."""
from __future__ import annotations
import math

import trio
import wx

from app.errors import ErrorUI
from transtoken import AppError, TransToken
from .wid_transtoken import set_text, set_win_title
from . import MAIN_WINDOW


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

    window = wx.Dialog(
        MAIN_WINDOW,
        style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP | wx.RESIZE_BORDER,
    )
    panel_main = wx.Panel(window)
    sizer_outer = wx.BoxSizer(wx.VERTICAL)
    panel_main.SetSizer(sizer_outer)

    label_desc = wx.StaticText(panel_main, wx.ID_ANY, "An error occurred:")
    sizer_outer.Add(label_desc, wx.SizerFlags().DoubleBorder())

    panel_errors = wx.ScrolledWindow(panel_main, wx.ID_ANY, style=wx.BORDER_SUNKEN)
    panel_errors.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
    panel_errors.SetScrollRate(0, 10)
    sizer_outer.Add(panel_errors, wx.SizerFlags().Proportion(1).Expand().TripleBorder())

    sizer_errors = wx.BoxSizer(wx.VERTICAL)
    panel_errors.SetSizer(sizer_errors)

    button_sizer = wx.StdDialogButtonSizer()
    button_close = wx.Button(panel_main, wx.ID_CLOSE, "")
    button_close.SetDefault()
    button_sizer.Add(button_close)
    button_sizer.Realize()
    sizer_outer.Add(button_sizer, wx.SizerFlags().CenterHorizontal())

    # Cache the labels and separators.
    error_widgets: list[tuple[wx.StaticText, wx.StaticLine]] = []

    label_font = wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, 0, "")
    label_flags = wx.SizerFlags().Expand().Border()
    sep_flags = wx.SizerFlags().Expand().Border(wx.TOP | wx.BOTTOM)

    def on_close(event: wx.Event) -> None:
        """Late binding to the event object."""
        close_event.set()

    window.Bind(wx.EVT_CLOSE, on_close)
    button_close.Bind(wx.EVT_BUTTON, on_close)

    with ErrorUI.install_handler(handler):
        # We're now ready for events.
        task_status.started()
        while True:
            # Alternate between waiting for an error, displaying, then waiting for it to close.
            title, desc, errors, close_event = await receive.receive()
            set_win_title(window, title)
            set_text(label_desc, desc)

            # Create enough for this set of errors.
            while len(error_widgets) < len(errors):
                label = wx.StaticText(panel_errors)
                label.SetFont(label_font)
                error_widgets.append((
                    label,
                    wx.StaticLine(panel_errors, wx.HORIZONTAL),
                ))
            error_wid_iter = iter(error_widgets)
            sizer_errors.Clear(delete_windows=False)
            panel_errors.SetVirtualSize(0, 0)
            for i, (error, (label, sep)) in enumerate(zip(errors, error_wid_iter, strict=False)):
                if i != 0:
                    # Place behind for all except the first, so it goes in between.
                    # The first separator is unused, but that isn't important.
                    sizer_errors.Add(sep, sep_flags)
                    sep.Show()

                set_text(label, error.message)
                label.Show()
                sizer_errors.Add(label, label_flags)
            for label, sep in error_wid_iter:
                set_text(label, TransToken.BLANK)
                label.Hide()
                sep.Hide()

            window.Layout()
            window.Show()
            window.Raise()
            window.CenterOnScreen()
            wx.Bell()
            await close_event.wait()
            window.Hide()
