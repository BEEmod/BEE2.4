"""Implements drag/drop logic."""
from __future__ import annotations

import abc
from enum import Enum
from collections import defaultdict

import attrs
import trio
from tkinter import ttk, messagebox
from typing import (
    Awaitable, Callable, NewType, Union, Generic, TypeVar, Protocol, Optional,
    List, Tuple, Dict, Iterator, Iterable, runtime_checkable,
)
from typing_extensions import Literal, ParamSpec, Concatenate, TypeAlias
import tkinter

from srctools.logger import get_logger

from app import localisation, sound, img, TK_ROOT, tk_tools, background_run
from transtoken import TransToken
from ui_tk.img import TK_IMG
import utils
import event

__all__ = ['Manager', 'Slot', 'ItemProto', 'ItemGroupProto', 'DragUIProto', 'ItemT']
LOGGER = get_logger(__name__)


@attrs.frozen
class DragInfo:
    """The information required to display drag/drop items."""
    icon: img.Handle
    group: str | None = None
    # Set to the same as icon if not passed.
    group_icon: img.Handle = attrs.Factory(lambda self: self.icon, takes_self=True)


@runtime_checkable
class ItemProto(Protocol):
    """Protocol draggable items satisfy."""
    @property
    def dnd_icon(self) -> img.Handle:
        """Image for the item."""
        return img.Handle.error(0, 0)


@runtime_checkable
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


ItemT = TypeVar('ItemT')  # String etc representing the item being moved around.
ArgsT = ParamSpec('ArgsT')
ParentT = TypeVar('ParentT')  # Type indicating the "parent" of slots when being created.

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


InfoCB: TypeAlias = Callable[['Slot[ItemT]'], DragInfo]
FlexiCB: TypeAlias = Callable[[float, float], Optional[str]]
# Constant used instead of a Slot to represent the drag/drop window.
DragWin = NewType("DragWin", object)
SLOT_DRAG: DragWin = DragWin("<drag>")


# noinspection PyProtectedMember
class ManagerBase(Generic[ItemT, ParentT]):
    """Manages a set of drag-drop points."""
    def __init__(
        self,
        *,
        info_cb: InfoCB,
        size: Tuple[int, int]=(64, 64),
        config_icon: bool=False,
        pick_flexi_group: Optional[FlexiCB]=None,
    ):
        """Create a group of drag-drop slots.

        - ui: The implementation of the UI logic that will be used.
        - info_cb: Called on the items to look up the image and group.
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
        self._info_cb = info_cb
        self._pick_flexi_group = pick_flexi_group

        # If dragging, the item we are dragging.
        self._cur_drag: Optional[ItemT] = None
        # While dragging, the place we started at.
        self._cur_slot: Optional[Slot[ItemT]] = None

        self.event_bus = event.EventBus()

    @property
    def cur_slot(self) -> Optional[Slot[ItemT]]:
        """If dragging, the current slot."""
        return self._cur_slot

    def slot_target(
        self,
        parent: tkinter.Misc,
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a slot to this group, which can have items added/removed.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot: Slot[ItemT] = Slot(self, parent, SlotType.TARGET, label)
        self._slots.append(slot)
        return slot

    def slot_source(
        self,
        parent: tkinter.Misc,
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a readonly slot to this group which the user can fetch copies from.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot: Slot[ItemT] = Slot(self, parent, SlotType.SOURCE, label)
        self._slots.append(slot)
        return slot

    def slot_flexi(
        self,
        parent: tkinter.Misc,
        *,
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a 'flexible' slot to this group.

        These slots can have items dragged into/out of them, but when present any destroyed items
        get put into a spare flexi slot. The total number of these should match the number of
        sources.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        if self._pick_flexi_group is None:
            raise ValueError('Flexi callback missing!')
        slot: Slot[ItemT] = Slot(self, parent, SlotType.FLEXI, label)
        self._slots.append(slot)
        return slot

    def load_icons(self) -> None:
        """Load in all the item icons."""
        # Sources are never grouped, both of the other types are.

        # Count the number of items in each group to find
        # which should have group icons.
        groups: Dict[Optional[str], int] = defaultdict(int)
        for slot in self._slots:
            if not slot.is_source:
                groups[slot.contents_group] += 1

        groups[None] = 2  # This must always be ungrouped.

        for slot in self._slots:
            if slot.is_source:
                # These are never grouped.
                self._display_item(slot, slot.contents)
            else:
                self._display_item(
                    slot,
                    slot.contents,
                    groups[slot.contents_group] == 1
                )

        if self._cur_drag is not None:
            self._display_item(SLOT_DRAG, self._cur_drag)

    def unload_icons(self) -> None:
        """Reset all icons to blank. This way they can be destroyed."""
        for slot in self._slots:
            self._ui_set_icon(slot, self._img_blank)
        self._ui_set_icon(SLOT_DRAG, self._img_blank)

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

    # Methods subclasses must override:
    @abc.abstractmethod
    def _ui_set_icon(self, slot: Slot[ItemT] | DragWin, icon: img.Handle) -> None:
        """Set the specified slot to use this icon, or the drag/drop window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_slot_showdeco(self, slot: Slot[ItemT]) -> None:
        """Show the button/title on a slot."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_slot_hidedeco(self, slot: Slot[ItemT]) -> None:
        """Hide the title/button on a slot."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_slot_set_highlight(self, slot: Slot[ItemT], highlight: bool) -> None:
        """Apply the highlighted state."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
        """Check if this x/y coordinate is hovering over a slot."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_dragwin_show(self, x: float, y: float) -> None:
        """Show the drag window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_dragwin_hide(self) -> None:
        """Hide the drag window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_dragwin_update(self, x: float, y: float) -> None:
        """Move the drag window to this position."""
        raise NotImplementedError

    def _pos_slot(self, x: float, y: float) -> Optional[Slot[ItemT]]:
        """Find the slot under this X,Y (if any). Sources are ignored."""
        for slot in self._slots:
            if not slot.is_source and slot.is_visible:
                if self._ui_in_bbox(slot, x, y):
                    return slot
        return None

    def _display_item(
        self,
        slot: Slot[ItemT] | DragWin,
        item: Optional[ItemT],
        group: bool=False,
    ) -> None:
        """Display the specified item on the given slot."""
        image: img.Handle
        if item is None:
            image = self._img_blank
        elif group:
            image = self._info_cb(item).group_icon
        else:
            image = self._info_cb(item).icon
        self._ui_set_icon(slot, image)

    def _group_update(self, group: Optional[str]) -> None:
        """Update all target items with this group."""
        if group is None:
            # None to do.
            return
        group_slots = [
            slot for slot in self._slots
            if not slot.is_source
            if slot.contents_group == group
        ]

        has_group = len(group_slots) == 1
        for slot in group_slots:
            self._display_item(slot, slot.contents, has_group)

    def _on_start(self, slot: Slot[ItemT], x: float, y: float) -> None:
        """Start the drag."""
        if slot.contents is None:
            return  # Can't pick up blank...

        self._cur_drag = slot.contents

        show_group = False

        if not slot.is_source:
            slot.contents = None

            # If none of this group are present in the targets, and we're
            # pulling from the items, we hold a group icon.
            try:
                group = self._cur_drag.dnd_group  # type: ignore
            except AttributeError:
                pass
            else:
                if group is not None:
                    for other_slot in self._slots:
                        if other_slot.is_target and other_slot.contents_group == group:
                            break
                    else:
                        # None present.
                        show_group = True

        self._display_item(SLOT_DRAG, self._cur_drag, show_group)
        self._cur_slot = slot

        sound.fx('config')
        self._ui_dragwin_show(x, y)

    def _on_move(self, x: float, y: float) -> None:
        """Reposition the item whenever moving."""
        if self._cur_drag is None or self._cur_slot is None:
            # We aren't dragging, ignore the event.
            return
        self._ui_dragwin_update(x, y)

    def _on_stop(self, x: float, y: float) -> None:
        """User released the item."""
        if self._cur_drag is None or self._cur_slot is None:
            # We weren't dragging?
            return

        dest = self._pos_slot(x, y)

        if dest is self._cur_slot:
            assert dest is not None
            # Dropped on itself, fire special event, put the item back.
            dest.contents = self._cur_drag
            background_run(self.event_bus, Event.REDROPPED, dest)
            self._cur_drag = None
            self._cur_slot = None
            return

        sound.fx('config')

        if self._cur_slot.is_flexi:
            # It's a flexi slot, lookup the group and drop.
            if self._pick_flexi_group is None:
                raise ValueError('No pick_flexi_group function!')
            group = self._pick_flexi_group(x, y)
            for slot in self._slots:
                if slot.is_flexi and slot.contents is None and group is not None:
                    slot.contents = self._cur_drag
                    slot.flexi_group = group
                    background_run(self.event_bus, Event.MODIFIED)
                    break
            else:
                LOGGER.warning('Ran out of FLEXI slots for "{}", restored item: {}', group, self._cur_drag)
                self._cur_slot.contents = self._cur_drag
                background_run(self.event_bus, Event.REDROPPED, self._cur_slot)
        elif dest:  # We have a target.
            dest.contents = self._cur_drag
            background_run(self.event_bus, Event.MODIFIED)
        # No target, and we dragged off an existing target, delete.
        elif not self._cur_slot.is_source:
            background_run(self.event_bus, Event.MODIFIED)
            sound.fx('delete')

        self._cur_drag = None
        self._cur_slot = None

    def _on_fastdrag(self, slot: Slot[ItemT]) -> None:
        """Quickly add/remove items by shift-clicking."""
        if slot.is_flexi:  # TODO: What to do here??
            return

        if slot.is_source:
            # Add this item to the first free position.
            item = slot.contents
            for free in slot.man._slots:
                if not free.is_target:
                    continue
                if free.contents is None:
                    free.contents = item
                    sound.fx('config')
                    if slot.is_flexi:
                        slot.contents = None
                    background_run(self.event_bus, Event.MODIFIED)
                    return
                elif free.contents is item:
                    # It's already on the board, don't change anything.
                    sound.fx('config')
                    return
            # Failed.
            sound.fx('delete')
        # Else: target.
        else:
            # Fast-delete this.
            slot.contents = None
            background_run(self.event_bus, Event.MODIFIED)
            sound.fx('delete')

    def _on_hover_enter(self, slot: Slot[ItemT]) -> None:
        """Fired when the cursor starts hovering over the item."""
        self._ui_slot_showdeco(slot)
        background_run(self.event_bus, Event.HOVER_ENTER, slot)

    def _on_hover_exit(self, slot: Slot[ItemT]) -> None:
        """Fired when the cursor stops hovering over the item."""
        self._ui_slot_hidedeco(slot)
        background_run(self.event_bus, Event.HOVER_EXIT, slot)

    def _on_configure(self, slot: Slot[ItemT]) -> None:
        """Configuration event, fired by clicking icon or right-clicking item."""
        if slot.contents:
            background_run(self.event_bus, Event.CONFIG, self)


# noinspection PyProtectedMember
class Slot(Generic[ItemT]):
    """Represents a single slot."""

    # Optional ability to highlight a specific slot.
    _is_highlighted: bool

    flexi_group: str  # If a flexi slot, the group.

    # The current thing in the slot.
    _contents: Optional[ItemT]

    # The kind of slot.
    type: SlotType
    man: ManagerBase  # Our drag/drop controller.

    def __init__(
        self,
        man: ManagerBase,
        parent: tkinter.Misc,
        kind: SlotType,
        label: TransToken,
    ) -> None:
        """Internal only, use Manager.slot_*()."""
        self.man = man
        self.kind = kind
        self._contents = None
        self._pos_type = None

        self.flexi_group = ''

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
            self.man._group_update(self.man._info_cb(old_cont).group)
            new_group = self.man._info_cb(value).group
        else:
            # Source pickers never group items.
            new_group = None

        if self.is_flexi and (old_cont is None) != (value is None):
            # We're showing/hiding, we need to redraw.
            background_run(self.man.event_bus, Event.FLEXI_FLOW, self)

        if new_group is not None:
            # Update myself and the entire group to get the group
            # icon if required.
            self.man._group_update(new_group)
        else:
            # Just update myself.
            self.man._display_item(self, value)

    @property
    def contents_group(self) -> Optional[str]:
        """If the item in this slot has a group, return it."""
        if self._contents is not None:
            return getattr(self._contents, 'dnd_group', None)
        return None

    def __repr__(self) -> str:
        return f'<{self.kind.name} Slot @ {id(self):016x}: {self._contents!r}>'
