"""Test the signage UI."""

from __future__ import annotations

import trio
import wx

from app import img, lifecycle, sound
from app.errors import ErrorUI
from ui_wx.img import WX_IMG
from ui_wx.signage_ui import SignageUI
from ui_wx import MAIN_WINDOW
import app
import BEE2_config
import config
import packages


async def test(core_nursery: trio.Nursery) -> None:
    """Test the GUI."""
    BEE2_config.GEN_OPTS.load()
    config.APP.read_file(config.APP_LOC)

    print('Loading packages...')
    async with ErrorUI() as errors, trio.open_nursery() as pack_nursery:
        for loc in BEE2_config.get_package_locs():
            pack_nursery.start_soon(
                packages.find_packages,
                errors,
                packages.get_loaded_packages(),
                loc,
            )

    core_nursery.start_soon(lifecycle.lifecycle)
    await packages.LOADED.wait_transition()
    await core_nursery.start(img.init, WX_IMG)
    core_nursery.start_soon(sound.sound_task)
    print('Done.')

    panel_main = wx.Panel(MAIN_WINDOW)
    sizer_main = wx.BoxSizer(wx.VERTICAL)
    panel_main.SetSizer(sizer_main)

    signage_trigger: app.EdgeTrigger[()] = app.EdgeTrigger()
    sign_ui = SignageUI(WX_IMG)
    core_nursery.start_soon(sign_ui.task, signage_trigger)

    button_sign = wx.Button(panel_main, label='Select Signage')
    button_sign.Bind(wx.EVT_BUTTON, lambda evt: signage_trigger.trigger())
    sizer_main.Add(button_sign)

    MAIN_WINDOW.Layout()

    async with trio.open_nursery() as nursery:
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())
        MAIN_WINDOW.CenterOnScreen()
        async for enabled in signage_trigger.ready.eventual_values():
            button_sign.Enable(enabled)
