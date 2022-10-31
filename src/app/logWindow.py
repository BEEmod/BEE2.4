"""Displays logs for the application.

The implementation is in bg_daemon, to ensure it remains responsive.
"""
import logging
import math
import multiprocessing
from typing import Union

import srctools.logger
import trio
import attrs

from config.gen_opts import GenOptions
import config


_PIPE_MAIN_REC, PIPE_DAEMON_SEND = multiprocessing.Pipe(duplex=False)
PIPE_DAEMON_REC, _PIPE_MAIN_SEND = multiprocessing.Pipe(duplex=False)
_SEND_LOGS: trio.MemorySendChannel
_REC_LOGS: trio.MemoryReceiveChannel
_SEND_LOGS, _REC_LOGS = trio.open_memory_channel(384)


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
        try:
            _SEND_LOGS.send_nowait(('log', record.levelname, text))
        except trio.WouldBlock:
            print('Log queue overflowed!')

    def set_visible(self, is_visible: bool) -> None:
        """Show or hide the window."""
        conf = config.APP.get_cur_conf(GenOptions)
        config.APP.store_conf(attrs.evolve(conf, show_log_win=is_visible))
        _SEND_LOGS.send_nowait(('visible', is_visible, None))

    def setLevel(self, level: Union[int, str]) -> None:
        """Set the level of the log window."""
        if isinstance(level, int):
            level = logging.getLevelName(level)
        super(TextHandler, self).setLevel(level)
        _SEND_LOGS.send_nowait(('level', level, None))

HANDLER = TextHandler()
logging.getLogger().addHandler(HANDLER)


async def loglevel_bg() -> None:
    """Tasks that run in the background of the main application."""
    global _SEND_LOGS
    async with trio.open_nursery() as nursery:
        nursery.start_soon(emit_logs)
        nursery.start_soon(setting_apply)
        await trio.sleep_forever()


async def emit_logs() -> None:
    """Send logs across the pipe in a background thread, since it can wait for synchronisation."""
    sender = _PIPE_MAIN_SEND.send
    while True:
        msg = await _REC_LOGS.receive()
        await trio.to_thread.run_sync(sender, msg)


async def setting_apply() -> None:
    """Monitor and apply setting changes from the log window."""
    while True:
        # TODO: Ideally use a Trio object for this pipe so it doesn't need to thread.
        # If cancelled, this is going to continue receiving in an abandoned thread - so the data
        # is potentially lost. But this should only be cancelled if the app's quitting, so that's
        # fine.
        try:
            cmd, param = await trio.to_thread.run_sync(_PIPE_MAIN_REC.recv, cancellable=True)
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
