import wx

import trio

from app.dialogs import test_generic_msg, test_generic_prompt, test_generic_files
from ui_wx.dialogs import DIALOG
from ui_wx import MAIN_WINDOW


async def test(core_nursery: trio.Nursery) -> None:
    """Test the WX implementation."""
    panel = wx.Panel(MAIN_WINDOW)
    label = wx.StaticText(panel, label='Hello: |')
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(label, wx.SizerFlags().Border(wx.TOP|wx.LEFT, 25))

    btn = wx.Button(panel, label='Test messages')
    btn.Bind(wx.EVT_BUTTON, lambda evt: nursery.start_soon(test_generic_msg, DIALOG))
    sizer.Add(btn, wx.SizerFlags().Border(wx.TOP | wx.LEFT, 25))

    btn = wx.Button(panel, label='Test prompt')
    btn.Bind(wx.EVT_BUTTON, lambda evt: nursery.start_soon(test_generic_prompt, DIALOG))
    sizer.Add(btn, wx.SizerFlags().Border(wx.TOP | wx.LEFT, 25))

    btn = wx.Button(panel, label='Test file dialogs')
    btn.Bind(wx.EVT_BUTTON, lambda evt: nursery.start_soon(test_generic_files, DIALOG))
    sizer.Add(btn, wx.SizerFlags().Border(wx.TOP | wx.LEFT, 25))

    panel.SetSizer(sizer)
    MAIN_WINDOW.Layout()

    async with trio.open_nursery() as nursery:
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())

        # Prove that the event loop is running.
        while True:
            await trio.sleep(1.0)
            label.SetLabelText('Hello: -')
            await trio.sleep(1.0)
            label.SetLabelText('Hello: |')
