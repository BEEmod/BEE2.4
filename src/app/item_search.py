from tkinter import ttk
import tkinter as tk

from collections import defaultdict

from app import UI

from lexpy.trie import Trie
from typing import Dict, Optional, Set, Callable
import srctools.logger


LOGGER = srctools.logger.get_logger(__name__)
database = Trie()
word_to_ids: Dict[str,  Set[str]] = defaultdict(set)
_type_cback: Optional[Callable[[], None]] = None


def init(frm: tk.Frame, refresh_cback: Callable[[Optional[Set[str]]], None]) -> None:
    """Initialise the UI objects.

    The callback is triggered whenever the UI changes, passing along
    the visible items.
    """
    global _type_cback

    def on_type(*args):
        """Re-search whenever text is typed."""
        text = search_var.get()
        words = text.split()
        if not words:
            refresh_cback(None)
            return

        found = set()
        for word in words:
            for name in database.search_with_prefix(word):
                found |= word_to_ids[name]
        # Calling the callback deselects us, so save and restore.
        selected = searchbar.selection_present()
        if selected:
            start = searchbar.index('sel.first')
            end = searchbar.index('sel.last')
        else:
            start = end = 0

        refresh_cback(found)

        if selected:
            searchbar.selection_range(start, end)

    frm.columnconfigure(1, weight=1)

    ttk.Label(
        frm,
        text=_('Search:'),
    ).grid(row=0, column=0)

    search_var = tk.StringVar()
    search_var.trace_add('write', on_type)

    searchbar = tk.Entry(frm, textvariable=search_var)
    searchbar.grid(row=0, column=1, sticky='EW')

    _type_cback = on_type


def rebuild_database() -> None:
    """Rebuild the search database."""
    LOGGER.info('Updating search database...')
    # Clear and reset.
    database.__init__()
    word_to_ids.clear()

    for item in UI.item_list.values():
        for word in item.get_tags():
            word = word.casefold()
            database.add(word)
            word_to_ids[word].add(item.id)
    _type_cback()
