import wx

import trio

from app.dialogs import test_generic
from ui_wx.dialogs import DIALOG
from ui_wx import MAIN_WINDOW


async def test(core_nursery: trio.Nursery) -> None:
    """Test the WX implementation."""
    panel = wx.Panel(MAIN_WINDOW)
    label = wx.StaticText(panel, label='Hello: |')
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(label, wx.SizerFlags().Border(wx.TOP|wx.LEFT, 25))
    panel.SetSizer(sizer)
    MAIN_WINDOW.Layout()

    scope = trio.CancelScope()

    async def ticker() -> None:
        """Prove that the event loop is running."""
        with scope:
            while True:
                await trio.sleep(1.0)
                label.SetLabelText('Hello: -')
                await trio.sleep(1.0)
                label.SetLabelText('Hello: |')

    async with trio.open_nursery() as nursery:
        nursery.start_soon(ticker)
        await test_generic(DIALOG)
        scope.cancel()
