"""A consistent interface for dialog boxes."""
from __future__ import annotations
from typing_extensions import override

from collections.abc import Callable

import trio
import wx

from app.dialogs import DEFAULT_TITLE, Dialogs, Icon, validate_non_empty
from loadScreen import suppress_screens
from transtoken import AppError, TransToken

from . import MAIN_WINDOW


__all__ = ['Dialogs', 'WxDialogs', 'DIALOG']


async def _messagebox(
    style: int,
    parent: wx.TopLevelWindow,
    message: TransToken,
    title: TransToken,
    icon: Icon,
    detail: str,
) -> int:
    """Common logic for message dialogs"""
    match icon:
        case Icon.INFO:
            style |= wx.ICON_INFORMATION
        case Icon.WARNING:
            style |= wx.ICON_WARNING
        case Icon.QUESTION:
            style |= wx.ICON_QUESTION
        case Icon.ERROR:
            style |= wx.ICON_ERROR
    style |= wx.CENTRE
    if detail:
        box = wx.RichMessageDialog(parent, str(message), str(title), style)
        box.ShowDetailedText(detail)
    else:
        box = wx.MessageDialog(parent, str(message), str(title), style)
    return box.ShowModal()


class WxDialogs(Dialogs):
    """The class allows passing through a parent window."""
    INFO = Icon.INFO
    WARNING = Icon.WARNING
    QUESTION = Icon.QUESTION
    ERROR = Icon.ERROR

    def __init__(self, parent: wx.TopLevelWindow) -> None:
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
        await _messagebox(wx.OK | wx.ICON_INFORMATION, self.parent, message, title, icon, detail)

    @override
    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        res = await _messagebox(wx.OK | wx.CANCEL, self.parent, message, title, icon, detail)
        if res == wx.ID_OK:
            return True
        elif res == wx.ID_CANCEL:
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
        res = await _messagebox(wx.YES_NO, self.parent, message, title, icon, detail)
        if res == wx.ID_YES:
            return True
        elif res == wx.ID_NO:
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
        res = await _messagebox(wx.YES_NO | wx.CANCEL, self.parent, message, title, icon, detail)
        if res == wx.ID_YES:
            return True
        elif res == wx.ID_NO:
            return False
        elif res == wx.ID_CANCEL:
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
            win = wx.TextEntryDialog(
                self.parent,
                str(message),
                str(title),
                str(initial_value),
            )
            # TODO: Reimplement to be non-modal
            if win.ShowModal() != wx.ID_OK:
                return None
            return win.GetValue()


DIALOG = WxDialogs(MAIN_WINDOW)
