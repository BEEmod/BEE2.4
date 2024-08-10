"""Wx implementation of the corridor selector."""
from __future__ import annotations
from typing import Final
from typing_extensions import override

import itertools

import trio
import wx.html

from app import WidgetCache, img
from app.corridor_selector import (
    WIDTH, HEIGHT, IMG_ARROW_LEFT, IMG_ARROW_RIGHT, IMG_CORR_BLANK, Icon,
    OPTS_DIR, OPTS_MODE, OPTS_ORIENT, OptionRow, Selector,
    TRANS_HELP, TRANS_NO_OPTIONS, TRANS_ONLY_THIS, TRANS_RAND_OPTION, TRANS_TITLE,
)
from app.mdown import MarkdownData
from config.corridors import UIState
from corridor import Option
from transtoken import TransToken
import config
import packages
import utils

from .img import ImageSlot, WXImages
from . import MARKDOWN, PEN_SLOT_BORDER, PEN_SLOT_BORDER_SEL, MAIN_WINDOW, discretise_scrollwheel
from .wid_transtoken import set_text, set_tooltip, set_win_title
from .widgets import EnumButton


ICON_INSET: Final = 8


class IconUI(Icon):
    """An icon for a corridor."""
    def __init__(self, selector: WxSelector, index: int) -> None:
        """Create the widgets."""
        self.widget = wx.Panel(selector.panel_items)
        self.index = index
        self.selector = selector
        self.img = ImageSlot(self.widget)
        self._selected = self._hovered = self._highlight = self._readonly = False
        self.check_bounds = wx.Rect()

        self.widget.SetMinSize((WIDTH, HEIGHT))
        self.widget.Bind(wx.EVT_ENTER_WINDOW, self._evt_hover_enter)
        self.widget.Bind(wx.EVT_LEAVE_WINDOW, self._evt_hover_exit)
        self.widget.Bind(wx.EVT_LEFT_UP, self._evt_clicked)
        self.widget.Bind(wx.EVT_PAINT, self._on_paint)

    def _evt_clicked(self, evt: wx.MouseEvent) -> None:
        """Detect clicking on the checkbox."""
        if not self._readonly and self.check_bounds.Contains(evt.Position):
            self._selected = not self._selected
            self.widget.Refresh()
            self.selector.select_trigger.maybe_trigger()
        else:
            self.selector.evt_selected(self)

    def _on_paint(self, evt: wx.PaintEvent) -> None:
        """Draw the icon."""
        dc = wx.PaintDC(self.widget)
        native = wx.RendererNative.Get()
        wid_size = self.widget.GetSize()
        check_size = native.GetCheckBoxSize(self.widget)

        dc.SetPen(PEN_SLOT_BORDER_SEL if self._highlight else PEN_SLOT_BORDER)
        dc.DrawRectangle(wx.Rect(wid_size))
        self.img.draw(dc, ICON_INSET, ICON_INSET)

        self.check_bounds = wx.Rect(
            ICON_INSET,
            wid_size.Height - check_size.Height - ICON_INSET,
            check_size.Width, check_size.Height,
        )
        native.DrawCheckBox(
            self.widget, dc,
            self.check_bounds,
            (self._selected * wx.CONTROL_CHECKED) |
            (self._hovered * wx.CONTROL_CURRENT) |
            (self._readonly * wx.CONTROL_DISABLED),
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
    def set_image(self, handle: img.Handle | None) -> None:
        """Set the image for this icon."""
        self.img.set_handle(handle)
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

    def __init__(self, parent: wx.Panel, sizer: wx.GridSizer) -> None:
        super().__init__()
        self.parent_sizer = sizer
        self.label = wx.StaticText(parent, style=wx.ALIGN_RIGHT)
        self.combo = wx.ComboBox(parent, style=wx.CB_DROPDOWN | wx.CB_READONLY)
        self._value_order = ()
        self.combo.Bind(wx.EVT_COMBOBOX, self.on_changed)

    @override
    async def display(
        self, row: int, option: Option, remove_event: trio.Event,
        *, task_status: trio.TaskStatus = trio.TASK_STATUS_IGNORED,
    ) -> None:
        """Reconfigure this row to display the specified option, then show it.

        Once the event triggers, remove the row.
        """
        set_text(self.label, option.name)
        set_tooltip(self.label, option.desc)
        set_tooltip(self.combo, option.desc)
        self.combo.Set([
            str(TRANS_RAND_OPTION),
            *[str(val.name) for val in option.values],
        ])
        self._value_order = [
            utils.ID_RANDOM,
            *[val.id for val in option.values],
        ]
        # Caller has assigned one of our IDs to our AsyncValue, so index() should always succeed.
        self.combo.Selection = self._value_order.index(self.current.value)

        self.parent_sizer.Add(self.label, 0, wx.EXPAND, 0)
        self.parent_sizer.Add(self.combo, 0, 0, 0)
        self.label.Show()
        self.combo.Show()
        self.parent_sizer.Layout()
        # Wait for the signal that the corridor has been deselected, then remove.
        await remove_event.wait()
        self.parent_sizer.Detach(self.label)
        self.parent_sizer.Detach(self.combo)
        self.label.Hide()
        self.combo.Hide()
        self.parent_sizer.Layout()

    def on_changed(self, evt: wx.Event) -> None:
        """Apply changes to the combobox."""
        if (ind := self.combo.Selection) != wx.NOT_FOUND:
            self.current.value = self._value_order[ind]


class WxSelector(Selector[IconUI, OptionRowUI]):
    """Wx implementation of the corridor selector."""
    def __init__(self, packset: packages.PackagesSet, wx_img: WXImages, cur_style: utils.ObjectID) -> None:
        self_ref = self
        conf = config.APP.get_cur_conf(UIState)
        super().__init__(conf)

        self.wx_img = wx_img
        self.win = wx.Frame(
            MAIN_WINDOW,
            style=wx.CAPTION | wx.CLIP_CHILDREN | wx.CLOSE_BOX
                | wx.FRAME_FLOAT_ON_PARENT | wx.RESIZE_BORDER | wx.SYSTEM_MENU,
        )
        self.win.Bind(wx.EVT_CLOSE, lambda evt: self_ref.close_event.set())
        set_win_title(self.win, TRANS_TITLE)

        self.win_splitter = wx.SplitterWindow(self.win)
        self.win_splitter.SetMinimumPaneSize(20)

        self.pane_left = wx.Panel(self.win_splitter)
        self.pane_right = wx.Panel(self.win_splitter)

        self.win_splitter.SplitVertically(self.pane_left, self.pane_right)

        self.sizer_right = sizer_right = wx.BoxSizer(wx.VERTICAL)
        self.pane_right.SetSizer(sizer_right)

        sizer_img = wx.BoxSizer(wx.HORIZONTAL)
        sizer_right.Add(sizer_img, wx.SizerFlags().Proportion(0).CenterHorizontal())

        self.btn_image_left = wx.Button(self.pane_right, style=wx.BU_EXACTFIT)
        self.wid_image = wx.StaticBitmap(self.pane_right)
        self.btn_image_right = wx.Button(self.pane_right, style=wx.BU_EXACTFIT)
        sizer_img.Add(self.btn_image_left, 0, wx.EXPAND, 0)
        sizer_img.Add(self.wid_image, 1, wx.EXPAND, 0)
        sizer_img.Add(self.btn_image_right, 0, wx.EXPAND, 0)

        wx_img.apply(self.btn_image_left, IMG_ARROW_LEFT)
        wx_img.apply(self.wid_image, IMG_CORR_BLANK)
        wx_img.apply(self.btn_image_right, IMG_ARROW_RIGHT)
        self.btn_image_left.Bind(wx.EVT_BUTTON, lambda evt: self_ref._sel_img(-1))
        self.btn_image_right.Bind(wx.EVT_BUTTON, lambda evt: self_ref._sel_img(+1))
        self.wid_image.Bind(wx.EVT_MOUSEWHEEL, discretise_scrollwheel(self._sel_img))

        self.wid_title = wx.StaticText(self.pane_right)
        self.wid_title.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, 0, ""))
        sizer_right.Add(self.wid_title, wx.SizerFlags().Proportion(0).CenterHorizontal())

        self.wid_authors = wx.StaticText(self.pane_right)
        sizer_right.Add(self.wid_authors, wx.SizerFlags().Proportion(0).CenterHorizontal())

        self.wid_desc = wx.html.HtmlWindow(self.pane_right, wx.ID_ANY)
        sizer_right.Add(self.wid_desc, 1, wx.EXPAND, 0)

        self.wid_options_title = wx.StaticText(self.pane_right)
        self.wid_options_title.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, 0, ""))
        sizer_right.Add(self.wid_options_title, 0, 0, 0)

        self.wid_no_options = wx.StaticText(self.pane_right)
        set_text(self.wid_no_options, TRANS_NO_OPTIONS)
        sizer_right.Add(self.wid_no_options, 0, wx.EXPAND, 0)

        self.sizer_options = wx.GridSizer(0, 2, 0, 0)
        sizer_right.Add(self.sizer_options, 0, wx.EXPAND, 0)

        sizer_ctrl_btns = wx.BoxSizer(wx.HORIZONTAL)
        sizer_right.Add(0, 8)
        sizer_right.Add(sizer_ctrl_btns, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        self.btn_just_this = wx.Button(self.pane_right)
        set_text(self.btn_just_this, TRANS_ONLY_THIS)
        sizer_ctrl_btns.Add(self.btn_just_this, wx.SizerFlags().Proportion(0))

        self.btn_close = wx.Button(self.pane_right, wx.ID_CLOSE, "")
        sizer_ctrl_btns.Add(self.btn_close, wx.SizerFlags().Proportion(0))

        self.btn_just_this.Bind(wx.EVT_BUTTON, lambda evt: self_ref.evt_select_one())
        self.btn_close.Bind(wx.EVT_BUTTON, lambda evt: self_ref.close_event.set())

        sizer_left = wx.BoxSizer(wx.VERTICAL)
        self.pane_left.SetSizer(sizer_left)

        sizer_btns = wx.BoxSizer(wx.HORIZONTAL)
        sizer_left.Add(sizer_btns, wx.SizerFlags().Proportion(0))

        self.btn_mode = EnumButton(self.pane_left, self.state_mode, OPTS_MODE)
        self.btn_direction = EnumButton(self.pane_left, self.state_dir, OPTS_DIR)
        self.btn_orient = EnumButton(self.pane_left, self.state_orient, OPTS_ORIENT)

        btn_flags = wx.SizerFlags().Proportion(0).Border(wx.LEFT | wx.RIGHT, 4)
        sizer_btns.Add(self.btn_mode.sizer, btn_flags)
        sizer_btns.Add(self.btn_direction.sizer, btn_flags)
        sizer_btns.Add(self.btn_orient.sizer, btn_flags)

        lbl_info = wx.StaticText(self.pane_left)
        set_text(lbl_info, TRANS_HELP)
        sizer_left.Add(lbl_info, wx.SizerFlags().Proportion(0).Border(wx.ALL, 8))

        self.panel_items = wx.ScrolledWindow(self.pane_left, style=wx.BORDER_SUNKEN)
        self.sizer_items = wx.BoxSizer(wx.VERTICAL)
        sizer_left.Add(self.panel_items, wx.SizerFlags().Proportion(1).Expand())
        self.panel_items.SetSizer(self.sizer_items)
        self.panel_items.Bind(wx.EVT_SIZE, self.evt_window_resized)
        self.panel_items.SetScrollRate(0, 10)

        self.icons = WidgetCache(lambda ind: IconUI(self_ref, ind), lambda icon: icon.widget.Hide())

        self.load_corridors(packset, cur_style)

    @override
    async def ui_task(self) -> None:
        """Task which runs to update the UI."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self.btn_direction.task)
            nursery.start_soon(self.btn_mode.task)
            nursery.start_soon(self.btn_orient.task)

    @override
    def _ui_calc_columns(self) -> int:
        """Calculate the number of columns required for corridors."""
        return (self.pane_left.GetSize().Width - 10) // WIDTH

    @override
    async def _ui_reposition_items(self) -> None:
        self.sizer_items.Clear(delete_windows=False)
        row_flags = wx.SizerFlags().Left().Border(wx.TOP | wx.BOTTOM, 2)
        item_flags = wx.SizerFlags().Border(wx.ALL, 2)

        print(f'Reposition: {len(self.icons.placed)} in {self.column_count}')
        for row in itertools.batched(self.icons.placed, self.column_count):
            await trio.lowlevel.checkpoint()
            row_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.sizer_items.Add(row_sizer, row_flags)
            for icon in row:
                icon.widget.Show()
                row_sizer.Add(icon.widget, item_flags)
        self.panel_items.SetVirtualSize(1, 1)
        self.sizer_items.Layout()

    @override
    def ui_win_hide(self) -> None:
        self.win.Hide()

    @override
    def ui_win_show(self) -> None:
        self.win.Show()
        self.win.Raise()
        self.win.CentreOnScreen()

    @override
    def ui_win_getsize(self) -> tuple[int, int]:
        size = self.win.GetSize()
        return size.Width, size.Height

    @override
    def ui_enable_just_this(self, enable: bool) -> None:
        self.btn_just_this.Enabled = enable

    @override
    def ui_desc_display(
        self, *,
        title: TransToken,
        authors: TransToken,
        desc: MarkdownData,
        options_title: TransToken,
        show_no_options: bool,
    ) -> None:
        set_text(self.wid_title, title)
        set_text(self.wid_authors, authors)
        self.wid_desc.SetPage(MARKDOWN.convert(desc))
        set_text(self.wid_options_title, options_title)
        self.wid_no_options.Show(show_no_options)
        self.sizer_right.Layout()

    @override
    def ui_desc_set_img_state(self, handle: img.Handle | None, left: bool, right: bool) -> None:
        self.wx_img.apply(self.wid_image, handle)
        self.btn_image_left.Enabled = left
        self.btn_image_right.Enabled = right

    @override
    def ui_option_create(self) -> OptionRowUI:
        return OptionRowUI(self.pane_right, self.sizer_options)

    @override
    def ui_option_refreshed(self) -> None:
        self.sizer_right.Layout()
