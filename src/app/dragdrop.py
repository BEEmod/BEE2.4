"""Implements drag/drop logic."""
from __future__ import annotations
from enum import Enum
from collections import defaultdict

import trio
from tkinter import ttk, messagebox
from typing import (
    Callable, Union, Generic, TypeVar, Protocol, Optional,
    List, Tuple, Dict, Iterator, Iterable,
)
import tkinter

from srctools.logger import get_logger

from app import sound, img, TK_ROOT, tk_tools, background_run
import utils
import event

__all__ = ['Manager', 'Slot', 'ItemProto', 'ItemGroupProto']
LOGGER = get_logger(__name__)


class ItemProto(Protocol):
    """Protocol draggable items satisfy."""
    @property
    def dnd_icon(self) -> img.Handle:
        """Image for the item."""
        return img.Handle.error(0, 0)


class ItemGroupProto(ItemProto, Protocol):
    """Additional values required when grouping."""
    @property
    def dnd_group(self) -> Optional[str]:
        """If set, the group an item belongs to."""
        return None

    @property
    def dnd_group_icon(self) -> Optional[img.Handle]:
        """If only one item is present for a group, it uses this."""
        return None


ItemT = TypeVar('ItemT', bound=ItemProto)  # The object the items move around.

# Tag used on canvases for our flowed slots.
_CANV_TAG = '_BEE2_dragdrop_item'


class Event(Enum):
    """Context for manager events. They provide either a relevant slot or None as the argument."""
    # Fires when items are right-clicked on. If one is registered, the gear
    # icon appears.
    CONFIG = 'config'

    # Fired when any slot is modified. This occurs only once if two swap etc.
    # The parameter is None.
    MODIFIED = 'modified'

    # Fired when a slot is dropped on itself - allows detecting a left click.
    REDROPPED = 'redropped'

    # When flexi slots are present, called when they're filled/emptied.
    FLEXI_FLOW = 'flexi_flow'

    # Mouse over or out of the items (including drag item).
    HOVER_ENTER = 'hover_enter'
    HOVER_EXIT = 'hover_exit'


class SlotType(Enum):
    """Kind of slot.

    FLEXI and SOURCE shouldn't be used together, that causes endless duplication.
    """
    TARGET = 'target'
    SOURCE = 'source'
    FLEXI = 'flexi'


class GeoManager(Enum):
    """Kind of geometry manager used for a slot."""
    GRID = 'grid'
    PLACE = 'place'
    PACK = 'pack'
    CANVAS = 'canvas'


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


class Positioner:
    """Utility for positioning slots in a grid on a canvas.

    - spacing is the amount added on each side of each slot.
    - yoff is the offset from the top, the new height is then returned to allow chaining.
    """
    def __init__(
        self,
        canvas: tkinter.Canvas,
        width: int,
        height: int,
        spacing: int=16 if utils.MAC else 8,
        yoff: int=0,
    ) -> None:
        self.canvas = canvas
        self.spacing = spacing
        self.current = 0  # Current x index.
        self.yoff = yoff + self.spacing

        self.item_width = width + spacing * 2
        self.item_height = height + spacing * 2

        self.width = canvas.winfo_width()
        self.height = canvas.winfo_height()

        self.columns = (self.width - spacing) // self.item_width
        if self.columns < 1:
            # Can't fit, they're going to stick out.
            self.columns = 1

    def xpos(self, col: int) -> int:
        """Return the x offset of a column"""
        return self.spacing + col * self.item_width

    def ypos(self, row: int) -> int:
        """Return the y offset of a row."""
        return self.yoff + row * self.item_height

    def advance_row(self) -> None:
        """Advance to the next row."""
        self.current = 0
        self.yoff += self.item_height

    def resize_canvas(self) -> None:
        """Set the scroll region of the canvas to fit items.

        This advances a row if the last is nonempty.
        """
        if self.current != 0:
            self.advance_row()
        self.canvas['scrollregion'] = (
            0, 0,
            self.columns * self.item_width + self.spacing,
            self.yoff,
        )

    def place_slots(self, slots: Iterable[Slot], tag: str, xoff: int=0) -> None:
        """Place these slots gradually."""
        for slot in slots:
            x = self.xpos(self.current)
            slot.canvas(self.canvas, x, self.yoff, tag)
            self.current += 1
            if self.current >= self.columns:
                self.advance_row()


# noinspection PyProtectedMember
class Manager(Generic[ItemT]):
    """Manages a set of drag-drop points."""
    def __init__(
        self,
        master: Union[tkinter.Tk, tkinter.Toplevel],
        *,
        size: Tuple[int, int]=(64, 64),
        config_icon: bool=False,
        pick_flexi_group: Optional[Callable[[int, int], Optional[str]]]=None,
    ):
        """Create a group of drag-drop slots.

        - size: This is the size of each moved image.
        - config_icon: If set, gear icons will be added to each slot to
          configure items. This indicates the right-click option is available,
          and makes it easier to press that.
        - pick_flexi_group: Allows using flexi slots. This is called with a root x/y position,
          and should return the name of the group to pick a slot from, or None if it should cancel.
        """
        self.width, self.height = size

        self._slots: List[Slot[ItemT]] = []

        self._img_blank = img.Handle.color(img.PETI_ITEM_BG, *size)

        self.config_icon = config_icon
        self._pick_flexi_group = pick_flexi_group

        # If dragging, the item we are dragging.
        self._cur_drag: Optional[ItemT] = None
        # While dragging, the place we started at.
        self._cur_slot: Optional[Slot[ItemT]] = None

        self.event = event.EventManager()

        self._drag_win = drag_win = tkinter.Toplevel(master)
        drag_win.withdraw()
        drag_win.transient(master=master)
        drag_win.wm_overrideredirect(True)

        self._drag_lbl = drag_lbl = tkinter.Label(drag_win)
        img.apply(drag_lbl, self._img_blank)
        drag_lbl.grid(row=0, column=0)
        drag_win.bind(tk_tools.EVENTS['LEFT_RELEASE'], self._evt_stop)

    @property
    def cur_slot(self) -> Optional[Slot[ItemT]]:
        """If dragging, the current slot."""
        return self._cur_slot

    def slot_target(
        self,
        parent: tkinter.Misc,
        label: str='',
    ) -> Slot[ItemT]:
        """Add a slot to this group, which can have items added/removed.

        Parameters:
            - parent: Parent widget for the slot.
            - label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot: Slot[ItemT] = Slot(self, parent, SlotType.TARGET, label)
        self._slots.append(slot)
        return slot

    def slot_source(
        self,
        parent: tkinter.Misc,
        label: str='',
    ) -> Slot[ItemT]:
        """Add a readonly slot to this group which the user can fetch copies from.

        Parameters:
            - parent: Parent widget for the slot.
            - label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot: Slot[ItemT] = Slot(self, parent, SlotType.SOURCE, label)
        self._slots.append(slot)
        return slot

    def slot_flexi(
        self,
        parent: tkinter.Misc,
        *,
        label: str='',
    ) -> Slot[ItemT]:
        """Add a 'flexible' slot to this group.

        These slots can have items dragged into/out of them, but when present any destroyed items
        get put into a spare flexi slot. The total number of these should match the number of
        sources.
        Parameters:
            - parent: Parent widget for the slot.
            - group: The group it's categorised in, should match that returned by the
              pick_flexi_group() callback.
            - label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        if self._pick_flexi_group is None:
            raise ValueError('Flexi callback missing!')
        slot: Slot[ItemT] = Slot(self, parent, SlotType.FLEXI, label)
        self._slots.append(slot)
        return slot

    def remove(self, slot: Slot[ItemT]) -> None:
        """Remove the specified slot."""
        self._slots.remove(slot)

    def load_icons(self) -> None:
        """Load in all the item icons."""
        # Sources are never grouped, both of the other types are.

        # Count the number of items in each group to find
        # which should have group icons.
        groups: Dict[Optional[str], int] = defaultdict(int)
        for slot in self._slots:
            if not slot.is_source:
                groups[getattr(slot.contents, 'dnd_group', None)] += 1

        groups[None] = 2  # This must always be ungrouped.

        for slot in self._slots:
            if slot.is_source:
                # These are never grouped.
                self._display_item(slot._lbl, slot.contents)
            else:
                self._display_item(
                    slot._lbl,
                    slot.contents,
                    groups[getattr(slot.contents, 'dnd_group', None)] == 1
                )

        if self._cur_drag is not None:
            self._display_item(self._drag_lbl, self._cur_drag)

    def unload_icons(self) -> None:
        """Reset all icons to blank. This way they can be destroyed."""
        for slot in self._slots:
            img.apply(slot._lbl, self._img_blank)
        img.apply(self._drag_lbl, self._img_blank)

    def sources(self) -> Iterator[Slot[ItemT]]:
        """Yield all source slots."""
        for slot in self._slots:
            if slot.is_source:
                yield slot

    def targets(self) -> Iterator[Slot[ItemT]]:
        """Yield all target slots."""
        for slot in self._slots:
            if slot.is_target:
                yield slot

    def flexi_slots(self) -> Iterator[Slot[ItemT]]:
        """Yield all flexible slots."""
        for slot in self._slots:
            if slot.is_flexi:
                yield slot

    def all_slots(self) -> Iterator[Slot[ItemT]]:
        """Yield all slots."""
        return iter(self._slots)

    def flow_slots(
        self,
        canv: tkinter.Canvas,
        slots: Iterable[Slot[ItemT]],
        spacing: int=16 if utils.MAC else 8,
        yoff: int=0,
        tag: str=_CANV_TAG,
    ) -> int:
        """Place all the slots in a grid on the provided canvas.

        Any previously added slots with the same tag will be removed.
        - spacing is the amount added on each side of each slot.
        - yoff is the offset from the top, the new height is then returned to allow chaining.
        """
        canv.delete(tag)
        pos = Positioner(canv, self.width, self.height, spacing, yoff)
        pos.place_slots(slots, tag)
        pos.resize_canvas()
        return pos.yoff

    def _pos_slot(self, x: float, y: float) -> Optional[Slot[ItemT]]:
        """Find the slot under this X,Y (if any). Sources are ignored."""
        for slot in self._slots:
            if not slot.is_source and slot.is_visible:
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
        image: img.Handle
        if item is None:
            image = self._img_blank
        elif group:
            try:
                image = item.dnd_group_icon  # type: ignore
            except AttributeError:
                image = item.dnd_icon
        else:
            image = item.dnd_icon
        img.apply(lbl, image)

    def _group_update(self, group: Optional[str]) -> None:
        """Update all target items with this group."""
        if group is None:
            # None to do..
            return
        group_slots = [
            slot for slot in self._slots
            if not slot.is_source
            if getattr(slot.contents, 'dnd_group', None) == group
        ]

        has_group = len(group_slots) == 1
        for slot in group_slots:
            self._display_item(slot._lbl, slot.contents, has_group)

    def _start(self, slot: Slot[ItemT], event: tkinter.Event) -> None:
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
                group = self._cur_drag.dnd_group  # type: ignore
            except AttributeError:
                pass
            else:
                if group is not None:
                    for other_slot in self._slots:
                        if other_slot.is_target and getattr(other_slot.contents, 'dnd_group', None) == group:
                            break
                    else:
                        # None present.
                        show_group = True

        self._display_item(self._drag_lbl, self._cur_drag, show_group)
        self._cur_slot = slot

        sound.fx('config')

        self._drag_win.deiconify()
        self._drag_win.lift()
        # grab makes this window the only one to receive mouse events, so
        # it is guaranteed that it'll drop when the mouse is released.
        self._drag_win.grab_set_global()
        # NOTE: _global means no other programs can interact, make sure
        # it's released eventually or you won't be able to quit!

        # Call this to reposition it.
        self._evt_move(event)

        self._drag_win.bind(tk_tools.EVENTS['LEFT_MOVE'], self._evt_move)

    def _evt_move(self, event: tkinter.Event) -> None:
        """Reposition the item whenever moving."""
        if self._cur_drag is None or self._cur_slot is None:
            # We aren't dragging, ignore the event.
            return

        self._drag_win.geometry('+{}+{}'.format(
            event.x_root - self.width // 2,
            event.y_root - self.height // 2,
        ))

        dest = self._pos_slot(event.x_root, event.y_root)

        if dest:
            self._drag_win['cursor'] = tk_tools.Cursors.MOVE_ITEM
        elif self._cur_slot.is_source:
            self._drag_win['cursor'] = tk_tools.Cursors.INVALID_DRAG
        elif self._cur_slot.is_flexi:  # If it's a flexi slot, it's going back.
            self._drag_win['cursor'] = tk_tools.Cursors.MOVE_ITEM
        else:
            self._drag_win['cursor'] = tk_tools.Cursors.DESTROY_ITEM

    def _evt_stop(self, evt: tkinter.Event) -> None:
        """User released the item."""
        if self._cur_drag is None or self._cur_slot is None:
            return
        self._drag_win.grab_release()
        self._drag_win.withdraw()
        self._drag_win.unbind(tk_tools.EVENTS['LEFT_MOVE'])

        dest = self._pos_slot(evt.x_root, evt.y_root)

        if dest is self._cur_slot:
            assert dest is not None
            # Dropped on itself, fire special event, put the item back.
            dest.contents = self._cur_drag
            background_run(self.event, Event.REDROPPED, dest)
            self._cur_drag = None
            self._cur_slot = None
            return

        sound.fx('config')

        if self._cur_slot.is_flexi:
            # It's a flexi slot, lookup the group and drop.
            if self._pick_flexi_group is None:
                raise ValueError('No pick_flexi_group function!')
            group = self._pick_flexi_group(evt.x_root, evt.y_root)
            for slot in self._slots:
                if slot.is_flexi and slot.contents is None and group is not None:
                    slot.contents = self._cur_drag
                    slot.flexi_group = group
                    background_run(self.event, Event.MODIFIED)
                    break
            else:
                LOGGER.warning('Ran out of FLEXI slots for "{}", restored item: {}', group, self._cur_drag)
                self._cur_slot.contents = self._cur_drag
                background_run(self.event, Event.REDROPPED, self._cur_slot)
        elif dest:  # We have a target.
            dest.contents = self._cur_drag
            background_run(self.event, Event.MODIFIED)
        # No target, and we dragged off an existing target, delete.
        elif not self._cur_slot.is_source:
            background_run(self.event, Event.MODIFIED)
            sound.fx('delete')

        self._cur_drag = None
        self._cur_slot = None


# noinspection PyProtectedMember
class Slot(Generic[ItemT]):
    """Represents a single slot."""
    # The two widgets shown at the bottom when moused over.
    _text_lbl: Optional[tkinter.Label]
    _info_btn: Optional[tkinter.Label]
    # Our main widget.
    _lbl: ttk.Label

    # Optional ability to highlight a specific slot.
    _is_highlighted: bool

    flexi_group: str  # If a flexi slot, the group.

    # The current thing in the slot.
    _contents: Optional[ItemT]

    # The geometry manager used to position this.
    _pos_type: Optional[GeoManager]
    # If canvas, the tag and x/y coords.
    _canv_info: Optional[Tuple[int, int, int]]

    # The kind of slot.
    type: SlotType
    man: Manager  # Our drag/drop controller.

    def __init__(
        self,
        man: Manager,
        parent: tkinter.Misc,
        kind: SlotType,
        label: str,
    ) -> None:
        """Internal only, use Manager.slot()."""
        self.man = man
        self.kind = kind
        self._contents = None
        self._pos_type = None
        self._canv_info = None
        self._lbl = ttk.Label(parent, anchor='center')
        self._selected = False

        self.flexi_group = ''

        img.apply(self._lbl, man._img_blank)
        tk_tools.bind_leftclick(self._lbl, self._evt_start)
        self._lbl.bind(tk_tools.EVENTS['LEFT_SHIFT'], self._evt_fastdrag)
        self._lbl.bind('<Enter>', self._evt_hover_enter)
        self._lbl.bind('<Leave>', self._evt_hover_exit)
        # Bind this not the self variable.
        config_event = self._evt_configure
        tk_tools.bind_rightclick(self._lbl, config_event)

        if label:
            self._text_lbl = tkinter.Label(
                self._lbl,
                text=label,
                font=('Helvetica', -12),
                relief='ridge',
                bg=img.PETI_ITEM_BG_HEX,
            )
        else:
            self._text_lbl = None

        if man.config_icon:
            self._info_btn = tkinter.Label(
                self._lbl,
                relief='ridge',
            )
            img.apply(self._info_btn, img.Handle.builtin('icons/gear', 10, 10))

            @tk_tools.bind_leftclick(self._info_btn)
            def info_button_click(e: tkinter.Event) -> object:
                """Trigger the callback whenever the gear button was pressed."""
                config_event(e)
                # Cancel the event sequence, so it doesn't travel up to the main
                # window and hide the window again.
                return 'break'
            # Rightclick does the same as the main icon.
            tk_tools.bind_rightclick(self._info_btn, config_event)
        else:
            self._info_btn = None

    @property
    def is_target(self) -> bool:
        """Check if this is a target slot."""
        return self.kind is SlotType.TARGET

    @property
    def is_source(self) -> bool:
        """Check if this is a source slot."""
        return self.kind is SlotType.SOURCE

    @property
    def is_flexi(self) -> bool:
        """Check if this is a flexi slot."""
        return self.kind is SlotType.FLEXI

    @property
    def is_visible(self) -> bool:
        """Check if this slot is currently displayed."""
        return self._pos_type is not None

    @property
    def highlight(self) -> bool:
        """Allows setting/getting if the slot has an alternate selection state."""
        return self._is_highlighted

    @highlight.setter
    def highlight(self, value: bool) -> None:
        """Allows setting/getting if the slot has an alternate selection state."""
        self._is_highlighted = bool(value)
        self._lbl['background'] = (
            '#5AD2D2' if self._is_highlighted else ''
        )

    @property
    def contents(self) -> Optional[ItemT]:
        """Get the item in this slot, or None if empty."""
        return self._contents

    @contents.setter
    def contents(self, value: Optional[ItemT]) -> None:
        """Set the item in this slot."""
        old_cont = self._contents

        if value is not None and self.is_target:
            # Make sure this isn't already present.
            for slot in self.man._slots:
                if slot.is_target and slot.contents is value:
                    slot.contents = None
        # Then set us.
        self._contents = value

        if self.is_target:
            # Update items in the previous group, so they gain the group icon
            # if only one now exists.
            self.man._group_update(getattr(old_cont, 'dnd_group', None))
            new_group = getattr(value, 'dnd_group', None)
        else:
            # Source pickers never group items.
            new_group = None

        if self.is_flexi and (old_cont is None) != (value is None):
            # We're showing/hiding, we need to redraw.
            background_run(self.man.event, Event.FLEXI_FLOW, self)

        if new_group is not None:
            # Update myself and the entire group to get the group
            # icon if required.
            self.man._group_update(new_group)
        else:
            # Just update myself.
            self.man._display_item(self._lbl, value)

    def __repr__(self) -> str:
        return f'<{self.kind.name} Slot @ {id(self):016x}: {self._contents!r}>'

    def grid(self, *args, **kwargs) -> None:
        """Grid-position this slot."""
        self._pos_type = GeoManager.GRID
        self._canv_info = None
        self._lbl.grid(*args, **kwargs)

    def place(self, *args, **kwargs) -> None:
        """Place-position this slot."""
        self._pos_type = GeoManager.PLACE
        self._canv_info = None
        self._lbl.place(*args, **kwargs)

    def pack(self, *args, **kwargs) -> None:
        """Pack-position this slot."""
        self._pos_type = GeoManager.PACK
        self._canv_info = None
        self._lbl.pack(*args, **kwargs)

    def canvas(self, canv: tkinter.Canvas, x: int, y: int, tag: str) -> None:
        """Position this slot on a canvas."""
        if self._pos_type is not None and self._pos_type is not GeoManager.CANVAS:
            raise ValueError("Can't add already positioned slot!")
        obj_id = canv.create_window(
            x, y,
            width=self.man.width,
            height=self.man.height,
            anchor='nw',
            window=self._lbl,
            tags=(tag,),
        )
        self._pos_type = GeoManager.CANVAS
        self._canv_info = (obj_id, x, y)

    def canvas_pos(self, canv: tkinter.Canvas) -> Tuple[int, int]:
        """If on a canvas, fetch the current x/y position."""
        if self._canv_info is not None:
            _, x, y = self._canv_info
            return x, y
        raise ValueError('Not on a canvas!')

    def hide(self) -> None:
        """Remove this slot from the set position manager."""
        if self._pos_type is None:
            raise ValueError('Not added to a geometry manager yet!')
        elif self._pos_type is GeoManager.CANVAS:
            # Attached via canvas, with an ID as suffix.
            canv = self._lbl.nametowidget(self._lbl.winfo_parent())
            assert isinstance(canv, tkinter.Canvas)
            assert self._canv_info is not None
            obj_id, _, _ = self._canv_info
            canv.delete(obj_id)
        else:
            getattr(self._lbl, self._pos_type.value + '_forget')()
        self._pos_type = None
        self._canv_info = None

    def _evt_start(self, event: tkinter.Event) -> None:
        """Start dragging."""
        self.man._start(self, event)

    def _evt_fastdrag(self, event: tkinter.Event) -> None:
        """Quickly add/remove items by shift-clicking."""
        if self.is_flexi:  # TODO:
            return

        if self.is_source:
            # Add this item to the first free position.
            item = self.contents
            for slot in self.man._slots:
                if not slot.is_target:
                    continue
                if slot.contents is None:
                    slot.contents = item
                    sound.fx('config')
                    if self.is_flexi:
                        self.contents = None
                    background_run(self.man.event, Event.MODIFIED)
                    return
                elif slot.contents is item:
                    # It's already on the board, don't change anything.
                    sound.fx('config')
                    return
            # Failed.
            sound.fx('delete')
        # Else: target.
        else:
            # Fast-delete this.
            self.contents = None
            background_run(self.man.event, Event.MODIFIED)
            sound.fx('delete')

    def _evt_hover_enter(self, event: tkinter.Event) -> None:
        """Fired when the cursor starts hovering over the item."""
        padding = 2 if utils.WIN else 0
        # Add border, but only if either icon exists or we contain an item.
        if self._text_lbl or self._contents is not None:
            self._lbl['relief'] = 'ridge'

        # Show configure icon for items.
        if self._info_btn is not None and self._contents is not None:
            self._info_btn.place(
                x=self._lbl.winfo_width() - padding,
                y=self._lbl.winfo_height() - padding,
                anchor='se',
            )
        background_run(self.man.event, Event.HOVER_ENTER, self)

        if self._text_lbl:
            self._text_lbl.place(
                x=-padding,
                y=self._lbl.winfo_height() - padding,
                anchor='sw',
            )

    def _evt_hover_exit(self, _: tkinter.Event) -> None:
        """Fired when the cursor stops hovering over the item."""
        self._lbl['relief'] = 'flat'

        if self._info_btn:
            self._info_btn.place_forget()
        if self._text_lbl:
            self._text_lbl.place_forget()
        background_run(self.man.event, Event.HOVER_EXIT, self)

    def _evt_configure(self, _: tkinter.Event) -> None:
        """Configuration event, fired by clicking icon or right-clicking item."""
        if self.contents:
            background_run(self.man.event, Event.CONFIG, self)


async def test() -> None:
    """Test the GUI."""
    import BEE2_config
    import config
    import packages

    BEE2_config.GEN_OPTS.load()
    config.read_settings()

    # Setup images to read from packages.
    print('Loading packages for images.')
    async with trio.open_nursery() as pack_nursery:
        for loc in BEE2_config.get_package_locs():
            pack_nursery.start_soon(
                packages.find_packages,
                pack_nursery,
                packages.LOADED,
                loc,
            )
    background_run(img.init, packages.PACKAGE_SYS)
    background_run(sound.sound_task)
    print('Done.')

    left_frm = ttk.Frame(TK_ROOT)
    right_canv = tkinter.Canvas(TK_ROOT)

    left_frm.grid(row=0, column=0, sticky='NSEW', padx=8)
    right_canv.grid(row=0, column=1, sticky='NSEW', padx=8)
    TK_ROOT.rowconfigure(0, weight=1)
    TK_ROOT.columnconfigure(1, weight=1)

    slot_dest = []
    slot_src = []

    class TestItem:
        def __init__(
            self,
            name: str,
            pak_id: str,
            icon: str,
            group: str=None,
            group_icon: str=None,
        ) -> None:
            self.name = name
            self.dnd_icon = img.Handle.parse_uri(utils.PackagePath(pak_id, ('items/clean/{}.png'.format(icon))), 64, 64)
            self.dnd_group = group
            if group_icon:
                self.dnd_group_icon = img.Handle.parse_uri(utils.PackagePath(pak_id, 'items/clean/{}.png'.format(group_icon)), 64, 64)

        def __repr__(self) -> str:
            return '<Item {}>'.format(self.name)

    manager: Manager[TestItem] = Manager(TK_ROOT, config_icon=True)

    def func(ev):
        async def call(slot: Slot[TestItem]) -> None:
            print('Cback: ', ev, slot)
        return call

    for evt in Event:
        manager.event.register(evt, Slot[TestItem], func(evt))

    PAK_CLEAN = 'BEE2_CLEAN_STYLE'
    PAK_ELEM = 'VALVE_TEST_ELEM'
    items = [
        TestItem('Dropper', PAK_CLEAN, 'dropper'),
        TestItem('Entry', PAK_CLEAN, 'entry_door'),
        TestItem('Exit', PAK_CLEAN, 'exit_door'),
        TestItem('Large Obs', PAK_CLEAN, 'large_obs_room'),
        TestItem('Faith Plate', PAK_ELEM, 'faithplate'),

        TestItem('Standard Cube', PAK_ELEM, 'cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Companion Cube', PAK_ELEM, 'companion_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Reflection Cube', PAK_ELEM, 'reflection_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Edgeless Cube', PAK_ELEM, 'edgeless_safety_cube', 'ITEM_CUBE', 'cubes'),
        TestItem('Franken Cube', PAK_ELEM, 'frankenturret', 'ITEM_CUBE', 'cubes'),

        TestItem('Repulsion Gel', PAK_ELEM, 'paintsplat_bounce', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Propulsion Gel', PAK_ELEM, 'paintsplat_speed', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Reflection Gel', PAK_ELEM, 'paintsplat_reflection', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Conversion Gel', PAK_ELEM, 'paintsplat_portal', 'ITEM_PAINT_SPLAT', 'paints'),
        TestItem('Cleansing Gel', PAK_ELEM, 'paintsplat_water', 'ITEM_PAINT_SPLAT', 'paints'),
    ]

    for y in range(8):
        for x in range(4):
            slot = manager.slot_target(left_frm, label=(format(x + 4*y, '02') if y < 3 else ''))
            slot.grid(column=x, row=y, padx=1, pady=1)
            slot_dest.append(slot)

    FLEXI = True
    right_kind = manager.slot_flexi if FLEXI else manager.slot_source
    for i, item in enumerate(items):
        slot = right_kind(right_canv, label=format(i+1, '02'))
        slot_src.append(slot)
        slot.contents = item

    def configure(e):
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

    async def evt_enter(evt_slot: Slot[TestItem]) -> None:
        if evt_slot.contents is not None:
            name_lbl['text'] = 'Name: ' + evt_slot.contents.name

    async def evt_exit(evt_slot: Slot[TestItem]) -> None:
        name_lbl['text'] = ''

    async def evt_config(evt_slot: Slot[TestItem]) -> None:
        messagebox.showinfo('Hello World', str(evt_slot.contents))

    manager.event.register(Event.HOVER_ENTER, Slot[TestItem], evt_enter)
    manager.event.register(Event.HOVER_EXIT, Slot[TestItem], evt_exit)
    manager.event.register(Event.CONFIG, Slot[TestItem], evt_config)

    TK_ROOT.deiconify()
    with trio.CancelScope() as scope:
        TK_ROOT.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
        await trio.sleep_forever()
