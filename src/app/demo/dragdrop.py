from __future__ import annotations

from typing import Awaitable, Callable

import trio
import tkinter as tk

from tkinter import messagebox, ttk

import utils
from app import background_run, img, sound
from app import TK_ROOT
import BEE2_config
import config
import packages
from app.dragdrop import DragInfo, Event, Slot
from transtoken import TransToken
from ui_tk.dragdrop import DragDrop
from ui_tk.img import TK_IMG


async def test() -> None:
    """Test the GUI."""
    BEE2_config.GEN_OPTS.load()
    config.APP.read_file()

    # Setup images to read from packages.
    print('Loading packages for images.')
    async with trio.open_nursery() as pack_nursery:
        for loc in BEE2_config.get_package_locs():
            pack_nursery.start_soon(
                packages.find_packages,
                pack_nursery,
                packages.get_loaded_packages(),
                loc,
            )
    background_run(img.init, packages.PACKAGE_SYS,  TK_IMG)
    background_run(sound.sound_task)
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
        pak_id: str,
        icon: str,
        group: str=None,
        group_icon: str=None,
    ) -> str:
        """Simple implementation of the DND protocol."""
        icon = img.Handle.parse_uri(
            utils.PackagePath(pak_id, f'items/clean/{icon}.png'),
            64, 64,
        )
        if group_icon is not None:
            group_handle = img.Handle.parse_uri(
                utils.PackagePath(pak_id,f'items/clean/{group_icon}.png'),
                64, 64,
            )
        else:
            group_handle = None
        infos[name] = DragInfo(icon, group, group_handle)
        return name

    manager: DragDrop[str] = DragDrop(
        TK_ROOT,
        info_cb=infos.__getitem__,
        config_icon=True,
    )

    def func(ev: Event) -> Callable[[Slot[str]], Awaitable[object]]:
        """Ensure each callback is bound in a different scope."""
        async def call(slot: Slot[str]) -> None:
            """Just display when any event is triggered."""
            print('Cback: ', ev, slot)
        return call

    for evt in Event:
        manager.event_bus.register(evt, Slot[str], func(evt))

    PAK_CLEAN = 'BEE2_CLEAN_STYLE'
    PAK_ELEM = 'VALVE_TEST_ELEM'
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

    ttk.Button(
        TK_ROOT,
        text='Debug',
        command=lambda: print('Dest:', [slot.contents for slot in slot_dest])
    ).grid(row=2, column=0)
    ttk.Button(
        TK_ROOT,
        text='Debug',
        command=lambda: print('Source:', [slot.contents for slot in slot_src])
    ).grid(row=2, column=1)

    name_lbl = ttk.Label(TK_ROOT, text='')
    name_lbl.grid(row=3, column=0)

    async def evt_enter(evt_slot: Slot[str]) -> None:
        if evt_slot.contents is not None:
            name_lbl['text'] = 'Name: ' + evt_slot.contents

    async def evt_exit(evt_slot: Slot[str]) -> None:
        name_lbl['text'] = ''

    async def evt_config(evt_slot: Slot[str]) -> None:
        messagebox.showinfo('Hello World', evt_slot.contents)

    manager.event_bus.register(Event.HOVER_ENTER, Slot[str], evt_enter)
    manager.event_bus.register(Event.HOVER_EXIT, Slot[str], evt_exit)
    manager.event_bus.register(Event.CONFIG, Slot[str], evt_config)

    TK_ROOT.deiconify()
    with trio.CancelScope() as scope:
        TK_ROOT.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
        await trio.sleep_forever()
