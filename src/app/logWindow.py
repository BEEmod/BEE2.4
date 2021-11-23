"""Displays logs for the application.
"""
import logging
import multiprocessing, threading
from typing import Union

import srctools.logger
from BEE2_config import GEN_OPTS

_PIPE_MAIN_REC, PIPE_DAEMON_SEND = multiprocessing.Pipe(duplex=False)
PIPE_DAEMON_REC, _PIPE_MAIN_SEND = multiprocessing.Pipe(duplex=False)


class TextHandler(logging.Handler):
    """Log all data to a Tkinter Text widget."""
    def __init__(self) -> None:
        super().__init__(logging.NOTSET)
        self.setFormatter(logging.Formatter(
            # One letter for level name
            '[{levelname[0]}] {module}.{funcName}(): {message}',
            style='{',
        ))

    def emit(self, record: logging.LogRecord):
        """Add a logging message."""
        msg = record.msg
        try:
            if isinstance(record.msg, srctools.logger.LogMessage):
                # Ensure we don't use the extra ASCII indents here.
                record.msg = record.msg.format_msg()
            text = self.format(record)
        finally:
            # Undo the record overwrite, so other handlers get the correct object.
            record.msg = msg
        _PIPE_MAIN_SEND.send(('log', record.levelname, text))

    def set_visible(self, is_visible: bool):
        """Show or hide the window."""
        GEN_OPTS['Debug']['show_log_win'] = srctools.bool_as_int(is_visible)
        _PIPE_MAIN_SEND.send(('visible', is_visible, None))

    def setLevel(self, level: Union[int, str]) -> None:
        """Set the level of the log window."""
        if isinstance(level, int):
            level = logging.getLevelName(level)
        super(TextHandler, self).setLevel(level)
        _PIPE_MAIN_SEND.send(('level', level, None))

HANDLER = TextHandler()
logging.getLogger().addHandler(HANDLER)


def setting_apply_thread() -> None:
    """Thread to apply setting changes."""
    while True:
        cmd, param = _PIPE_MAIN_REC.recv()
        if cmd == 'level':
            TextHandler.setLevel(HANDLER, param)
            GEN_OPTS['Debug']['window_log_level'] = param
        elif cmd == 'visible':
            GEN_OPTS['Debug']['show_log_win'] = srctools.bool_as_int(param)
        else:
            raise ValueError(f'Unknown command {cmd}({param})!')

_setting_thread = threading.Thread(
    target=setting_apply_thread,
    name='logwindow_settings_apply',
    daemon=True,
)
_setting_thread.start()
