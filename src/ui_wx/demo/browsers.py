"""Test the browser windows."""

from __future__ import annotations

import trio
import wx

import packages
from app import gameMan, lifecycle
from config.last_sel import LastSelected
from ui_wx.browsers import SoundBrowser
from ui_wx.dialogs import DIALOG
from ui_wx import MAIN_WINDOW
import BEE2_config
import config


async def test(core_nursery: trio.Nursery) -> None:
    """Test the GUI."""
    BEE2_config.GEN_OPTS.load()
    config.APP.read_file(config.APP_LOC)

    await gameMan.load(DIALOG)
    try:
        last_game = config.APP.get_cur_conf(LastSelected, 'game')
    except KeyError:
        pass
    else:
        gameMan.set_game_by_name(last_game.id)

    core_nursery.start_soon(lifecycle.lifecycle)
    await packages.LOADED.wait_transition()

    panel_main = wx.Panel(MAIN_WINDOW)
    sizer_main = wx.BoxSizer(wx.VERTICAL)

    btn_browse = wx.Button(panel_main, wx.ID_OPEN)
    btn_browse.Bind(wx.EVT_BUTTON, lambda evt: nursery.start_soon(browse))
    sizer_main.Add(btn_browse)

    browser = SoundBrowser()

    async def browse() -> None:
        result = await browser.browse('Default.Null')
        print('Chosen:', result)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(browser.task)

        MAIN_WINDOW.Layout()
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())
        MAIN_WINDOW.CenterOnScreen()
        browser.start_loading()
