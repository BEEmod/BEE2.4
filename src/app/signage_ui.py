"""Configures which signs are defined for the Signage item."""
from __future__ import annotations
from collections.abc import Sequence
from datetime import timedelta

from tkinter import ttk
import tkinter as tk

import trio
import srctools.logger

from ui_tk.dragdrop import DragDrop, DragInfo
from ui_tk.img import TKImages
from ui_tk.wid_transtoken import set_text, set_win_title
from app import dragdrop, img, tk_tools, TK_ROOT
from config.signage import DEFAULT_IDS, Layout
from packages import Signage, Style, PakRef
import packages
from transtoken import TransToken
import config
import utils


LOGGER = srctools.logger.get_logger(__name__)

window = tk.Toplevel(TK_ROOT, name='signageChooser')
window.withdraw()
SLOTS_SELECTED: dict[int, dragdrop.Slot[PakRef[Signage]]] = {}
# The valid timer indexes for signs.
SIGN_IND: Sequence[int] = range(3, 31)
IMG_ERROR = img.Handle.error(64, 64)
IMG_BLANK = img.Handle.background(64, 64)

TRANS_SIGN_NAME = TransToken.ui('Signage: {name}')
TRANS_UNKNOWN_SIGN = TransToken.ui('Unknown Signage: {id}')
_cur_style_id: PakRef[Style] = PakRef(Style, packages.CLEAN_STYLE)


def export_data() -> list[tuple[str, utils.ObjectID]]:
    """Returns selected items, for Signage.export() to use."""
    conf: Layout = config.APP.get_cur_conf(Layout, default=Layout())
    return [
        (str(ind), utils.obj_id(sign_id))
        for ind in SIGN_IND
        if (sign_id := conf.signs.get(ind, '')) != ''
    ]


def get_icon(sign: Signage, style: Style) -> img.Handle:
    """Get the icon currently in use for a sign."""
    for potential_style in style.bases:
        try:
            return sign.styles[potential_style.reference()].icon
        except KeyError:
            pass
    LOGGER.warning(
        'No valid <{}> style for "{}" signage!',
        style.id,
        sign.id,
    )
    try:
        return sign.styles[PakRef(Style, packages.CLEAN_STYLE)].icon
    except KeyError:
        return IMG_ERROR


def get_drag_info(ref: PakRef[Signage]) -> DragInfo:
    """Get the icon for displaying this sign."""
    packset = packages.get_loaded_packages()
    style = _cur_style_id.resolve(packset)
    if style is None:
        return DragInfo(IMG_ERROR)

    sign = ref.resolve(packages.get_loaded_packages())
    if sign is None:
        LOGGER.warning('No signage with id "{}"!', ref.id)
        return DragInfo(IMG_ERROR)
    return DragInfo(get_icon(sign, style))


drag_man: DragDrop[PakRef[Signage]] = DragDrop(window, info_cb=get_drag_info)


async def apply_config(data: Layout) -> None:
    """Apply saved signage info to the UI."""
    for timer in SIGN_IND:
        try:
            slot = SLOTS_SELECTED[timer]
        except KeyError:
            LOGGER.warning('Invalid timer value {}!', timer)
            continue

        value = data.signs.get(timer, '')
        if value:
            slot.contents = PakRef(Signage, value)
        else:
            slot.contents = None


def style_changed(new_style_id: utils.ObjectID) -> None:
    """Update the icons for the selected signage."""
    global _cur_style_id
    _cur_style_id = PakRef(Style, new_style_id)
    if window.winfo_ismapped():
        drag_man.load_icons()


async def init_widgets(master: tk.Widget, tk_img: TKImages) -> tk.Widget:
    """Construct the widgets, returning the configuration button.
    """
    window.resizable(True, True)
    set_win_title(window, TransToken.ui('Configure Signage'))

    frame_selected = ttk.Labelframe(window, relief='raised', labelanchor='n', name='frame_selected')
    set_text(frame_selected, TransToken.ui('Selected'))

    canv_all = tk.Canvas(window, name='canv_all')

    scroll = tk_tools.HidingScroll(window, orient='vertical', command=canv_all.yview, name='scrollbar')
    canv_all['yscrollcommand'] = scroll.set

    name_label = ttk.Label(window, text='', justify='center', name='lbl_name')
    frame_preview = ttk.Frame(window, relief='raised', borderwidth=4, name='frame_preview')

    frame_selected.grid(row=0, column=0, sticky='nsew')
    ttk.Separator(orient='horizontal', name='sep').grid(row=1, column=0, sticky='ew')
    name_label.grid(row=2, column=0)
    frame_preview.grid(row=3, column=0, pady=4)
    canv_all.grid(row=0, column=1, rowspan=4, sticky='nsew')
    scroll.grid(row=0, column=2, rowspan=4, sticky='ns')
    window.columnconfigure(1, weight=1)
    window.rowconfigure(3, weight=1)

    tk_tools.add_mousewheel(canv_all, canv_all, window)

    preview_left = ttk.Label(frame_preview, anchor='e', name='left')
    preview_right = ttk.Label(frame_preview, anchor='w', name='right')
    tk_img.apply(preview_left, IMG_BLANK)
    tk_img.apply(preview_right, IMG_BLANK)
    preview_left.grid(row=0, column=0)
    preview_right.grid(row=0, column=1)

    # Dummy initial parameter, will be overwritten. Allows us to stop the display when the mouse
    # leaves.
    hover_scope = trio.CancelScope()

    @drag_man.on_hover_enter.register
    async def on_hover(hovered: dragdrop.Slot[PakRef[Signage]]) -> None:
        """Show the signage when hovered, then toggle."""
        nonlocal hover_scope
        hover_sign_ref = hovered.contents
        if hover_sign_ref is None:
            await on_leave(hovered)
            return
        hover_scope.cancel()
        packset = packages.get_loaded_packages()

        hover_sign = hover_sign_ref.resolve(packset)
        if hover_sign is None:
            set_text(name_label, TRANS_UNKNOWN_SIGN.format(id=hover_sign_ref.id))
            tk_img.apply(preview_left, IMG_ERROR)
            tk_img.apply(preview_right, IMG_ERROR)
            return

        set_text(name_label, TRANS_SIGN_NAME.format(name=hover_sign.name))

        style = _cur_style_id.resolve(packset)
        if style is None:
            LOGGER.warning('No such style: {}', _cur_style_id)
            await on_leave(hovered)
            return

        single_left = get_icon(hover_sign, style)
        try:
            single_right = get_icon(packset.obj_by_id(Signage, 'SIGN_ARROW'), style)
        except KeyError:
            LOGGER.warning('No arrow signage defined!')
            single_right = IMG_BLANK

        double_left: img.Handle = single_left
        double_right: img.Handle = IMG_BLANK

        if hover_sign.prim_id:
            try:
                double_left = get_icon(packset.obj_by_id(Signage, hover_sign.prim_id), style)
            except KeyError:
                pass

        if hover_sign.sec_id:
            try:
                double_right = get_icon(packset.obj_by_id(Signage, hover_sign.sec_id), style)
            except KeyError:
                pass

        with trio.CancelScope() as hover_scope:
            while True:
                tk_img.apply(preview_left, single_left)
                tk_img.apply(preview_right, single_right)
                await trio.sleep(1.0)
                tk_img.apply(preview_left, double_left)
                tk_img.apply(preview_right, double_right)
                await trio.sleep(1.0)

    @drag_man.on_hover_exit.register
    async def on_leave(hovered: dragdrop.Slot[PakRef[Signage]]) -> None:
        """Reset the visible sign when left."""
        nonlocal hover_scope
        name_label['text'] = ''
        hover_scope.cancel()
        tk_img.apply(preview_left, IMG_BLANK)
        tk_img.apply(preview_right, IMG_BLANK)

    load_packset = packages.get_loaded_packages()
    for i in SIGN_IND:
        SLOTS_SELECTED[i] = slot = drag_man.slot_target(
            frame_selected,
            label=TransToken.untranslated('{delta:ms}').format(delta=timedelta(seconds=i)),
        )
        row, col = divmod(i-3, 4)
        drag_man.slot_grid(slot, row=row, column=col, padx=1, pady=1)

        prev_id = DEFAULT_IDS.get(i, '')
        if prev_id != "":
            slot.contents = PakRef(Signage, prev_id)

    # TODO: Dynamically refresh this.
    for sign in sorted(load_packset.all_obj(Signage), key=lambda s: s.name):
        if not sign.hidden:
            slot = drag_man.slot_source(canv_all)
            slot.contents = PakRef(Signage, utils.obj_id(sign.id))

    drag_man.flow_slots(canv_all, drag_man.sources())
    canv_all.bind('<Configure>', lambda e: drag_man.flow_slots(canv_all, drag_man.sources()))

    def hide_window() -> None:
        """Hide the window."""
        # Store off the configured signage.
        config.APP.store_conf(Layout({
            timer: slt.contents.id if slt.contents is not None else ''
            for timer, slt in SLOTS_SELECTED.items()
        }))
        window.withdraw()
        drag_man.unload_icons()
        tk_img.apply(preview_left, IMG_BLANK)
        tk_img.apply(preview_right, IMG_BLANK)

    def show_window() -> None:
        """Show the window."""
        drag_man.load_icons()
        window.deiconify()
        tk_tools.center_win(window, TK_ROOT)

    window.protocol("WM_DELETE_WINDOW", hide_window)
    await config.APP.set_and_run_ui_callback(Layout, apply_config)

    show_btn = ttk.Button(master, command=show_window)
    set_text(show_btn, TransToken.ui('Configure Signage'))
    return show_btn
