"""This package contains UI code specific to WxWidgets."""
from __future__ import annotations
from typing import Final, Literal

from collections.abc import Callable
import logging

import wx

import utils
from app import img


APP = wx.App()
APP.SetAppName('BEEmod')
MAIN_WINDOW = wx.Frame(None)
APP.SetTopWindow(MAIN_WINDOW)


# Convert WX log levels to stdlib equivalents.
levels_wx_to_stdlib = {
    wx.LOG_Debug: logging.DEBUG,
    wx.LOG_Error: logging.ERROR,
    wx.LOG_FatalError: logging.FATAL,
    wx.LOG_Info: logging.INFO,
    wx.LOG_Max: logging.DEBUG,
    wx.LOG_Message: logging.INFO,
    wx.LOG_Progress: logging.DEBUG,
    wx.LOG_Status: logging.INFO,
    wx.LOG_Trace: logging.DEBUG,
    wx.LOG_User: logging.DEBUG,
    wx.LOG_Warning: logging.WARNING,
}


class WXLogTarg(wx.Log):
    """Handle WX logging, and redirect it to Python's log system."""
    def __init__(self) -> None:
        super().__init__()
        self.logger: logging.Logger = logging.getLogger('wxWidgets')

    def DoLogRecord(self, level: int, msg: str, info: wx.LogRecordInfo) -> None:
        """Pass the WX log system into the Python system."""
        # Filename and function name are bytes, ew.
        self.logger.handle(self.logger.makeRecord(
            'wxWidgets',
            levels_wx_to_stdlib.get(level, logging.INFO),
            info.filename.decode('utf8', 'ignore'),
            info.line,
            msg,
            (),  # It's already been formatted so no args are needed.
            None,  # Exception info, not compatible.
            info.func.decode('utf8', 'ignore'),
        ))


wx.Log.SetActiveTarget(WXLogTarg())


def get_scrollflow_size_handler(
    panel: wx.ScrolledWindow,
    sizer: wx.WrapSizer,
) -> Callable[[wx.SizeEvent], None]:
    """Create an event handler used to fix interactions between a scrolling window and a wrap-sizer.

    When making a scrolled window larger, the virtual size gets extended to match the window,
    but it never gets shrunk. That means making the window smaller messes up the wrapping.
    """
    def size_handler(evt: wx.SizeEvent) -> None:
        """Handle the event."""
        size = panel.GetVirtualSize()
        size.Width = 10
        panel.SetVirtualSize(size)
        # The sizer needs to be repositioned twice, otherwise it can be left with the
        # last column sticking outside the window.
        wx.CallAfter(wx.WrapSizer.RepositionChildren, sizer, size)
        evt.Skip()

    return size_handler


def discretise_scrollwheel(func: Callable[[Literal[-1, 1]], None]) -> Callable[[wx.MouseEvent], None]:
    """Convert the scrollwheel events into discrete movement calls.

    Mousewheel events might trigger with less/more than a single tick, so this needs
    to accumulate results, then trigger the function.
    """
    amount = 0

    def handler(evt: wx.MouseEvent) -> None:
        """Handle using the mousewheel on the corridor icon."""
        nonlocal amount
        amount += evt.WheelRotation
        delta = max(1, evt.WheelDelta)
        while amount >= delta:
            amount -= delta
            func(-1)
        while amount <= -delta:
            amount += delta
            func(1)

    return handler


BRUSH_PETI_BG = wx.Brush(img.PETI_ITEM_BG, wx.BRUSHSTYLE_SOLID)
BRUSH_ALPHA = wx.Brush(wx.NullColour, wx.BRUSHSTYLE_TRANSPARENT)
PEN_ALPHA = wx.Pen()
PEN_SLOT_BORDER = wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWFRAME), 3)
PEN_SLOT_BORDER_SEL = wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT), 3)


def _make_radio_icon() -> wx.Bitmap:
    """Generate a bitmap which makes check-style menus look like radio menus."""
    from PIL import Image, ImageDraw
    fill = wx.SystemSettings.GetColour(wx.SYS_COLOUR_MENUTEXT)
    # Draw oversize then scale down to get some antialiasing.
    img = Image.new('RGBA', (64, 64))
    draw = ImageDraw.Draw(img)
    draw.ellipse([20, 20, 40, 40], (fill.red, fill.green, fill.blue, fill.alpha))
    return wx.Bitmap.FromBufferRGBA(16, 16, img.resize((16, 16)).tobytes())


# TODO: Can't change the button design on other platforms, unfortunately.
#       They only allow a single icon for both checked/unchecked.
RADIO_MENU_BITMAP: Final = _make_radio_icon() if utils.WIN else wx.NullBitmap


def set_fixed_size(widget: wx.Window, width: float, height: float) -> None:
    """Set the min and max sizes to the same (DIP) size."""
    size = widget.FromDIP(wx.Size(round(width), round(height)))
    widget.SetMinSize(size)
    widget.SetMaxSize(size)
