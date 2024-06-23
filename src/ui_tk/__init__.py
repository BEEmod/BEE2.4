"""This package contains UI code specific to TKinter."""
from __future__ import annotations
from types import TracebackType
import tkinter as tk

from exceptiongroup import BaseExceptionGroup
import trio

import app


# We must always have one Tk object, and it needs to be constructed
# before most of TKinter will function. So doing it here does it first.
TK_ROOT = tk.Tk()
TK_ROOT.withdraw()  # Hide the window until everything is loaded.

TK_ROOT.protocol("WM_DELETE_WINDOW", app.quit_app)

if '__class_getitem__' not in vars(tk.Event):
    # Patch in it being generic, by replacing it with a copy that subclasses Generic.
    class _GenericEvent[W: tk.Misc](tk.Event):  # type: ignore
        pass

    _GenericEvent.__name__ = 'Event'
    tk.Event = _GenericEvent  # type: ignore


async def route_callback_exceptions(
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Set Tk.report_callback_exception, so that exceptions raised in callbacks crash the app."""
    # Use a list, in case multiple callbacks error before the loop resumes.
    exceptions: list[BaseException] = []
    error_occurred = trio.Event()

    def callback(
        exc_type: type[BaseException],
        exc_value: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Store off the exception, then wake the task to raise it."""
        if exc_value is None:
            exceptions.append(exc_type())
        else:
            exceptions.append(exc_value)
        error_occurred.set()

    TK_ROOT.report_callback_exception = callback
    task_status.started()
    await error_occurred.wait()
    raise BaseExceptionGroup('In Tk callback', exceptions)
