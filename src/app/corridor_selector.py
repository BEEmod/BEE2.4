"""Implements UI for selecting corridors."""
from tkinter import ttk
import tkinter as tk
from typing import List

import srctools.logger
import trio

import event
import packages
from app import TK_ROOT, background_run, config, dragdrop, img, sound, tk_tools
from app.richTextBox import tkRichText
from localisation import gettext
from packages import corridor
from corridor import GameMode, Direction, Orient


LOGGER = srctools.logger.get_logger(__name__)
WIDTH = corridor.IMG_WIDTH_SML + 16
HEIGHT = corridor.IMG_HEIGHT_SML + 16
ICON_BLANK = img.Handle.blank(corridor.IMG_WIDTH_LRG, corridor.IMG_HEIGHT_LRG)


# If no groups are defined for a style, use this.
FALLBACK = corridor.CorridorGroup(
    '<Fallback>',
    {
        (mode, direction, orient): []
        for mode in GameMode
        for direction in Direction
        for orient in Orient
    }
)


class Selector:
    """Corridor selection UI."""
    win: tk.Toplevel
    drag_man: dragdrop.Manager[corridor.Corridor]

    # Current corridor on the right side.
    wid_image: ttk.Label
    wid_title: ttk.Label
    wid_desc: tkRichText

    # The 7 selected slots, and the rest.
    selected: List[dragdrop.Slot[corridor.Corridor]]
    unused: List[dragdrop.Slot[corridor.Corridor]]

    # The current corridor group for the selected style, and the config ID to save/load.
    # These are updated by load_corridors().
    corr_group: corridor.CorridorGroup
    conf_id: str

    def __init__(self, packset: packages.PackagesSet) -> None:
        self.win = tk.Toplevel(TK_ROOT)
        self.win.withdraw()
        self.win.wm_protocol("WM_DELETE_WINDOW", self.hide)

        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)

        frm_left = ttk.Frame(self.win)
        frm_left.grid(row=0, column=0, sticky='nsew')

        frm_right = ttk.Frame(self.win)
        frm_right.columnconfigure(0, weight=1)
        frm_right.grid(row=0, column=1, sticky='ns')

        self.wid_image = ttk.Label(frm_right)
        self.wid_image.grid(row=0, column=0, sticky='ew')
        img.apply(self.wid_image, ICON_BLANK)

        self.wid_title = ttk.Label(frm_right, text='Corridor')
        self.wid_title.grid(row=1, column=0, sticky='ew')

        self.wid_desc = tkRichText(frm_right)
        self.wid_desc.grid(row=2, column=0, sticky='nsew')
        frm_right.rowconfigure(2, weight=1)

        ttk.Button(frm_right, text=gettext('Close'), command=self.hide).grid(row=3, column=0)

        self.events = event.EventManager()

        button_frm = ttk.Frame(frm_left)
        button_frm.grid(row=0, column=0, columnspan=3)
        self.btn_mode = tk_tools.EnumButton(
            button_frm, self.events,
            (GameMode.SP, gettext('SP')),
            (GameMode.COOP, gettext('Coop')),
        )
        self.btn_direction = tk_tools.EnumButton(
            button_frm, self.events,
            (Direction.ENTRY, gettext('Entry')),
            (Direction.EXIT, gettext('Exit')),
        )
        self.btn_orient = tk_tools.EnumButton(
            button_frm, self.events,
            (Orient.FLAT, gettext('Flat')),
            (Orient.UP, gettext('Upward')),
            (Orient.DN, gettext('Downward')),
        )
        self.btn_mode.frame.grid(row=0, column=0, padx=8)
        self.btn_direction.frame.grid(row=0, column=1, padx=8)
        self.btn_orient.frame.grid(row=0, column=2, padx=8)
        refresh = self.refresh
        self.events.register(self.btn_mode, GameMode, refresh)
        self.events.register(self.btn_direction, Direction, refresh)
        self.events.register(self.btn_orient, Orient, refresh)

        canv_frame = ttk.Frame(frm_left, relief="sunken")
        canv_frame.grid(row=1, column=0, columnspan=3, sticky='nsew', ipadx=8, ipady=8)
        canv_frame.rowconfigure(0, weight=1)
        canv_frame.columnconfigure(0, weight=1)
        frm_left.columnconfigure(0, weight=1)
        frm_left.rowconfigure(1, weight=1)

        self.canvas = tk.Canvas(canv_frame)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(canv_frame, orient='vertical', command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas['yscrollcommand'] = scrollbar.set
        self.unsel_div = self.canvas.create_line(
            0, 0, 1024, 0,
            width=2,
            fill='black',
        )

        reflow = self.reflow  # Avoid making self a cell var.
        self.canvas.bind('<Configure>', lambda e: background_run(reflow))

        self.drag_man = drop = dragdrop.Manager(self.win, size=(WIDTH, HEIGHT))
        drop.event.register(
            dragdrop.Event.HOVER_ENTER, dragdrop.Slot[corridor.Corridor],
            self.show_corr,
        )
        drop.event.register(
            dragdrop.Event.FLEXI_FLOW, dragdrop.Slot[corridor.Corridor],
            self.reflow,
        )
        drop.event.register(dragdrop.Event.MODIFIED, None, self._on_changed)
        self.selected = [
            drop.slot_target(self.canvas)
            for _ in range(7)
        ]
        self.unused_count = 0
        self.load_corridors(packset)

    def show(self) -> None:
        """Display the window."""
        self.drag_man.load_icons()
        self.win.deiconify()

    def hide(self) -> None:
        """Hide the window."""
        self.win.withdraw()
        self.drag_man.unload_icons()

    async def _on_changed(self, _: None) -> None:
        """Store configuration when changed."""
        selected = [
            slot.contents.instance.casefold() if slot.contents is not None else ''
            for slot in self.selected
        ]
        config.store_conf(corridor.Config(selected), self.conf_id)

    def load_corridors(self, packset: packages.PackagesSet) -> None:
        """Fetch the current set of corridors from this style."""
        style_id = config.get_cur_conf(
            config.LastSelected, 'styles',
            config.LastSelected('BEE2_CLEAN'),
        ).id or 'BEE2_CLEAN'
        try:
            self.corr_group = packset.obj_by_id(corridor.CorridorGroup, style_id)
        except KeyError:
            LOGGER.warning('No corridors defined for style "{}"', style_id)
            self.corr_group = FALLBACK
        self.conf_id = corridor.Config.get_id(
            style_id,
            self.btn_mode.current,
            self.btn_direction.current,
            self.btn_orient.current,
        )

    async def refresh(self, _=None) -> None:
        """Called to update the slots with new items if the corridor set changes."""
        mode = self.btn_mode.current
        direction = self.btn_direction.current
        orient = self.btn_orient.current
        self.conf_id = corridor.Config.get_id(self.corr_group.id, mode, direction, orient)
        conf = config.get_cur_conf(corridor.Config, self.conf_id, corridor.Config())

        try:
            corr_list = self.corr_group.corridors[mode, direction, orient]
        except KeyError:
            # Up/down can have missing ones.
            if orient is Orient.HORIZONTAL:
                LOGGER.warning(
                    'No flat corridor for {}:{}_{}!',
                    self.corr_group.id, mode.value, direction.value,
                )
            corr_list = []

        # Ensure enough flexible slots exist to hold all of them, and clear em all.
        for slot in self.drag_man.all_slots():
            slot.contents = None
        for _ in range(len(corr_list) - self.unused_count):
            self.drag_man.slot_flexi(self.canvas)
        self.unused_count = len(corr_list)
        # Never fill the invisible slots.
        fillable = self.selected[:corridor.CORRIDOR_COUNTS[mode, direction]]

        inst_to_corr = {corr.instance.casefold(): corr for corr in corr_list}
        if conf.selected:
            for slot, sel_id in zip(fillable, conf.selected):
                if not sel_id:
                    continue
                try:
                    slot.contents = inst_to_corr.pop(sel_id.casefold())
                except KeyError:
                    LOGGER.warning('Unknown corridor instance "{}" in config!')
        else:
            # No configuration, populate with the defaults.
            for slot, corr in zip(fillable, self.corr_group.defaults(mode, direction, orient)):
                slot.contents = corr
                del inst_to_corr[corr.instance.casefold()]

        # Put all remaining in flexi slots.
        for slot, corr in zip(
            self.drag_man.flexi_slots(),
            sorted(inst_to_corr.values(), key=lambda corr: corr.name),
        ):
            slot.contents = corr
        self.drag_man.load_icons()

        # Reset item display, it's invalid.
        img.apply(self.wid_image, ICON_BLANK)
        self.wid_title['text'] = ''
        self.wid_desc.set_text(corridor.EMPTY_DESC)
        # Reposition everything.
        await self.reflow()

    async def reflow(self, _=None) -> None:
        """Called to reposition the corridors."""
        count = corridor.CORRIDOR_COUNTS[self.btn_mode.current, self.btn_direction.current]
        # The first item is always visible.
        yoff = self.drag_man.flow_slots(self.canvas, self.selected[:1], tag='sel_1')
        if count >= 4:
            yoff = self.drag_man.flow_slots(self.canvas, self.selected[1:4], tag='sel_2', yoff=yoff)
        else:
            self.canvas.delete('sel_2')
        if count >= 7:
            yoff = self.drag_man.flow_slots(self.canvas, self.selected[4:], tag='sel_3', yoff=yoff)
        else:
            self.canvas.delete('sel_3')

        yoff += 16
        self.canvas.coords(self.unsel_div, 8, yoff, self.canvas.winfo_width()-16, yoff)
        yoff += 16

        self.drag_man.flow_slots(
            self.canvas, (
                slot for slot in
                self.drag_man.flexi_slots()
                if slot.contents is not None
            ),
            yoff=yoff,
            tag='unselected',
        )

    async def show_corr(self, slot: dragdrop.Slot[corridor.Corridor]) -> None:
        """Display the specified corridor on hover."""
        if slot.contents is not None:
            corr = slot.contents
            if corr.images:
                img.apply(self.wid_image, corr.images[0])
            else:
                img.apply(self.wid_image, corridor.ICON_GENERIC_LRG)
            self.wid_title['text'] = corr.name
            self.wid_desc.set_text(corr.desc)


async def test() -> None:
    from app import background_run
    background_run(img.init, {})
    background_run(sound.sound_task)

    test_sel = Selector(packages.LOADED)
    config.read_settings()
    test_sel.show()
    with trio.CancelScope() as scope:
        test_sel.win.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
        await trio.sleep_forever()
