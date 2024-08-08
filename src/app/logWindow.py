"""Displays logs for the application.

The implementation is in bg_daemon, to ensure it remains responsive.
"""
from __future__ import annotations
import logging
import queue

import attrs
import srctools.logger
import trio
from typing_extensions import override

from config.gen_opts import GenOptions
from loadScreen import _QUEUE_SEND_LOGGING, _QUEUE_REPLY_LOGGING  # noqa: PLC2701
import config


class TextHandler(logging.Handler):
    """Log all data to a Tkinter Text widget."""
    def __init__(self) -> None:
        super().__init__(logging.NOTSET)
        self.setFormatter(logging.Formatter(
            # One letter for level name
            '[{levelname[0]}]{srctools_context} {module}.{funcName}(): {message}',
            style='{',
        ))

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Add a logging message. This may be called by any thread!"""
        msg = record.msg
        try:
            if isinstance(record.msg, srctools.logger.LogMessage):
                # Ensure we don't use the extra ASCII indents here.
                record.msg = record.msg.format_msg()
            text = self.format(record)
        finally:
            # Undo the record overwrite, so other handlers get the correct object.
            record.msg = msg
        try:
            _QUEUE_SEND_LOGGING.put_nowait(('log', record.levelname, text))
        except queue.Full:
            print('Log queue overflowed!')
        except ValueError:
            # Queue closed.
            pass

    def set_visible(self, is_visible: bool) -> None:
        """Show or hide the window."""
        conf = config.APP.get_cur_conf(GenOptions)
        config.APP.store_conf(attrs.evolve(conf, show_log_win=is_visible))
        try:
            _QUEUE_SEND_LOGGING.put(('visible', is_visible), timeout=0.5)
        except queue.Full:
            pass

    @override
    def setLevel(self, level: int | str) -> None:
        """Set the level of the log window."""
        if isinstance(level, int):
            level_str = logging.getLevelName(level)
        else:
            level_str = level
        super().setLevel(level_str)
        try:
            _QUEUE_SEND_LOGGING.put(('level', level_str), timeout=0.5)
        except queue.Full:
            pass


HANDLER = TextHandler()
logging.getLogger().addHandler(HANDLER)


async def loglevel_bg() -> None:
    """Task that run in the background of the main application."""
    while True:
        # TODO: Ideally use a Trio object for this queue so it doesn't need to thread.
        #       If cancelled, this is going to continue receiving in an abandoned thread
        #       - so the data is potentially lost. But this should only be cancelled if
        #       the app's quitting, so that's fine.
        try:
            cmd = await trio.to_thread.run_sync(_QUEUE_REPLY_LOGGING.get, abandon_on_cancel=True)
        except ValueError:
            # Pipe closed, we're useless.
            return
        match cmd:
            case ['level', level]:
                TextHandler.setLevel(HANDLER, level)
                conf = config.APP.get_cur_conf(GenOptions)
                config.APP.store_conf(attrs.evolve(conf, log_win_level=level))
            case ['visible', enabled]:
                conf = config.APP.get_cur_conf(GenOptions)
                config.APP.store_conf(attrs.evolve(conf, show_log_win=enabled))
            case _:
                raise ValueError(f'Unknown command {cmd!r}!')
