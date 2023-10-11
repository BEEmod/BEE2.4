"""A consistent interface for dialog boxes."""
from typing import Callable, List, Optional, Tuple, Union

from tkinter import simpledialog, ttk
import tkinter as tk

import trio

from loadScreen import suppress_screens
from app.dialogs import DEFAULT_TITLE, Dialogs, Icon, validate_non_empty
from app.errors import AppError
from app.tk_tools import set_window_icon
from transtoken import TransToken

from app import TK_ROOT, localisation


async def _messagebox(
    kind: str,
    parent: Union[tk.Toplevel, tk.Tk],
    message: TransToken,
    title: TransToken,
    icon: Icon,
    detail: str,
) -> List[str]:
    """Don't bother with `tkinter.messagebox`, it just calls this which is more flexible anyway."""
    args: Tuple[str, ...] = (
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
    return await trio.to_thread.run_sync(TK_ROOT.tk.call,*args)


class BasicQueryValidator(simpledialog.Dialog):
    """Implement the dialog with the simpledialog code."""
    result: Optional[str]
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

    def wait_window(self, window: object = None) -> None:
        """Block this method call, to prevent the Tk loop from being frozen."""

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
        localisation.set_text(w, self.__message)
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

        def entry_ok(self) -> Optional[str]:
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

    def __init__(self, parent: Union[tk.Toplevel, tk.Tk]) -> None:
        """Create with the specified parent."""
        self.parent = parent

    async def show_info(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> None:
        """Show a message box with some information."""
        await _messagebox("ok", self.parent, message, title, icon, detail)

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

    async def ask_yes_no_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> Optional[bool]:
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

    async def prompt(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        initial_value: TransToken = TransToken.BLANK,
        validator: Callable[[str], str] = validate_non_empty,
    ) -> Optional[str]:
        """Ask the user to enter a string."""
        with suppress_screens():
            # If the main loop isn't running, this doesn't work correctly.
            # Probably also if it's not visible. So swap back to the old style.
            # It's also only a problem on Windows.
            if Query is None:  # or (utils.WIN and (not _main_loop_running or not TK_ROOT.winfo_viewable())):
                query_cls = BasicQueryValidator
            else:
                query_cls = QueryValidator
            win = query_cls(self.parent, title, message, initial_value, validator)
            await win.wait()
            return win.result


DIALOG = TkDialogs(TK_ROOT)
