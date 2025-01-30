"""Implements the selected palette and list of items."""
from typing import Final

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from contextlib import aclosing
import random

from trio_util import AsyncValue
import attrs
import trio

from app import LOGGER, ReflowWindow, WidgetCache, dragdrop, img
from app.dragdrop import DragInfo
from app.paletteLoader import Coord, ItemPos
from async_util import iterval_cancelling
from config.filters import FilterConf
from config.item_defaults import ItemDefault
from packages import LOADED as PAK_LOADED, PackagesSet, PakRef, Style
from packages.item import Item, SubItemRef
from packages.widgets import mandatory_unlocked
from transtoken import TransToken
import config


type ItemSlot = dragdrop.Slot[SubItemRef]
IMG_MENU = img.Handle.builtin('BEE2/menu', 271, 573)
INFO_ERROR: Final[DragInfo] = DragInfo(img.Handle.error(64, 64))

TRANS_ITEMS_TITLE = TransToken.ui("All Items: ")
TRANS_ERROR = TransToken.untranslated('???')
TRANS_UNKNOWN_ID = TransToken.ui('Unknown: <{id}>')


class ItemPickerBase[ParentT](ReflowWindow, ABC):
    """The picker window."""
    # Style ID, referenced from the style window.
    selected_style: AsyncValue[PakRef[Style]]
    # The current filtering state.
    cur_filter: AsyncValue[set[SubItemRef] | None]
    filter_conf: FilterConf
    packset: PackagesSet

    # Items on the palette. Dict is backwards because
    # we only need to do pos -> slot when iterating all of them.
    slots_pal: dict[ItemSlot, Coord]
    # Slots used for the full items list.
    slots_picker: WidgetCache[ItemSlot]

    # Fired whenever the number/position of items need to change.
    items_dirty: trio.Event

    # The current list of items.
    _all_items: list[Item]

    @property
    @abstractmethod
    def drag_man(self) -> dragdrop.ManagerBase[SubItemRef, ParentT]:
        """Subclasses must create an appropriate drag manager.

        We can't require this to be passed into __init__(), since that ends up requiring HKT.
        """
        ...

    def __init__(self, selected_style: AsyncValue[PakRef[Style]]) -> None:
        super().__init__()
        self.cur_filter = AsyncValue(None)
        self.selected_style = selected_style
        self.packset = PackagesSet.blank()
        self.filter_conf = FilterConf()
        self.slots_pal = {}
        self._all_items = []
        self.items_dirty = trio.Event()
        self.slots_picker = WidgetCache(self._ui_picker_create, self._ui_picker_hide)

    def cur_style(self) -> PakRef[Style]:
        """Fetch the current style."""
        return self.selected_style.value

    async def task(self) -> None:
        """Operate the picker."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._packset_changed_task)
            nursery.start_soon(self._style_changed_task)
            nursery.start_soon(self._filter_conf_changed_task)
            nursery.start_soon(self._filter_search_changed_task)
            nursery.start_soon(self._reload_items_task)
            nursery.start_soon(self.reposition_items_task)
            nursery.start_soon(self._update_name_task)

    def change_version(self, item_ref: PakRef[Item], version: str) -> None:
        """Set the version of an item."""
        old_conf = config.APP.get_cur_conf(ItemDefault, item_ref.id)
        config.APP.store_conf(attrs.evolve(old_conf, version=version), item_ref.id)
        self.item_pos_dirty.set()
        self.drag_man.load_icons()

    def change_pal_subtype(self, slot: ItemSlot, ref: SubItemRef) -> bool:
        """Change the subtype of a slot, then reopen the context window.

        This removes duplicates from the palette if needed.
        """
        if slot.contents is None:
            LOGGER.warning('No item for {!r}', slot)
            return False
        if slot.contents.item != ref.item:
            LOGGER.warning('Slot {!r} does not have a "{}"', slot, ref)
            return False
        slot.contents = ref

        for other_slot in self.slots_pal:
            if other_slot is slot:
                continue
            match other_slot.contents:
                case SubItemRef(item=ref.item):
                    other_slot.contents = None
        return True

    def find_matching_slot(
        self, ref: SubItemRef, check_palette: bool,
    ) -> tuple[ItemSlot | None, Coord | None]:
        """Find a slot which contains the specified subitem.

        Optionally, check the palette first.
        """
        pass

        if check_palette:
            for slot, coord in self.slots_pal.items():
                if slot.contents == ref:
                    return slot, coord

        # Fall back to the picker.
        for slot in self.slots_picker.placed:
            if slot.contents == ref:
                return slot, None
        return None, None

    def get_items(self) -> ItemPos:
        """Return the currently selected items."""
        return {
            pos: (ref.item.id, ref.subtype)
            for slot, pos in self.slots_pal.items()
            if (ref := slot.contents) is not None
        }

    def set_items(self, palette: Mapping[Coord, tuple[str, int]]) -> None:
        """Change the selected items."""
        for slot, coord in self.slots_pal.items():
            try:
                item_id, subtype = palette[coord]
            except KeyError:
                slot.contents = None
            else:
                slot.contents = SubItemRef(PakRef.parse(Item, item_id), subtype)

    def clear_palette(self) -> None:
        """Clear the palette."""
        for slot in self.slots_pal:
            slot.contents = None

    def fill_palette(self) -> None:
        """Fill the palette with random items."""
        include_mandatory = mandatory_unlocked()

        empty_slots = [
            slot for slot in self.slots_pal
            if slot.contents is None
        ]
        if not empty_slots:
            return

        existing_items = {
            subitem.item
            for slot in self.slots_pal
            if (subitem := slot.contents) is not None
        }

        # Use a set to eliminate duplicates.
        # We don't actually have to handle filters, just look at the current item list.
        shuff_items: list[PakRef[Item]] = list({
            subitem.item
            for slot in self.slots_picker.placed
            if (subitem := slot.contents) is not None
            if subitem.item not in existing_items
        })

        random.shuffle(shuff_items)

        for slot, item_ref in zip(empty_slots, shuff_items, strict=False):
            item = item_ref.resolve(self.packset)
            if item is not None:
                # Pick a random available palette icon.
                slot.contents = SubItemRef(item_ref, random.choice(item.visual_subtypes))

    async def open_contextwin_task(
        self, open_func: Callable[[ItemSlot, Coord | None], None],
    ) -> None:
        """Monitors rightclicks, then triggers the window.

        This is started by the context window, not us.
        """
        while True:
            slot = await self.drag_man.on_config.wait()
            if slot.contents is not None:
                open_func(slot, self.slots_pal.get(slot))

    def _drag_info(self, ref: SubItemRef) -> DragInfo:
        """Compute the info for an item."""
        item = ref.item.resolve(self.packset)
        if item is None:
            return INFO_ERROR
        style = self.selected_style.value
        icon = item.get_icon(style, ref.subtype)
        all_icon = item.get_all_icon(style)
        if all_icon is not None:
            return DragInfo(icon, ref.item.id, all_icon)
        else:
            return DragInfo(icon)

    async def _reload_items_task(self) -> None:
        """Update all the items."""
        while True:
            await self.items_dirty.wait()
            self.items_dirty = trio.Event()

            hide_mandatory = not mandatory_unlocked()
            cur_filter = self.cur_filter.value
            compress = self.filter_conf.compress

            self.slots_picker.reset()
            for item in self._all_items:
                await trio.lowlevel.checkpoint()
                if hide_mandatory and item.needs_unlock:
                    continue

                ref = item.reference()
                visible = []
                for subkey in item.visual_subtypes:
                    sub_ref = SubItemRef(ref, subkey)
                    if cur_filter is None or sub_ref in cur_filter:
                        visible.append(sub_ref)

                if compress:
                    visible = visible[:1]
                for ref in visible:
                    await trio.lowlevel.checkpoint()
                    self.slots_picker.fetch().contents = ref
            self.slots_picker.hide_unused()
            self.item_pos_dirty.set()

    async def _style_changed_task(self) -> None:
        """Update whenever the style changes."""
        while True:
            await self.selected_style.wait_transition()
            self.drag_man.load_icons()
            await trio.lowlevel.checkpoint()

    async def _packset_changed_task(self) -> None:
        """Update whenever packages reload."""
        packset: PackagesSet
        async with iterval_cancelling(PAK_LOADED) as aiterator:
            async for scope in aiterator:
                with scope as packset:
                    await packset.ready(Item).wait()
                    # Create the items in the palette.
                    # Sort by item ID, and then group by package ID.
                    # Reverse sort packages so 'Valve' appears at the top...
                    items = sorted(packset.all_obj(Item), key=lambda item: item.id)
                    items.sort(key=lambda item: item.pak_id, reverse=True)
                    self._all_items = items
                    self.packset = packset
                    self.items_dirty.set()

    async def _filter_search_changed_task(self) -> None:
        """Update whenever the filter configuration changes."""
        while True:
            await self.cur_filter.wait_transition()
            self.items_dirty.set()

    async def _filter_conf_changed_task(self) -> None:
        """Update whenever the filter configuration changes."""
        with config.APP.get_ui_channel(FilterConf) as channel:
            async for self.filter_cont in channel:
                self.items_dirty.set()

    async def _update_name_task(self) -> None:
        """Update the name of the selected item."""
        hovered: SubItemRef | None
        async with aclosing(self.drag_man.hovered_item.eventual_values()) as agen:
            async for hovered in agen:
                if hovered is None:
                    self._ui_set_sel_name(TransToken.BLANK)
                    continue
                item = hovered.item.resolve(self.packset)
                if item is None:
                    self._ui_set_sel_name(TRANS_UNKNOWN_ID.format(id=hovered))
                    continue
                style = self.selected_style.value
                variant = item.selected_version().get(style)
                try:
                    name = variant.editor.subtypes[hovered.subtype].name
                except IndexError:
                    LOGGER.warning(
                        'Item {} in <{}> style has mismatched subtype count!',
                        hovered, style,
                    )
                    self._ui_set_sel_name(TRANS_UNKNOWN_ID.format(id=hovered))
                else:
                    self._ui_set_sel_name(name)

    @abstractmethod
    def _ui_picker_create(self, index: int) -> ItemSlot:
        """Create a source slot, likely by calling dragdrop.slot_source."""
        raise NotImplementedError

    @abstractmethod
    def _ui_picker_hide(self, slot: ItemSlot) -> None:
        """Hide the specified slot widget."""
        raise NotImplementedError

    @abstractmethod
    def _ui_set_sel_name(self, name: TransToken) -> None:
        """Set the name for the currently selected item."""
        raise NotImplementedError
