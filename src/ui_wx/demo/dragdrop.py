"""Test drag-drop logic."""

from __future__ import annotations

from contextlib import aclosing

import trio
import wx

from app import img, sound
from app.dragdrop import DragInfo
from app.errors import ErrorUI
from transtoken import TransToken
from ui_wx.dragdrop import DragDrop, Slot
from ui_wx.flow_sizer import FlowSizer
from ui_wx.img import WX_IMG
from ui_wx.dialogs import DIALOG
from ui_wx import MAIN_WINDOW
import app
import BEE2_config
import config
import packages
import utils


async def test(core_nursery: trio.Nursery) -> None:
    """Test the GUI."""
    BEE2_config.GEN_OPTS.load()
    config.APP.read_file(config.APP_LOC)

    # Setup images to read from packages.
    print('Loading packages for images...')
    async with ErrorUI() as errors, trio.open_nursery() as pack_nursery:
        for loc in BEE2_config.get_package_locs():
            pack_nursery.start_soon(
                packages.find_packages,
                errors,
                packages.get_loaded_packages(),
                loc,
            )
    assert app._APP_NURSERY is not None
    await app._APP_NURSERY.start(img.init, packages.PACKAGE_SYS,  WX_IMG)
    core_nursery.start_soon(sound.sound_task)
    print('Done.')

    panel_main = wx.Panel(MAIN_WINDOW)

    left_panel = wx.Panel(panel_main)
    right_panel = wx.ScrolledWindow(panel_main)

    sizer_vert = wx.BoxSizer(wx.VERTICAL)

    sizer_main = wx.BoxSizer(wx.HORIZONTAL)
    sizer_main.Add(left_panel, wx.SizerFlags().Proportion(1).Border(wx.ALL, 25).Expand())
    sizer_main.Add(right_panel, wx.SizerFlags().Proportion(1).Border(wx.ALL, 25).Expand())

    sizer_vert.Add(sizer_main, wx.SizerFlags().Proportion(1))
    panel_main.SetSizer(sizer_vert)

    slot_dest: list[Slot[str]] = []
    slot_src: list[Slot[str]] = []

    infos: dict[str, DragInfo] = {}

    def demo_item(
        name: str,
        pak_id: utils.ObjectID,
        icon: str,
        group: str | None = None,
        group_icon: str | None = None,
    ) -> str:
        """Simple implementation of the DND protocol."""
        handle = img.Handle.parse_uri(
            utils.PackagePath(pak_id, f'items/clean/{icon}.png'),
            64, 64,
        )
        if group_icon is not None:
            group_handle = img.Handle.parse_uri(
                utils.PackagePath(pak_id, f'items/clean/{group_icon}.png'),
                64, 64,
            )
        else:
            group_handle = handle
        infos[name] = DragInfo(handle, group, group_handle)
        return name

    manager: DragDrop[str] = DragDrop(
        panel_main,
        info_cb=infos.__getitem__,
        config_icon=True,
    )

    PAK_CLEAN = utils.obj_id('BEE2_CLEAN_STYLE')
    PAK_ELEM = utils.obj_id('VALVE_TEST_ELEM')
    items = [
        demo_item('Dropper', PAK_CLEAN, 'dropper'),
        demo_item('Entry', PAK_CLEAN, 'entry_door'),
        demo_item('Exit', PAK_CLEAN, 'exit_door'),
        demo_item('Large Obs', PAK_CLEAN, 'large_obs_room'),
        demo_item('Faith Plate', PAK_ELEM, 'faithplate'),

        demo_item('Standard Cube', PAK_ELEM, 'cube', 'ITEM_CUBE', 'cubes'),
        demo_item('Companion Cube', PAK_ELEM, 'companion_cube', 'ITEM_CUBE', 'cubes'),
        demo_item('Reflection Cube', PAK_ELEM, 'reflection_cube', 'ITEM_CUBE', 'cubes'),
        demo_item('Edgeless Cube', PAK_ELEM, 'edgeless_safety_cube', 'ITEM_CUBE', 'cubes'),
        demo_item('Franken Cube', PAK_ELEM, 'frankenturret', 'ITEM_CUBE', 'cubes'),

        demo_item('Repulsion Gel', PAK_ELEM, 'paintsplat_bounce', 'ITEM_PAINT_SPLAT', 'paints'),
        demo_item('Propulsion Gel', PAK_ELEM, 'paintsplat_speed', 'ITEM_PAINT_SPLAT', 'paints'),
        demo_item('Reflection Gel', PAK_ELEM, 'paintsplat_reflection', 'ITEM_PAINT_SPLAT', 'paints'),
        demo_item('Conversion Gel', PAK_ELEM, 'paintsplat_portal', 'ITEM_PAINT_SPLAT', 'paints'),
        demo_item('Cleansing Gel', PAK_ELEM, 'paintsplat_water', 'ITEM_PAINT_SPLAT', 'paints'),
    ]

    sizer_left = wx.GridSizer(4, 8, 15)
    for y in range(8):
        for x in range(4):
            slot = manager.slot_target(
                left_panel,
                label=TransToken.untranslated('{n:00}').format(n=x + 4*y)
                if y < 3 else TransToken.BLANK
            )
            sizer_left.Add(manager.slot_widget(slot))
            slot_dest.append(slot)

    sizer_right = FlowSizer()

    FLEXI = False
    right_kind = manager.slot_flexi if FLEXI else manager.slot_source
    for i, item in enumerate(items):
        slot = right_kind(right_panel, label=TransToken.untranslated('{n:00}').format(n=i+1))
        sizer_right.Add(manager.slot_widget(slot))
        slot_src.append(slot)
        slot.contents = item

    left_panel.SetSizer(sizer_left)
    right_panel.SetSizer(sizer_right)

    def src_debug(evt: wx.Event) -> None:
        print('Source: ')
        for slot in slot_src:
            info: object = '<N/A>'
            if slot.contents is not None:
                info = manager._info_cb(slot.contents)
            print('- ', slot, slot.contents, info, manager._slot_ui[slot])
        img.refresh_all()

    sizer_btn = wx.BoxSizer(wx.HORIZONTAL)
    sizer_vert.Add(sizer_btn)
    btn = wx.Button(panel_main, label='Dests')
    btn.Bind(wx.EVT_BUTTON, lambda evt: print('Dest:', [slot.contents for slot in slot_dest]))
    sizer_btn.Add(btn)

    btn = wx.Button(panel_main, label='Sources')
    btn.Bind(wx.EVT_BUTTON, src_debug)
    sizer_btn.Add(btn)

    name_lbl = wx.StaticText(panel_main)
    sizer_btn.Add(name_lbl)

    async def handle_modified() -> None:
        """Just display when any event is triggered."""
        async for _ in manager.on_modified.events():
            print('On modified')

    async def handle_flexi_flow() -> None:
        """Just display when any event is triggered."""
        async for _ in manager.on_flexi_flow.events():
            print('On Flexi Flow')

    async def update_hover_text() -> None:
        """Update the hovered text."""
        async with aclosing(manager.hovered_item.eventual_values()) as agen:
            async for item in agen:
                if item is not None:
                    name_lbl.SetLabelText(f'Name: {item}')
                else:
                    name_lbl.SetLabelText('No hover')

    async def handle_config() -> None:
        """Respond to items being right-clicked."""
        trans_title = TransToken.untranslated('Hello World')
        trans_slot = TransToken.untranslated('Slot: "{slot}"')
        while True:
            slot = await manager.on_config.wait()
            await DIALOG.show_info(
                title=trans_title,
                message=trans_slot.format(slot=slot.contents),
            )

    MAIN_WINDOW.Layout()
    manager.load_icons()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(update_hover_text)
        nursery.start_soon(handle_config)
        nursery.start_soon(handle_modified)
        nursery.start_soon(handle_flexi_flow)
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())
        MAIN_WINDOW.CenterOnScreen()
        await trio.sleep_forever()
