"""Implements drag/drop logic."""
from collections import defaultdict

from tk_tools import TK_ROOT
import tkinter
import img
import utils
import sound
from enum import Enum
from tkinter import ttk, messagebox
from srctools.logger import get_logger
from typing import (
    Union, Generic, Any, TypeVar,
    Optional, Callable,
    List, Tuple, Dict,
)

__all__ = ['Manager', 'Slot', 'ItemProto']

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol

LOGGER = get_logger(__name__)


class ItemProto(Protocol):
    """Protocol draggable items satisfy."""
    dnd_icon: tkinter.PhotoImage  # Image for the item.
    dnd_group: Optional[str]  # If set, the group an item belongs to.
    # If only one item is present for a group, it uses this.
    dnd_group_icon: Optional[tkinter.PhotoImage]

ItemT = TypeVar('ItemT', bound=ItemProto)  # The object the items move around.


class Event(Enum):
    """Callbacks that can be registered to be called by the manager."""
    # Fires when items are right-clicked on. If one is registered, the gear
    # icon appears.
    CONFIG = 'config'

    # Mouse over or out of the items (including drag item).
    HOVER_ENTER = 'hover_enter'
    HOVER_EXIT = 'hover_exit'


def in_bbox(
    x: float, y: float,
    left: float, top: float,
    width: float, height: float,
) -> bool:
    """Checks if (x, y) is inside the (left, top, width, height) bbox."""
    if x < left or y < top:
        return False
    if x > left + width or y > top + height:
        return False
    return True


# noinspection PyProtectedMember
class Manager(Generic[ItemT]):
    """Manages a set of drag-drop points."""
    def __init__(
        self,
        *,
        size: Tuple[int, int]=(64, 64),
        config_icon: bool=False
    ):
        """Create a group of drag-drop slots.

        size is the size of each moved image.
        If config_icon is set, gear icons will be added to each slot to
        configure items. This indicates the right-click option is available,
        and makes it easier to press that.
        """
        self.width, self.height = size

        self._targets = []  # type: List[Slot[ItemT]]
        self._sources = []  # type: List[Slot[ItemT]]

        self._img_blank = img.color_square(img.PETI_ITEM_BG, size)

        self.config_icon = config_icon

        # If dragging, the item we are dragging.
        self._cur_drag = None  # type: Optional[ItemT]
        # While dragging, the place we started at.
        self._cur_prev_slot = None  # type: Optional[Slot[ItemT]]

        self._callbacks = {
            event: []
            for event in Event
        }  # type: Dict[Event, List[Callable[[Slot], None]]]

        self._drag_win = drag_win = tkinter.Toplevel(TK_ROOT)
        drag_win.withdraw()
        drag_win.transient(master=TK_ROOT)
        drag_win.wm_overrideredirect(True)

        self._drag_lbl = drag_lbl = tkinter.Label(
            drag_win,
            image=self._img_blank,
        )
        drag_lbl.grid(row=0, column=0)
        drag_win.bind(utils.EVENTS['LEFT_RELEASE'], self._evt_stop)

    def slot(
        self: 'Manager[ItemT]',
        parent: tkinter.Misc,
        *,
        source: bool,
        label: str='',
    ) -> 'Slot[ItemT]':
        """Add a slot to this group.

        Parameters:
            - parent: Parent widget for the slot.
            - source: If True this cannot be edited, and produces
              copies of the contained item. If False, users can remove
              items.
            - label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot = Slot(self, parent, source, label)  # type: Slot[ItemT]
        if source:
            self._sources.append(slot)
        else:
            self._targets.append(slot)

        return slot

    def refresh_icons(self) -> None:
        """Update all items to set new icons."""
        # Count the number of items in each group to find
        # which should have group icons.
        groups = defaultdict(int)   # type: Dict[Optional[str], int]
        for slot in self._targets:
            groups[getattr(slot.contents, 'dnd_group', None)] += 1

        groups[None] = 2  # This must always be ungrouped.

        for slot in self._targets:
            self._display_item(
                slot._lbl,
                slot.contents,
                groups[getattr(slot.contents, 'dnd_group', None)] == 1
            )

        for slot in self._sources:
            # These are never grouped.
            self._display_item(slot._lbl, slot.contents)

    def reg_callback(self, event: Event, func: Callable[['Slot'], Any]) -> None:
        """Register a callback."""
        self._callbacks[event].append(func)

    def _fire_callback(self, event: Event, slot: 'Slot') -> None:
        """Fire all the registered callbacks."""
        for cback in self._callbacks[event]:
            cback(slot)

    def _pos_slot(self, x: float, y: float) -> 'Optional[Slot[ItemT]]':
        """Find the slot under this X,Y (if any)."""
        for slot in self._targets:
            if slot._pos_type is not None:
                lbl = slot._lbl
                if in_bbox(
                    x, y,
                    lbl.winfo_rootx(),
                    lbl.winfo_rooty(),
                    lbl.winfo_width(),
                    lbl.winfo_height(),
                ):
                    return slot
        return None

    def _display_item(
        self,
        lbl: Union[tkinter.Label, ttk.Label],
        item: Optional[ItemT],
        group: bool=False,
    ) -> None:
        """Display the specified item on the given label."""
        if item is None:
            lbl['image'] = self._img_blank
        elif group:
            try:
                lbl['image'] = item.dnd_group_icon
            except AttributeError:
                lbl['image'] = item.dnd_icon
        else:
            lbl['image'] = item.dnd_icon

    def _group_update(self, group: Optional[str]) -> None:
        """Update all target items with this group."""
        if group is None:
            # None to do..
            return
        group_slots = [
            slot for slot in self._targets
            if getattr(slot.contents, 'dnd_group', None) == group
        ]

        has_group = len(group_slots) == 1
        for slot in group_slots:
            self._display_item(slot._lbl, slot.contents, has_group)

    def _start(self, slot: 'Slot[ItemT]', event: tkinter.Event) -> None:
        """Start the drag."""
        if slot.contents is None:
            return  # Can't pick up blank...

        self._cur_drag = slot.contents

        show_group = False

        if not slot.is_source:
            slot.contents = None

            # If none of this group are present in the targets and we're
            # pulling from the items, we hold a group icon.
            try:
                group = self._cur_drag.dnd_group
            except AttributeError:
                pass
            else:
                if group is not None:
                    for other_slot in self._targets:
                        if getattr(other_slot.contents, 'dnd_group', None) == group:
                            break
                    else:
                        # None present.
                        show_group = True

        self._display_item(self._drag_lbl, self._cur_drag, show_group)
        self._cur_prev_slot = slot

        sound.fx('config')

        self._drag_win.deiconify()
        self._drag_win.lift(TK_ROOT)
        # grab makes this window the only one to receive mouse events, so
        # it is guaranteed that it'll drop when the mouse is released.
        self._drag_win.grab_set_global()
        # NOTE: _global means no other programs can interact, make sure
        # it's released eventually or you won't be able to quit!

        # Call this to reposition it.
        self._evt_move(event)

        self._drag_win.bind(utils.EVENTS['LEFT_MOVE'], self._evt_move)
        # UI['pre_sel_line'].lift()

    def _evt_move(self, event: tkinter.Event) -> None:
        """Reposition the item whenever moving."""
        if self._cur_drag is None or self._cur_prev_slot is None:
            # We aren't dragging, ignore the event.
            return

        self._drag_win.geometry('+{}+{}'.format(
            event.x_root - self.width // 2,
            event.y_root - self.height // 2,
        ))

        dest = self._pos_slot(event.x_root, event.y_root)

        if dest:
            self._drag_win.configure(cursor=utils.CURSORS['move_item'])
        elif self._cur_prev_slot.is_source:
            self._drag_win.configure(cursor=utils.CURSORS['invalid_drag'])
        else:
            self._drag_win.configure(cursor=utils.CURSORS['destroy_item'])

    def _evt_stop(self, event: tkinter.Event) -> None:
        """User released the item."""
        if self._cur_drag is None or self._cur_prev_slot is None:
            return

        sound.fx('config')
        self._drag_win.grab_release()
        self._drag_win.withdraw()
        self._drag_win.unbind(utils.EVENTS['LEFT_MOVE'])

        dest = self._pos_slot(event.x_root, event.y_root)

        if dest:
            # We have a target.
            dest.contents = self._cur_drag
        # No target, and we dragged off an existing target - delete.
        elif not self._cur_prev_slot.is_source:
            sound.fx('delete')

        self._cur_drag = None
        self._cur_prev_slot = None


# noinspection PyProtectedMember
class Slot(Generic[ItemT]):
    """Represents a single slot."""
    def __init__(
        self,
        man: Manager,
        parent: tkinter.Misc,
        is_source: bool,
        label: str,
    ) -> None:
        """Internal only, use Manager.slot()."""

        self.man = man
        self.is_source = is_source
        self._contents = None  # type: Optional[ItemT]
        self._pos_type = None  # type: Optional[str]
        self._lbl = tkinter.Label(
            parent,
            image=man._img_blank,
        )
        utils.bind_leftclick(self._lbl, self._evt_start)
        self._lbl.bind(utils.EVENTS['LEFT_SHIFT'], self._evt_fastdrag)
        self._lbl.bind('<Enter>', self._evt_hover_enter)
        self._lbl.bind('<Leave>', self._evt_hover_exit)

        config_event = self._evt_configure
        utils.bind_rightclick(self._lbl, config_event)

        if label:
            self._text_lbl = tkinter.Label(
                self._lbl,
                text=label,
                font=('Helvetica', -12),
                relief='ridge',
                bg=img.PETI_ITEM_BG_HEX,
            )  # type: Optional[tkinter.Label]
        else:
            self._text_lbl = None

        if man.config_icon:
            self._info_btn = tkinter.Label(
                self._lbl,
                image=img.png('icons/gear'),
                relief='ridge',
            )  # type: Optional[tkinter.Label]

            @utils.bind_leftclick(self._info_btn)
            def info_button_click(e):
                """Trigger the callback whenever the gear button was pressed."""
                config_event(e)
                # Cancel the event sequence, so it doesn't travel up to the main
                # window and hide the window again.
                return 'break'
            # Rightclick does the same as the main icon.
            utils.bind_rightclick(self._info_btn, config_event)
        else:
            self._info_btn = None

    @property
    def contents(self) -> Optional[ItemT]:
        """Get the item in this slot, or None if empty."""
        return self._contents

    @contents.setter
    def contents(self, value: Optional[ItemT]) -> None:
        """Set the item in this slot."""
        old_cont = self._contents

        if value is not None:
            # Make sure this isn't already present.
            for slot in self.man._targets:
                if slot.contents is value:
                    slot.contents = None
        # Then set us.
        self._contents = value

        if not self.is_source:
            # Update items in the previous group, so they gain the group icon
            # if only one now exists.
            self.man._group_update(getattr(old_cont, 'dnd_group', None))
            new_group = getattr(value, 'dnd_group', None)
        else:
            # Source pickers never group items.
            new_group = None

        if new_group is not None:
            # Update myself and the entire group to get the group
            # icon if required.
            self.man._group_update(new_group)
        else:
            # Just update myself.
            self.man._display_item(self._lbl, value)

    def grid(self, *args, **kwargs) -> None:
        """Grid-position this slot."""
        self._pos_type = 'grid'
        self._lbl.grid(*args, **kwargs)

    def place(self, *args, **kwargs) -> None:
        """Place-position this slot."""
        self._pos_type = 'place'
        self._lbl.place(*args, **kwargs)

    def pack(self, *args, **kwargs) -> None:
        """Pack-position this slot."""
        self._pos_type = 'pack'
        self._lbl.pack(*args, **kwargs)

    def hide(self) -> None:
        """Remove this slot from the set position manager."""
        if self._pos_type is None:
            raise ValueError('Not added to a geometry manager yet!')
        getattr(self._lbl, self._pos_type + '_forget')()
        self._pos_type = None

    def _evt_start(self, event: tkinter.Event) -> None:
        """Start dragging."""
        self.man._start(self, event)

    def _evt_fastdrag(self, event: tkinter.Event):
        """Quickly add/remove items by shift-clicking."""
        if self.is_source:
            # Add this item to the first free position.
            item = self.contents
            for slot in self.man._targets:
                if slot.contents is None:
                    slot.contents = item
                    sound.fx('config')
                    return
                elif slot.contents is item:
                    # It's already on the board, don't change anything.
                    sound.fx('config')
                    return
            sound.fx('delete')
        else:
            # Fast-delete this.
            self.contents = None
            sound.fx('delete')

    def _evt_hover_enter(self, event: tkinter.Event) -> None:
        """Fired when the cursor starts hovering over the item."""
        padding = 2 if utils.WIN else 0
        # Add border, but only if either icon exists or we contain an item.
        if self._text_lbl or self._contents is not None:
            self._lbl['relief'] = 'ridge'

        # Show configure icon for items.
        if self._info_btn and self._contents is not None:
            self._info_btn.place(
                x=self._lbl.winfo_width() - padding,
                y=self._lbl.winfo_height() - padding,
                anchor='se',
            )
        self.man._fire_callback(Event.HOVER_ENTER, self)

        if self._text_lbl:
            self._text_lbl.place(
                x=-padding,
                y=self._lbl.winfo_height() - padding,
                anchor='sw',
            )

    def _evt_hover_exit(self, event: tkinter.Event) -> None:
        """Fired when the cursor stops hovering over the item."""
        self._lbl['relief'] = 'flat'

        if self._info_btn:
            self._info_btn.place_forget()
        if self._text_lbl:
            self._text_lbl.place_forget()
        self.man._fire_callback(Event.HOVER_EXIT, self)

    def _evt_configure(self, event: tkinter.Event) -> None:
        """Configuration event, fired by clicking icon or right-clicking item."""
        if self.contents:
            self.man._fire_callback(Event.CONFIG, self)


def _test() -> None:
    """Test the GUI."""
    from srctools.logger import init_logging
    from tk_tools import TK_ROOT
    from BEE2_config import GEN_OPTS
    from packageLoader import find_packages, PACKAGE_SYS

    init_logging()

    # Setup images to read from packages.
    print('Loading packages for images.')
    GEN_OPTS.load()
    find_packages(GEN_OPTS['Directories']['package'])
    img.load_filesystems(PACKAGE_SYS.values())
    print('Done.')

    left_frm = ttk.Frame(TK_ROOT)
    right_frm = ttk.Frame(TK_ROOT)

    left_frm.grid(row=0, column=0, sticky='NSEW', padx=8)
    right_frm.grid(row=0, column=1, sticky='NSEW', padx=8)
    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.columnconfigure(1, weight=1)

    slot_dest = []
    slot_src = []

    class TestItem:
        def __init__(
            self,
            name: str,
            icon: str,
            group: str=None,
            group_icon: str=None,
        ) -> None:
            self.name = name
            self.dnd_icon = img.png('items/clean/{}.png'.format(icon))
            self.dnd_group = group
            if group_icon:
                self.dnd_group_icon = img.png('items/clean/{}.png'.format(group_icon))

        def __repr__(self) -> str:
            return '<Item {}>'.format(self.name)

    manager = Manager[TestItem](config_icon=True)

    def func(ev):
        def call(slot):
            print('Cback: ', ev, slot)
        return call

    for event in Event:
        manager.reg_callback(event, func(event))

    items = [
        TestItem('Dropper', 'dropper'),
        TestItem('Entry', 'entry_door'),
        TestItem('Exit', 'exit_door'),
        TestItem('Large Obs', 'large_obs_room'),
        TestItem('Faith Plate', 'faithplate'),

        TestItem('Standard Cube', 'cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Companion Cube', 'companion_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Reflection Cube', 'reflection_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Edgeless Cube', 'edgeless_safety_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Franken Cube', 'frankenturret', 'ITEM_CUBE', 'cubes'),

        TestItem('Repulsion Gel', 'paintsplat_bounce', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Propulsion Gel', 'paintsplat_speed', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Reflection Gel', 'paintsplat_reflection', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Conversion Gel', 'paintsplat_portal', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Cleansing Gel', 'paintsplat_water', 'ITEM_PAINT_SPLAT', 'paints'),
    ]

    for y in range(8):
        for x in range(4):
            slot = manager.slot(left_frm, source=False, label=(format(x + 4*y, '02') if y < 2 else ''))
            slot.grid(column=x, row=y, padx=1, pady=1)
            slot_dest.append(slot)

    for i, item in enumerate(items):
            slot = manager.slot(right_frm, source=True, label=format(i+1, '02'))
            slot.grid(column=i % 5, row=i // 5, padx=1, pady=1)
            slot_src.append(slot)
            slot.contents = item

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

    def enter(slot):
        if slot.contents is not None:
            name_lbl['text'] = 'Name: ' + slot.contents.name

    def exit(slot):
        name_lbl['text'] = ''

    manager.reg_callback(Event.HOVER_ENTER, enter)
    manager.reg_callback(Event.HOVER_EXIT, exit)
    manager.reg_callback(Event.CONFIG, lambda slot: messagebox.showinfo('Hello World', str(slot.contents)))

    TK_ROOT.deiconify()
    TK_ROOT.mainloop()

if __name__ == '__main__':
    _test()
