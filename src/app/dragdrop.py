"""Implements drag/drop logic."""
from __future__ import annotations
from typing import Any, Final

from collections import Counter
from collections.abc import Callable, Iterator
from enum import Enum
import abc
import itertools

from srctools.logger import get_logger
from trio_util import AsyncValue, RepeatedEvent
import attrs

from app import img, sound
from async_util import EdgeTrigger
from transtoken import TransToken
import utils


__all__ = [
    'ManagerBase', 'Slot', 'DragInfo', 'SlotType', 'SLOT_DRAG',
    'InfoCB', 'DragWin', 'FlexiCB', 'in_bbox',
]
LOGGER = get_logger(__name__)
type Group = utils.SpecialID


@attrs.frozen
class DragInfo:
    """The information required to display drag/drop items."""
    icon: img.Handle
    group: Group | None = None
    # Set to the same as icon if not passed.
    group_icon: img.Handle = attrs.Factory(lambda self: self.icon, takes_self=True)


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


type InfoCB[ItemT] = Callable[[ItemT], DragInfo]
type FlexiCB = Callable[[float, float], str | None]


class DragWin(Enum):
    """Constant used instead of a Slot to represent the drag/drop window."""
    DRAG = "drag"


SLOT_DRAG: Final = DragWin.DRAG


# noinspection PyProtectedMember
class ManagerBase[ItemT, ParentT]:
    """Manages a set of drag-drop points.

    ItemT: Value representing the item being moved around.
    ParentT: Indicates the "parent" of slots when being created.
    """
    width: Final[int]
    height: Final[int]
    config_icon: Final[bool]
    _info_cb: InfoCB[ItemT]
    _pick_flexi_group: FlexiCB | None

    _slots: dict[SlotType, list[Slot[ItemT]]]
    _img_blank: img.Handle  # Image for an empty slot.

    # If dragging, the item we are dragging.
    _cur_drag: ItemT | None
    # While dragging, the place we started at.
    _cur_slot: Slot[ItemT] | None

    # Various hooks for reacting to events.

    # Fires when items are right-clicked on or the config button is pressed.
    on_config: EdgeTrigger[Slot[ItemT]]
    # Fired when any slot is modified. This occurs only once if two swap etc.
    on_modified: RepeatedEvent

    # When flexi slots are present, called when they're filled/emptied.
    on_flexi_flow: RepeatedEvent

    # The item currently being hovered over (including the drag item).
    hovered_item: AsyncValue[ItemT | None]

    def __init__(
        self,
        *,
        info_cb: InfoCB[ItemT],
        size: tuple[int, int] = (64, 64),
        config_icon: bool = False,
        pick_flexi_group: FlexiCB | None = None,
    ) -> None:
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
        self.config_icon = config_icon
        self._info_cb = info_cb
        self._pick_flexi_group = pick_flexi_group

        self._slots = {kind: [] for kind in SlotType}
        self._img_blank = img.Handle.color(img.PETI_ITEM_BG, *size)
        self._cur_drag = self._cur_slot = None

        self.on_config = EdgeTrigger()
        self.on_modified = RepeatedEvent()
        self.on_flexi_flow = RepeatedEvent()
        self.hovered_item = AsyncValue(None)

    @property
    def cur_slot(self) -> Slot[ItemT] | None:
        """If dragging, the current slot."""
        return self._cur_slot

    def slot_target(
        self,
        parent: ParentT,
        *,
        desc: str = '',
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a slot to this group, which can have items added/removed.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        :param desc: If set, a description to use to identify the slot in logs etc.
        """
        slot: Slot[ItemT] = Slot(self, SlotType.TARGET, desc or str(label))
        self._ui_slot_create(slot, parent, label)
        self._slots[SlotType.TARGET].append(slot)
        return slot

    def slot_source(
        self,
        parent: ParentT,
        *,
        desc: str = '',
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a readonly slot to this group which the user can fetch copies from.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        :param desc: If set, a description to use to identify the slot in logs etc.
        """
        slot: Slot[ItemT] = Slot(self, SlotType.SOURCE, desc or str(label))
        self._ui_slot_create(slot, parent, label)
        self._slots[SlotType.SOURCE].append(slot)
        return slot

    def slot_flexi(
        self,
        parent: ParentT,
        *,
        desc: str = '',
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a 'flexible' slot to this group.

        These slots can have items dragged into/out of them, but when present any destroyed items
        get put into a spare flexi slot. The total number of these should match the number of
        sources.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        :param desc: If set, a description to use to identify the slot in logs etc.
        """
        if self._pick_flexi_group is None:
            raise ValueError('Flexi callback missing!')
        slot: Slot[ItemT] = Slot(self, SlotType.FLEXI, desc or str(label))
        self._ui_slot_create(slot, parent, label)
        self._slots[SlotType.FLEXI].append(slot)
        return slot

    def load_icons(self) -> None:
        """Load in all the item icons."""
        # Sources are never grouped, both of the other types are.

        # Count the number of items in each group to find
        # which should have group icons.
        for kind in SlotType:
            groups: dict[str | None, int] = Counter()
            for slot in self._slots[kind]:
                groups[slot.contents_group] += 1

            groups[None] = 2  # This must always be ungrouped.

            for slot in self._slots[kind]:
                self._display_item(
                    slot,
                    slot.contents,
                    groups[slot.contents_group] == 1
                )

        if self._cur_drag is not None:
            self._display_item(SLOT_DRAG, self._cur_drag)

    def unload_icons(self) -> None:
        """Reset all icons to blank. This way they can be destroyed."""
        for slot in self.all_slots():
            self._ui_set_icon(slot, self._img_blank)
        self._ui_set_icon(SLOT_DRAG, self._img_blank)

    def sources(self) -> Iterator[Slot[ItemT]]:
        """Yield all source slots."""
        return iter(self._slots[SlotType.SOURCE])

    def targets(self) -> Iterator[Slot[ItemT]]:
        """Yield all target slots."""
        return iter(self._slots[SlotType.TARGET])

    def flexi_slots(self) -> Iterator[Slot[ItemT]]:
        """Yield all flexible slots."""
        return iter(self._slots[SlotType.FLEXI])

    def all_slots(self) -> Iterator[Slot[ItemT]]:
        """Yield all slots."""
        return itertools.chain.from_iterable(self._slots.values())

    # Methods subclasses must override:
    @abc.abstractmethod
    def _ui_set_icon(self, slot: Slot[ItemT] | DragWin, icon: img.Handle) -> None:
        """Set the specified slot to use this icon, or the drag/drop window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_slot_create(
        self,
        slot: Slot[ItemT],
        parent: ParentT,
        title: TransToken,
    ) -> None:
        """Called when a slot is added, to create the UI form."""
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
    def _ui_slot_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
        """Check if this x/y coordinate is hovering over a slot."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_slot_coords(self, slot: Slot[ItemT]) -> tuple[int, int]:
        """Return the screen position for this slot.

        :raises ValueError: if the slot is not placed.
        """
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

    def _pos_slot(self, x: float, y: float) -> Slot[ItemT] | None:
        """Find the slot under this X,Y (if any). Sources are ignored."""
        for slot in self._slots[SlotType.TARGET]:
            if self._ui_slot_in_bbox(slot, x, y):
                return slot
        for slot in self._slots[SlotType.FLEXI]:
            if self._ui_slot_in_bbox(slot, x, y):
                return slot
        return None

    def _display_item(
        self,
        slot: Slot[ItemT] | DragWin,
        item: ItemT | None,
        group: bool = False,
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

    def _group_update(self, slot_type: SlotType, group: Group | None) -> None:
        """Update all target items with this group."""
        if group is None:
            # None to do.
            return
        group_slots = [
            slot for slot in self._slots[slot_type]
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
            group = self._info_cb(self._cur_drag).group
            if group is not None:
                for other_slot in self._slots[SlotType.TARGET]:
                    if other_slot.contents_group == group:
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

    def _on_cancel(self) -> None:
        """Abort dragging."""
        self._ui_dragwin_hide()
        if self._cur_drag is not None and self._cur_slot is not None:
            # Put the item back on its original position.
            self._cur_slot.contents = self._cur_drag
            self._cur_drag = self._cur_slot = None

    def _on_stop(self, x: float, y: float) -> None:
        """User released the item."""
        if self._cur_drag is None or self._cur_slot is None:
            # We weren't dragging?
            return

        self._ui_dragwin_hide()
        dest = self._pos_slot(x, y)

        sound.fx('config')

        if dest is self._cur_slot:
            # Dropped on itself, just put the item back.
            dest.contents = self._cur_drag
            self._cur_drag = self._cur_slot = None
            return

        if self._cur_slot.is_flexi:
            # It's a flexi slot, lookup the group and drop.
            if self._pick_flexi_group is None:
                raise ValueError('No pick_flexi_group function!')
            group = self._pick_flexi_group(x, y)
            for slot in self._slots[SlotType.FLEXI]:
                if slot.contents is None and group is not None:
                    slot.contents = self._cur_drag
                    slot.flexi_group = group
                    self.on_modified.set()
                    break
            else:
                LOGGER.warning('Ran out of FLEXI slots for "{}", restored item: {}', group, self._cur_drag)
                self._cur_slot.contents = self._cur_drag
                self.on_modified.set()
        elif dest:  # We have a target.
            dest.contents = self._cur_drag
            self.on_modified.set()
        # No target, and we dragged off an existing target, delete.
        elif not self._cur_slot.is_source:
            self.on_modified.set()
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
            for free in slot.man._slots[SlotType.TARGET]:
                if free.contents is None:
                    free.contents = item
                    sound.fx('config')
                    if slot.is_flexi:
                        slot.contents = None
                    self.on_modified.set()
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
            self.on_modified.set()
            sound.fx('delete')

    def _on_hover_enter(self, slot: Slot[ItemT]) -> None:
        """Fired when the cursor starts hovering over the item."""
        self._ui_slot_showdeco(slot)
        self.hovered_item.value = slot.contents

    def _on_hover_exit(self, slot: Slot[ItemT]) -> None:
        """Fired when the cursor stops hovering over the item."""
        self._ui_slot_hidedeco(slot)
        self.hovered_item.value = None

    def _on_configure(self, slot: Slot[ItemT]) -> None:
        """Configuration event, fired by clicking icon or right-clicking item."""
        if slot.contents is not None and self.on_config.ready.value:
            self.on_config.trigger(slot)


# noinspection PyProtectedMember
class Slot[ItemT]:
    """Represents a single slot."""

    # Optional ability to highlight a specific slot.
    _is_highlighted: bool

    flexi_group: str  # If a flexi slot, the group.

    # The current thing in the slot.
    _contents: ItemT | None

    # The kind of slot.
    kind: Final[SlotType]
    man: ManagerBase[ItemT, Any]  # Our drag/drop controller.
    # Used to identify the slot in logs etc.
    desc: str

    def __init__(self, man: ManagerBase[ItemT, Any], kind: SlotType, desc: str) -> None:
        """Internal only, use Manager.slot_*()."""
        self.man = man
        self.kind = kind
        self._contents = None
        self._pos_type = None
        self.desc = desc

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
    def highlight(self) -> bool:
        """Allows setting/getting if the slot has an alternate selection state."""
        return self._is_highlighted

    @highlight.setter
    def highlight(self, value: bool) -> None:
        """Allows setting/getting if the slot has an alternate selection state."""
        self._is_highlighted = bool(value)

    @property
    def contents(self) -> ItemT | None:
        """Get the item in this slot, or None if empty."""
        return self._contents

    @contents.setter
    def contents(self, value: ItemT | None) -> None:
        """Set the item in this slot."""
        old_cont = self._contents

        if value is not None and self.is_target:
            # Make sure this isn't already present.
            for slot in self.man._slots[SlotType.TARGET]:
                if slot.contents == value:
                    slot.contents = None
        # Then set us.
        self._contents = value

        # Update items in the previous group, so they gain the group icon
        # if only one now exists.
        if old_cont is not None:
            self.man._group_update(self.kind, self.man._info_cb(old_cont).group)

        if value is not None:
            new_group = self.man._info_cb(value).group
        else:
            new_group = None

        if self.is_flexi and (old_cont is None) != (value is None):
            # We're showing/hiding, we need to redraw.
            self.man.on_flexi_flow.set()

        if new_group is not None:
            # Update myself and the entire group to get the group
            # icon if required.
            self.man._group_update(self.kind, new_group)
        else:
            # Just update myself.
            self.man._display_item(self, value)

    @property
    def contents_group(self) -> Group | None:
        """If the item in this slot has a group, return it."""
        if self._contents is not None:
            return self.man._info_cb(self._contents).group
        return None

    def __repr__(self) -> str:
        desc = f'"{self.desc}"' if self.desc else f'@ {id(self):016x}'
        return f'<{self.kind.name} Slot {desc}: {self._contents!r}>'

    def get_coords(self) -> tuple[int, int]:
        """Return the screen location of this slot.

        :raises ValueError: if the slot is not placed.
        """
        return self.man._ui_slot_coords(self)
