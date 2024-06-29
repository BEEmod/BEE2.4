"""Demonstrate the flow sizer."""
import wx

import trio

from ui_wx.flow_sizer import FlowSizer
from ui_wx import MAIN_WINDOW


async def test(core_nursery: trio.Nursery) -> None:
    """Test the flow sizer."""
    panel = wx.ScrolledWindow(MAIN_WINDOW, style=wx.VSCROLL)
    sizer = FlowSizer(25)
    panel.SetSizer(sizer)
    MAIN_WINDOW.Layout()

    for i in range(1, 101):
        await trio.sleep(0)
        label = wx.StaticText(panel, label=f'Item {i:02}')
        sizer.Add(label)
        sizer.Layout()

    await trio.sleep_forever()
