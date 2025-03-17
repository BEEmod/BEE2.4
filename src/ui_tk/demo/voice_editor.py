from tkinter import ttk

import trio

from app import gameMan, img, lifecycle
from packages import QuotePack
from ui_tk import TK_ROOT
from ui_tk.dialogs import DIALOG
from ui_tk.img import TK_IMG
import config
import loadScreen
import packages
from ui_tk.voice_editor import VoiceEditor


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)

    core_nursery.start_soon(lifecycle.lifecycle)
    packset, _ = await packages.LOADED.wait_transition()
    core_nursery.start_soon(img.init, TK_IMG)
    loadScreen.main_loader.destroy()

    editor = VoiceEditor()
    core_nursery.start_soon(editor.task)

    def make_button(x: int, y: int, voice: QuotePack) -> None:
        btn = ttk.Button(
            TK_ROOT, text=str(voice.selitem_data.name),
            command=lambda: editor.evt_open.trigger(voice)
        )
        btn.grid(row=y, column=x)

    for i, voice in enumerate(packset.all_obj(QuotePack)):
        y, x = divmod(i, 5)
        make_button(x, y, voice)

    TK_ROOT.wm_deiconify()
    await trio.sleep_forever()
