import trio

import BEE2_config
import config
import loadScreen
import packages
from app import background_run, img, sound

from ui_tk.corridor_selector import TkSelector
from ui_tk.dialogs import DIALOG
from ui_tk.img import TK_IMG


async def test() -> None:
    config.APP.read_file()
    await packages.load_packages(
        packages.get_loaded_packages(),
        list(BEE2_config.get_package_locs()),
        DIALOG,
    )
    background_run(img.init, packages.PACKAGE_SYS, TK_IMG)
    background_run(sound.sound_task)
    loadScreen.main_loader.destroy()

    test_sel = TkSelector(packages.get_loaded_packages(), TK_IMG)
    await test_sel.show()
    with trio.CancelScope() as scope:
        test_sel.win.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
        await trio.sleep_forever()
