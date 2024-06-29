"""Demonstrate the flow sizer."""
import wx

import trio

from ui_wx.flow_sizer import FlowSizer
from ui_wx import MAIN_WINDOW


async def test(core_nursery: trio.Nursery) -> None:
    """Test the flow sizer."""
    panel = wx.Panel(MAIN_WINDOW)
    sizer = FlowSizer(25)
    panel.SetSizer(sizer)

    for i in range(1, 101):
        await trio.sleep(0)
        label = wx.StaticText(panel, label=f'Item {i:02}')
        sizer.Add(label)
        sizer.Layout()

    await trio.sleep_forever()
