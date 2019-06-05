"""Configures which signs are defined for the Signage item."""
from typing import Optional, Tuple, List, Dict, overload

import dragdrop
import img
import srctools.logger
import utils
import BEE2_config
from packageLoader import Signage, Style
import tkinter as tk
from srctools import Property
from tkinter import ttk
from tk_tools import TK_ROOT, HidingScroll

LOGGER = srctools.logger.get_logger(__name__)

window = tk.Toplevel(TK_ROOT)
window.withdraw()

drag_man: dragdrop.Manager[Signage] = dragdrop.Manager(window)
SLOTS_SELECTED: Dict[int, dragdrop.Slot[Signage]] = {}

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
        if sign.hidden:
            # Don't bother with making the icon.
            continue

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
                sign.dnd_icon = img.img_error
                continue
        if icon:
            sign.dnd_icon = img.png(icon, resize_to=(64, 64))
        else:
            LOGGER.warning(
                'No icon for "{}" signage in <{}> style!',
                sign.id,
                new_style.id,
            )
            sign.dnd_icon = img.img_error
    drag_man.refresh_icons()


def init_widgets(master: ttk.Frame) -> Optional[tk.Misc]:
    """Construct the widgets, returning the configuration button.

    If no signages are defined, this returns None.
    """

    if not any(Signage.all()):
        return ttk.Label(master)

    window.protocol("WM_DELETE_WINDOW", window.withdraw)
    window.resizable(True, True)
    window.title(_('Configure Signage'))

    frame_selected = ttk.Labelframe(
        window,
        text=_('Selected'),
        relief='raised',
        labelanchor='n',
    )

    canv_all = tk.Canvas(window)

    scroll = HidingScroll(window, orient='vertical', command=canv_all.yview)
    canv_all['yscrollcommand'] = scroll.set

    name_label = ttk.Label(window, text='', justify='center')

    frame_selected.grid(row=0, column=0, sticky='nsew')
    name_label.grid(row=1, column=0, sticky='ew')
    canv_all.grid(row=0, column=1, rowspan=2, sticky='nsew')
    scroll.grid(row=0, column=2, rowspan=2, sticky='ns')
    window.columnconfigure(1, weight=1)
    window.rowconfigure(0, weight=1)

    utils.add_mousewheel(canv_all, canv_all, window)

    def on_hover(slot: dragdrop.Slot[Signage]) -> None:
        name_label['text'] = (
            _('Signage: {}').format(slot.contents.name)
            if slot.contents is not None else
            ''
        )

    def on_leave(slot: dragdrop.Slot[Signage]) -> None:
        name_label['text'] = ''

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

    def show_window() -> None:
        """Show the window."""
        window.deiconify()
        utils.center_win(window, TK_ROOT)

    return ttk.Button(
        master,
        text=_('Configure Signage'),
        command=show_window,
    )
