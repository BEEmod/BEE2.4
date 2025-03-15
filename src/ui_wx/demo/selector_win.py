"""Test selectorwin."""
from srctools import FileSystemChain
import trio
import wx

import utils
from transtoken import TransToken
from app import img, lifecycle, sound
from consts import MusicChannel
import packages
import BEE2_config
import config

from ui_wx import MAIN_WINDOW
from ui_wx.img import WX_IMG
from ui_wx.selector_win import SelectorWin, Options as SelOptions


async def test(core_nursery: trio.Nursery) -> None:
    """Test the SelectorWin window."""
    BEE2_config.GEN_OPTS.load()
    config.APP.read_file(config.APP_LOC)

    core_nursery.start_soon(lifecycle.lifecycle)
    packset, _ = await packages.LOADED.wait_transition()

    # Setup images to read from packages.
    await core_nursery.start(img.init,  WX_IMG)
    core_nursery.start_soon(sound.sound_task)
    print('Done.')

    sizer = wx.BoxSizer(wx.VERTICAL)

    filesystem = FileSystemChain()
    for pack in packset.packages.values():
        filesystem.add_sys(pack.fsys, prefix='resources/music_samp/')

    selector = SelectorWin(MAIN_WINDOW, SelOptions(
        func_get_ids=packages.Music.music_for_channel(MusicChannel.BASE),
        func_get_data=packages.Music.selector_data_getter(packages.SelitemData.build(
            small_icon=packages.NONE_ICON,
            short_name=TransToken.BLANK,
            long_name=packages.TRANS_NONE_NAME,
            desc=TransToken.ui(
                'Add no music to the map at all. Testing Element-specific music may still be added.'
            ),
        )),
        save_id='music_base',
        title=TransToken.ui('Select Background Music - Base'),
        desc=TransToken.ui(
            'This controls the background music used for a map. Expand the dropdown to set tracks '
            'for specific test elements.'
        ),
        default_id=utils.obj_id('VALVE_PETI'),
        func_get_sample=packages.Music.sample_getter_func(MusicChannel.BASE),
        sound_sys=filesystem,
        func_get_attr=packages.Music.get_base_selector_attrs,
        attributes=[
            packages.AttrDef.bool('SPEED', TransToken.ui('Propulsion Gel SFX')),
            packages.AttrDef.bool('BOUNCE', TransToken.ui('Repulsion Gel SFX')),
            packages.AttrDef.bool('TBEAM', TransToken.ui('Excursion Funnel Music')),
            packages.AttrDef.bool('TBEAM_SYNC', TransToken.ui('Synced Funnel Music')),
        ],
    ))

    def set_sugg(evt: wx.Event) -> None:
        selector.set_suggested(selector.item_list[::2])

    async with trio.open_nursery() as nursery:
        nursery.start_soon(selector.task)
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())

        sizer.Add(await selector.widget(MAIN_WINDOW))

        sugg = wx.Button(MAIN_WINDOW, label='Set suggested')
        sugg.Bind(wx.EVT_BUTTON, set_sugg)
        sizer.Add(sugg)

        MAIN_WINDOW.SetSizerAndFit(sizer)
        MAIN_WINDOW.Layout()

        MAIN_WINDOW.Show()
        await trio.sleep_forever()
