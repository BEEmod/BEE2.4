"""Manage applying translation tokens to TK widgets."""
from __future__ import annotations

from tkinter import ttk
import tkinter as tk
from typing import TypeVar, Union
from weakref import WeakKeyDictionary

from typing_extensions import TypeAlias

from transtoken import TransToken as TransToken  # Re-export
from app.localisation import add_callback as add_callback  # Re-export.


__all__ = [
    'add_callback', 'TransToken',  # Re-exports
    'set_text', 'set_win_title', 'set_menu_text', 'clear_stored_menu',
]


# Widgets that have a 'text' property.
TextWidget: TypeAlias = Union[
    tk.Label, tk.LabelFrame, tk.Button, tk.Radiobutton, tk.Checkbutton,
    ttk.Label, ttk.LabelFrame, ttk.Button, ttk.Radiobutton, ttk.Checkbutton,
]
TextWidgetT = TypeVar('TextWidgetT', bound=TextWidget)
# Assigns to widget['text'].
_applied_text_tokens: WeakKeyDictionary[TextWidget, TransToken] = WeakKeyDictionary()
# menu -> index -> token.
_applied_menu_tokens: WeakKeyDictionary[tk.Menu, dict[int, TransToken]] = WeakKeyDictionary()
_window_titles: WeakKeyDictionary[tk.Wm, TransToken] = WeakKeyDictionary()


def set_text(widget: TextWidgetT, token: TransToken) -> TextWidgetT:
    """Apply a token to the specified label/button/etc."""
    widget['text'] = str(token)
    _applied_text_tokens[widget] = token
    return widget


def set_win_title(win: tk.Wm, token: TransToken) -> None:
    """Set the title of a window to this token."""
    win.wm_title(str(token))
    _window_titles[win] = token


def set_menu_text(menu: tk.Menu, token: TransToken, index: str | int = 'end') -> None:
    """Apply this text to the item on the specified menu.

    By default, it is applied to the last item.
    """
    try:
        tok_map = _applied_menu_tokens[menu]
    except KeyError:
        tok_map = _applied_menu_tokens[menu] = {}
    ind = menu.index(index)
    if ind is None:
        raise ValueError(f'Invalid index "{index}" for menu "{menu}"!')
    menu.entryconfigure(ind, label=str(token))
    tok_map[ind] = token


def clear_stored_menu(menu: tk.Menu) -> None:
    """Clear the tokens for the specified menu."""
    _applied_menu_tokens.pop(menu, None)


@add_callback(call=False)
def _apply_changes() -> None:
    """Apply new languages to all stored widgets."""
    for text_widget, token in _applied_text_tokens.items():
        text_widget['text'] = str(token)
    for menu, menu_map in _applied_menu_tokens.items():
        for index, token in menu_map.items():
            menu.entryconfigure(index, label=str(token))
    for window, token in _window_titles.items():
        window.wm_title(str(token))


def stats() -> str:
    """Output debingging statistics."""
    return (
        f'TransTokens:\n'
        f'- label["text"]: {len(_applied_text_tokens)}\n'
        f'- Menus: {len(_applied_menu_tokens)}\n'
        f'- Windows: {len(_window_titles)}\n'
    )
