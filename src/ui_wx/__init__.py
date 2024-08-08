"""This package contains UI code specific to WxWidgets."""
from __future__ import annotations

import logging
from collections.abc import Callable

import wx
import mistletoe

import utils
from app import mdown


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


class _MarkdownConverter(mdown.BaseRenderer[str]):
    def _convert(self, text: str, package: utils.ObjectID | None) -> str:
        """Convert to HTML."""
        # TODO images?
        return mistletoe.markdown(text)

    def _join(self, children: list[str]) -> str:
        """Join two fragments together."""
        return '<br /><br />\n'.join(children)


MARKDOWN = _MarkdownConverter(str)

PEN_SLOT_BORDER = wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWFRAME), 3)
PEN_SLOT_BORDER_SEL = wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT), 3)
