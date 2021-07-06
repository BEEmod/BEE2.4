"""Implement the item searchbar for filtering items by various keywords.
"""
from tkinter import ttk
import tkinter as tk
from typing import Optional, Set, Callable, Tuple

import srctools.logger
from pygtrie import CharTrie

from app import UI, TK_ROOT

LOGGER = srctools.logger.get_logger(__name__)
word_to_ids: 'CharTrie[Set[Tuple[str, int]]]' = CharTrie()
_type_cback: Optional[Callable[[], None]] = None


def init(frm: tk.Frame, refresh_cback: Callable[[Optional[Set[Tuple[str, int]]]], None]) -> None:
    """Initialise the UI objects.

    The callback is triggered whenever the UI changes, passing along
    the visible items or None if no filter is specified.
    """
    global _type_cback
    refresh_tim: Optional[str] = None
    result: Optional[set[tuple[str, int]]] = None

    def on_type(*args) -> None:
        """Re-search whenever text is typed."""
        nonlocal refresh_tim, result
        text = search_var.get().casefold()
        words = text.split()
        if not words:
            refresh_cback(None)
            return

        found: set[tuple[str, int]] = set()
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
            TK_ROOT.after_cancel(refresh_tim)
        refresh_tim = TK_ROOT.after(500, trigger_cback)

    def trigger_cback() -> None:
        """Trigger the callback, after the user paused the UI."""
        nonlocal refresh_tim, result
        refresh_tim = None
        refresh_cback(result)
        result = None

    frm.columnconfigure(1, weight=1)

    ttk.Label(
        frm,
        text=_('Search:'),
    ).grid(row=0, column=0)

    search_var = tk.StringVar()
    search_var.trace_add('write', on_type)

    searchbar = ttk.Entry(frm, textvariable=search_var)
    searchbar.grid(row=0, column=1, sticky='EW')

    _type_cback = on_type


def rebuild_database() -> None:
    """Rebuild the search database."""
    LOGGER.info('Updating search database...')
    # Clear and reset.
    word_set: set[tuple[str, int]]
    word_to_ids.clear()

    for item in UI.item_list.values():
        for subtype_ind in item.visual_subtypes:
            for tag in item.get_tags(subtype_ind):
                for word in tag.split():
                    word_set = word_to_ids.setdefault(word.casefold(), set())
                    word_set.add((item.id, subtype_ind))

    LOGGER.info('Computed {} tags.', sum(1 for _ in word_to_ids.iterkeys()))
    _type_cback()
