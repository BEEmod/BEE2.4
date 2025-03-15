"""A consistent interface for dialog boxes."""
from typing import overload, override

from collections.abc import Callable

import trio
import wx

from app.dialogs import DEFAULT_TITLE, Btn3, Dialogs, Icon, validate_non_empty
from loadScreen import suppress_screens
from transtoken import AppError, TransToken
from ui_wx.wid_transtoken import set_text, set_win_title

from . import MAIN_WINDOW


__all__ = ['Dialogs', 'WxDialogs', 'DIALOG']

@overload
def _messagebox(
    style: int, parent: wx.TopLevelWindow,
    message: TransToken, title: TransToken,
    icon: Icon,
) -> wx.MessageDialog: ...
@overload
def _messagebox(
    style: int, parent: wx.TopLevelWindow,
    message: TransToken, title: TransToken,
    icon: Icon, detail: str,
) -> wx.RichMessageDialog: ...
def _messagebox(
    style: int,
    parent: wx.TopLevelWindow,
    message: TransToken,
    title: TransToken,
    icon: Icon,
    detail: str = '',
) -> wx.RichMessageDialog | wx.MessageDialog:
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
        return box
    else:
        return wx.MessageDialog(parent, str(message), str(title), style)


class TextValidator(wx.Validator):
    """Handles validation for the text entry window."""
    result: str | None

    def __init__(
        self,
        done_event: trio.Event,
        error_label: wx.StaticText,
        func: Callable[[str], str],
        show_error: Callable[[], object],
        value: str | None,
    ) -> None:
        super().__init__()
        self.error_label = error_label
        self.func = func
        self.show_error = show_error
        self.done_event = done_event
        self.result = value

    def Clone(self) -> 'TextValidator':
        copy = TextValidator(self.done_event, self.error_label, self.func, self.show_error, self.result)
        return copy

    def TransferToWindow(self) -> bool:
        if isinstance(self.Window, wx.TextEntry):
            self.Window.ChangeValue(self.result or '')
            return True
        return False

    def Validate(self, parent: wx.Window) -> bool:
        if not isinstance(self.Window, wx.TextEntry):
            return False
        try:
            self.result = self.func(self.Window.GetValue())
        except AppError as err:
            set_text(self.error_label, err.message)
            self.error_label.Show()
            self.show_error()
            wx.Bell()
            return False
        self.done_event.set()
        return True


async def text_entry_window(
    parent: wx.Window,
    title: TransToken,
    prompt: TransToken,
    initial: TransToken,
    func: Callable[[str], str],
) -> str | None:
    """Create and show a text entry window."""
    dialog = wx.Dialog(parent)
    set_win_title(dialog, title)
    done_event = trio.Event()

    sizer_vert = wx.BoxSizer(wx.VERTICAL)

    label_prompt = set_text(wx.StaticText(dialog, wx.ID_ANY), prompt)
    sizer_vert.Add(label_prompt, 0, wx.EXPAND, 0)

    text_ctrl = wx.TextCtrl(dialog, wx.ID_ANY, "")
    sizer_vert.Add(text_ctrl, 0, wx.EXPAND, 0)

    label_error = wx.StaticText(dialog, wx.ID_ANY, "", style=wx.ST_ELLIPSIZE_END)
    label_error.SetForegroundColour(wx.Colour(255, 0, 0))
    label_error.Hide()
    sizer_vert.Add(label_error, 0, wx.EXPAND, 0)
    sizer_vert.SetSizeHints(dialog)

    text_ctrl.SetValidator(TextValidator(
        done_event=done_event,
        error_label=label_error,
        func=func,
        show_error=lambda: sizer_vert.SetSizeHints(dialog),
        value=str(initial),
    ))

    sizer_btn = wx.StdDialogButtonSizer()
    sizer_vert.Add(sizer_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 4)

    btn_ok = wx.Button(dialog, wx.ID_OK, "")
    btn_cancel = wx.Button(dialog, wx.ID_CANCEL, "")
    btn_ok.SetDefault()

    sizer_btn.AddButton(btn_ok)
    sizer_btn.AddButton(btn_cancel)
    sizer_btn.Realize()

    dialog.SetSizer(sizer_vert)
    sizer_vert.Fit(dialog)
    sizer_vert.SetSizeHints(dialog)

    dialog.SetAffirmativeId(wx.ID_OK)
    dialog.SetEscapeId(wx.ID_CANCEL)

    def on_cancel(_: object) -> None:
        """Handle closing the dialog."""
        validator: wx.Validator = text_ctrl.GetValidator()
        assert isinstance(validator, TextValidator)
        validator.result = None
        done_event.set()

    sizer_vert.Layout()
    dialog.Layout()
    dialog.Bind(wx.EVT_CLOSE, on_cancel)
    btn_cancel.Bind(wx.EVT_BUTTON, on_cancel)
    dialog.Show()
    await done_event.wait()
    # Validators get cloned when set, so we have to fetch the one actually used.
    validator: wx.Validator = text_ctrl.GetValidator()
    assert isinstance(validator, TextValidator)
    dialog.Hide()
    dialog.Destroy()
    return validator.result


class WxDialogs(Dialogs):
    """The class allows passing through a parent window."""
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
        await trio.lowlevel.checkpoint()
        box = _messagebox(wx.OK | wx.ICON_INFORMATION, self.parent, message, title, icon, detail)
        box.ShowModal()

    @override
    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        await trio.lowlevel.checkpoint()
        box = _messagebox(wx.OK | wx.CANCEL, self.parent, message, title, icon, detail)
        match box.ShowModal():
            case wx.ID_OK:
                return True
            case wx.ID_CANCEL:
                return False
            case btn_id:
                raise ValueError(f"Unknown button ID: {btn_id}")

    @override
    async def ask_yes_no(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool:
        """Show a message box with "Yes" and "No" buttons."""
        await trio.lowlevel.checkpoint()
        box = _messagebox(wx.YES_NO, self.parent, message, title, icon, detail)
        match box.ShowModal():
            case wx.ID_YES:
                return True
            case wx.ID_NO:
                return False
            case btn_id:
                raise ValueError(f"Unknown button ID: {btn_id}")

    @override
    async def ask_yes_no_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool | None:
        """Show a message box with "Yes", "No" and "Cancel" buttons."""
        await trio.lowlevel.checkpoint()
        box = _messagebox(wx.YES_NO | wx.CANCEL, self.parent, message, title, icon, detail)
        match box.ShowModal():
            case wx.ID_YES:
                return True
            case wx.ID_NO:
                return False
            case wx.ID_CANCEL:
                return None
            case btn_id:
                raise ValueError(f"Unknown button ID: {btn_id}")

    async def ask_custom(
        self,
        message: TransToken,
        button_1: TransToken,
        button_2: TransToken,
        button_3: TransToken | None = None,
        *,
        cancel: Btn3,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
    ) -> Btn3:
        """Show a message box with custom buttons."""
        buttons: list[tuple[TransToken, Btn3]] = [
            (button_1, 0),
            (button_2, 1),
        ]
        has_three = False
        if button_3 is not None:
            has_three = True
            buttons.append((button_3, 2))
        elif cancel == 2:
            raise ValueError("Button 3 is missing but set as cancel button?")
        # Now move the cancel button to the end to line up.
        buttons.append(buttons.pop(cancel))
        await trio.lowlevel.checkpoint()

        # TODO: Stock IDs, if ever used with eligible tokens.
        box = _messagebox(
            style=wx.CANCEL | (wx.YES_NO if has_three else wx.OK),
            parent=self.parent,
            message=message,
            title=title,
            icon=icon,
        )
        match buttons:
            case [(first, first_val), (second, sec_val), (third, last_val)]:
                changed = box.SetYesNoCancelLabels(str(first), str(second), str(third))
            case [(first, first_val), (second, sec_val)]:
                changed = box.SetOKCancelLabels(str(first), str(second))
                last_val = sec_val
            case _:
                raise AssertionError(buttons)
        if not changed:
            # Use wx.GenericMessageDialog?
            raise NotImplementedError("No custom buttons for this platform?")
        await trio.lowlevel.checkpoint()
        match box.ShowModal():
            case wx.ID_YES | wx.ID_OK:
                return first_val
            case wx.ID_NO:
                return sec_val
            case wx.ID_CANCEL:
                return last_val
            case btn_id:
                raise ValueError(f"Unknown button ID: {btn_id}")

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
            return await text_entry_window(self.parent, title, message, initial_value, validator)

    @override
    async def ask_open_filename(
        self,
        title: TransToken = DEFAULT_TITLE,
        file_types: tuple[TransToken, str] | None = None,
    ) -> str:
        """Ask the user to open a filename, optionally with a file filter."""
        dialog = wx.FileDialog(self.parent, str(title), style=wx.FD_OPEN)
        if file_types is not None:
            desc, ext = file_types
            dialog.SetWildcard(f'{desc}|*{ext}')
        await trio.lowlevel.checkpoint()
        dialog.ShowModal()
        return dialog.GetPath()


DIALOG = WxDialogs(MAIN_WINDOW)
