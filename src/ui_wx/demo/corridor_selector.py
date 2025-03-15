import trio

from app import gameMan, img, lifecycle, sound
from trio_util import AsyncValue
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

    test_sel = WxSelector(
        WX_IMG,
        # Will never change.
        AsyncValue(packages.PakRef(packages.Style, packages.CLEAN_STYLE)),
    )
    core_nursery.start_soon(test_sel.task)

    # Wait for it to be ready, trigger, wait for it to exit then shutdown.
    await test_sel.show_trigger.ready.wait_value(True)
    test_sel.show_trigger.trigger()
    await test_sel.close_event.wait()
