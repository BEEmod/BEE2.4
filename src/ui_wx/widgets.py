"""Implements various widget combos."""
from collections.abc import Callable, Sequence
from contextlib import aclosing
from enum import Enum

from transtoken import TransToken
from trio_util import AsyncValue
import wx

from ui_wx.wid_transtoken import set_text


class EnumButton[EnumT: Enum]:
    """Provides a set of buttons for toggling between enum values.

    This is bound to the provided AsyncValue, updating it when changed.
    """
    sizer: wx.Sizer
    buttons: dict[EnumT, wx.ToggleButton]
    current: AsyncValue[EnumT]

    def __init__(
        self,
        parent: wx.Window,
        current: AsyncValue[EnumT],
        values: Sequence[tuple[EnumT, TransToken]],
    ) -> None:
        self.sizer = sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.current = current
        self.buttons = {}

        for x, (val, label) in enumerate(values):
            btn = wx.ToggleButton(parent)
            btn.Bind(wx.EVT_TOGGLEBUTTON, self._pressed_func(val))
            set_text(btn, label)
            sizer.Add(btn)
            self.buttons[val] = btn

        if current.value not in self.buttons:
            raise ValueError(f'Default value {current.value!r} not present in {values!r}!')

        if len(self.buttons) != len(values):
            raise ValueError(f'No duplicates allowed, got: {values!r}')

    def _pressed_func(self, value: EnumT) -> Callable[[wx.CommandEvent], None]:
        """Create the function for a button."""
        def handler(evt: wx.CommandEvent) -> None:
            """Handle changes."""
            self.current.value = value
            wid = evt.GetEventObject()
            if isinstance(wid, wx.ToggleButton):
                wid.SetValue(True)  # Don't let it be unpressed.
        return handler

    async def task(self) -> None:
        """Task which must be run to update the button state."""
        async with aclosing(self.current.eventual_values()) as agen:
            async for chosen in agen:
                for val, button in self.buttons.items():
                    button.SetValue(val is chosen)
