from trio_util import AsyncValue
import trio
import wx

from app import gameMan, img, lifecycle, sound
from ui_wx import MAIN_WINDOW
from ui_wx.corridor_selector import WxSelector
from ui_wx.dialogs import DIALOG
from ui_wx.img import WX_IMG
import config
import loadScreen
import packages


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)

    core_nursery.start_soon(lifecycle.lifecycle)
    packset, _ = await packages.LOADED.wait_transition()
    core_nursery.start_soon(img.init, WX_IMG)
    core_nursery.start_soon(sound.sound_task)
    loadScreen.main_loader.destroy()

    panel_main = wx.Panel(MAIN_WINDOW)
    sizer_main = wx.BoxSizer(wx.VERTICAL)
    panel_main.SetSizer(sizer_main)

    test_sel: WxSelector
    button = wx.Button(panel_main, label='Select')
    button.SetMinSize((256, 32))
    button.Bind(wx.EVT_BUTTON, lambda evt: test_sel.show_trigger.trigger())
    sizer_main.Add(button)

    MAIN_WINDOW.Layout()

    test_sel = WxSelector(
        WX_IMG,
        # Will never change.
        AsyncValue(packages.PakRef(packages.Style, packages.CLEAN_STYLE)),
    )
    core_nursery.start_soon(test_sel.task, button)

    # Wait for it to exit then shutdown.
    await test_sel.close_event.wait()
