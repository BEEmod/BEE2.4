# coding=utf-8
import collections
import logging
import os.path
import stat
import tempfile
from enum import Enum
from sys import platform

from typing import (
    Tuple, Iterator,
)

try:
    # This module is generated when cx_freeze compiles the app.
    from BUILD_CONSTANTS import BEE_VERSION
except ImportError:
    # We're running from source!
    BEE_VERSION = "(dev)"
    FROZEN = False
else:
    FROZEN = True

WIN = platform.startswith('win')
MAC = platform.startswith('darwin')
LINUX = platform.startswith('linux')

# Formatters for the logger handlers.
short_log_format = None
long_log_format = None

# Various logger handlers
stdout_loghandler = None
stderr_loghandler = None
file_loghandler = None

# App IDs for various games. Used to determine which game we're modding
# and activate special support for them
STEAM_IDS = {
    'PORTAL2': '620',

    'APTAG': '280740',
    'APERTURE TAG': '280740',
    'ALATAG': '280740',
    'TAG': '280740',

    'TWTM': '286080',
    'THINKING WITH TIME MACHINE': '286080',

    # Others:
    # 841: P2 Beta
    # 213630: Educational
    # 247120: Sixense
    # 211480: 'In Motion'
    # 317400: PS Mel - No workshop
}

if WIN:
    # Some events differ on different systems, so define them here.
    EVENTS = {
        'LEFT': '<Button-1>',
        'LEFT_DOUBLE': '<Double-Button-1>',
        'LEFT_CTRL': '<Control-Button-1>',
        'LEFT_SHIFT': '<Shift-Button-1>',
        'LEFT_RELEASE': '<ButtonRelease-1>',
        'LEFT_MOVE': '<B1-Motion>',

        'RIGHT': '<Button-3>',
        'RIGHT_DOUBLE': '<Double-Button-3>',
        'RIGHT_CTRL': '<Control-Button-3>',
        'RIGHT_SHIFT': '<Shift-Button-3>',
        'RIGHT_RELEASE': '<ButtonRelease-3>',
        'RIGHT_MOVE': '<B3-Motion>',

        'KEY_EXPORT': '<Control-e>',
        'KEY_SAVE_AS': '<Control-s>',
        'KEY_SAVE': '<Control-Shift-s>',
    }
    # The text used to show shortcuts in menus.
    KEY_ACCEL = {
        'KEY_EXPORT': 'Ctrl-E',
        'KEY_SAVE': 'Ctrl-S',
        'KEY_SAVE_AS': 'Ctrl-Shift-S',
    }

    CURSORS = {
        'regular': 'arrow',
        'link': 'hand2',
        'wait': 'watch',
        'stretch_vert': 'sb_v_double_arrow',
        'stretch_horiz': 'sb_h_double_arrow',
        'move_item': 'plus',
        'destroy_item': 'x_cursor',
        'invalid_drag': 'no',
    }

    def add_mousewheel(target, *frames, orient='y'):
        """Add events so scrolling anywhere in a frame will scroll a target.

        frames should be the TK objects to bind to - mainly Frame or
        Toplevel objects.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - Windows needs the delta value to be divided by 120.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def mousewheel_handler(event):
            scroll_func(int(event.delta / -120), "units")
        for frame in frames:
            frame.bind('<MouseWheel>', mousewheel_handler, add='+')

elif MAC:
    EVENTS = {
        'LEFT': '<Button-1>',
        'LEFT_DOUBLE': '<Double-Button-1>',
        'LEFT_CTRL': '<Control-Button-1>',
        'LEFT_SHIFT': '<Shift-Button-1>',
        'LEFT_RELEASE': '<ButtonRelease-1>',
        'LEFT_MOVE': '<B1-Motion>',

        'RIGHT': '<Button-2>',
        'RIGHT_DOUBLE': '<Double-Button-2>',
        'RIGHT_CTRL': '<Control-Button-2>',
        'RIGHT_SHIFT': '<Shift-Button-2>',
        'RIGHT_RELEASE': '<ButtonRelease-2>',
        'RIGHT_MOVE': '<B2-Motion>',

        'KEY_EXPORT': '<Command-e>',
        'KEY_SAVE_AS': '<Command-s>',
        'KEY_SAVE': '<Command-Shift-s>',
    }

    KEY_ACCEL = {
        # tkinter replaces Command- with the special symbol automatically.
        'KEY_EXPORT': 'Command-E',
        'KEY_SAVE': 'Command-S',
        'KEY_SAVE_AS': 'Command-Shift-S',
    }

    CURSORS = {
        'regular': 'arrow',
        'link': 'pointinghand',
        'wait': 'spinning',
        'stretch_vert': 'resizeupdown',
        'stretch_horiz': 'resizeleftright',
        'move_item': 'plus',
        'destroy_item': 'poof',
        'invalid_drag': 'notallowed',
    }

    def add_mousewheel(target, *frames, orient='y'):
        """Add events so scrolling anywhere in a frame will scroll a target.

        frame should be a sequence of any TK objects, like a Toplevel or Frame.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - OS X needs the delta value passed unmodified.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def mousewheel_handler(event):
            scroll_func(-event.delta, "units")
        for frame in frames:
            frame.bind('<MouseWheel>', mousewheel_handler, add='+')
elif LINUX:
    EVENTS = {
        'LEFT': '<Button-1>',
        'LEFT_DOUBLE': '<Double-Button-1>',
        'LEFT_CTRL': '<Control-Button-1>',
        'LEFT_SHIFT': '<Shift-Button-1>',
        'LEFT_RELEASE': '<ButtonRelease-1>',
        'LEFT_MOVE': '<B1-Motion>',

        'RIGHT': '<Button-3>',
        'RIGHT_DOUBLE': '<Double-Button-3>',
        'RIGHT_CTRL': '<Control-Button-3>',
        'RIGHT_SHIFT': '<Shift-Button-3>',
        'RIGHT_RELEASE': '<ButtonRelease-3>',
        'RIGHT_MOVE': '<B3-Motion>',

        'KEY_EXPORT': '<Control-e>',
        'KEY_SAVE_AS': '<Control-s>',
        'KEY_SAVE': '<Control-Shift-s>',
    }
    KEY_ACCEL = {
        'KEY_EXPORT': 'Ctrl-E',
        'KEY_SAVE': 'Ctrl-S',
        'KEY_SAVE_AS': 'Ctrl-Shift-S',
    }

    CURSORS = {
        'regular': 'arrow',
        'link': 'hand2',
        'wait': 'watch',
        'stretch_vert': 'sb_v_double_arrow',
        'stretch_horiz': 'sb_h_double_arrow',
        'move_item': 'plus',
        'destroy_item': 'x_cursor',
        'invalid_drag': 'no',
    }

    def add_mousewheel(target, *frames, orient='y'):
        """Add events so scrolling anywhere in a frame will scroll a target.

        frame should be a sequence of any TK objects, like a Toplevel or Frame.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - Linux uses Button-4 and Button-5 events instead of
        a MouseWheel event.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def scroll_up(_):
            scroll_func(-1, "units")

        def scroll_down(_):
            scroll_func(1, "units")

        for frame in frames:
            frame.bind('<Button-4>', scroll_up, add='+')
            frame.bind('<Button-5>', scroll_down, add='+')

if MAC:
    # On OSX, make left-clicks switch to a rightclick when control is held.
    def bind_leftclick(wid, func, add='+'):
        """On OSX, left-clicks are converted to right-clicks

        when control is held.
        """
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func()
        wid.bind(EVENTS['LEFT'], event_handler, add=add)

    def bind_leftclick_double(wid, func, add='+'):
        """On OSX, left-clicks are converted to right-clicks

        when control is held."""
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func()
        wid.bind(EVENTS['LEFT_DOUBLE'], event_handler, add=add)

    def bind_rightclick(wid, func):
        """On OSX, we need to bind to both rightclick and control-leftclick."""
        wid.bind(EVENTS['RIGHT'], func)
        wid.bind(EVENTS['LEFT_CTRL'], func)
else:
    def bind_leftclick(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT'], func, add=add)

    def bind_leftclick_double(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT_DOUBLE'], func, add=add)

    def bind_rightclick(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['RIGHT'], func, add=add)

USE_SIZEGRIP = not MAC  # On Mac, we don't want to use the sizegrip widget


class CONN_TYPES(Enum):
    """Possible connections when joining things together.

    Used for things like catwalks, and bottomless pit sides.
    """
    none = 0
    side = 1  # Points E
    straight = 2  # Points E-W
    corner = 3  # Points N-W
    triple = 4  # Points N-S-W
    all = 5  # Points N-S-E-W

N = "0 90 0"
S = "0 270 0"
E = "0 0 0"
W = "0 180 0"
# Lookup values for joining things together.
CONN_LOOKUP = {
    # N S  E  W : (Type, Rotation)
    (1, 0, 0, 0): (CONN_TYPES.side, N),
    (0, 1, 0, 0): (CONN_TYPES.side, S),
    (0, 0, 1, 0): (CONN_TYPES.side, E),
    (0, 0, 0, 1): (CONN_TYPES.side, W),

    (1, 1, 0, 0): (CONN_TYPES.straight, S),
    (0, 0, 1, 1): (CONN_TYPES.straight, E),

    (0, 1, 0, 1): (CONN_TYPES.corner, N),
    (1, 0, 1, 0): (CONN_TYPES.corner, S),
    (1, 0, 0, 1): (CONN_TYPES.corner, E),
    (0, 1, 1, 0): (CONN_TYPES.corner, W),

    (0, 1, 1, 1): (CONN_TYPES.triple, N),
    (1, 0, 1, 1): (CONN_TYPES.triple, S),
    (1, 1, 0, 1): (CONN_TYPES.triple, E),
    (1, 1, 1, 0): (CONN_TYPES.triple, W),

    (1, 1, 1, 1): (CONN_TYPES.all, E),

    (0, 0, 0, 0): (CONN_TYPES.none, E),
}

del N, S, E, W


def get_indent(line: str):
    """Return the whitespace which this line starts with.

    """
    white = []
    for char in line:
        if char in ' \t':
            white.append(char)
        else:
            return ''.join(white)


def iter_grid(
        max_x: int,
        max_y: int,
        min_x: int=0,
        min_y: int=0,
        stride: int=1,
        ) -> Iterator[Tuple[int, int]]:
    """Loop over a rectangular grid area."""
    for x in range(min_x, max_x, stride):
        for y in range(min_y, max_y, stride):
            yield x, y


DISABLE_ADJUST = False


def adjust_inside_screen(x, y, win, horiz_bound=14, vert_bound=45):
    """Adjust a window position to ensure it fits inside the screen."""
    if DISABLE_ADJUST:  # Allow disabling this adjustment
        return x, y     # for multi-window setups
    max_x = win.winfo_screenwidth() - win.winfo_width() - horiz_bound
    max_y = win.winfo_screenheight() - win.winfo_height() - vert_bound

    if x < horiz_bound:
        x = horiz_bound
    elif x > max_x:
        x = max_x

    if y < vert_bound:
        y = vert_bound
    elif y > max_y:
        y = max_y
    return x, y


def center_win(window, parent=None):
    """Center a subwindow to be inside a parent window."""
    if parent is None:
        parent = window.nametowidget(window.winfo_parent())

    x = parent.winfo_rootx() + (parent.winfo_width()-window.winfo_width())//2
    y = parent.winfo_rooty() + (parent.winfo_height()-window.winfo_height())//2

    x, y = adjust_inside_screen(x, y, window)

    window.geometry('+' + str(x) + '+' + str(y))


def append_bothsides(deq):
    """Alternately add to each side of a deque."""
    while True:
        deq.append((yield))
        deq.appendleft((yield))


def fit(dist, obj):
    """Figure out the smallest number of parts to stretch a distance."""
    # If dist is a float the outputs will become floats as well
    # so ensure it's an int.
    dist = int(dist)
    if dist <= 0:
        return []
    orig_dist = dist
    smallest = obj[-1]
    items = collections.deque()

    # We use this so the small sections appear on both sides of the area.
    adder = append_bothsides(items)
    next(adder)
    while dist >= smallest:
        for item in obj:
            if item <= dist:
                adder.send(item)
                dist -= item
                break
    if dist > 0:
        adder.send(dist)

    assert sum(items) == orig_dist
    return list(items)  # Dump the deque


def restart_app():
    """Restart this python application.

    This will not return!
    """
    import os, sys
    # sys.executable is the program which ran us - when frozen,
    # it'll our program.
    # We need to add the program to the arguments list, since python
    # strips that off.
    args = [sys.executable] + sys.argv
    getLogger(__name__).info(
        'Restarting using "{}", with args {!r}',
        sys.executable,
        args,
    )
    logging.shutdown()
    os.execv(sys.executable, args)


def set_readonly(file):
    """Make the given file read-only."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it read-only
    os.chmod(
        file,
        flags & ~
        stat.S_IWUSR & ~
        stat.S_IWGRP & ~
        stat.S_IWOTH
    )


def unset_readonly(file):
    """Set the writeable flag on a file."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it writeable
    os.chmod(
        file,
        flags |
        stat.S_IWUSR |
        stat.S_IWGRP |
        stat.S_IWOTH
    )

class LogMessage:
    """Allow using str.format() in logging messages.

    The __str__() method performs the joining.
    """
    def __init__(self, fmt, args, kwargs):
        self.fmt = fmt
        self.args = args
        self.kwargs = kwargs
        self.has_args = kwargs or args

    def format_msg(self):
        # Only format if we have arguments!
        # That way { or } can be used in regular messages.
        if self.has_args:
            f = self.fmt = str(self.fmt).format(*self.args, **self.kwargs)

            # Don't repeat the formatting
            del self.args, self.kwargs
            self.has_args = False
            return f
        else:
            return str(self.fmt)

    def __str__(self):
        """Format the string, and add an ASCII indent."""
        msg = self.format_msg()

        if '\n' not in msg:
            return msg

        # For multi-line messages, add an indent so they're associated
        # with the logging tag.
        lines = msg.split('\n')
        if lines[-1].isspace():
            # Strip last line if it's blank
            del lines[-1]
        # '|' beside all the lines, '|_ beside the last. Add an empty
        # line at the end.
        return '\n | '.join(lines[:-1]) + '\n |_' + lines[-1] + '\n'


class LoggerAdapter(logging.LoggerAdapter):
    """Fix loggers to use str.format().

    """
    def __init__(self, logger: logging.Logger, alias=None):
        # Alias is a replacement module name for log messages.
        self.alias = alias
        super(LoggerAdapter, self).__init__(logger, extra={})

    def log(self, level, msg, *args, exc_info=None, stack_info=False, **kwargs):
        """This version of .log() is for str.format() compatibility.

        The message is wrapped in a LogMessage object, which is given the
        args and kwargs
        """
        if self.isEnabledFor(level):
            self.logger._log(
                level,
                LogMessage(msg, args, kwargs),
                (), # No positional arguments, we do the formatting through
                # LogMessage..
                # Pull these two arguments out of kwargs, so they can be set..
                exc_info=exc_info,
                stack_info=stack_info,
                extra={'alias': self.alias},
            )

class NewLogRecord(logging.getLogRecordFactory()):
    """Allow passing an alias for log modules."""

    def getMessage(self):
        """We have to hook here to change the value of .module.

        It's called just before the formatting call is made.
        """
        if self.alias is not None:
            self.module = self.alias
        return str(self.msg)
logging.setLogRecordFactory(NewLogRecord)


def init_logging(filename: str=None) -> logging.Logger:
    """Setup the logger and logging handlers.

    If filename is set, all logs will be written to this file.
    """
    global short_log_format, long_log_format
    global stderr_loghandler, stdout_loghandler, file_loghandler
    import logging
    from logging import handlers
    import sys, io, os

    logger = logging.getLogger('BEE2')
    logger.setLevel(logging.DEBUG)

    # Put more info in the log file, since it's not onscreen.
    long_log_format = logging.Formatter(
        '[{levelname}] {module}.{funcName}(): {message}',
        style='{',
    )
    # Console messages, etc.
    short_log_format = logging.Formatter(
        # One letter for level name
        '[{levelname[0]}] {module}: {message}',
        style='{',
    )

    if filename is not None:
        # Make the directories the logs are in, if needed.
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        # The log contains DEBUG and above logs.
        # We rotate through logs of 500kb each, so it doesn't increase too much.
        log_handler = handlers.RotatingFileHandler(
            filename,
            maxBytes=500 * 1024,
            backupCount=10,
        )
        log_handler.setLevel(logging.DEBUG)
        log_handler.setFormatter(long_log_format)

        logger.addHandler(log_handler)

    # This is needed for multiprocessing, since it tries to flush stdout.
    # That'll fail if it is None.
    class NullStream(io.IOBase):
        """A stream object that discards all data."""
        def __init__(self):
            super(NullStream, self).__init__()

        @staticmethod
        def write(self, *args, **kwargs):
            pass

        @staticmethod
        def read(*args, **kwargs):
            return ''

    if sys.stdout:
        stdout_loghandler = logging.StreamHandler(sys.stdout)
        stdout_loghandler.setLevel(logging.INFO)
        stdout_loghandler.setFormatter(short_log_format)
        logger.addHandler(stdout_loghandler)

        if sys.stderr:
            def ignore_warnings(record: logging.LogRecord):
                """Filter out messages higher than WARNING.

                Those are handled by stdError, and we don't want duplicates.
                """
                return record.levelno < logging.WARNING
            stdout_loghandler.addFilter(ignore_warnings)
    else:
        sys.stdout = NullStream()

    if sys.stderr:
        stderr_loghandler = logging.StreamHandler(sys.stderr)
        stderr_loghandler.setLevel(logging.WARNING)
        stderr_loghandler.setFormatter(short_log_format)
        logger.addHandler(stderr_loghandler)
    else:
        sys.stderr = NullStream()

    # Use the exception hook to report uncaught exceptions, and finalise the
    # logging system.
    old_except_handler = sys.__excepthook__

    def except_handler(*exc_info):
        """Log uncaught exceptions."""
        logger._log(
            level=logging.ERROR,
            msg='Uncaught Exception:',
            args=(),
            exc_info=exc_info,
        )
        logging.shutdown()
        # Call the original handler - that prints to the normal console.
        old_except_handler()

    sys.__excepthook__ = except_handler

    return LoggerAdapter(logger)


def getLogger(name: str='', alias: str=None) -> logging.Logger:
    """Get the named logger object.

    This puts the logger into the BEE2 namespace, and wraps it to
    use str.format() instead of % formatting.
    If set, alias is the name to show for the module.
    """
    if name:
        return LoggerAdapter(logging.getLogger('BEE2.' + name), alias)
    else:  # Allow retrieving the main logger.
        return LoggerAdapter(logging.getLogger('BEE2'), alias)


class AtomicWriter:
    """Atomically overwrite a file.

    Use as a context manager - the returned temporary file
    should be written to. When cleanly exiting, the file will be transfered.
    If an exception occurs in the body, the temporary data will be discarded.

    This is not reentrant, but can be repeated - starting the context manager
    clears the file.
    """
    def __init__(self, filename, is_bytes=False):
        """Create an AtomicWriter.
        is_bytes sets text or bytes writing mode. The file is always writable.
        """
        self.filename = filename
        self.dir = os.path.dirname(filename)
        self.is_bytes = is_bytes
        self.temp = None

    def make_tempfile(self):
        """Create the temporary file object."""
        if self.temp is not None:
            # Already open - close and delete the current file.
            self.temp.close()
            os.remove(self.temp.name)

        # Create folders if needed..
        os.makedirs(self.dir, exist_ok=True)

        self.temp = tempfile.NamedTemporaryFile(
            mode='wb' if self.is_bytes else 'wt',
            dir=self.dir,
            delete=False,
        )

    def __enter__(self):
        """Delagate to the underlying temporary file handler."""
        self.make_tempfile()
        return self.temp.__enter__()

    def __exit__(self, exc_type, exc_value, tback):
        # Pass to tempfile, which also closes().
        temp_path = self.temp.name
        self.temp.__exit__(exc_type, exc_value, tback)
        self.temp = None
        if exc_type is not None:
            # An exception occured, clean up.
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
        else:
            # No exception, commit changes
            os.replace(temp_path, self.filename)

        return False  # Don't cancel the exception.
