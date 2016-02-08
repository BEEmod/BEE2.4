"""
General code used for tkinter portions.

"""
from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox
import tkinter as tk

import os.path

from idlelib.WidgetRedirector import WidgetRedirector

import utils

# Put this in a module so it's a singleton, and we can always import the same
# object.
TK_ROOT = tk.Tk()

if utils.WIN:
    # Ensure everything has our icon (including dialogs)
    TK_ROOT.wm_iconbitmap(default='../BEE2.ico')
TK_ROOT.withdraw()  # Hide the window until everything is loaded.


def hook_tk_errors():
    """TKinter catches and swallows callback errors.

     we need to hook into that to log those seperately.
    """
    import loadScreen
    import traceback
    main_logger = utils.getLogger()

    def tk_error(exc_type, exc_value, exc_tb):
        """Log TK errors."""
        # The exception is caught inside the TK code.
        # We don't care about that, so try and move the traceback up
        # one level.
        import sys
        if exc_tb.tb_next:
            exc_tb = exc_tb.tb_next
        main_logger.error(
            'TKinter callback exception occurred:\n{}',
            ''.join(
                traceback.format_exception(
                    exc_type,
                    exc_value,
                    exc_tb,
                )
            ),
        )
        # Close loading screens if they're visible..
        loadScreen.LoadScreen.close_all()

        # Release the grab, if it exists. Otherwise you can't see the error dialog.
        TK_ROOT.grab_set_global()
        TK_ROOT.grab_release()

        messagebox.showerror(
            title='BEE2 Error:',
            message='{}: {!r}'.format(exc_type.__name__, exc_value),
            parent=TK_ROOT,
        )
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
    def __init__(self, master, range=None, **kw):
        """Initialise a spinbox.
        Arguments:
            range: The range buttons will run in
            values: A list of values to use
            wrap: Wether to loop at max/min
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


class FileField(ttk.Frame):
    """A text box which allows searching for a file or directory.
    """
    def __init__(self, master, is_dir=False, loc='', width=24, callback=None):
        """Initialise the field.

        - Set is_dir to true to look for directories, instead of files.
        - width sets the number of characters to display.
        - loc is the initial value of the field.
        - callback is a function to be called with the new path whenever it
          changes.
        """
        super(FileField, self).__init__(master)

        self._location = loc
        self.is_dir = is_dir
        self.width = width

        self._text_var = tk.StringVar(master=self, value=self._truncate(loc))
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

        if callback is not None:
            self.callback = callback

        self.textbox = ReadOnlyEntry(
            self,
            textvariable=self._text_var,
            width=width,
            cursor=utils.CURSORS['regular'],
        )
        self.textbox.grid(row=0, column=0)
        utils.bind_leftclick(self.textbox, self.browse)

        self.browse_btn = ttk.Button(
            self,
            text="...",
            width=1.5,
            command=self.browse,
        )
        self.browse_btn.grid(row=0, column=1)

    def browse(self, event=None):
        """Browse for a file."""
        path = self.browser.show()
        if path:
            self.value = path

    def callback(self, path):
        """Callback function, called whenever the value changes."""
        pass

    @property
    def value(self):
        """Get the current path."""
        return self._location

    @value.setter
    def value(self, path):
        """Set the current path. This calls the callback function."""
        self.callback(path)
        self._location = path
        self._text_var.set(self._truncate(path))

    def _truncate(self, path):
        """Truncate the path to the end portion."""
        if not self.is_dir:
            path = os.path.basename(path)

        if len(path) > self.width - 4:
            return '...' + path[-(self.width - 1):]

        return path
