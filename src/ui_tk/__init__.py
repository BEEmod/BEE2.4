"""This package contains UI code specific to TKinter."""
from __future__ import annotations
from typing import Generic, TypeVar
from types import TracebackType, new_class
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
    _W_co = TypeVar("_W_co", covariant=True, bound=tk.Misc)
    _W_co.__module__ = 'tkinter'
    tk.Event = new_class(  # type: ignore
        'Event', (Generic[_W_co], ),
        exec_body=lambda ns: ns.update({
            name: getattr(tk.Event, name)
            for name in vars(tk.Event)
            # Specify the vars to assign, so we don't include things like __dict__ descriptors.
            if name in ['__doc__', '__module__', '__repr__']
        }),
    )


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
