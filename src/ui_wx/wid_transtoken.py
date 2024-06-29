"""Manage applying translation tokens to Wx widgets."""
from __future__ import annotations

from contextlib import aclosing
from weakref import WeakKeyDictionary

import trio.lowlevel
import wx

from app.localisation import gradual_iter
from transtoken import TransToken, CURRENT_LANG


__all__ = [
    'TransToken', 'CURRENT_LANG',  # Re-exports
    'set_text', 'set_win_title', 'set_menu_text',
]


# Widgets that have a SetText method.
type TextWidget = (
    wx.Control
)
_control_labels: WeakKeyDictionary[TextWidget, TransToken] = WeakKeyDictionary()
_menu_labels: WeakKeyDictionary[wx.MenuItem, TransToken] = WeakKeyDictionary()
_window_titles: WeakKeyDictionary[wx.TopLevelWindow, TransToken] = WeakKeyDictionary()


def set_text[Widget: TextWidget](widget: Widget, token: TransToken) -> Widget:
    """Apply a token to the specified control."""
    # TODO: Should we use SetLabel here to allow mnemonics?
    widget.SetLabel(str(token))
    if token.is_untranslated:  # No need to have a callback for this one.
        _control_labels.pop(widget, None)
    else:
        _control_labels[widget] = token
    return widget


def set_win_title(win: wx.TopLevelWindow, token: TransToken) -> None:
    """Set the title of a window to this token."""
    win.SetTitle(str(token))
    _window_titles[win] = token


def set_menu_text(menu: wx.MenuItem, token: TransToken) -> None:
    """Apply this text to an item on a menu."""
    menu.SetItemLabel(str(token))
    _menu_labels[menu] = token


async def update_task() -> None:
    """Apply new languages to all stored widgets."""
    # Using gradual_iter() yields to the event loop in-between each conversion.
    while True:
        await CURRENT_LANG.wait_transition()
        async with aclosing(gradual_iter(_control_labels)) as agen1:
            async for control, token in agen1:
                control.SetTextLabel(str(token))

        await trio.lowlevel.checkpoint()

        async with aclosing(gradual_iter(_menu_labels)) as agen2:
            async for menu, token in agen2:
                menu.SetItemLabel(str(token))

        await trio.lowlevel.checkpoint()

        for window, token in _window_titles.items():
            window.SetTitle(str(token))


def stats() -> str:
    """Output debingging statistics."""
    return (
        f'TransTokens:\n'
        f'- Controls: {len(_control_labels)}\n'
        f'- Menus: {len(_menu_labels)}\n'
        f'- Windows: {len(_window_titles)}\n'
    )
