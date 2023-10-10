"""A consistent interface for dialog boxes."""
from typing import List, Optional, Union

import tkinter as tk

from app.dialogs import DEFAULT_TITLE, Dialogs, Icon
from transtoken import TransToken

from app import TK_ROOT


def _messagebox(
    kind: str,
    parent: Union[tk.Toplevel, tk.Tk],
    message: TransToken,
    title: TransToken,
    icon: Icon,
) -> List[str]:
    """Don't bother with `tkinter.messagebox`, it just calls this which is more flexible anyway."""
    return TK_ROOT.tk.call(
        "tk_messageBox",
        "-type", kind,
        "-icon", icon.value,
        "-parent", str(parent),
        "-title", str(title),
        "-message", str(message),
    )


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
    ) -> None:
        """Show a message box with some information."""
        _messagebox("ok", self.parent, message, title, icon)

    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        res = _messagebox("okcancel", self.parent, message, title, icon)
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
    ) -> bool:
        """Show a message box with "Yes" and "No" buttons."""
        res = _messagebox("yesno", self.parent, message, title, icon)
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
    ) -> Optional[bool]:
        """Show a message box with "Yes", "No" and "Cancel" buttons."""
        res = _messagebox("yesnocancel", self.parent, message, title, icon)
        if res == "yes":
            return True
        elif res == "no":
            return False
        elif res == "cancel":
            return None
        else:
            raise ValueError(res)


DIALOG = TkDialogs(TK_ROOT)
