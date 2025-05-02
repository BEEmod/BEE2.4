"""Implement the item searchbar for filtering items by various keywords.
"""
from tkinter import ttk
import tkinter as tk
from collections.abc import Callable
from contextlib import aclosing

from pygtrie import CharTrie
import srctools.logger
import trio_util
import trio

from app import localisation
from async_util import iterval_cancelling
from packages import PackagesSet, PakRef, Style
from packages.item import Item, SubItemRef
from ui_tk.wid_transtoken import set_text
import packages


LOGGER = srctools.logger.get_logger(__name__)
type Filter = set[SubItemRef]
type FilterTrie = CharTrie[Filter]
word_to_ids: FilterTrie = CharTrie()
_type_cback: Callable[[], None] | None = None
searchbar_wid: ttk.Entry


def init(frm: ttk.Frame, refresh_val: trio_util.AsyncValue[Filter | None]) -> None:
    """Initialise the UI objects.

    The callback is triggered whenever the UI changes, passing along
    the visible items or None if no filter is specified.
    """
    global _type_cback, searchbar_wid
    refresh_tim: str | None = None
    result: Filter | None = None

    def on_type(*args: object) -> None:
        """Re-search whenever text is typed."""
        nonlocal refresh_tim, result
        text = search_var.get().casefold()
        words = text.split()
        if not words:
            refresh_val.value = None
            return

        found: Filter = set()
        *words, last = words
        for word in words:
            try:
                found |= word_to_ids[word]
            except KeyError:
                pass
        if last:
            try:
                for group in word_to_ids.itervalues(last):
                    found |= group
            except KeyError:
                pass

        # The callback causes us to be deselected, so delay it until the user
        # stops typing.
        result = found
        if refresh_tim is not None:
            frm.after_cancel(refresh_tim)
        refresh_tim = frm.after(500, trigger_cback)

    def trigger_cback() -> None:
        """Trigger the callback, after the user paused the UI."""
        nonlocal refresh_tim, result
        refresh_tim = None
        refresh_val.value = result
        result = None

    frm.columnconfigure(1, weight=1)

    set_text(ttk.Label(frm), localisation.TransToken.ui('Search:')).grid(row=0, column=0)

    search_var = tk.StringVar()
    search_var.trace_add('write', on_type)

    searchbar = ttk.Entry(frm, textvariable=search_var)
    searchbar.grid(row=0, column=1, sticky='EW')
    searchbar_wid = searchbar

    _type_cback = on_type


async def update_task(cur_style: trio_util.AsyncValue[PakRef[Style]]) -> None:
    """Whenever styles or packages change, reload."""
    scope = trio.CancelScope()
    style = cur_style.value
    packset = packages.PackagesSet.blank()

    async def wait_packset() -> None:
        """Reload if the package changes, making sure items are ready first."""
        nonlocal packset
        while True:
            async with iterval_cancelling(packages.LOADED) as new_packset:
                await new_packset.ready(Item).wait()
                packset = new_packset
                scope.cancel()

    async def wait_style() -> None:
        """Reload if the style changes."""
        nonlocal style
        async with aclosing(cur_style.eventual_values()) as agen:
            async for style in agen:
                scope.cancel()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_packset)
        nursery.start_soon(wait_style)
        while True:
            searchbar_wid.state(('disabled', ))
            with trio.CancelScope() as scope:
                await _rebuild_database(packset, style)
                searchbar_wid.state(('!disabled',))
                await trio.sleep_forever()
            LOGGER.info('End scope.')


def _build_words(packset: PackagesSet, style: PakRef[Style]) -> FilterTrie:
    """Build the full filters, for this package set and style."""
    word_to_ids: FilterTrie = CharTrie()
    word_set: Filter
    for item in packset.all_obj(Item):
        for subtype_ind in item.visual_subtypes:
            trio.from_thread.check_cancelled()
            for tag in item.get_tags(style, subtype_ind):
                for word in tag.split():
                    word_set = word_to_ids.setdefault(word.casefold(), set())
                    word_set.add(SubItemRef(item.reference(), subtype_ind))
    return word_to_ids


async def _rebuild_database(packset: PackagesSet, style: PakRef[Style]) -> None:
    """Rebuild the search database."""
    global word_to_ids
    LOGGER.info('Updating search database...')

    new_words = await trio.to_thread.run_sync(_build_words, packset, style)
    word_to_ids = new_words

    LOGGER.info('Computed {} tags.', sum(1 for _ in word_to_ids.iterkeys()))
    if _type_cback is not None:
        _type_cback()
