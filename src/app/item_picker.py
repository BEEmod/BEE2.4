"""Implements the selected palette and list of items."""
from typing import Final

from abc import ABC, abstractmethod

import attrs
import trio

from app import LOGGER, ReflowWindow, WidgetCache, dragdrop, img
from app.dragdrop import DragInfo
from app.paletteLoader import Coord, ItemPos, Palette
from async_util import iterval_cancelling
from config.filters import FilterConf
from config.item_defaults import ItemDefault
from packages import (
    CLEAN_STYLE, LOADED as PAK_LOADED, PackagesSet, PakRef, Style,
)
from packages.item import Item, SubItemRef
from packages.widgets import mandatory_unlocked
from transtoken import TransToken
from trio_util import AsyncValue
import config
import utils


type ItemSlot = dragdrop.Slot[SubItemRef]
IMG_MENU = img.Handle.builtin('BEE2/menu', 271, 573)
INFO_ERROR: Final[DragInfo] = DragInfo(img.Handle.error(64, 64))

TRANS_ITEMS_TITLE = TransToken.ui("All Items: ")


class ItemPickerBase[ParentT](ReflowWindow, ABC):
    """The picker window."""
    # Style ID, referenced from the style window.
    selected_style: AsyncValue[utils.SpecialID]
    # The current filtering state.
    cur_filter: AsyncValue[set[SubItemRef] | None]
    filter_conf: FilterConf
    packset: PackagesSet

    # Items on the palette.
    slots_pal: dict[Coord, ItemSlot]
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

    def __init__(self, selected_style: AsyncValue[utils.SpecialID]) -> None:
        super().__init__()
        self.cur_filter = AsyncValue(None)
        self.selected_style = selected_style
        self.packset = PackagesSet()
        self.filter_conf = FilterConf()
        self.slots_pal = {}
        self._all_items = []
        self.items_dirty = trio.Event()
        self.slots_picker = WidgetCache(self.ui_picker_create, self.ui_picker_hide)

    def _cur_style(self) -> PakRef[Style]:
        """Fetch the current style."""
        style = self.selected_style.value
        if utils.not_special_id(style):
            return PakRef(Style, style)
        else:
            LOGGER.warning('Invalid style {}!', style)
            return CLEAN_STYLE

    async def task(self) -> None:
        """Operate the picker."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._ui_task)
            nursery.start_soon(self._packset_changed_task)
            nursery.start_soon(self._style_changed_task)
            nursery.start_soon(self._filter_conf_changed_task)
            nursery.start_soon(self._filter_search_changed_task)
            nursery.start_soon(self.reload_items_task)
            nursery.start_soon(self.reposition_items_task)

    def change_version(self, item_ref: PakRef[Item], version: str) -> None:
        """Set the version of an item."""
        old_conf = config.APP.get_cur_conf(ItemDefault, item_ref.id)
        config.APP.store_conf(attrs.evolve(old_conf, version=version), item_ref.id)
        self.item_pos_dirty.set()
        self.drag_man.load_icons()

    def get_items(self) -> ItemPos:
        """Return the currently selected items."""
        return {
            pos: (ref.item.id, ref.subtype)
            for pos, slot in self.slots_pal.items()
            if (ref := slot.contents) is not None
        }

    async def set_items(self, new_items: Palette) -> None:
        """Change the selected items."""
        pass

    def _drag_info(self, ref: SubItemRef) -> DragInfo:
        """Compute the info for an item."""
        try:
            item = ref.item.resolve(self.packset)
        except KeyError:
            LOGGER.warning('Unknown item "{}"!', ref)
            return INFO_ERROR
        style = self._cur_style()
        icon = item.get_icon(style, ref.subtype)
        all_icon = item.get_all_icon(style)
        if all_icon is not None:
            return DragInfo(icon, ref.item.id, all_icon)
        else:
            return DragInfo(icon)

    async def reload_items_task(self) -> None:
        """Update all the items."""
        while True:
            await self.items_dirty.wait()
            self.items_dirty = trio.Event()
            LOGGER.info('Reloading items list.')

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

    @abstractmethod
    async def _ui_task(self) -> None:
        """Update the UI."""

    @abstractmethod
    def ui_picker_create(self, index: int) -> ItemSlot:
        """Create a source slot, likely by calling dragdrop.slot_source."""
        raise NotImplementedError

    @abstractmethod
    def ui_picker_hide(self, slot: ItemSlot) -> None:
        """Hide the specified slot widget."""
        raise NotImplementedError
