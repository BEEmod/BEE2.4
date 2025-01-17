"""A consistent interface for dialog boxes."""
from __future__ import annotations

from typing_extensions import override

from tkinter import commondialog, filedialog, simpledialog, ttk
from tkinter.font import Font
import tkinter as tk
from collections.abc import Callable

import trio

from app.dialogs import DEFAULT_TITLE, Dialogs, Icon, validate_non_empty
from loadScreen import suppress_screens
from transtoken import AppError, TransToken

from . import TK_ROOT
from .tk_tools import center_onscreen, center_win, set_window_icon
from .wid_transtoken import set_text


__all__ = ['Dialogs', 'TkDialogs', 'DIALOG']
# Patch various tk windows to hide loading screens while they are open.
# Messageboxes, file dialogs and colorchooser all inherit from Dialog,
# so patching .show() will fix them all.
# contextlib managers can also be used as decorators.
commondialog.Dialog.show = suppress_screens()(commondialog.Dialog.show)  # type: ignore

TRANS_OK = TransToken.ui('OK')
TRANS_CANCEL = TransToken.ui('Cancel')


async def _messagebox(
    kind: str,
    parent: tk.Toplevel | tk.Tk,
    message: TransToken,
    title: TransToken,
    icon: Icon,
    detail: str,
) -> str:
    """Don't bother with `tkinter.messagebox`, it just calls this which is more flexible anyway."""
    args: tuple[str, ...] = (
        "tk_messageBox",
        "-type", kind,
        "-icon", icon.value,
        "-parent", str(parent),
        "-title", str(title),
        "-message", str(message),
    )
    if detail:
        args += ('-detail', detail)

    # Threading seems to work, not sure if safe...
    with suppress_screens():
        return await trio.to_thread.run_sync(TK_ROOT.tk.call, *args)


class BasicQueryValidator(simpledialog.Dialog):
    """Implement the dialog with the simpledialog code."""
    result: str | None

    def __init__(
        self,
        parent: tk.Misc,
        title: TransToken,
        message: TransToken,
        initial: TransToken,
        validator: Callable[[str], str],
    ) -> None:
        self.__validator = validator
        self.__title = title
        self.__message = message
        self.__initial = initial
        self.result = None
        self.__has_closed = trio.Event()
        super().__init__(parent, str(title))

    @override
    def wait_window(self, window: object = None) -> None:
        """Block this method call, to prevent the Tk loop from being frozen."""

    @override
    def destroy(self) -> None:
        """Called when the window is either canceled or submitted."""
        self.__has_closed.set()
        super().destroy()

    async def wait(self) -> None:
        """Wait for the query to close."""
        await self.__has_closed.wait()

    def body(self, master: tk.Frame) -> ttk.Entry:
        """Ensure the window icon is changed, and copy code from askstring's internals."""
        super().body(master)
        set_window_icon(self)
        w = ttk.Label(master, justify='left')
        set_text(w, self.__message)
        w.grid(row=0, padx=5, sticky='w')

        self.entry = ttk.Entry(master, name="entry")
        self.entry.grid(row=1, padx=5, sticky='we')

        if self.__initial:
            self.entry.insert(0, str(self.__initial))
            self.entry.select_range(0, 'end')

        return self.entry

    def validate(self) -> bool:
        """Check if the parameter is valid."""
        try:
            self.result = self.__validator(self.entry.get())
        except AppError as exc:
            self.tk.call(
                "tk_messageBox",
                "-type", "ok",
                "-icon", "warning",
                "-parent", str(self),
                "-title", str(self.__title),
                "-message", str(exc.message),
            )
            return False
        else:
            return True


class QueryValidator(tk.Toplevel):
    """Copied from idlelib, a better query window compared to BasicQueryValidator"""
    result: str | None

    entryvar: tk.StringVar
    entry: ttk.Entry
    error_font: Font
    entry_error: ttk.Label
    button_ok: ttk.Button
    button_cancel: ttk.Button
    def __init__(
        self,
        parent: tk.Toplevel | tk.Tk,
        title: TransToken, message: TransToken, initial: TransToken,
        validator: Callable[[str], str],
    ) -> None:
        """Create modal popup, return when destroyed."""
        self.parent = parent  # Needed for Font call.
        self.message = message
        self.initial = initial

        self.validator = validator  # Added
        self.has_closed = trio.Event()
        self.result = None

        super().__init__(parent)
        self.withdraw()  # Hide while configuring, especially geometry.
        self.title(str(title))
        self.transient(parent)
        self.grab_set()

        # Aside from bind, these inlined from simpledialog._setup_dialog
        if self._windowingsystem == "aqua":
            self.tk.call("::tk::unsupported::MacWindowStyle", "style", self, "moveableModal", "")
            self.bind("<Command-.>", self.cancel)
        elif self._windowingsystem == "x11":
            self.wm_attributes("type", "dialog")

        self.bind('<Key-Escape>', self.cancel)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind('<Key-Return>', self.ok)
        self.bind("<KP_Enter>", self.ok)

        self.create_widgets()
        self.update_idletasks()  # Need here for winfo_reqwidth below.
        center_win(self, parent)
        self.resizable(height=False, width=False)

        self.deiconify()  # Unhide now that geometry set.
        self.entry.focus_set()
        # Removed wait_window() call.

    def create_widgets(self) -> None:
        """Create entry (rows, extras, buttons.

        Entry stuff on rows 0-2, spanning cols 0-2.
        Buttons on row 99, cols 1, 2.
        """
        frame = ttk.Frame(self, padding=10)
        frame.grid(column=0, row=0, sticky='news')
        frame.grid_columnconfigure(0, weight=1)

        entrylabel = ttk.Label(frame, anchor='w', justify='left', text=str(self.message))
        self.entryvar = tk.StringVar(self, str(self.initial))
        self.entry = ttk.Entry(frame, width=30, textvariable=self.entryvar)
        self.error_font = Font(name='TkCaptionFont', exists=True, root=self.parent)
        self.entry_error = ttk.Label(frame, text=' ', foreground='red', font=self.error_font)
        # Display or blank error by setting ['text'] =.
        entrylabel.grid(column=0, row=0, columnspan=3, padx=5, sticky='W')
        self.entry.grid(column=0, row=1, columnspan=3, padx=5, sticky='EW', pady=(10,0))
        self.entry_error.grid(column=0, row=2, columnspan=3, padx=5, sticky='EW')

        self.button_ok = ttk.Button(frame, text=str(TRANS_OK), default='active', command=self.ok)
        self.button_cancel = ttk.Button(frame, text=str(TRANS_CANCEL), command=self.cancel)

        self.button_ok.grid(column=1, row=99, padx=5)
        self.button_cancel.grid(column=2, row=99, padx=5)

    def entry_ok(self) -> str | None:
        """Changed, use our validator and AppError."""
        try:
            return self.validator(self.entry.get())
        except AppError as exc:
            self.entry_error['text'] = str(exc.message)
            return None

    def ok(self, event: object = None) -> None:
        """If entry is valid, bind it to 'result' and destroy tk widget.

        Otherwise leave dialog open for user to correct entry or cancel.
        """
        try:
            self.result = self.validator(self.entry.get())
        except AppError as exc:
            self.entry_error['text'] = str(exc.message)
            # [Ok] moves focus.  (<Return> does not.)  Move it back.
            self.entry.focus_set()
            return None
        else:
            self.entry_error['text'] = ''
            self.destroy()

    def cancel(self, event: object = None) -> None:
        """Set dialog result to None and destroy tk widget."""
        self.result = None
        self.destroy()

    def destroy(self) -> None:
        self.grab_release()
        self.has_closed.set()
        super().destroy()

    async def wait(self) -> str | None:
        """Wait for the query to close."""
        await self.has_closed.wait()
        return self.result


class TkDialogs(Dialogs):
    """The class allows passing through a parent window."""
    INFO = Icon.INFO
    WARNING = Icon.WARNING
    QUESTION = Icon.QUESTION
    ERROR = Icon.ERROR

    def __init__(self, parent: tk.Toplevel | tk.Tk) -> None:
        """Create with the specified parent."""
        self.parent = parent

    @override
    async def show_info(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> None:
        """Show a message box with some information."""
        await _messagebox("ok", self.parent, message, title, icon, detail)

    @override
    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        res = await _messagebox("okcancel", self.parent, message, title, icon, detail)
        if res == "ok":
            return True
        elif res == "cancel":
            return False
        else:
            raise ValueError(res)

    @override
    async def ask_yes_no(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool:
        """Show a message box with "Yes" and "No" buttons."""
        res = await _messagebox("yesno", self.parent, message, title, icon, detail)
        if res == "yes":
            return True
        elif res == "no":
            return False
        else:
            raise ValueError(res)

    @override
    async def ask_yes_no_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool | None:
        """Show a message box with "Yes", "No" and "Cancel" buttons."""
        res = await _messagebox("yesnocancel", self.parent, message, title, icon, detail)
        if res == "yes":
            return True
        elif res == "no":
            return False
        elif res == "cancel":
            return None
        else:
            raise ValueError(res)

    @override
    async def prompt(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        initial_value: TransToken = TransToken.BLANK,
        validator: Callable[[str], str] = validate_non_empty,
    ) -> str | None:
        """Ask the user to enter a string."""
        with suppress_screens():
            win = QueryValidator(self.parent, title, message, initial_value, validator)

            if self.parent is TK_ROOT:
                # Force to be centered and visible - the root might be hidden if doing an early add-game.
                TK_ROOT.deiconify()
                center_onscreen(win)

            await win.wait()
            return win.result

    @override
    async def ask_open_filename(
        self,
        title: TransToken = DEFAULT_TITLE,
        file_types: tuple[TransToken, str] | None = None,
    ) -> str:
        """Ask the user to open a filename, optionally with a file filter."""
        if file_types is not None:
            desc, ext = file_types
            return filedialog.askopenfilename(
                title=str(title),
                filetypes=[(str(desc), f'*{ext.lstrip('*')}')],
            )
        else:
            return filedialog.askopenfilename(title=str(title))


DIALOG = TkDialogs(TK_ROOT)
