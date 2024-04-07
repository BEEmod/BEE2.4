import trio

import BEE2_config
import config
import loadScreen
import packages
from app import background_run, gameMan, img, sound
from app.errors import ErrorUI
from exporting import mod_support

from ui_tk.corridor_selector import TkSelector
from ui_tk.img import TK_IMG
from ui_tk.dialogs import DIALOG


async def test() -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)
    mod_support.scan_music_locs(packages.get_loaded_packages(), gameMan.all_games)
    async with ErrorUI() as errors:
        await packages.load_packages(
            packages.get_loaded_packages(),
            list(BEE2_config.get_package_locs()),
            errors,
        )
    background_run(img.init, packages.PACKAGE_SYS, TK_IMG)
    background_run(sound.sound_task)
    loadScreen.main_loader.destroy()

    test_sel = TkSelector(packages.get_loaded_packages(), TK_IMG, packages.CLEAN_STYLE)
    background_run(test_sel.task)

    # Wait for it to be ready, trigger, wait for it to exit then shutdown.
    await test_sel.show_trigger.ready.wait_value(True)
    test_sel.show_trigger.trigger()
    await test_sel.close_event.wait()
