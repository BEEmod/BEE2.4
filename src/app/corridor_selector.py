"""Implements UI for selecting corridors."""
from tkinter import ttk
import tkinter as tk
from typing import Optional, List, Sequence, Literal
from typing_extensions import TypeAlias, Final

import srctools.logger
import trio

import event
import packages
from app import TK_ROOT, background_run, config, dragdrop, img, sound, tk_tools
from app.richTextBox import tkRichText
from localisation import gettext
from packages import corridor
from corridor import GameMode, Direction, Orient, CORRIDOR_COUNTS


LOGGER = srctools.logger.get_logger(__name__)
WIDTH: Final = corridor.IMG_WIDTH_SML + 16
HEIGHT: Final = corridor.IMG_HEIGHT_SML + 16
Slot: TypeAlias = dragdrop.Slot[corridor.CorridorUI]

IMG_CORR_BLANK: Final = img.Handle.blank(corridor.IMG_WIDTH_LRG, corridor.IMG_HEIGHT_LRG)
IMG_ARROW_LEFT: Final = img.Handle.builtin('BEE2/switcher_arrow', 17, 64)
IMG_ARROW_RIGHT: Final = IMG_ARROW_LEFT.crop(transpose=img.FLIP_LEFT_RIGHT)
# TODO: Variants for other OSes with appropriate colouring.
IMG_SELECTOR: Final = img.Handle.builtin('BEE2/sel_divider_win', 16, 120)
SELECTED_COLOR: Final = '#14B0FF'

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
    drag_man: dragdrop.Manager[corridor.CorridorUI]

    # Widgets to display info about the corridor on the right side.
    wid_image: ttk.Label
    wid_title: ttk.Label
    wid_desc: tkRichText
    # When you click a corridor, it's saved here and displayed when others aren't
    # moused over. Reset on style/group swap.
    sticky_corr: Optional[corridor.CorridorUI]
    # Currently selected image.
    cur_images: Sequence[img.Handle]
    img_ind: int

    # The slots items are on.
    slots: List[Slot]
    sel_count: int # Number which are being used.

    # The current corridor group for the selected style, and the config ID to save/load.
    # These are updated by load_corridors().
    corr_group: corridor.CorridorGroup
    conf_id: str

    def __init__(self, packset: packages.PackagesSet) -> None:
        self.sticky_corr = None
        self.img_ind = 0
        self.slots = []
        self.sel_count = 0

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
        frm_img = ttk.Frame(frm_right, relief='raised', width=2)
        frm_img.grid(row=0, column=0, sticky='ew')

        sel_img = self._sel_img
        self.wid_image_left = ttk.Button(frm_img, command=lambda: sel_img(-1))
        self.wid_image = ttk.Label(frm_img)
        self.wid_image_right = ttk.Button(frm_img, command=lambda: sel_img(1))

        self.wid_image_left.grid(row=0, column=0, sticky='ns')
        self.wid_image.grid(row=0, column=1, sticky='nsew')
        self.wid_image_right.grid(row=0, column=2, sticky='ns')

        img.apply(self.wid_image_left, IMG_ARROW_LEFT)
        img.apply(self.wid_image, IMG_CORR_BLANK)
        img.apply(self.wid_image_right, IMG_ARROW_RIGHT)

        self.wid_title = ttk.Label(frm_right, text='')
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

        self.sel_handle = ttk.Label(self.canvas, cursor=tk_tools.Cursors.MOVE_ITEM, border=0)
        img.apply(self.sel_handle, IMG_SELECTOR)
        self.sel_handle_pos = self.canvas.create_window(
            128, 128,
            anchor='nw',
            window=self.sel_handle,
        )

        self.drag_man = drop = dragdrop.Manager[corridor.CorridorUI](self.win, size=(WIDTH, HEIGHT))
        drop.event.register(dragdrop.Event.HOVER_ENTER, Slot, self.evt_hover_enter)
        drop.event.register(dragdrop.Event.HOVER_EXIT, Slot, self.evt_hover_exit)
        drop.event.register(dragdrop.Event.REDROPPED, Slot, self.evt_redropped)
        drop.event.register(dragdrop.Event.FLEXI_FLOW, Slot, self.reflow)
        drop.event.register(dragdrop.Event.MODIFIED, None, self._on_changed)
        self.load_corridors(packset)

        def shuffle(_) -> None:
            """Temp function for testing."""
            import random
            count = sum(
                1 for slot in self.slots
                if slot.contents is not None
            )
            self.sel_count = random.randint(1, count)
            background_run(self.reflow)
        self.sel_handle.bind(tk_tools.EVENTS['LEFT'], shuffle)

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
        slots = [
            slot.contents.instance.casefold() if slot.contents is not None else ''
            for slot in self.slots
        ]
        # Drop empties at the end.
        while slots and not slots[-1]:
            slots.pop()

        config.store_conf(corridor.Config(slots, min(len(self.slots), self.sel_count)), self.conf_id)

        # Fix up the highlight, if it was moved.
        for slot in self.drag_man.all_slots():
            slot.highlight = slot.contents is not None and slot.contents is self.sticky_corr

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

        # Ensure enough slots exist to hold all of them, and clear em all.
        for slot in self.slots:
            slot.highlight = False
            slot.contents = None
        for _ in range(len(corr_list) + 1 - len(self.slots)):
            self.slots.append(self.drag_man.slot_flexi(self.canvas))

        inst_to_corr = {corr.instance.casefold(): corr for corr in corr_list}
        next_slot = 0
        if conf.selected:
            self.sel_count = conf.selected
            for i, sel_id in enumerate(conf.slots):
                if not sel_id:
                    # If empty slots are before the cursor, shift it to compensate.
                    if i <= self.sel_count:
                        self.sel_count -= 1
                    continue
                try:
                    self.slots[next_slot].contents = inst_to_corr.pop(sel_id.casefold())
                except KeyError:
                    LOGGER.warning('Unknown corridor instance "{}" in config!')
                    if i <= self.sel_count:
                        self.sel_count -= 1
                else:
                    next_slot += 1
        else:
            # No configuration, populate with the defaults.
            defaults = self.corr_group.defaults(mode, direction, orient)
            for slot, corr in zip(self.slots, defaults):
                slot.contents = corr
                del inst_to_corr[corr.instance.casefold()]
            next_slot = len(defaults)
            self.sel_count = max(next_slot, CORRIDOR_COUNTS[mode, direction])

        # Put all remaining in a spare slot.
        for slot, corr in zip(
            self.slots[next_slot:],
            sorted(inst_to_corr.values(), key=lambda corr: corr.name),
        ):
            slot.contents = corr

        if self.sel_count < 1:
            self.sel_count = 1
        if self.sel_count > len(corr_list):
            self.sel_count = len(corr_list)

        self.drag_man.load_icons()

        # Reset item display, it's invalid.
        self.sticky_corr = None
        self.disp_corr(None)
        # Reposition everything.
        await self.reflow()

    async def reflow(self, _=None) -> None:
        """Called to reposition the corridors."""
        corr_order = [
            slot for slot in
            self.slots
            if slot.contents is not None
        ]
        self.canvas.delete('slots')
        self.canvas.delete('sel_bg')

        if not corr_order:
            # No corridors, hide selector.
            self.canvas.coords(
                self.sel_handle_pos,
                -16, 0,
            )
            return

        pos = dragdrop.Positioner(self.canvas, WIDTH, HEIGHT)
        selecting = True
        for row_off in range(0, len(corr_order), pos.columns):
            if row_off < self.sel_count <= row_off + pos.columns:
                # Placing selector on this row.
                x = pos.xpos(self.sel_count - row_off)
                y = pos.ypos(row_off // pos.columns)
                self.canvas.coords(
                    self.sel_handle_pos,
                    x + WIDTH, y - 6,
                )
                selecting = False
                self.canvas.create_rectangle(
                    0, y - 4,
                    x + WIDTH,
                    y + HEIGHT + 4,
                    fill=SELECTED_COLOR,
                    outline='',
                    tags=('sel_bg', ),
                )
            elif selecting:
                # On another row, extend all the way.
                y = pos.ypos(row_off // pos.columns)
                self.canvas.create_rectangle(
                    0, y - 4,
                    pos.width, y + HEIGHT + 4,
                    fill=SELECTED_COLOR,
                    outline='',
                    tags=('sel_bg', ),
                )
        pos.place_slots(corr_order, 'slots')
        pos.resize_canvas()

    async def evt_hover_enter(self, slot: Slot) -> None:
        """Display the specified corridor temporarily on hover."""
        if slot.contents is not None:
            self.disp_corr(slot.contents)

    async def evt_hover_exit(self, slot: Slot) -> None:
        """When leaving, reset to the sticky corridor."""
        if self.sticky_corr is not None:
            self.disp_corr(self.sticky_corr)
        else:
            self.disp_corr(None)

    async def evt_redropped(self, slot: Slot) -> None:
        """Fires when a slot is dropped back on itself. This is effectively a left-click."""
        if slot.contents is not None and self.sticky_corr is not slot.contents:
            if self.sticky_corr is not None:
                # Clear the old one.
                for old_slot in self.drag_man.all_slots():
                    old_slot.highlight = False
            slot.highlight = True
            self.sticky_corr = slot.contents
            self.disp_corr(self.sticky_corr)

    def disp_corr(self, corr: Optional[corridor.CorridorUI]) -> None:
        """Display the specified corridor, or reset if None."""
        if corr is not None:
            self.img_ind = 0
            self.cur_images = corr.images
            self._sel_img(0)  # Updates the buttons.

            self.wid_title['text'] = corr.name
            self.wid_desc.set_text(corr.desc)
        else:  # Reset.
            self.wid_title['text'] = ''
            self.wid_desc.set_text(corridor.EMPTY_DESC)
            img.apply(self.wid_image, IMG_CORR_BLANK)
            self.wid_image_left.state(('disabled', ))
            self.wid_image_right.state(('disabled', ))

    def _sel_img(self, direction: Literal[-1, 0, 1]) -> None:
        """Go forward or backwards in the preview images."""
        max_ind = len(self.cur_images) - 1
        self.img_ind += direction
        # Order this and the comparisons so size = 0 means index is forced to 0 with both
        # hidden.
        if self.img_ind > max_ind:
            self.img_ind = max_ind
        if self.img_ind < 0:
            self.img_ind = 0

        if self.cur_images:
            img.apply(self.wid_image, self.cur_images[self.img_ind])
        else:
            img.apply(self.wid_image, corridor.ICON_GENERIC_LRG)
        self.wid_image_left.state(('!disabled', ) if self.img_ind > 0 else ('disabled', ))
        self.wid_image_right.state(('!disabled', ) if self.img_ind < max_ind else ('disabled', ))


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
