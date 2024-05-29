"""Implement the item searchbar for filtering items by various keywords.
"""
from tkinter import ttk
import tkinter as tk
from collections.abc import Callable

import srctools.logger
from pygtrie import CharTrie

from app import UI, localisation
from ui_tk.wid_transtoken import set_text


LOGGER = srctools.logger.get_logger(__name__)
# A set of id/subtype pairs.
type FoundItems = set[tuple[str, int]]
word_to_ids: 'CharTrie[FoundItems]' = CharTrie()
_type_cback: Callable[[], None] | None = None


def init(frm: ttk.Frame, refresh_cback: Callable[[set[tuple[str, int]] | None], None]) -> None:
    """Initialise the UI objects.

    The callback is triggered whenever the UI changes, passing along
    the visible items or None if no filter is specified.
    """
    global _type_cback
    refresh_tim: str | None = None
    result: FoundItems | None = None

    def on_type(*args: object) -> None:
        """Re-search whenever text is typed."""
        nonlocal refresh_tim, result
        text = search_var.get().casefold()
        words = text.split()
        if not words:
            refresh_cback(None)
            return

        found: FoundItems = set()
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
        refresh_cback(result)
        result = None

    frm.columnconfigure(1, weight=1)

    set_text(ttk.Label(frm), localisation.TransToken.ui('Search:')).grid(row=0, column=0)

    search_var = tk.StringVar()
    search_var.trace_add('write', on_type)

    searchbar = ttk.Entry(frm, textvariable=search_var)
    searchbar.grid(row=0, column=1, sticky='EW')

    _type_cback = on_type


def rebuild_database() -> None:
    """Rebuild the search database."""
    LOGGER.info('Updating search database...')
    # Clear and reset.
    word_set: FoundItems
    word_to_ids.clear()

    for item in UI.item_list.values():
        for subtype_ind in item.item.visual_subtypes:
            for tag in item.get_tags(subtype_ind):
                for word in tag.split():
                    word_set = word_to_ids.setdefault(word.casefold(), set())
                    word_set.add((item.item.id, subtype_ind))

    LOGGER.info('Computed {} tags.', sum(1 for _ in word_to_ids.iterkeys()))
    if _type_cback is not None:
        _type_cback()
