"""
General code used for tkinter portions.

"""
import functools
from enum import Enum
from typing import overload, cast, Any, TypeVar, Protocol, Union, Callable, Optional, Literal

from tkinter import ttk
from tkinter import font as _tk_font
from tkinter import filedialog, commondialog, simpledialog
import tkinter as tk
import os.path

from app import TK_ROOT

try:
    # Python 3.6+
    # noinspection PyCompatibility
    from idlelib.redirector import WidgetRedirector
    from idlelib.query import Query
except ImportError:
    # Python 3.5 and below
    # noinspection PyCompatibility, PyUnresolvedReferences
    from idlelib.WidgetRedirector import WidgetRedirector
    Query = None


import utils


# Set icons for the application.

ICO_PATH = str(utils.install_path('BEE2.ico'))

if utils.WIN:
    # Ensure everything has our icon (including dialogs)
    TK_ROOT.wm_iconbitmap(default=ICO_PATH)

    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]):
        """Set the window icon."""
        window.wm_iconbitmap(ICO_PATH)

    import ctypes
    # Use Windows APIs to tell the taskbar to group us as our own program,
    # not with python.exe. Then our icon will apply, and also won't group
    # with other scripts.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'BEEMOD.application',
        )
    except (AttributeError, WindowsError, ValueError):
        pass  # It's not too bad if it fails.

    LISTBOX_BG_SEL_COLOR = '#0078D7'
    LISTBOX_BG_COLOR = 'white'
elif utils.MAC:
    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]):
        """ Call OS-X's specific api for setting the window icon."""
        TK_ROOT.tk.call(
            'tk::mac::iconBitmap',
            window,
            256,  # largest size in the .ico
            256,
            '-imageFile',
            ICO_PATH,
        )

    set_window_icon(TK_ROOT)

    LISTBOX_BG_SEL_COLOR = '#C2DDFF'
    LISTBOX_BG_COLOR = 'white'
else:  # Linux
    # Get the tk image object.
    from app import img
    app_icon = img.get_app_icon(ICO_PATH)

    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]):
        """Set the window icon."""
        # Weird argument order for default=True...
        window.wm_iconphoto(True, app_icon)

    LISTBOX_BG_SEL_COLOR = 'blue'
    LISTBOX_BG_COLOR = 'white'


# Some events differ on different systems, so define them here.
if utils.MAC:
    KEY_EXPORT = '<Command-e>'
    KEY_SAVE = '<Command-s>'
    KEY_SAVE_AS = '<Command-Shift-s>'

    # tkinter replaces Command- with the special symbol automatically.
    ACCEL_EXPORT = 'Command-E'
    ACCEL_SAVE = 'Command-S'
    ACCEL_SAVE_AS = 'Command-Shift-S'
else:
    KEY_EXPORT = '<Control-e>'
    KEY_SAVE = '<Control-s>'
    KEY_SAVE_AS = '<Control-Shift-s>'

    # The text used to show shortcuts in menus.
    ACCEL_EXPORT = 'Ctrl-E'
    ACCEL_SAVE = 'Ctrl-S'
    ACCEL_SAVE_AS = 'Ctrl-Shift-S'

USE_SIZEGRIP = not utils.MAC  # On Mac, we don't want to use the sizegrip widget.

if utils.WIN:
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
    }
elif utils.MAC:
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
    }
elif utils.LINUX:
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
    }
else:
    raise AssertionError

if utils.WIN:
    class Cursors(str, Enum):
        """Cursors we use, mapping to the relevant OS cursor."""
        REGULAR = 'arrow'
        LINK = 'hand2'
        WAIT = 'watch'
        STRETCH_VERT = 'sb_v_double_arrow'
        STRETCH_HORIZ = 'sb_h_double_arrow'
        MOVE_ITEM = 'plus'
        DESTROY_ITEM = 'x_cursor'
        INVALID_DRAG = 'no'
elif utils.MAC:
    class Cursors(str, Enum):
        """Cursors we use, mapping to the relevant OS cursor."""
        REGULAR = 'arrow'
        LINK = 'pointinghand'
        WAIT = 'spinning'
        STRETCH_VERT = 'resizeupdown'
        STRETCH_HORIZ = 'resizeleftright'
        MOVE_ITEM = 'plus'
        DESTROY_ITEM = 'poof'
        INVALID_DRAG = 'notallowed'
elif utils.LINUX:
    class Cursors(str, Enum):
        """Cursors we use, mapping to the relevant OS cursor."""
        REGULAR = 'arrow'
        LINK = 'hand1'
        WAIT = 'watch'
        STRETCH_VERT = 'bottom_side'
        STRETCH_HORIZ = 'right_side'
        MOVE_ITEM = 'crosshair'
        DESTROY_ITEM = 'X_cursor'
        INVALID_DRAG = 'circle'
else:
    raise AssertionError


@overload
def add_mousewheel(target: tk.XView, *frames: tk.Misc, orient: Literal['x']) -> None: """..."""
@overload
def add_mousewheel(target: tk.YView, *frames: tk.Misc, orient: Literal['y']='y') -> None: """..."""

if utils.WIN:
    def add_mousewheel(target: Union[tk.XView, tk.YView], *frames: tk.Misc, orient: Literal['x', 'y']='y') -> None:
        """Add events so scrolling anywhere in a frame will scroll a target.

        frames should be the TK objects to bind to - mainly Frame or
        Toplevel objects.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - Windows needs the delta value to be divided by 120.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def mousewheel_handler(event: tk.Event) -> None:
            """Handle mousewheel events."""
            scroll_func(int(event.delta / -120), "units")
        for frame in frames:
            frame.bind('<MouseWheel>', mousewheel_handler, add=True)
elif utils.MAC:
    def add_mousewheel(target: Union[tk.XView, tk.YView], *frames: tk.Misc, orient: Literal['x', 'y']='y') -> None:
        """Add events so scrolling anywhere in a frame will scroll a target.

        frame should be a sequence of any TK objects, like a Toplevel or Frame.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - OS X needs the delta value passed unmodified.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def mousewheel_handler(event: tk.Event) -> None:
            """Handle mousewheel events."""
            scroll_func(-event.delta, "units")
        for frame in frames:
            frame.bind('<MouseWheel>', mousewheel_handler, add=True)
elif utils.LINUX:
    def add_mousewheel(target: Union[tk.XView, tk.YView], *frames: tk.Misc, orient: Literal['x', 'y']='y') -> None:
        """Add events so scrolling anywhere in a frame will scroll a target.

        frame should be a sequence of any TK objects, like a Toplevel or Frame.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - Linux uses Button-4 and Button-5 events instead of
        a MouseWheel event.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def scroll_up(event: tk.Event) -> None:
            """Handle scrolling up."""
            scroll_func(-1, "units")

        def scroll_down(event: tk.Event) -> None:
            """Handle scrolling down."""
            scroll_func(1, "units")

        for frame in frames:
            frame.bind('<Button-4>', scroll_up, add=True)
            frame.bind('<Button-5>', scroll_down, add=True)


EventFuncT = TypeVar('EventFuncT', bound=Callable[[tk.Event], Any])


class _Binder(Protocol):
    @overload
    def __call__(self, wid: tk.Misc, add: bool=False) -> Callable[[EventFuncT], EventFuncT]:
        pass
    @overload
    def __call__(self, wid: tk.Misc, func: EventFuncT, add: bool=False) -> str:
        pass
    def __call__(self, wid: tk.Misc, func: Optional[EventFuncT]=None, add: bool=False):
        pass


def _bind_event_handler(bind_func: Callable[[tk.Misc, EventFuncT, bool], None]) -> _Binder:
    """Decorator for the bind_click functions.

    This allows calling directly, or decorating a function with just wid and add
    attributes.
    """
    def deco(wid, func=None, add=False):
        """Decorator or normal interface, func is optional to be a decorator."""
        if func is None:
            def deco_2(func):
                """Used as a decorator - must be called second with the function."""
                bind_func(wid, func, add)
                return func
            return deco_2
        else:
            # Normally, call directly
            return bind_func(wid, func, add)
    return functools.update_wrapper(cast(_Binder, deco), bind_func)

if utils.MAC:
    # On OSX, make left-clicks switch to a rightclick when control is held.
    @_bind_event_handler
    def bind_leftclick(wid, func, add=False):
        """On OSX, left-clicks are converted to right-clicks

        when control is held.
        """
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func(e)
        wid.bind(EVENTS['LEFT'], event_handler, add=add)

    @_bind_event_handler
    def bind_leftclick_double(wid, func, add=False):
        """On OSX, left-clicks are converted to right-clicks

        when control is held."""
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func(e)
        wid.bind(EVENTS['LEFT_DOUBLE'], event_handler, add=add)

    @_bind_event_handler
    def bind_rightclick(wid, func, add=False):
        """On OSX, we need to bind to both rightclick and control-leftclick."""
        wid.bind(EVENTS['RIGHT'], func, add=add)
        wid.bind(EVENTS['LEFT_CTRL'], func, add=add)
else:
    @_bind_event_handler
    def bind_leftclick(wid, func, add=False):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT'], func, add=add)

    @_bind_event_handler
    def bind_leftclick_double(wid, func, add=False):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT_DOUBLE'], func, add=add)

    @_bind_event_handler
    def bind_rightclick(wid, func, add=False):
        """Other systems just bind directly."""
        wid.bind(EVENTS['RIGHT'], func, add=add)


def event_cancel(*args, **kwargs) -> str:
    """Bind to an event to cancel it, and prevent it from propagating."""
    return 'break'


class QueryShim(simpledialog._QueryString):
    """Replicate the new API with the old simpledialog code."""
    def __init__(self, parent, title, message, text0):
        super().__init__(title, message, initialvalue=text0, parent=parent)

    def body(self, master):
        """Ensure the window icon is changed."""
        super().body(master)
        set_window_icon(self)


def prompt(
    title: str, message: str,
    initialvalue: str='',
    parent: tk.Misc= TK_ROOT,
) -> Optional[str]:
    """Ask the user to enter a string."""
    from loadScreen import suppress_screens
    from app import _main_loop_running
    with suppress_screens():
        # If the main loop isn't running, this doesn't work correctly.
        # Probably also if it's not visible. So swap back to the old style.
        # It's also only a problem on Windows.
        if Query is None or (utils.WIN and (
            not _main_loop_running or not TK_ROOT.winfo_viewable()
        )):
            query_cls = QueryShim
        else:
            query_cls = Query
        return query_cls(
            parent,
            title, message,
            text0=initialvalue,
        ).result


class HidingScroll(ttk.Scrollbar):
    """A scrollbar variant which auto-hides when not needed.

    """
    def set(self, low, high):
        """Set the size needed for the scrollbar, and hide/show if needed."""
        if float(low) <= 0.0 and float(high) >= 1.0:
            # Remove this, but remember gridding options
            self.grid_remove()
        else:
            self.grid()
        super(HidingScroll, self).set(low, high)


class ReadOnlyEntry(ttk.Entry):
    """A modified Entry widget which prevents editing the text.

    See http://tkinter.unpythonic.net/wiki/ReadOnlyText
    """
    def __init__(self, master, **opt):

        opt['exportselection'] = 0 # Don't let it write to clipboard
        opt['takefocus'] = 0 # Ignore when tabbing
        super().__init__(master, **opt)

        self.redirector = redir = WidgetRedirector(self)
        # These two TK commands are used for all text operations,
        # so cancelling them stops anything from happening.
        self.insert = redir.register('insert', event_cancel)
        self.delete = redir.register('delete', event_cancel)


class ttk_Spinbox(ttk.Widget, tk.Spinbox):
    """This is missing from ttk, but still exists."""
    def __init__(self, master: tk.Misc, range: Union[range, slice]=None, **kw) -> None:
        """Initialise a spinbox.
        Arguments:
            range: The range buttons will run in
            values: A list of values to use
            wrap: Whether to loop at max/min
            format: A specifier of the form ' %<pad>.<pad>f'
            command: A command to run whenever the value changes
        """
        if range is not None:
            kw['from'] = range.start
            kw['to'] = range.stop
            kw['increment'] = range.step
            if 'width' not in kw:
                kw['width'] = len(str(range.stop)) + 1

        self.old_val = kw.get('from', '0')
        kw['validate'] = 'all'
        kw['validatecommand'] = self.validate

        ttk.Widget.__init__(self, master, 'ttk::spinbox', kw)

    @property
    def value(self) -> int:
        """Get the value of the spinbox."""
        return self.tk.call(self._w, 'get')

    @value.setter
    def value(self, value: int) -> None:
        """Set the spinbox to a value."""
        self.tk.call(self._w, 'set', value)

    def validate(self) -> bool:
        """Values must be integers."""
        try:
            self.old_val = int(self.value)
            return True
        except ValueError:
            self.value = str(self.old_val)
            return False

_file_field_font = _tk_font.nametofont('TkFixedFont')  # Monospaced font
_file_field_char_len = _file_field_font.measure('x')


class FileField(ttk.Frame):
    """A text box which allows searching for a file or directory.
    """
    browser: commondialog.Dialog
    def __init__(
        self,
        master,
        is_dir: bool=False,
        loc: str='',
        callback: Callable[[str], None]=None,
    ) -> None:
        """Initialise the field.

        - Set is_dir to true to look for directories, instead of files.
        - width sets the number of characters to display.
        - callback is a function to be called with the new path whenever it
          changes.
        """
        from app.tooltip import add_tooltip

        super(FileField, self).__init__(master)

        self._location = loc
        self.is_dir = is_dir

        self._text_var = tk.StringVar(master=self, value='')
        if is_dir:
            self.browser = filedialog.Directory(
                self,
                initialdir=loc,
            )
        else:
            self.browser = filedialog.SaveAs(
                self,
                initialdir=loc,
            )

        if callback is None:
            callback = self._nop_callback

        self.callback = callback

        self.textbox = ReadOnlyEntry(
            self,
            textvariable=self._text_var,
            font=_file_field_font,
            cursor=Cursors.REGULAR,
        )
        self.textbox.grid(row=0, column=0, sticky='ew')
        self.columnconfigure(0, weight=1)
        bind_leftclick(self.textbox, self.browse)
        # The full location is displayed in a tooltip.
        add_tooltip(self.textbox, self._location)
        self.textbox.bind('<Configure>', self._text_configure)

        self.browse_btn = ttk.Button(
            self,
            text="...",
            width=1.5,
            command=self.browse,
        )
        self.browse_btn.grid(row=0, column=1)

        self._text_var.set(self._truncate(loc))

    def browse(self, event: tk.Event=None) -> None:
        """Browse for a file."""
        path = self.browser.show()
        if path:
            self.value = path

    @staticmethod  # No need to bind to a method.
    def _nop_callback(path: str) -> None:
        """Callback function, called whenever the value changes."""
        pass

    @property
    def value(self) -> str:
        """Get the current path."""
        return self._location

    @value.setter
    def value(self, path: str) -> None:
        """Set the current path. This calls the callback function."""
        from app import tooltip
        self.callback(path)
        self._location = path
        tooltip.set_tooltip(self, path)
        self._text_var.set(self._truncate(path))

    def _truncate(self, path: str) -> str:
        """Truncate the path to the end portion."""
        self.textbox.update_idletasks()
        wid = (self.textbox.winfo_width() // _file_field_char_len) - 3

        if wid <= 4:  # No room from text
            return '...'

        if not self.is_dir:
            path = os.path.basename(path)

        if len(path) > wid + 2:
            return '...' + path[-(wid - 1):]
        else:
            return path

    def _text_configure(self, e: tk.Event) -> None:
        """Truncate text every time the text widget resizes."""
        self._text_var.set(self._truncate(self._location))
