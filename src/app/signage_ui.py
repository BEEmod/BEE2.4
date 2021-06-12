"""Configures which signs are defined for the Signage item."""
from typing import Optional, Tuple, List, Dict, overload

from app import dragdrop, img, TK_ROOT
import srctools.logger
import utils
import BEE2_config
from packages import Signage, Style
import tkinter as tk
from srctools import Property
from tkinter import ttk
from app import tk_tools

LOGGER = srctools.logger.get_logger(__name__)

window = tk.Toplevel(TK_ROOT)
window.withdraw()

drag_man: dragdrop.Manager[Signage] = dragdrop.Manager(window)
SLOTS_SELECTED: Dict[int, dragdrop.Slot[Signage]] = {}
IMG_ERROR = img.Handle.error(64, 64)
IMG_BLANK = img.Handle.color(img.PETI_ITEM_BG, 64, 64)

DEFAULT_IDS = {
    3: 'SIGN_NUM_1',
    4: 'SIGN_NUM_2',
    5: 'SIGN_NUM_3',
    6: 'SIGN_NUM_4',

    7: 'SIGN_EXIT',
    8: 'SIGN_CUBE_DROPPER',
    9: 'SIGN_BALL_DROPPER',
    10: 'SIGN_REFLECT_CUBE',

    11: 'SIGN_GOO_TOXIC',
    12: 'SIGN_TBEAM',
    13: 'SIGN_TBEAM_POLARITY',
    14: 'SIGN_LASER_RELAY',

    15: 'SIGN_TURRET',
    16: 'SIGN_LIGHT_BRIDGE',
    17: 'SIGN_PAINT_BOUNCE',
    18: 'SIGN_PAINT_SPEED',
}


def export_data() -> List[Tuple[str, str]]:
    """Returns selected items, for Signage.export() to use."""
    return [
        (str(ind), slot.contents.id)
        for ind, slot in SLOTS_SELECTED.items()
        if slot.contents is not None
    ]


@overload
def save_load_signage() -> Property: ...
@overload
def save_load_signage(props: Property) -> None: ...


@BEE2_config.option_handler('Signage')
def save_load_signage(props: Property=None) -> Optional[Property]:
    """Save or load the signage info."""
    if props is None:  # Save to properties.
        props = Property('Signage', [])
        for timer, slot in SLOTS_SELECTED.items():
            props.append(Property(
                str(timer),
                '' if slot.contents is None
                else slot.contents.id,
            ))
        return props
    else:  # Load from provided properties.
        for child in props:
            try:
                slot = SLOTS_SELECTED[int(child.name)]
            except (ValueError, TypeError):
                LOGGER.warning('Non-numeric timer value "{}"!', child.name)
                continue
            except KeyError:
                LOGGER.warning('Invalid timer value {}!', child.name)
                continue

            if child.value:
                try:
                    slot.contents = Signage.by_id(child.value)
                except KeyError:
                    LOGGER.warning('No signage with id "{}"!', child.value)
            else:
                slot.contents = None
        return None


def style_changed(new_style: Style) -> None:
    """Update the icons for the selected signage."""
    for sign in Signage.all():
        for potential_style in new_style.bases:
            try:
                icon = sign.styles[potential_style.id.upper()].icon
                break
            except KeyError:
                pass
        else:
            LOGGER.warning(
                'No valid <{}> style for "{}" signage!',
                new_style.id,
                sign.id,
            )
            try:
                icon = sign.styles['BEE2_CLEAN'].icon
            except KeyError:
                sign.dnd_icon = IMG_ERROR
                continue
        if icon:
            sign.dnd_icon = icon
        else:
            LOGGER.warning(
                'No icon for "{}" signage in <{}> style!',
                sign.id,
                new_style.id,
            )
            sign.dnd_icon = IMG_ERROR
    if window.winfo_ismapped():
        drag_man.load_icons()


def init_widgets(master: ttk.Frame) -> Optional[tk.Widget]:
    """Construct the widgets, returning the configuration button.

    If no signages are defined, this returns None.
    """

    if not any(Signage.all()):
        return ttk.Label(master)

    window.resizable(True, True)
    window.title(_('Configure Signage'))

    frame_selected = ttk.Labelframe(
        window,
        text=_('Selected'),
        relief='raised',
        labelanchor='n',
    )

    canv_all = tk.Canvas(window)

    scroll = tk_tools.HidingScroll(window, orient='vertical', command=canv_all.yview)
    canv_all['yscrollcommand'] = scroll.set

    name_label = ttk.Label(window, text='', justify='center')
    frame_preview = ttk.Frame(window, relief='raised', borderwidth=4)

    frame_selected.grid(row=0, column=0, sticky='nsew')
    ttk.Separator(orient='horiz').grid(row=1, column=0, sticky='ew')
    name_label.grid(row=2, column=0)
    frame_preview.grid(row=3, column=0, pady=4)
    canv_all.grid(row=0, column=1, rowspan=4, sticky='nsew')
    scroll.grid(row=0, column=2, rowspan=4, sticky='ns')
    window.columnconfigure(1, weight=1)
    window.rowconfigure(3, weight=1)

    tk_tools.add_mousewheel(canv_all, canv_all, window)

    preview_left = ttk.Label(frame_preview, anchor='e')
    preview_right = ttk.Label(frame_preview, anchor='w')
    img.apply(preview_left, IMG_BLANK)
    img.apply(preview_right, IMG_BLANK)
    preview_left.grid(row=0, column=0)
    preview_right.grid(row=0, column=1)

    try:
        sign_arrow = Signage.by_id('SIGN_ARROW')
    except KeyError:
        LOGGER.warning('No arrow signage defined!')
        sign_arrow = None

    hover_arrow = False
    hover_toggle_id = None
    hover_sign: Optional[Signage] = None

    def hover_toggle() -> None:
        """Toggle between arrows and dual icons."""
        nonlocal hover_arrow, hover_toggle_id
        hover_arrow = not hover_arrow
        if hover_sign is None:
            return
        if hover_arrow and sign_arrow:
            left = hover_sign.dnd_icon
            right = sign_arrow.dnd_icon
        else:
            try:
                left = Signage.by_id(hover_sign.prim_id or '').dnd_icon
            except KeyError:
                left = hover_sign.dnd_icon
            try:
                right = Signage.by_id(hover_sign.sec_id or '').dnd_icon
            except KeyError:
                right = IMG_BLANK
        img.apply(preview_left, left)
        img.apply(preview_right, right)
        hover_toggle_id = TK_ROOT.after(1000, hover_toggle)

    def on_hover(slot: dragdrop.Slot[Signage]) -> None:
        """Show the signage when hovered."""
        nonlocal hover_arrow, hover_sign
        if slot.contents is not None:
            name_label['text'] = _('Signage: {}').format(slot.contents.name)
            hover_sign = slot.contents
            hover_arrow = True
            hover_toggle()
        else:
            on_leave(slot)

    def on_leave(slot: dragdrop.Slot[Signage]) -> None:
        """Reset the visible sign when left."""
        nonlocal hover_toggle_id, hover_sign
        name_label['text'] = ''
        hover_sign = None
        if hover_toggle_id is not None:
            TK_ROOT.after_cancel(hover_toggle_id)
            hover_toggle_id = None
        img.apply(preview_left, IMG_BLANK)
        img.apply(preview_right, IMG_BLANK)

    drag_man.reg_callback(dragdrop.Event.HOVER_ENTER, on_hover)
    drag_man.reg_callback(dragdrop.Event.HOVER_EXIT, on_leave)

    for i in range(3, 31):
        SLOTS_SELECTED[i] = slot = drag_man.slot(
            frame_selected,
            source=False,
            label=f'00:{i:02g}'
        )
        row, col = divmod(i-3, 4)
        slot.grid(row=row, column=col, padx=1, pady=1)

        prev_id = DEFAULT_IDS.get(i, '')
        if prev_id:
            try:
                slot.contents = Signage.by_id(prev_id)
            except KeyError:
                LOGGER.warning('Missing sign id: {}', prev_id)

    for sign in sorted(Signage.all(), key=lambda s: s.name):
        if not sign.hidden:
            slot = drag_man.slot(canv_all, source=True)
            slot.contents = sign

    drag_man.flow_slots(canv_all, drag_man.sources())

    canv_all.bind(
        '<Configure>',
        lambda e: drag_man.flow_slots(canv_all, drag_man.sources()),
    )

    def hide_window() -> None:
        """Hide the window."""
        window.withdraw()
        drag_man.unload_icons()
        img.apply(preview_left, IMG_BLANK)
        img.apply(preview_right, IMG_BLANK)

    def show_window() -> None:
        """Show the window."""
        drag_man.load_icons()
        window.deiconify()
        utils.center_win(window, TK_ROOT)

    window.protocol("WM_DELETE_WINDOW", hide_window)
    return ttk.Button(
        master,
        text=_('Configure Signage'),
        command=show_window,
    )
