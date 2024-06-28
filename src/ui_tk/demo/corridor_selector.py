import trio

from app import gameMan, img, sound
from app.errors import ErrorUI
from exporting import mod_support
from ui_tk.corridor_selector import TkSelector
from ui_tk.dialogs import DIALOG
from ui_tk.img import TK_IMG
import BEE2_config
import config
import loadScreen
import packages


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)
    mod_support.scan_music_locs(packages.get_loaded_packages(), gameMan.all_games)
    async with ErrorUI() as errors:
        await packages.load_packages(
            packages.get_loaded_packages(),
            list(BEE2_config.get_package_locs()),
            errors,
        )
    core_nursery.start_soon(img.init, packages.PACKAGE_SYS, TK_IMG)
    core_nursery.start_soon(sound.sound_task)
    loadScreen.main_loader.destroy()

    test_sel = TkSelector(packages.get_loaded_packages(), TK_IMG, packages.CLEAN_STYLE)
    core_nursery.start_soon(test_sel.task)

    # Wait for it to be ready, trigger, wait for it to exit then shutdown.
    await test_sel.show_trigger.ready.wait_value(True)
    test_sel.show_trigger.trigger()
    await test_sel.close_event.wait()
