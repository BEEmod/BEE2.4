import trio

from app import gameMan, img, lifecycle, sound
from trio_util import AsyncValue
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

    test_sel = TkSelector(
        TK_IMG,
        # Will never change.
        AsyncValue(packages.PakRef(packages.Style, packages.CLEAN_STYLE)),
    )
    core_nursery.start_soon(test_sel.task)

    # Wait for it to be ready, trigger, wait for it to exit then shutdown.
    await test_sel.show_trigger.ready.wait_value(True)
    test_sel.show_trigger.trigger()
    await test_sel.close_event.wait()
