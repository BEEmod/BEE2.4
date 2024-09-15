"""Implements the selected palette and list of items."""
from abc import ABC, abstractmethod
from contextlib import aclosing
from typing import Final

import attrs
import trio

import config
import utils
from app.dragdrop import DragInfo
from config.item_defaults import ItemDefault
from transtoken import TransToken
from trio_util import AsyncValue

from app import LOGGER, ReflowWindow, WidgetCache, dragdrop, img
from app.paletteLoader import Coord, COORDS, HorizInd, VERT, VertInd
from packages import PackagesSet, PakRef, Style, CLEAN_STYLE
from packages.item import Item, SubItemRef


type ItemSlot = dragdrop.Slot[SubItemRef]
IMG_MENU = img.Handle.builtin('BEE2/menu', 271, 573)
INFO_ERROR: Final[DragInfo] = DragInfo(img.Handle.error(64, 64))


class ItemPickerBase[ParentT](ReflowWindow, ABC):
    """The picker window."""
    # Style ID, referenced from the style window.
    selected_style: AsyncValue[utils.SpecialID]
    # The current filtering state.
    cur_filter: set[SubItemRef] | None = None
    packset: PackagesSet

    # Items on the palette.
    slots_pal: dict[Coord, ItemSlot]
    # Slots used for the full items list.
    slots_picker: WidgetCache[ItemSlot]

    @property
    @abstractmethod
    def drag_man(self) -> dragdrop.ManagerBase[SubItemRef, ParentT]:
        """Subclasses must create an appropriate drag manager.

        We can't require this to be passed into __init__(), since that ends up requiring HKT.
        """
        ...

    def __init__(self, selected_style: AsyncValue[utils.SpecialID]) -> None:
        super().__init__()
        self.cur_filter = None
        self.selected_style = selected_style
        self.packset = PackagesSet()
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
            nursery.start_soon(self._style_changed_task)

    def change_version(self, item_ref: PakRef[Item], version: str) -> None:
        """Set the version of an item."""
        old_conf = config.APP.get_cur_conf(ItemDefault, item_ref.id)
        config.APP.store_conf(attrs.evolve(old_conf, version=version), item_ref.id)
        self.items_dirty.set()
        self.drag_man.load_icons()

    def drag_info(self, ref: SubItemRef) -> DragInfo:
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

    async def _style_changed_task(self) -> None:
        """Update whenever the style changes."""
        while True:
            await self.selected_style.wait_transition()
            self.items_dirty.set()
            await trio.lowlevel.checkpoint()

    async def _packset_changed_task(self) -> None:
        """Update whenever packages reload."""
        async with aclosing(self.selected_style.eventual_values()) as agen:
            async for style_id in agen:
                self.items_dirty.set()
                await trio.lowlevel.checkpoint()

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
