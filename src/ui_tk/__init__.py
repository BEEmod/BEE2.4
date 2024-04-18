"""This package contains UI code specific to TKinter."""
from typing import Generic, TypeVar
from types import new_class
import tkinter as tk

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
