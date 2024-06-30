"""This package contains UI code specific to WxWidgets."""
from __future__ import annotations

import logging

import wx


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
