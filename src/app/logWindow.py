"""Displays logs for the application.

The implementation is in bg_daemon, to ensure it remains responsive.
"""
from __future__ import annotations
from typing import Literal, Tuple, Type, Union
import logging
import multiprocessing
import queue

import attrs
import srctools.logger
import trio
from typing_extensions import override

from config.gen_opts import GenOptions
import config


_PIPE_MAIN_REC, PIPE_DAEMON_SEND = multiprocessing.Pipe(duplex=False)
PIPE_DAEMON_REC, _PIPE_MAIN_SEND = multiprocessing.Pipe(duplex=False)
# We need a queue because logs could be sent in from another thread.
_LOG_QUEUE: queue.Queue[
    Type[StopIteration] |
    Tuple[Literal['log'], str, str] |
    Tuple[Literal['visible'], bool, None] |
    Tuple[Literal['level'], str | int, None],
] = queue.Queue(394)
_SHUTDOWN = False


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
            _LOG_QUEUE.put_nowait(('log', record.levelname, text))
        except queue.Full:
            print('Log queue overflowed!')

    def set_visible(self, is_visible: bool) -> None:
        """Show or hide the window."""
        conf = config.APP.get_cur_conf(GenOptions)
        config.APP.store_conf(attrs.evolve(conf, show_log_win=is_visible))
        try:
            _LOG_QUEUE.put(('visible', is_visible, None), timeout=0.5)
        except queue.Full:
            pass

    @override
    def setLevel(self, level: Union[int, str]) -> None:
        """Set the level of the log window."""
        if isinstance(level, int):
            level = logging.getLevelName(level)
        super().setLevel(level)
        try:
            _LOG_QUEUE.put(('level', level, None), timeout=0.5)
        except queue.Full:
            pass

HANDLER = TextHandler()
logging.getLogger().addHandler(HANDLER)


async def loglevel_bg() -> None:
    """Tasks that run in the background of the main application."""
    global _SHUTDOWN
    async with trio.open_nursery() as nursery:
        nursery.start_soon(trio.to_thread.run_sync, emit_logs)
        nursery.start_soon(setting_apply)
        try:
            await trio.sleep_forever()
        finally:
            _SHUTDOWN = True  # Indicate it should shut down.
            # If it was blocked on an empty queue, this will wake it.
            _LOG_QUEUE.put(StopIteration)


def emit_logs() -> None:
    """Send logs across the pipe in a background thread, so the main does not block."""
    while True:
        msg = _LOG_QUEUE.get()
        if msg is StopIteration or _SHUTDOWN:
            return
        _PIPE_MAIN_SEND.send(msg)
        _LOG_QUEUE.task_done()


async def setting_apply() -> None:
    """Monitor and apply setting changes from the log window."""
    while True:
        # TODO: Ideally use a Trio object for this pipe so it doesn't need to thread.
        # If cancelled, this is going to continue receiving in an abandoned thread - so the data
        # is potentially lost. But this should only be cancelled if the app's quitting, so that's
        # fine.
        try:
            cmd, param = await trio.to_thread.run_sync(_PIPE_MAIN_REC.recv, abandon_on_cancel=True)
        except BrokenPipeError:
            # Pipe failed, we're useless.
            return
        if cmd == 'level':
            TextHandler.setLevel(HANDLER, param)
            conf = config.APP.get_cur_conf(GenOptions)
            config.APP.store_conf(attrs.evolve(conf, log_win_level=param))
        elif cmd == 'visible':
            conf = config.APP.get_cur_conf(GenOptions)
            config.APP.store_conf(attrs.evolve(conf, show_log_win=param))
        elif cmd == 'quit':
            return
        else:
            raise ValueError(f'Unknown command {cmd}({param})!')
