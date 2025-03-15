"""Wx-specific help menu implementation."""
from collections.abc import Callable
from typing import override

from contextlib import aclosing

import trio
import wx.html

from app.helpMenu import (
    TRANS_CREDITS_BUTTON, TRANS_CREDITS_TITLE,
    ICONS, WEB_RESOURCES, SEPERATOR,
    CreditsWindowBase, open_url,
)
from app.mdown import MarkdownData

from . import MAIN_WINDOW, MARKDOWN
from .img import WX_IMG
from .dialogs import DIALOG
from .wid_transtoken import set_menu_text, set_win_title


class CreditsWindow(CreditsWindowBase):
    """Wx-specific credits window.

    Based on `wx.lib.dialogs.ScrolledMessageDialog`, but HTML.
    """

    def __init__(self) -> None:
        super().__init__()
        close = self._close

        self.win = wx.Dialog(MAIN_WINDOW, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.win.Bind(wx.EVT_CLOSE, lambda e: close())
        set_win_title(self.win, TRANS_CREDITS_TITLE)

        self.text = wx.html.HtmlWindow(self.win)

        ok = wx.Button(self.win, wx.ID_CLOSE, '')
        ok.SetDefault()
        ok.Bind(wx.EVT_BUTTON, lambda e: close())

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.text, wx.SizerFlags(1).Border().Expand())
        sizer.Add(ok, wx.SizerFlags().Border().Center())
        self.win.SetSizer(sizer)
        self.win.Layout()

    @override
    async def _ui_apply_text(self, text: MarkdownData) -> None:
        self.text.SetPage(MARKDOWN.convert(text))

    @override
    async def _ui_show_window(self) -> None:
        self.win.Show()
        self.win.CenterOnScreen(wx.BOTH)

    @override
    async def _ui_hide_window(self) -> None:
        self.win.Hide()


async def create(
    menu: wx.Menu,
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create and operate the application 'Help' menu."""
    credit_window = CreditsWindow()

    def command(url: str) -> Callable[[wx.CommandEvent], None]:
        """Implement the command for a resource."""
        def func(event: wx.CommandEvent) -> None:
            """Open the URL when clicked."""
            nursery.start_soon(open_url, DIALOG, res.url_key)

        return func

    # The menu items need to be kept alive.
    items = []

    async with trio.open_nursery() as nursery:
        for res in WEB_RESOURCES:
            if res is SEPERATOR:
                menu.AppendSeparator()
            else:
                menu_item = menu.Append(wx.ID_ANY, str(res), '')
                items.append(menu_item)
                menu.Bind(wx.EVT_MENU, command(res.url_key), menu_item)
                set_menu_text(menu_item, res.name)
                WX_IMG.menu_set_icon(menu_item, ICONS[res.icon])

        menu.AppendSeparator()

        credits_item = menu.Append(wx.ID_ANY, 'CreditsOption', '')
        open_credits = credit_window.open.trigger
        menu.Bind(wx.EVT_MENU, lambda e: open_credits(), credits_item)
        set_menu_text(credits_item, TRANS_CREDITS_BUTTON)

        nursery.start_soon(credit_window.display_task)
        async with aclosing(credit_window.open.ready.eventual_values()) as agen:
            task_status.started()
            async for enabled in agen:
                credits_item.Enable(enabled)
