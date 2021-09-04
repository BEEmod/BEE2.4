"""The package containg all UI code."""
import tkinter as tk
import wx
import logging
from types import TracebackType
from typing import Type
import utils

# We must always have one Tk object, and it needs to be constructed
# before most of TKinter will function. So doing it here does it first.
TK_ROOT = tk.Tk()
TK_ROOT.withdraw()  # Hide the window until everything is loaded.

# Same with wxWidgets.
WX_APP = wx.App()


def run_main_loop() -> None:
    """Allow determining if this is running."""
    global _main_loop_running
    _main_loop_running = True
    # Drive TK from WX's loop.
    WX_APP.Bind(wx.EVT_UPDATE_UI, lambda e: TK_ROOT.update())
    WX_APP.MainLoop()


_main_loop_running = False


# noinspection PyBroadException
def tk_error(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType,
) -> None:
    """Log TK errors."""
    # The exception is caught inside the TK code.
    # We don't care about that, so try and move the traceback up
    # one level.
    import sys
    import logging
    if exc_tb.tb_next:
        exc_tb = exc_tb.tb_next

    try:
        on_error(exc_type, exc_value, exc_tb)
    except:
        pass

    logger = logging.getLogger('BEE2')
    logger.error(
        msg='Uncaught Exception:',
        exc_info=(exc_type, exc_value, exc_tb),
    )

    # Since this isn't caught normally, it won't quit the application.
    # Quit ourselves manually. to prevent TK just freezing.
    TK_ROOT.quit()
    sys.exit()

TK_ROOT.report_callback_exception = tk_error


# noinspection PyBroadException
def on_error(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType,
) -> None:
    """Run when the application crashes. Display to the user, log it, and quit."""
    # We don't want this to fail, so import everything here, and wrap in
    # except Exception.
    import traceback

    err = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Grab and release the grab so nothing else can block the error message.
    try:
        TK_ROOT.grab_set_global()
        TK_ROOT.grab_release()

        # Append traceback to the clipboard.
        TK_ROOT.clipboard_append(err)
    except Exception:
        pass

    # Try and terminate background operations.
    try:
        import loadScreen
        loadScreen.BG_PROC.kill()
    except Exception:
        pass
    try:
        from . import sound
        sound.sounds = sound.NullSound()
    except Exception:
        pass

    if not issubclass(exc_type, Exception):
        # It's subclassing BaseException (KeyboardInterrupt, SystemExit),
        # so ignore the error.
        return

    # Put it onscreen.
    try:
        from tkinter import messagebox
        messagebox.showinfo(
            title='BEEMOD {} Error!'.format(utils.BEE_VERSION),
            message='An error occurred: \n{}\n\nThis has '
                    'been copied to the clipboard.'.format(err),
            icon=messagebox.ERROR,
        )
    except Exception:
        pass

    try:
        from BEE2_config import GEN_OPTS
        # Try to turn on the logging window for next time..
        GEN_OPTS.load()
        GEN_OPTS['Debug']['show_log_win'] = '1'
        GEN_OPTS['Debug']['window_log_level'] = 'DEBUG'
        GEN_OPTS.save()
    except Exception:
        # Ignore failures...
        pass


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

# Various configuration booleans.
PLAY_SOUND = tk.BooleanVar(value=True, name='OPT_play_sounds')
KEEP_WIN_INSIDE = tk.BooleanVar(value=True, name='OPT_keep_win_inside')
FORCE_LOAD_ONTOP = tk.BooleanVar(value=True, name='OPT_force_load_ontop')
SHOW_LOG_WIN = tk.BooleanVar(value=False, name='OPT_show_log_window')
LAUNCH_AFTER_EXPORT = tk.BooleanVar(value=True, name='OPT_launch_after_export')
PRESERVE_RESOURCES = tk.BooleanVar(value=False, name='OPT_preserve_bee2_resource_dir')
DEV_MODE = tk.BooleanVar(value=utils.DEV_MODE, name='OPT_development_mode')


