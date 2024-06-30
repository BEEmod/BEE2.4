"""A consistent interface for dialog boxes."""
from __future__ import annotations
from typing_extensions import override

from collections.abc import Callable
from tkinter import simpledialog, ttk, commondialog, filedialog
import tkinter as tk

import trio

from app.dialogs import DEFAULT_TITLE, Dialogs, Icon, validate_non_empty
from loadScreen import suppress_screens
from transtoken import AppError, TransToken

from . import TK_ROOT
from .tk_tools import set_window_icon, center_onscreen
from .wid_transtoken import set_text


__all__ = ['Dialogs', 'TkDialogs', 'DIALOG']
# Patch various tk windows to hide loading screens while they are open.
# Messageboxes, file dialogs and colorchooser all inherit from Dialog,
# so patching .show() will fix them all.
# contextlib managers can also be used as decorators.
commondialog.Dialog.show = suppress_screens()(commondialog.Dialog.show)  # type: ignore


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


try:
    from idlelib.query import Query  # type: ignore[import-not-found]
except ImportError:
    QueryValidator = BasicQueryValidator
else:
    class QueryValidator(Query):  # type: ignore[no-redef]
        """Implement using IDLE's better code for this."""
        def __init__(
            self,
            parent: tk.Misc,
            title: str, message: str, initial: str,
            validator: Callable[[str], str],
        ) -> None:
            self.__validator = validator
            super().__init__(parent, title, message, text0=initial)
            self.__has_closed = trio.Event()

        def wait_window(self, window: object = None) -> None:
            """Block this method call, to prevent the Tk loop from being frozen."""

        def destroy(self) -> None:
            """Called when the window is either canceled or submitted."""
            self.__has_closed.set()
            super().destroy()

        async def wait(self) -> None:
            """Wait for the query to close."""
            await self.__has_closed.wait()

        def entry_ok(self) -> str | None:
            """Return non-blank entry or None."""
            try:
                return self.__validator(self.entry.get())
            except AppError as exc:
                self.showerror(str(exc.message))
                return None


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
            # If the main loop isn't running, this doesn't work correctly.
            # Probably also if it's not visible. So swap back to the old style.
            # It's also only a problem on Windows.
            if Query is None:
                query_cls = BasicQueryValidator
            else:
                query_cls = QueryValidator
            win = query_cls(self.parent, title, message, initial_value, validator)

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
