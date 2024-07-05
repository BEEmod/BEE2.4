"""Test interaction between a wrapped sizer and a scrolling window."""
import wx

import trio

from ui_wx import MAIN_WINDOW, get_scrollflow_size_handler


async def test(core_nursery: trio.Nursery) -> None:
    """Test wx.ScrolledWindow + wx.WrapSizer works."""
    panel = wx.ScrolledWindow(MAIN_WINDOW, style=wx.VSCROLL)
    sizer = wx.WrapSizer()
    panel.SetSizer(sizer)
    panel.SetScrollRate(0, 10)
    MAIN_WINDOW.Bind(wx.EVT_SIZE, get_scrollflow_size_handler(panel, sizer))

    for i in range(1, 101):
        await trio.sleep(0)
        label = wx.StaticText(panel, label=f'Item {i:02}')
        sizer.Add(label, wx.SizerFlags().TripleBorder())
        sizer.Layout()

    MAIN_WINDOW.Layout()

    async with trio.open_nursery() as nursery:
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())
        await trio.sleep_forever()
