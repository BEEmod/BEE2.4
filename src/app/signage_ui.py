"""Configures which signs are defined for the Signage item."""
from typing import Optional, Sequence, Tuple, List, Dict
import tkinter as tk
from datetime import timedelta

from tkinter import ttk

import trio
import srctools.logger

from ui_tk.dragdrop import DragDrop, DragInfo
from ui_tk.img import TKImages
from app import dragdrop, img, localisation, tk_tools, TK_ROOT
from config.signage import DEFAULT_IDS, Layout
from packages import Signage, Style
import packages
from transtoken import TransToken
import config


LOGGER = srctools.logger.get_logger(__name__)

window = tk.Toplevel(TK_ROOT, name='signageChooser')
window.withdraw()
SLOTS_SELECTED: Dict[int, dragdrop.Slot[Signage]] = {}
# The valid timer indexes for signs.
SIGN_IND: Sequence[int] = range(3, 31)
IMG_ERROR = img.Handle.error(64, 64)
IMG_BLANK = img.Handle.background(64, 64)

TRANS_SIGN_NAME = TransToken.ui('Signage: {name}')
_cur_style: Optional[Style] = None


def export_data() -> List[Tuple[str, str]]:
    """Returns selected items, for Signage.export() to use."""
    conf: Layout = config.APP.get_cur_conf(Layout, default=Layout())
    return [
        (str(ind), sign_id)
        for ind in SIGN_IND
        if (sign_id := conf.signs.get(ind, '')) != ''
    ]


def get_drag_info(sign: Signage) -> DragInfo:
    """Get the icon for displaying this sign."""
    style = _cur_style
    if style is None:
        return DragInfo(IMG_ERROR)

    for potential_style in style.bases:
        try:
            return DragInfo(sign.styles[potential_style.id.upper()].icon)
        except KeyError:
            pass
    else:
        LOGGER.warning(
            'No valid <{}> style for "{}" signage!',
            style.id,
            sign.id,
        )
        try:
            return DragInfo(sign.styles[packages.CLEAN_PACKAGE].icon)
        except KeyError:
            return DragInfo(IMG_ERROR)


drag_man: DragDrop[Signage] = DragDrop(window, info_cb=get_drag_info)


async def apply_config(data: Layout) -> None:
    """Apply saved signage info to the UI."""
    packset = packages.get_loaded_packages()
    for timer in SIGN_IND:
        try:
            slot = SLOTS_SELECTED[timer]
        except KeyError:
            LOGGER.warning('Invalid timer value {}!', timer)
            continue

        value = data.signs.get(timer, '')
        if value:
            try:
                slot.contents = packset.obj_by_id(Signage, value)
            except KeyError:
                LOGGER.warning('No signage with id "{}"!', value)
        else:
            slot.contents = None


def style_changed(new_style: Style) -> None:
    """Update the icons for the selected signage."""
    global _cur_style
    _cur_style = new_style
    if window.winfo_ismapped():
        drag_man.load_icons()


async def init_widgets(master: tk.Widget, tk_img: TKImages) -> Optional[tk.Widget]:
    """Construct the widgets, returning the configuration button.
    """
    window.resizable(True, True)
    localisation.set_win_title(window, TransToken.ui('Configure Signage'))

    frame_selected = ttk.Labelframe(window, relief='raised', labelanchor='n')
    localisation.set_text(frame_selected, TransToken.ui('Selected'))

    canv_all = tk.Canvas(window)

    scroll = tk_tools.HidingScroll(window, orient='vertical', command=canv_all.yview)
    canv_all['yscrollcommand'] = scroll.set

    name_label = ttk.Label(window, text='', justify='center')
    frame_preview = ttk.Frame(window, relief='raised', borderwidth=4)

    frame_selected.grid(row=0, column=0, sticky='nsew')
    ttk.Separator(orient='horizontal').grid(row=1, column=0, sticky='ew')
    name_label.grid(row=2, column=0)
    frame_preview.grid(row=3, column=0, pady=4)
    canv_all.grid(row=0, column=1, rowspan=4, sticky='nsew')
    scroll.grid(row=0, column=2, rowspan=4, sticky='ns')
    window.columnconfigure(1, weight=1)
    window.rowconfigure(3, weight=1)

    tk_tools.add_mousewheel(canv_all, canv_all, window)

    preview_left = ttk.Label(frame_preview, anchor='e')
    preview_right = ttk.Label(frame_preview, anchor='w')
    tk_img.apply(preview_left, IMG_BLANK)
    tk_img.apply(preview_right, IMG_BLANK)
    preview_left.grid(row=0, column=0)
    preview_right.grid(row=0, column=1)

    # Dummy initial parameter, will be overwritten. Allows us to stop the display when the mouse
    # leaves.
    hover_scope = trio.CancelScope()

    async def on_hover(hovered: dragdrop.Slot[Signage]) -> None:
        """Show the signage when hovered, then toggle."""
        nonlocal hover_scope
        hover_sign = hovered.contents
        if hover_sign is None:
            await on_leave(hovered)
            return
        hover_scope.cancel()

        localisation.set_text(name_label, TRANS_SIGN_NAME.format(name=hover_sign.name))

        packset = packages.get_loaded_packages()

        sng_left = get_drag_info(hover_sign).icon
        try:
            sng_right = get_drag_info(packset.obj_by_id(Signage, 'SIGN_ARROW')).icon
        except KeyError:
            LOGGER.warning('No arrow signage defined!')
            sng_right = IMG_BLANK
        try:
            dbl_left = get_drag_info(packset.obj_by_id(Signage, hover_sign.prim_id or '')).icon
        except KeyError:
            dbl_left = sng_left
        try:
            dbl_right = get_drag_info(packset.obj_by_id(Signage, hover_sign.sec_id or '')).icon
        except KeyError:
            dbl_right = IMG_BLANK

        with trio.CancelScope() as hover_scope:
            while True:
                tk_img.apply(preview_left, sng_left)
                tk_img.apply(preview_right, sng_right)
                await trio.sleep(1.0)
                tk_img.apply(preview_left, dbl_left)
                tk_img.apply(preview_right, dbl_right)
                await trio.sleep(1.0)

    async def on_leave(hovered: dragdrop.Slot[Signage]) -> None:
        """Reset the visible sign when left."""
        nonlocal hover_scope
        name_label['text'] = ''
        hover_scope.cancel()
        tk_img.apply(preview_left, IMG_BLANK)
        tk_img.apply(preview_right, IMG_BLANK)

    drag_man.event_bus.register(dragdrop.Event.HOVER_ENTER, dragdrop.Slot[Signage], on_hover)
    drag_man.event_bus.register(dragdrop.Event.HOVER_EXIT, dragdrop.Slot[Signage], on_leave)

    load_packset = packages.get_loaded_packages()
    for i in SIGN_IND:
        SLOTS_SELECTED[i] = slot = drag_man.slot_target(
            frame_selected,
            label=TransToken.untranslated('{delta:ms}').format(delta=timedelta(seconds=i)),
        )
        row, col = divmod(i-3, 4)
        drag_man.slot_grid(slot, row=row, column=col, padx=1, pady=1)

        prev_id = DEFAULT_IDS.get(i, '')
        if prev_id:
            try:
                slot.contents = load_packset.obj_by_id(Signage, prev_id)
            except KeyError:
                LOGGER.warning('Missing sign id: {}', prev_id)

    # TODO: Dynamically refresh this.
    for sign in sorted(Signage.all(), key=lambda s: s.name):
        if not sign.hidden:
            slot = drag_man.slot_source(canv_all)
            slot.contents = sign

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
    localisation.set_text(show_btn, TransToken.ui('Configure Signage'))
    return show_btn
