import trio
import wx

from app import gameMan, img, lifecycle
from packages import QuotePack
from ui_wx import MAIN_WINDOW
from ui_wx.dialogs import DIALOG
from ui_wx.img import WX_IMG
import config
import loadScreen
import packages

from ui_wx.voice_editor import VoiceEditor


async def test(core_nursery: trio.Nursery) -> None:
    config.APP.read_file(config.APP_LOC)
    await gameMan.load(DIALOG)

    core_nursery.start_soon(lifecycle.lifecycle)
    packset, _ = await packages.LOADED.wait_transition()
    core_nursery.start_soon(img.init, WX_IMG)
    loadScreen.main_loader.destroy()

    editor = VoiceEditor()
    core_nursery.start_soon(editor.task)

    sizer = wx.WrapSizer()

    def make_button(voice: QuotePack) -> None:
        btn = wx.Button(
            MAIN_WINDOW, label=str(voice.selitem_data.name),
        )
        btn.Bind(wx.EVT_BUTTON, lambda e: editor.evt_open.trigger(voice))
        sizer.Add(btn)

    for voice in packset.all_obj(QuotePack):
        make_button(voice)

    MAIN_WINDOW.SetMinSize((500, 200))
    MAIN_WINDOW.SetSizer(sizer)
    MAIN_WINDOW.Layout()
    await trio.sleep_forever()
