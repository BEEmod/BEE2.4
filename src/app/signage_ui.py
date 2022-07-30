"""Configures which signs are defined for the Signage item."""
from typing import Iterable, Mapping, Optional, Sequence, Tuple, List, Dict, Union
import tkinter as tk
import trio
from tkinter import ttk

from srctools import Property
import srctools.logger
import attrs

from app import dragdrop, img, tk_tools, TK_ROOT
from packages import Signage, Style
from localisation import gettext
import config

LOGGER = srctools.logger.get_logger(__name__)

window = tk.Toplevel(TK_ROOT)
window.withdraw()

drag_man: dragdrop.Manager[Signage] = dragdrop.Manager(window)
SLOTS_SELECTED: Dict[int, dragdrop.Slot[Signage]] = {}
# The valid timer indexes for signs.
SIGN_IND: Sequence[int] = range(3, 31)
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
    # Remaining are blank.
    **dict.fromkeys(range(19, 31), ''),
}


def export_data() -> List[Tuple[str, str]]:
    """Returns selected items, for Signage.export() to use."""
    return [
        (str(ind), slot.contents.id)
        for ind, slot in SLOTS_SELECTED.items()
        if slot.contents is not None
    ]


@config.APP.register('Signage')
@attrs.frozen
class Layout(config.Data):
    """A layout of selected signs."""
    signs: Mapping[int, str] = attrs.Factory(DEFAULT_IDS.copy)

    @classmethod
    def parse_legacy(cls, props: Property) -> Dict[str, 'Layout']:
        """Parse the old config format."""
        # Simply call the new parse, it's unchanged.
        sign = Layout.parse_kv1(props.find_children('Signage'), 1)
        return {'': sign}

    @classmethod
    def parse_kv1(cls, data: Union[Property, Iterable[Property]], version: int) -> 'Layout':
        """Parse DMX config values."""
        sign = DEFAULT_IDS.copy()
        for child in data:
            try:
                timer = int(child.name)
            except (ValueError, TypeError):
                LOGGER.warning('Non-numeric timer value "{}"!', child.name)
                continue

            if timer not in sign:
                LOGGER.warning('Invalid timer value {}!', child.name)
                continue
            sign[timer] = child.value
        return cls(sign)

    def export_kv1(self) -> Property:
        """Generate keyvalues for saving signages."""
        props = Property('Signage', [])
        for timer, sign in self.signs.items():
            props.append(Property(str(timer), sign))
        return props


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
            try:
                slot.contents = Signage.by_id(value)
            except KeyError:
                LOGGER.warning('No signage with id "{}"!', value)
        else:
            slot.contents = None


def style_changed(new_style: Style) -> None:
    """Update the icons for the selected signage."""
    icon: Optional[img.Handle]
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


async def init_widgets(master: tk.Widget) -> Optional[tk.Widget]:
    """Construct the widgets, returning the configuration button.
    """

    if not any(Signage.all()):
        # There's no signage, disable the configurator. This will be invisible basically.
        return ttk.Frame(master)

    window.resizable(True, True)
    window.title(gettext('Configure Signage'))

    frame_selected = ttk.Labelframe(
        window,
        text=gettext('Selected'),
        relief='raised',
        labelanchor='n',
    )

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
    img.apply(preview_left, IMG_BLANK)
    img.apply(preview_right, IMG_BLANK)
    preview_left.grid(row=0, column=0)
    preview_right.grid(row=0, column=1)

    try:
        sign_arrow = Signage.by_id('SIGN_ARROW')
    except KeyError:
        LOGGER.warning('No arrow signage defined!')
        sign_arrow = None

    hover_scope: Optional[trio.CancelScope] = None

    async def on_hover(hovered: dragdrop.Slot[Signage]) -> None:
        """Show the signage when hovered, then toggle."""
        nonlocal hover_scope
        hover_sign = hovered.contents
        if hover_sign is None:
            await on_leave(hovered)
            return
        if hover_scope is not None:
            hover_scope.cancel()

        name_label['text'] = gettext('Signage: {}').format(hover_sign.name)

        sng_left = hover_sign.dnd_icon
        sng_right = sign_arrow.dnd_icon if sign_arrow is not None else IMG_BLANK
        try:
            dbl_left = Signage.by_id(hover_sign.prim_id or '').dnd_icon
        except KeyError:
            dbl_left = hover_sign.dnd_icon
        try:
            dbl_right = Signage.by_id(hover_sign.sec_id or '').dnd_icon
        except KeyError:
            dbl_right = IMG_BLANK

        with trio.CancelScope() as hover_scope:
            while True:
                img.apply(preview_left, sng_left)
                img.apply(preview_right, sng_right)
                await trio.sleep(1.0)
                img.apply(preview_left, dbl_left)
                img.apply(preview_right, dbl_right)
                await trio.sleep(1.0)

    async def on_leave(hovered: dragdrop.Slot[Signage]) -> None:
        """Reset the visible sign when left."""
        nonlocal hover_scope
        name_label['text'] = ''
        if hover_scope is not None:
            hover_scope.cancel()
            hover_scope = None
        img.apply(preview_left, IMG_BLANK)
        img.apply(preview_right, IMG_BLANK)

    drag_man.event_bus.register(dragdrop.Event.HOVER_ENTER, dragdrop.Slot[Signage], on_hover)
    drag_man.event_bus.register(dragdrop.Event.HOVER_EXIT, dragdrop.Slot[Signage], on_leave)

    for i in SIGN_IND:
        SLOTS_SELECTED[i] = slot = drag_man.slot_target(
            frame_selected,
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
            slot = drag_man.slot_source(canv_all)
            slot.contents = sign

    drag_man.flow_slots(canv_all, drag_man.sources())
    canv_all.bind('<Configure>', lambda e: drag_man.flow_slots(canv_all, drag_man.sources()))

    def hide_window() -> None:
        """Hide the window."""
        # Store off the configured signage.
        config.store_conf(Layout({
            timer: slt.contents.id if slt.contents is not None else ''
            for timer, slt in SLOTS_SELECTED.items()
        }))
        window.withdraw()
        drag_man.unload_icons()
        img.apply(preview_left, IMG_BLANK)
        img.apply(preview_right, IMG_BLANK)

    def show_window() -> None:
        """Show the window."""
        drag_man.load_icons()
        window.deiconify()
        tk_tools.center_win(window, TK_ROOT)

    window.protocol("WM_DELETE_WINDOW", hide_window)
    await config.set_and_run_ui_callback(Layout, apply_config)
    return ttk.Button(
        master,
        text=gettext('Configure Signage'),
        command=show_window,
    )
