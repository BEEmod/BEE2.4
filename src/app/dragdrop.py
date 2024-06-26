"""Implements drag/drop logic."""
from __future__ import annotations
from typing import Any, Callable, Final, Generic, TypeVar, Optional
from typing_extensions import ParamSpec, TypeAliasType

from collections.abc import Iterable, Iterator
from collections import defaultdict
from enum import Enum
import abc

from srctools.logger import get_logger
from trio_util import AsyncValue, RepeatedEvent
import attrs

from app import img, sound, EdgeTrigger
from transtoken import TransToken
import utils


__all__ = [
    'ManagerBase', 'Slot', 'DragInfo', 'ParentT', 'SlotType', 'SLOT_DRAG', 'ItemT',
    'InfoCB', 'DragWin', 'FlexiCB', 'PositionerBase', 'in_bbox',
]
LOGGER = get_logger(__name__)


@attrs.frozen
class DragInfo:
    """The information required to display drag/drop items."""
    icon: img.Handle
    group: str | None = None
    # Set to the same as icon if not passed.
    group_icon: img.Handle = attrs.Factory(lambda self: self.icon, takes_self=True)


ItemT = TypeVar('ItemT')  # String etc representing the item being moved around.
ArgsT = ParamSpec('ArgsT')
T = TypeVar('T')
ParentT = TypeVar('ParentT')  # Type indicating the "parent" of slots when being created.


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


class PositionerBase:
    """Utility for positioning slots in a grid on a canvas.

    - spacing is the amount added on each side of each slot.
    - yoff is the offset from the top, the new height is then returned to allow chaining.
    """

    def __init__(
        self,
        width: int,
        height: int,
        item_width: int,
        item_height: int,
        spacing: int = -1,
        yoff: int = 0,
    ) -> None:
        if spacing <= 0:
            spacing = 16 if utils.MAC else 8

        self.spacing = spacing
        self.current = 0  # Current x index.
        self.yoff = yoff + self.spacing

        self.item_width = item_width + spacing * 2
        self.item_height = item_height + spacing * 2

        self.width = width
        self.height = height

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

    def get_size(self) -> tuple[int, int]:
        """Calculate the total bounding box.

        This advances a row if the last is nonempty.
        """
        width = self.columns * self.item_width + self.spacing
        height = self.yoff
        if self.current != 0:
            height += self.item_height
        return width, height

    def _get_positions(
        self,
        slots: Iterable[T],
        xoff: int,
    ) -> Iterator[tuple[T, int, int]]:
        """Place these slots gradually."""
        for slot in slots:
            x = self.xpos(self.current) + xoff
            yield slot, x, self.yoff
            self.current += 1
            if self.current >= self.columns:
                self.advance_row()


InfoCB = TypeAliasType("InfoCB", Callable[[ItemT], DragInfo], type_params=(ItemT, ))
FlexiCB = TypeAliasType("FlexiCB", Callable[[float, float], Optional[str]])


class DragWin(Enum):
    """Constant used instead of a Slot to represent the drag/drop window."""
    DRAG = "drag"


SLOT_DRAG: Final = DragWin.DRAG


# noinspection PyProtectedMember
class ManagerBase(Generic[ItemT, ParentT]):
    """Manages a set of drag-drop points."""
    width: Final[int]
    height: Final[int]
    config_icon: Final[bool]
    _info_cb: InfoCB[ItemT]
    _pick_flexi_group: FlexiCB | None

    _slots: list[Slot[ItemT]]
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

        self._slots = []
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
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a slot to this group, which can have items added/removed.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot: Slot[ItemT] = Slot(self, SlotType.TARGET)
        self._ui_slot_create(slot, parent, label)
        self._slots.append(slot)
        return slot

    def slot_source(
        self,
        parent: ParentT,
        label: TransToken = TransToken.BLANK,
    ) -> Slot[ItemT]:
        """Add a readonly slot to this group which the user can fetch copies from.

        :param parent: Parent widget for the slot.
        :param label: Set to a short string to be displayed in the lower-left.
              Intended for numbers.
        """
        slot: Slot[ItemT] = Slot(self, SlotType.SOURCE)
        self._ui_slot_create(slot, parent, label)
        self._slots.append(slot)
        return slot

    def slot_flexi(
        self,
        parent: ParentT,
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
        slot: Slot[ItemT] = Slot(self, SlotType.FLEXI)
        self._ui_slot_create(slot, parent, label)
        self._slots.append(slot)
        return slot

    def load_icons(self) -> None:
        """Load in all the item icons."""
        # Sources are never grouped, both of the other types are.

        # Count the number of items in each group to find
        # which should have group icons.
        groups: dict[str | None, int] = defaultdict(int)
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
    def _ui_slot_set_highlight(self, slot: Slot[ItemT], highlight: bool) -> None:
        """Apply the highlighted state."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_slot_in_bbox(self, slot: Slot[ItemT], x: float, y: float) -> bool:
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

    def _pos_slot(self, x: float, y: float) -> Slot[ItemT] | None:
        """Find the slot under this X,Y (if any). Sources are ignored."""
        for slot in self._slots:
            if not slot.is_source and self._ui_slot_in_bbox(slot, x, y):
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

    def _group_update(self, group: str | None) -> None:
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
            group = self._info_cb(self._cur_drag).group
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

        self._ui_dragwin_hide()
        dest = self._pos_slot(x, y)

        if dest is self._cur_slot:
            # Dropped on itself, just put the item back.
            dest.contents = self._cur_drag
            self._cur_drag = self._cur_slot = None
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
            for free in slot.man._slots:
                if not free.is_target:
                    continue
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
class Slot(Generic[ItemT]):
    """Represents a single slot."""

    # Optional ability to highlight a specific slot.
    _is_highlighted: bool

    flexi_group: str  # If a flexi slot, the group.

    # The current thing in the slot.
    _contents: ItemT | None

    # The kind of slot.
    type: SlotType
    man: ManagerBase[ItemT, Any]  # Our drag/drop controller.

    def __init__(self, man: ManagerBase[ItemT, Any], kind: SlotType) -> None:
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
            for slot in self.man._slots:
                if slot.is_target and slot.contents is value:
                    slot.contents = None
        # Then set us.
        self._contents = value

        if self.is_target:
            # Update items in the previous group, so they gain the group icon
            # if only one now exists.
            if old_cont is not None:
                self.man._group_update(self.man._info_cb(old_cont).group)
            if value is not None:
                new_group = self.man._info_cb(value).group
            else:
                new_group = None
        else:
            # Source pickers never group items.
            new_group = None

        if self.is_flexi and (old_cont is None) != (value is None):
            # We're showing/hiding, we need to redraw.
            self.man.on_flexi_flow.set()

        if new_group is not None:
            # Update myself and the entire group to get the group
            # icon if required.
            self.man._group_update(new_group)
        else:
            # Just update myself.
            self.man._display_item(self, value)

    @property
    def contents_group(self) -> str | None:
        """If the item in this slot has a group, return it."""
        if self._contents is not None:
            return self.man._info_cb(self._contents).group
        return None

    def __repr__(self) -> str:
        return f'<{self.kind.name} Slot @ {id(self):016x}: {self._contents!r}>'
