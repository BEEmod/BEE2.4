import trio

import exporting
from app import EdgeTrigger, gameMan, img, lifecycle, sound
from ui_wx.corridor_selector import WxSelector
from ui_wx.dialogs import DIALOG
from ui_wx.img import WX_IMG
import BEE2_config
import config
import loadScreen
import packages


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)

    export_trig = EdgeTrigger[exporting.ExportInfo]()
    export_send, export_rec = trio.open_memory_channel[lifecycle.ExportResult](1)

    core_nursery.start_soon(
        lifecycle.lifecycle,
        EdgeTrigger[()](),  # Never reload.
        export_trig,
        export_send,
    )
    packset, _ = await packages.LOADED.wait_transition()
    core_nursery.start_soon(img.init, WX_IMG)
    core_nursery.start_soon(sound.sound_task)
    loadScreen.main_loader.destroy()

    test_sel = WxSelector(packages.get_loaded_packages(), WX_IMG, packages.CLEAN_STYLE)
    core_nursery.start_soon(test_sel.task)

    # Wait for it to be ready, trigger, wait for it to exit then shutdown.
    await test_sel.show_trigger.ready.wait_value(True)
    test_sel.show_trigger.trigger()
    await test_sel.close_event.wait()
