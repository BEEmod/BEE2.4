"""Wx implementation of the corridor selector."""
from __future__ import annotations
from typing import Final

import trio
from typing_extensions import override
from collections.abc import Sequence

import wx

from app import img
from app.corridor_selector import (
    HEIGHT, IMG_ARROW_LEFT, IMG_ARROW_RIGHT, IMG_CORR_BLANK, Icon,
    OptionRow, Selector, TRANS_HELP, TRANS_NO_OPTIONS, WIDTH, TRANS_RAND_OPTION,
)
from app.mdown import MarkdownData
from config.corridors import UIState
from corridor import Direction, GameMode, Option, Orient
from transtoken import TransToken
import config
import packages
import utils

from .img import ImageSlot, WXImages
from . import PEN_SLOT_BORDER, PEN_SLOT_BORDER_SEL

ICON_CHECK_PADDING: Final = 2 if utils.WIN else 0


class IconUI(Icon):
    """An icon for a corridor."""
    def __init__(self, selector: WxSelector, index: int) -> None:
        """Create the widgets."""
        self.widget = wx.Panel(selector.wid_corrlist)
        self.index = index
        self.selector = selector
        self.img = ImageSlot(self.widget)
        self._selected = self._hovered = self._highlight = self._readonly = False

        self.widget.SetMinSize((
            IMG_CORR_BLANK.width + 4,
            IMG_CORR_BLANK.height + 4,
        ))
        self.widget.Bind(wx.EVT_ENTER_WINDOW, self._evt_hover_enter)
        self.widget.Bind(wx.EVT_LEAVE_WINDOW, self._evt_hover_exit)
        self.widget.Bind(wx.EVT_LEFT_UP, lambda e: self.selector.evt_selected(self))
        self.widget.Bind(wx.EVT_PAINT, self._on_paint)

    def _on_paint(self, evt: wx.PaintEvent) -> None:
        """Draw the icon."""
        dc = wx.PaintDC(self.widget)
        native = wx.RendererNative.Get()
        wid_size = self.widget.GetSize()
        check_size = native.GetCheckBoxSize(self.widget)

        dc.SetPen(PEN_SLOT_BORDER_SEL if self._highlight else PEN_SLOT_BORDER)
        dc.DrawRectangle(wx.Rect(wid_size))
        self.img.draw(dc, 4, 4)

        native.DrawCheckBox(
            self.widget, dc,
            wx.Rect(
                ICON_CHECK_PADDING,
                wid_size.Height - check_size.Height - ICON_CHECK_PADDING,
                check_size.Width, check_size.Height,
            ),
            (self._selected * wx.CONTROL_CHECKED) | (self._hovered * wx.CONTROL_CURRENT),
        )

    def _evt_hover_enter(self, evt: wx.MouseEvent) -> None:
        """Handle hovering over the window."""
        self._hovered = True
        self.selector.evt_hover_enter(self)
        self.widget.Refresh()

    def _evt_hover_exit(self, evt: wx.MouseEvent) -> None:
        """Handle hovering out of the window."""
        self._hovered = False
        self.selector.evt_hover_exit()
        self.widget.Refresh()

    @property
    @override
    def selected(self) -> bool:
        """If the icon is currently selected."""
        return self._selected

    @selected.setter
    @override
    def selected(self, value: bool) -> None:
        self._selected = value
        self.widget.Refresh()

    @override
    def set_readonly(self, enabled: bool) -> None:
        """Set the checkbox to be readonly."""
        self._readonly = enabled
        self.widget.Refresh()

    @override
    def set_highlight(self, enabled: bool) -> None:
        """Change the highlight state."""
        self._highlight = enabled
        self.widget.Refresh()


class OptionRowUI(OptionRow):
    """Implementation of the option row."""

    async def display(self, row: int, option: Option, remove_event: trio.Event) -> None:
        """Reconfigure this row to display the specified option, then show it.

        Once the event triggers, remove the row.
        """
        raise NotImplementedError


class WxSelector(Selector[IconUI, OptionRowUI]):
    """Wx implementation of the corridor selector."""
    def __init__(self, packset: packages.PackagesSet, wx_img: WXImages, cur_style: utils.ObjectID) -> None:
        conf = config.APP.get_cur_conf(UIState)
        super().__init__(conf)

        self.wx_img = wx_img

    @override
    async def ui_task(self) -> None:
        raise NotImplementedError

    @override
    def ui_win_hide(self) -> None:
        raise NotImplementedError

    @override
    def ui_win_show(self) -> None:
        raise NotImplementedError

    @override
    def ui_win_getsize(self) -> tuple[int, int]:
        raise NotImplementedError

    @override
    async def ui_win_reflow(self) -> None:
        raise NotImplementedError

    @override
    def ui_enable_just_this(self, enable: bool) -> None:
        raise NotImplementedError

    @override
    def ui_desc_display(
        self, *,
        title: TransToken,
        authors: TransToken,
        desc: MarkdownData,
        options_title: TransToken,
        show_no_options: bool,
    ) -> None:
        raise NotImplementedError

    @override
    def ui_desc_set_img_state(self, handle: img.Handle | None, left: bool, right: bool) -> None:
        raise NotImplementedError

    @override
    def ui_option_create(self) -> OptionRowUI:
        raise NotImplementedError
