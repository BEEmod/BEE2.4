"""Test the browser windows."""
from tkinter import ttk

import trio

import packages
from app import gameMan, lifecycle
from config.last_sel import LastSelected
from ui_tk.browsers import SoundBrowser
from ui_tk.dialogs import DIALOG
from ui_tk import TK_ROOT
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

    nursery: trio.Nursery
    btn_browse = ttk.Button(TK_ROOT, text='Browse...', command=lambda: nursery.start_soon(browse))
    btn_browse.grid()

    browser = SoundBrowser()

    async def browse() -> None:
        result = await browser.browse('Default.Null')
        print('Chosen:', result)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(browser.task)

        TK_ROOT.deiconify()
        browser.start_loading()
