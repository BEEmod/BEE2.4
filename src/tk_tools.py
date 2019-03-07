"""
General code used for tkinter portions.

"""
from typing import Union, Callable

from tkinter import ttk
from tkinter import font as _tk_font
from tkinter import filedialog, commondialog
import tkinter as tk

import os.path

try:
    # Python 3.6+
    # noinspection PyCompatibility
    from idlelib.redirector import WidgetRedirector
except ImportError:
    # Python 3.5 and below
    # noinspection PyCompatibility, PyUnresolvedReferences
    from idlelib.WidgetRedirector import WidgetRedirector

import utils

# Put this in a module so it's a singleton, and we can always import the same
# object.
TK_ROOT = tk.Tk()

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
    import img
    app_icon = img.get_app_icon(ICO_PATH)

    def set_window_icon(window: Union[tk.Toplevel, tk.Tk]):
        """Set the window icon."""
        # Weird argument order for default=True...
        window.wm_iconphoto(True, app_icon)

    LISTBOX_BG_SEL_COLOR = 'blue'
    LISTBOX_BG_COLOR = 'white'

TK_ROOT.withdraw()  # Hide the window until everything is loaded.


# noinspection PyBroadException
def on_error(exc_type, exc_value, exc_tb):
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

    if not issubclass(exc_type, Exception):
        # It's subclassing BaseException (KeyboardInterrupt, SystemExit),
        # so ignore the error.
        return

    # Put it onscreen.
    try:
        from tkinter import messagebox
        messagebox.showinfo(
            title='BEE2 Error!',
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


def hook_tk_errors():
    """TKinter catches and swallows callback errors.

     We need to hook into that to log those seperately.
    """

    def tk_error(exc_type, exc_value, exc_tb):
        """Log TK errors."""
        # The exception is caught inside the TK code.
        # We don't care about that, so try and move the traceback up
        # one level.
        import sys
        import logging
        if exc_tb.tb_next:
            exc_tb = exc_tb.tb_next

        on_error(exc_type, exc_value, exc_tb)

        logger = logging.getLogger('BEE2')
        logger.error(
            msg='Uncaught Exception:',
            exc_info=(exc_type, exc_value, exc_tb),
        )
        logging.shutdown()

        # Since this isn't caught normally, it won't quit the application.
        # Quit ourselves manually. to prevent TK just freezing.
        TK_ROOT.quit()
        sys.exit()

    TK_ROOT.report_callback_exception = tk_error
hook_tk_errors()  # Always do this.


def event_cancel(*args, **kwargs):
    """Bind to an event to cancel it, and prevent it from propagating."""
    return 'break'


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
    def __init__(self, master, range: Union[range, slice]=None, **kw):
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
    def value(self):
        """Get the value of the spinbox."""
        return self.tk.call(self._w, 'get')

    @value.setter
    def value(self, value):
        """Set the spinbox to a value."""
        self.tk.call(self._w, 'set', value)

    def validate(self):
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
        from tooltip import add_tooltip

        super(FileField, self).__init__(master)

        self._location = loc
        self.is_dir = is_dir

        self._text_var = tk.StringVar(master=self, value='')
        if is_dir:
            self.browser = filedialog.Directory(
                self,
                initialdir=loc,
            )  # type: commondialog.Dialog
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
            cursor=utils.CURSORS['regular'],
        )
        self.textbox.grid(row=0, column=0, sticky='ew')
        self.columnconfigure(0, weight=1)
        utils.bind_leftclick(self.textbox, self.browse)
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
        import tooltip
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
