from __future__ import annotations
from tkinter import messagebox, ttk
import tkinter as tk

from contextlib import aclosing

import trio

from app import img, sound
from app.dragdrop import DragInfo
from app.errors import ErrorUI
from transtoken import TransToken
from ui_tk.dragdrop import DragDrop
from ui_tk.img import TK_IMG
from ui_tk import TK_ROOT
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
    await app._APP_NURSERY.start(img.init,  TK_IMG)
    core_nursery.start_soon(sound.sound_task)
    print('Done.')

    left_frm = ttk.Frame(TK_ROOT)
    right_canv = tk.Canvas(TK_ROOT)

    left_frm.grid(row=0, column=0, sticky='NSEW', padx=8)
    right_canv.grid(row=0, column=1, sticky='NSEW', padx=8)
    TK_ROOT.rowconfigure(0, weight=1)
    TK_ROOT.columnconfigure(1, weight=1)

    slot_dest = []
    slot_src = []

    infos = {}

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
        TK_ROOT,
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

    for y in range(8):
        for x in range(4):
            slot = manager.slot_target(
                left_frm,
                label=TransToken.untranslated('{n:00}').format(n=x + 4*y)
                if y < 3 else TransToken.BLANK
            )
            manager.slot_grid(slot, column=x, row=y, padx=1, pady=1)
            slot_dest.append(slot)

    FLEXI = False
    right_kind = manager.slot_flexi if FLEXI else manager.slot_source
    for i, item in enumerate(items):
        slot = right_kind(right_canv, label=TransToken.untranslated('{n:00}').format(n=i+1))
        slot_src.append(slot)
        slot.contents = item

    def configure(e: tk.Event[tk.Canvas] | None) -> None:
        """Reflow slots when the window resizes."""
        manager.flow_slots(right_canv, slot_src)

    configure(None)
    right_canv.bind('<Configure>', configure)

    def src_debug() -> None:
        print('Source: ')
        for slot in slot_src:
            info: object = '<N/A>'
            if slot.contents is not None:
                info = manager._info_cb(slot.contents)
            print('- ', slot, slot.contents, info, manager._slot_ui[slot])
        img.refresh_all()

    ttk.Button(
        TK_ROOT,
        text='Debug',
        command=lambda: print('Dest:', [slot.contents for slot in slot_dest])
    ).grid(row=2, column=0)
    ttk.Button(
        TK_ROOT,
        text='Debug',
        command=src_debug,
        # command=lambda: print('Source:', [slot.contents for slot in slot_src])
    ).grid(row=2, column=1)

    name_lbl = ttk.Label(TK_ROOT, text='')
    name_lbl.grid(row=3, column=0)

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
                    name_lbl['text'] = 'Name: ' + item
                else:
                    name_lbl['text'] = ''

    async def handle_config() -> None:
        """Respond to items being right-clicked."""
        while True:
            slot = await manager.on_config.wait()
            messagebox.showinfo('Hello World', slot.contents)

    manager.load_icons()

    with trio.CancelScope() as scope:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(update_hover_text)
            nursery.start_soon(handle_config)
            nursery.start_soon(handle_modified)
            nursery.start_soon(handle_flexi_flow)
            TK_ROOT.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
            TK_ROOT.deiconify()
            await trio.sleep_forever()
