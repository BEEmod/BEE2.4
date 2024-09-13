import trio

from app import gameMan, img, lifecycle, sound
from async_util import EdgeTrigger
from ui_tk.corridor_selector import TkSelector
from ui_tk.dialogs import DIALOG
from ui_tk.img import TK_IMG
import config
import exporting
import loadScreen
import packages


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)

    export_trig = EdgeTrigger[exporting.ExportInfo]()
    export_send, export_rec = trio.open_memory_channel[lifecycle.ExportResult](1)

    core_nursery.start_soon(lifecycle.lifecycle)
    packset, _ = await packages.LOADED.wait_transition()
    core_nursery.start_soon(img.init, TK_IMG)
    core_nursery.start_soon(sound.sound_task)
    loadScreen.main_loader.destroy()

    test_sel = TkSelector(packages.get_loaded_packages(), TK_IMG, packages.CLEAN_STYLE)
    core_nursery.start_soon(test_sel.task)

    # Wait for it to be ready, trigger, wait for it to exit then shutdown.
    await test_sel.show_trigger.ready.wait_value(True)
    test_sel.show_trigger.trigger()
    await test_sel.close_event.wait()
