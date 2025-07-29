from tkinter import ttk

import trio

from app import gameMan, img, lifecycle, sound
from trio_util import AsyncValue
from ui_tk import TK_ROOT
from ui_tk.corridor_selector import TkSelector
from ui_tk.dialogs import DIALOG
from ui_tk.img import TK_IMG
import config
import loadScreen
import packages


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)

    core_nursery.start_soon(lifecycle.lifecycle)
    await packages.LOADED.wait_transition()
    core_nursery.start_soon(img.init, TK_IMG)
    core_nursery.start_soon(sound.sound_task)
    loadScreen.main_loader.destroy()

    test_btn = ttk.Button(TK_ROOT, text='Select')
    test_btn.pack()

    test_sel = TkSelector(
        TK_IMG,
        # Will never change.
        AsyncValue(packages.PakRef(packages.Style, packages.CLEAN_STYLE)),
    )
    test_btn['command'] = test_sel.show_trigger.trigger
    core_nursery.start_soon(test_sel.task, test_btn)

    # Wait for it to exit then shutdown.
    TK_ROOT.deiconify()
    await test_sel.close_event.wait()
