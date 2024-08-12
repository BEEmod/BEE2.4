"""Implements various widget combos."""
from typing import override

from collections.abc import Sequence
from enum import Enum

import wx

from app import BaseEnumButton
from transtoken import TransToken
from trio_util import AsyncValue
from ui_wx.wid_transtoken import set_text


class EnumButton[EnumT: Enum](BaseEnumButton[wx.ToggleButton, EnumT]):
    """Provides a set of buttons for toggling between enum values.

    This is bound to the provided AsyncValue, updating it when changed.
    """
    sizer: wx.Sizer

    def __init__(
        self,
        parent: wx.Window,
        current: AsyncValue[EnumT],
        title: TransToken,
        values: Sequence[tuple[EnumT, TransToken]],
    ) -> None:
        self.frame = wx.StaticBox(parent, style=wx.ALIGN_CENTRE_HORIZONTAL)
        self.sizer = wx.StaticBoxSizer(self.frame, wx.HORIZONTAL)
        set_text(self.frame, title)

        super().__init__(current, values)

    @override
    def _ui_create(
        self,
        ind: int, label: TransToken,
        func: BaseEnumButton.EventFunc,
    ) -> wx.ToggleButton:
        """Create a button."""
        btn = wx.ToggleButton(self.frame)
        btn.Bind(wx.EVT_TOGGLEBUTTON, func)
        set_text(btn, label)
        self.sizer.Add(btn)
        return btn

    @override
    def _ui_set(self, button: wx.ToggleButton, pressed: bool, /) -> None:
        """Set the state manually."""
        button.SetValue(pressed)
