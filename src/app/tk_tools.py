"""
General code used for tkinter portions.

"""
import functools
import inspect
import sys
from enum import Enum
from typing import (
    Awaitable, Dict, Generic, Iterable, overload, cast, Any, TypeVar, Protocol, Union, Callable,
    Optional,
    Tuple, Literal,
)
from typing_extensions import TypeAlias, TypeVarTuple, Unpack

from tkinter import ttk
from tkinter import font as _tk_font
from tkinter import filedialog, commondialog, messagebox
import tkinter as tk
import os.path

from srctools import logger
from idlelib.redirector import WidgetRedirector  # type: ignore[import-not-found]
import trio

from app import TK_ROOT, background_run
from config.gen_opts import GenOptions
import event
import config
import utils
from transtoken import TransToken
from ui_tk.wid_transtoken import set_text


LOGGER = logger.get_logger(__name__)
ICO_PATH = str(utils.bins_path('BEE2.ico'))
T = TypeVar('T')
AnyWidT = TypeVar('AnyWidT', bound=tk.Misc)
WidgetT = TypeVar('WidgetT', bound=tk.Widget)
EventFunc: TypeAlias = Callable[[tk.Event[AnyWidT]], object]
EventFuncT = TypeVar('EventFuncT', bound=EventFunc[tk.Misc])


if utils.WIN:
    # Ensure everything has our icon (including dialogs)
    TK_ROOT.wm_iconbitmap(default=ICO_PATH)

    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]) -> None:
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
    except (AttributeError, OSError, ValueError):
        pass  # It's not too bad if it fails.

    LISTBOX_BG_SEL_COLOR = '#0078D7'
    LISTBOX_BG_COLOR = 'white'
    LABEL_HIGHLIGHT_BG = '#5AD2D2'
elif utils.MAC:
    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]) -> None:
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
    LABEL_HIGHLIGHT_BG = '#5AD2D2'
else:  # Linux
    # Get the tk image object.
    from ui_tk.img import get_app_icon
    app_icon = get_app_icon(ICO_PATH)

    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]) -> None:
        """Set the window icon."""
        # Weird argument order for default=True...
        window.wm_iconphoto(True, app_icon)

    LISTBOX_BG_SEL_COLOR = 'blue'
    LISTBOX_BG_COLOR = 'white'
    LABEL_HIGHLIGHT_BG = '#5AD2D2'

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
        ZOOM_IN = 'size_nw_se'
        STRETCH_VERT = 'sb_v_double_arrow'
        STRETCH_HORIZ = 'sb_h_double_arrow'
        MOVE_ITEM = 'fleur'
        DESTROY_ITEM = 'x_cursor'
        INVALID_DRAG = 'no'

        def __str__(self) -> str:
            """Allow passing to tkinter."""
            return self.value
elif utils.MAC:
    class Cursors(str, Enum):  # type: ignore
        """Cursors we use, mapping to the relevant OS cursor."""
        REGULAR = 'arrow'
        LINK = 'pointinghand'
        WAIT = 'spinning'
        ZOOM_IN = 'zoom-in'
        STRETCH_VERT = 'resizeupdown'
        STRETCH_HORIZ = 'resizeleftright'
        MOVE_ITEM = 'movearrow'
        DESTROY_ITEM = 'poof'
        INVALID_DRAG = 'notallowed'

        def __str__(self) -> str:
            """Allow passing to tkinter."""
            return self.value
elif utils.LINUX:
    class Cursors(str, Enum):  # type: ignore
        """Cursors we use, mapping to the relevant OS cursor."""
        REGULAR = 'arrow'
        LINK = 'hand1'
        WAIT = 'watch'
        ZOOM_IN = 'sizing'
        STRETCH_VERT = 'bottom_side'
        STRETCH_HORIZ = 'right_side'
        MOVE_ITEM = 'fleur'
        DESTROY_ITEM = 'X_cursor'
        INVALID_DRAG = 'circle'

        def __str__(self) -> str:
            """Allow passing to tkinter."""
            return self.value
else:
    raise AssertionError

_cur_update: Optional[trio.Event] = None


@TK_ROOT.register
def _update_complete() -> None:
    """Set the event, after the event loop has run."""
    global _cur_update
    if _cur_update is not None:
        _cur_update.set()
        _cur_update = None


async def wait_eventloop() -> None:
    """Wait until the next iteration of the TK event loop.

    This ensures widget dimensions are correct.
    """
    global _cur_update
    if _cur_update is None:
        _cur_update = trio.Event()
        TK_ROOT.tk.call('after', 'idle', _update_complete)
    await _cur_update.wait()


PosArgsT = TypeVarTuple('PosArgsT')


def bind_mousewheel(
    widgets: Union[Iterable[tk.Misc], tk.Misc],
    func: Callable[[int, Unpack[PosArgsT]], object],
    *args: Unpack[PosArgsT],
) -> None:
    """Bind mousewheel events, which function differently on each platform.

     The delta value is prepended to args, then the function is called.
     - Windows needs the delta value to be divided by 120.
     - OS X needs the delta value passed unmodified.
      - Linux uses Button-4 and Button-5 events instead of
        a MouseWheel event.
    """
    if isinstance(widgets, tk.Misc):
        widgets = [widgets]

    if utils.WIN:
        def mousewheel_handler(event: tk.Event[tk.Misc]) -> None:
            """Handle mousewheel events."""
            func(int(event.delta / -120), *args)
        for widget in widgets:
            widget.bind('<MouseWheel>', mousewheel_handler, add=True)
    elif utils.MAC:
        def mousewheel_handler(event: tk.Event[tk.Misc]) -> None:
            """Handle mousewheel events."""
            func(-event.delta, *args)
        for widget in widgets:
            widget.bind('<MouseWheel>', mousewheel_handler, add=True)
    elif utils.LINUX:
        def scroll_up(_: tk.Event[tk.Misc]) -> None:
            """Handle scrolling up."""
            func(-1, *args)

        def scroll_down(_: tk.Event[tk.Misc]) -> None:
            """Handle scrolling down."""
            func(1, *args)

        for widget in widgets:
            widget.bind('<Button-4>', scroll_up, add=True)
            widget.bind('<Button-5>', scroll_down, add=True)
    else:
        raise AssertionError('Unknown platform ' + sys.platform)


@overload
def add_mousewheel(target: tk.XView, *frames: tk.Misc, orient: Literal['x']) -> None: ...
@overload
def add_mousewheel(target: tk.YView, *frames: tk.Misc, orient: Literal['y']='y') -> None: ...
def add_mousewheel(target: Union[tk.XView, tk.YView], *frames: tk.Misc, orient: Literal['x', 'y']='y') -> None:
    """Add events so scrolling anywhere in a frame will scroll a target.

    frames should be the TK objects to bind to - mainly Frame or
    Toplevel objects.
    Set orient to 'x' or 'y'.
    """
    scroll_func = getattr(target, orient + 'view_scroll')
    # Call view_scroll(delta, "units").
    bind_mousewheel(frames, scroll_func, 'units', )


def make_handler(func: Union[
    Callable[[], Awaitable[object]],
    Callable[[tk.Event[tk.Misc]], Awaitable[object]],
]) -> Callable[[tk.Event[tk.Misc]], object]:
    """Given an asyncronous event handler, return a sync function which uses background_run().

    This checks the signature of the function to decide whether to pass along the event object.
    """
    sig = inspect.signature(func)
    if len(sig.parameters) == 0:
        def wrapper(e: tk.Event[tk.Misc]) -> None:
            """Discard the event."""
            background_run(func)  # type: ignore
    else:
        def wrapper(e: tk.Event[tk.Misc]) -> None:
            """Pass along the event."""
            background_run(func, e)  # type: ignore
    functools.update_wrapper(wrapper, func)
    return wrapper


class _EventDeco(Protocol[AnyWidT]):
    def __call__(self, func: EventFunc[AnyWidT], /) -> EventFunc[AnyWidT]:
        ...


class _Binder(Protocol):
    @overload
    def __call__(self, wid: WidgetT, *, add: bool=False) -> _EventDeco[WidgetT]: ...  # type: ignore[overload-overlap]
    @overload
    def __call__(self, wid: tk.Misc, *, add: bool=False) -> _EventDeco[tk.Misc]: ...
    @overload
    def __call__(self, wid: WidgetT, func: EventFunc[WidgetT], *, add: bool=False) -> str: ...
    @overload
    def __call__(self, wid: tk.Misc, func: EventFunc[tk.Misc], *, add: bool=False) -> str: ...


def _bind_event_handler(bind_func: Callable[[WidgetT, EventFunc[WidgetT], bool], None]) -> _Binder:
    """Decorator for the bind_click functions.

    This allows calling directly, or decorating a function with just wid and add
    attributes.
    """
    @functools.wraps(bind_func)
    def deco(wid: WidgetT, func: Optional[EventFunc[WidgetT]]=None, *, add: bool=False) -> Optional[Callable[..., object]]:
        """Decorator or normal interface, func is optional to be a decorator."""
        if func is None:
            def deco_2(func2: EventFuncT) -> EventFuncT:
                """Used as a decorator - must be called second with the function."""
                bind_func(wid, func2, add)
                return func2
            return deco_2
        else:
            # Normally, call directly
            return bind_func(wid, func, add)
    return cast(_Binder, deco)

if utils.MAC:
    # On OSX, make left-clicks switch to a right-click when control is held.
    @_bind_event_handler
    def bind_leftclick(wid: WidgetT, func: EventFunc[WidgetT], add: bool = False) -> None:
        """On OSX, left-clicks are converted to right-click when control is held."""
        def event_handler(e: tk.Event[WidgetT]) -> None:
            """Check if this should be treated as rightclick."""
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if not isinstance(e.state, int) or e.state & 4 == 0:
                func(e)
        wid.bind(EVENTS['LEFT'], event_handler, add=add)

    @_bind_event_handler
    def bind_leftclick_double(wid: WidgetT, func: EventFunc[WidgetT], add: bool = False) -> None:
        """On OSX, left-clicks are converted to right-click when control is held."""
        def event_handler(e: tk.Event[WidgetT]) -> None:
            """Check if this should be treated as rightclick."""
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if not isinstance(e.state, int) or e.state & 4 == 0:
                func(e)
        wid.bind(EVENTS['LEFT_DOUBLE'], event_handler, add=add)

    @_bind_event_handler
    def bind_rightclick(wid: WidgetT, func: EventFunc[WidgetT], add: bool = False) -> None:
        """On OSX, we need to bind to both rightclick and control-leftclick."""
        wid.bind(EVENTS['RIGHT'], func, add=add)
        wid.bind(EVENTS['LEFT_CTRL'], func, add=add)
else:
    @_bind_event_handler
    def bind_leftclick(wid: WidgetT, func: EventFunc[WidgetT], add: bool = False) -> None:
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT'], func, add=add)

    @_bind_event_handler
    def bind_leftclick_double(wid: WidgetT, func: EventFunc[WidgetT], add: bool = False) -> None:
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT_DOUBLE'], func, add=add)

    @_bind_event_handler
    def bind_rightclick(wid: WidgetT, func: EventFunc[WidgetT], add: bool = False) -> None:
        """Other systems just bind directly."""
        wid.bind(EVENTS['RIGHT'], func, add=add)


def link_checkmark(check: ttk.Checkbutton, widget: tk.Widget) -> None:
    """Link up a checkbutton with something else, so it can also be clicked to toggle.

    This replicates the native behaviour - if the mouse is held down and moved off of the widget,
    that cancels the press.
    """
    widget.bind('<Enter>', f'{check} state active', add=True)
    widget.bind('<Leave>', f'{check} state !active', add=True)

    def hovering(event: tk.Event) -> bool:
        """Check if the mouse is hovering over the label, or the checkmark."""
        # identify-element returns the component name under the specified position,
        # or an empty string if the widget isn't there.
        return str(widget.tk.call(
            widget, 'identify', 'element',
            event.x, event.y,
        )) != '' or str(check.tk.call(
            check, 'identify', 'element',
            event.x_root - check.winfo_rootx(),
            event.y_root - check.winfo_rooty(),
        )) != ''

    def on_press(event: tk.Event) -> None:
        """When pressed, highlight the checkmark."""
        check.state(['pressed'])

    def on_motion(event: tk.Event) -> None:
        """The checkmark is pressed only while the mouse is over it."""
        # Check if the mouse is over the label, or the checkmark. Just a bbox check.
        check.state(['pressed' if hovering(event) else '!pressed'])

    def on_release(event: tk.Event) -> None:
        """When released, toggle if the mouse is still over the widget."""
        check.state(['!pressed'])
        if hovering(event):
            check.invoke()

    bind_leftclick(widget, on_press, add=True)
    widget.bind(EVENTS['LEFT_MOVE'], on_motion, add=True)
    widget.bind(EVENTS['LEFT_RELEASE'], on_release, add=True)


def event_cancel(*args: Any, **kwargs: Any) -> str:
    """Bind to an event to cancel it, and prevent it from propagating."""
    return 'break'


def adjust_inside_screen(
    x: int,
    y: int,
    win: Union[tk.Tk, tk.Toplevel],
    horiz_bound: int = 14,
    vert_bound: int = 45,
) -> Tuple[int, int]:
    """Adjust a window position to ensure it fits inside the screen.

    The new value is returned.
    """
    # Allow disabling this adjustment for multi-window setups
    if not config.APP.get_cur_conf(GenOptions).keep_win_inside:
        return x, y
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


def center_win(window: Union[tk.Tk, tk.Toplevel], parent: Union[tk.Tk, tk.Toplevel, None] = None) -> None:
    """Center a subwindow to be inside a parent window."""
    if parent is None:
        parent = window.nametowidget(window.winfo_parent())

    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2

    x, y = adjust_inside_screen(x, y, window)

    window.geometry(f'+{x}+{y}')


def center_onscreen(window: Union[tk.Tk, tk.Toplevel]) -> None:
    """Center a window onscreen."""
    x = (window.winfo_screenwidth() - window.winfo_width()) // 2
    y = (window.winfo_screenheight() - window.winfo_height()) // 2

    window.geometry(f'+{x}+{y}')


def _default_validator(value: str) -> str:
    if not value.strip():
        raise ValueError("A value must be provided!")
    return value


class _MsgBoxFunc(Generic[T]):
    """Wrap messagebox functions that take TransToken."""
    _DEFAULT_TITLE = TransToken.ui('BEEmod')

    def __init__(self, original: Callable[..., T]) -> None:
        self.orig = original

    def __call__(
        self,
        title: Optional[TransToken]=None,
        message: Optional[TransToken]=None,
        parent: tk.Misc=TK_ROOT,
        **options: Any,
    ) -> T:
        disp_title = str(title) if title is not None else str(self._DEFAULT_TITLE)
        disp_msg = str(message) if message is not None else None
        return self.orig(disp_title, disp_msg, parent=parent, master=TK_ROOT, **options)


showinfo       = _MsgBoxFunc(messagebox.showinfo)
showerror      = _MsgBoxFunc(messagebox.showerror)
askokcancel    = _MsgBoxFunc(messagebox.askokcancel)
askyesno       = _MsgBoxFunc(messagebox.askyesno)


class HidingScroll(ttk.Scrollbar):
    """A scrollbar variant which auto-hides when not needed.

    """
    def set(self, low: Union[float, str], high: Union[float, str]) -> None:
        """Set the size needed for the scrollbar, and hide/show if needed."""
        if float(low) <= 0.0 and float(high) >= 1.0:
            # Remove this, but remember gridding options
            self.grid_remove()
        else:
            self.grid()
        super().set(low, high)


class ReadOnlyEntry(ttk.Entry):
    """A modified Entry widget which prevents editing the text.

    See http://tkinter.unpythonic.net/wiki/ReadOnlyText
    """
    def __init__(self, master: tk.Misc, **opt: Any) -> None:
        opt['exportselection'] = 0  # Don't let it write to clipboard
        opt['takefocus'] = 0  # Ignore when tabbing
        super().__init__(master, **opt)

        self.redirector = redir = WidgetRedirector(self)
        # These two TK commands are used for all text operations,
        # so cancelling them stops anything from happening.
        self.insert = redir.register('insert', event_cancel)  # type: ignore[method-assign]
        self.delete = redir.register('delete', event_cancel)  # type: ignore[method-assign]


# Widget and Spinbox have conflicting identify() definitions, not important.
class ttk_Spinbox(ttk.Widget, tk.Spinbox):  # type: ignore[misc]
    """This is missing from ttk, but still exists."""
    def __init__(self, master: tk.Misc, range: Union[range, slice, None] = None, **kw: Any) -> None:
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
        return self.tk.call(self._w, 'get')  # type: ignore

    @value.setter
    def value(self, value: int) -> None:
        """Set the spinbox to a value."""
        self.tk.call(self._w, 'set', value)  # type: ignore

    def validate(self) -> bool:
        """Values must be integers."""
        try:
            self.old_val = int(self.value)
            return True
        except ValueError:
            self.value = self.old_val
            return False

_file_field_font = _tk_font.nametofont('TkFixedFont')  # Monospaced font
_file_field_char_len = _file_field_font.measure('x')

if utils.WIN:
    # Temporary fix for #1993: tk_chooseDirectory seems to just freeze. Not sure why.
    filedialog.Directory.command = '::tk::dialog::file::chooseDir::'


async def _folderbrowse_powershell() -> Optional[str]:
    """For Windows, the TK bindings don't work properly. Use Powershell to call this one API."""
    result = await trio.run_process(
        [
            "powershell", "-NoProfile",
            "-command", "-",  # Run from stdin.
        ],
        shell=True,
        capture_stdout=True,
        capture_stderr=True,
        stdin=BROWSE_DIR_PS,
    )
    # An Ok or Cancel from ShowDialog, then the path.
    [btn, poss_path] = result.stdout.splitlines()
    if btn == b'Cancel':
        return None
    # Anything non-ASCII seems to just be dropped, or replaced by ?.
    if b'?' in poss_path:
        raise ValueError(poss_path)
    return os.fsdecode(poss_path)


BROWSE_DIR_PS = b'''\
Add-Type -AssemblyName System.Windows.Forms
$Dialog = New-Object -TypeName System.Windows.Forms.FolderBrowserDialog
$Dialog.ShowNewFolderButton = true
$Dialog.ShowDialog()
Write-Output $Dialog.SelectedPath
'''


class FileField(ttk.Frame):
    """A text box which allows searching for a file or directory.
    """
    browser: commondialog.Dialog
    def __init__(
        self,
        master: tk.Misc,
        is_dir: bool = False,
        loc: str = '',
        callback: Callable[[str], None] = lambda path: None,
    ) -> None:
        """Initialise the field.

        - Set is_dir to true to look for directories, instead of files.
        - width sets the number of characters to display.
        - callback is a function to be called with the new path whenever it
          changes.
        """
        from app.tooltip import add_tooltip

        super().__init__(master)

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

        self.callback = callback

        self.textbox = ReadOnlyEntry(
            self,
            textvariable=self._text_var,
            font=_file_field_font,
            cursor=Cursors.REGULAR,
        )
        self.textbox.grid(row=0, column=0, sticky='ew')
        self.columnconfigure(0, weight=1)
        bind_leftclick(self.textbox, lambda e: background_run(self.browse))
        # The full location is displayed in a tooltip.
        add_tooltip(self.textbox, TransToken.untranslated(self._location))
        self.textbox.bind('<Configure>', self._text_configure)

        self.browse_btn = ttk.Button(
            self,
            text="...",
            command=lambda: background_run(self.browse),
        )
        self.browse_btn.grid(row=0, column=1)
        # It should be this narrow, but perhaps this doesn't accept floats?
        try:
            self.browse_btn['width'] = 1.5
        except tk.TclError:
            self.browse_btn['width'] = 2

        self._text_var.set(self._truncate(loc))

    async def browse(self) -> None:
        """Browse for a file."""
        if utils.WIN and self.is_dir:
            try:
                path = await _folderbrowse_powershell()
            except Exception as exc:
                LOGGER.warning('Failed to browse for a directory:', exc_info=exc)
                path = self.browser.show()  # Fallback to generic widget.
        else:
            path = self.browser.show()

        if path:
            self.value = path

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
        tooltip.set_tooltip(self.textbox, TransToken.untranslated(path))
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


EnumT = TypeVar('EnumT')


class EnumButton(Generic[EnumT]):
    """Provides a set of buttons for toggling between enum values.

    An event is fired with the value as the arg when changed.
    """
    frame: ttk.Frame
    _current: EnumT
    buttons: Dict[EnumT, ttk.Button]
    on_changed: event.Event[EnumT]
    def __init__(
        self,
        master: tk.Misc,
        current: EnumT,
        *values: Tuple[EnumT, TransToken],
    ) -> None:
        self.frame = ttk.Frame(master)
        self._current = current
        self.buttons = {}
        self.on_changed = event.Event()

        for x, (val, label) in enumerate(values):
            btn = ttk.Button(
                self.frame,
                # Make partial do the method binding.
                command=functools.partial(EnumButton._select, self, val),
            )
            set_text(btn, label)
            btn.grid(row=0, column=x)
            self.buttons[val] = btn
            if val is current:
                btn.state(['pressed'])

        if current not in self.buttons:
            raise ValueError(f'Default value {current!r} not present in {list(values)}')

        if len(self.buttons) != len(values):
            raise ValueError(f'No duplicates allowed, got: {list(values)}')

    def _select(self, value: EnumT) -> None:
        """Select a specific value."""
        if value is not self._current:
            self.buttons[self._current].state(['!pressed'])
            self._current = value
            self.buttons[self._current].state(['pressed'])
            background_run(self.on_changed, value)

    @property
    def current(self) -> EnumT:
        """Return the currently selected button."""
        return self._current

    @current.setter
    def current(self, value: EnumT) -> None:
        """Change the currently selected button."""
        self._select(value)


class LineHeader(ttk.Frame):
    """A resizable line, with a title in the middle."""
    def __init__(self, parent: tk.Misc, title: TransToken) -> None:
        super().__init__(parent)
        sep_left = ttk.Separator(self)
        sep_left.grid(row=0, column=0, sticky='EW')
        self.columnconfigure(0, weight=1)

        self.title = ttk.Label(
            self,
            font='TkMenuFont',
            anchor='center',
        )
        set_text(self.title, title)
        self.title.grid(row=0, column=1)

        sep_right = ttk.Separator(self)
        sep_right.grid(row=0, column=2, sticky='EW')
        self.columnconfigure(2, weight=1)
