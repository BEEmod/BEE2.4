"""Wx-specific implementation of the selector window."""
from __future__ import annotations

from typing import Final, assert_never
from typing_extensions import override


from contextlib import aclosing
from collections.abc import Callable, Mapping
import itertools

import wx.html
import trio

from app import WidgetCache, img
from app.mdown import MarkdownData
from app.selector_win import (
    DispFont, GroupHeaderBase, SelectorWinBase, AttrDef, Options, NavKeys,
    TRANS_ATTR_DESC, TRANS_SUGGESTED, TRANS_WINDOW_TITLE,
)
from consts import SEL_ICON_SIZE
from packages import AttrTypes
from transtoken import CURRENT_LANG, TransToken
from ui_wx import MARKDOWN, PEN_SLOT_BORDER, PEN_SLOT_BORDER_SEL, RADIO_MENU_BITMAP, wid_transtoken
from ui_wx.img import WX_IMG, ImageSlot
import utils


__all__ = [
    'AttrDef',  # Re-export
    'SelectorWin',
    'Options',
]

ITEM_WIDTH = SEL_ICON_SIZE + 16
ITEM_HEIGHT = SEL_ICON_SIZE + 64

KEY_TO_NAV: Final[Mapping[str, NavKeys]] = {
    'Up': NavKeys.UP,
    'Down': NavKeys.DOWN,
    'Left': NavKeys.LEFT,
    'Right': NavKeys.RIGHT,

    'Home': NavKeys.HOME,
    'End': NavKeys.END,

    'Return': NavKeys.ENTER,
    'Space': NavKeys.PLAY_SOUND,
}
PEN_GROUP_HEADER = wx.Pen(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWFRAME), 2)
FONT_GROUP_HEADER = wx.Font(wx.FontInfo(12))
FONT_GROUP_HEADER_SUGG = FONT_GROUP_HEADER.Bold()
FONT_SUGGESTED = wx.Font(wx.FontInfo(8.0).Light())
FONT_ITEM_NAME = [
    wx.Font(wx.FontInfo(i))
    for i in range(10, 5, -1)
]


class ItemSlot(wx.Panel):
    """The widget displaying items."""
    def __init__(self, parent: wx.ScrolledWindow) -> None:
        super().__init__(parent, style=wx.RESERVE_SPACE_EVEN_IF_HIDDEN)
        size = wx.Size(ITEM_WIDTH, ITEM_HEIGHT)
        self.SetSize(size)
        self.SetMinSize(size)
        self.Bind(wx.EVT_PAINT, self._on_paint)

        self.slot = ImageSlot(self)
        self.selected = False
        self.suggested = False
        self.label = TransToken.BLANK

    def _on_paint(self, evt: wx.PaintEvent) -> None:
        """Paint the widget."""
        dc = wx.PaintDC(self)
        y = 0
        if self.suggested:
            dc.SetPen(PEN_SLOT_BORDER)
            dc.SetFont(FONT_SUGGESTED)
            extent = dc.DrawLabel(
                str(TRANS_SUGGESTED), wx.NullBitmap,
                wx.Rect(0, 4, SEL_ICON_SIZE + 16, 16),
                alignment=wx.ALIGN_CENTRE_HORIZONTAL | wx.ALIGN_TOP,
            )
            mid_y = extent.Top + extent.Height // 2
            dc.DrawLineList([
                (7, mid_y, extent.Left - 2, mid_y),
                (8, mid_y - 1, 8, 20),
                (extent.Right + 2, mid_y, SEL_ICON_SIZE + 5, mid_y),
                (SEL_ICON_SIZE + 5, mid_y, SEL_ICON_SIZE + 5, 20),
            ])

        dc.SetPen(PEN_SLOT_BORDER_SEL if self.selected else PEN_SLOT_BORDER)
        y += 20
        dc.DrawRectangle(
            4, y, SEL_ICON_SIZE + 8, y + SEL_ICON_SIZE + 20,
        )
        y += 8
        self.slot.draw(dc, 8, y, True)
        y += SEL_ICON_SIZE + 8

        label = str(self.label)
        label_rect = wx.Rect(4, y, SEL_ICON_SIZE + 8, 8)
        # If the text is too long to fit, shrink it down a little.
        if dc.CanGetTextExtent():
            for font in FONT_ITEM_NAME:
                dc.SetFont(font)
                if dc.GetTextExtent(label).Width <= label_rect.Width:
                    break
        else:
            dc.SetFont(FONT_ITEM_NAME[0])
        dc.DrawLabel(
            label, label_rect,
            alignment=wx.ALIGN_CENTRE_HORIZONTAL | wx.ALIGN_TOP,
        )


# noinspection PyProtectedMember
class GroupHeader(GroupHeaderBase):
    """The widget used for group headers."""
    menu_item: wx.MenuItem | None

    def __init__(self, win: SelectorWin) -> None:
        super().__init__(win)
        self.parent_menu = win.context_menu
        self.panel = wx.Panel(win.wid_itemlist)
        # The right-click cascade widget. Default to the root one, will be reassigned after.
        self.menu = win.context_menu
        self.menu_item = None
        self.panel.SetMinSize((10, 24))

        self.title = TransToken.BLANK
        self.suggested = False
        self._hovered = self._opened = self._pressed = False
        self._arrow_flags = wx.CONTROL_NONE
        self.panel.Bind(wx.EVT_PAINT, self._on_paint)

        self.panel.Bind(wx.EVT_LEFT_DOWN, self._evt_mouse_down)
        self.panel.Bind(wx.EVT_LEFT_UP, self._evt_mouse_up)
        self.panel.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.panel.Bind(wx.EVT_ENTER_WINDOW, self._evt_hover_start)
        self.panel.Bind(wx.EVT_LEAVE_WINDOW, self._evt_hover_end)

    def hide(self) -> None:
        """Hide the widgets and stop tracking translations."""
        super().hide()
        if self.menu_item is not None:
            wid_transtoken.set_menu_text(self.menu_item, TransToken.BLANK)
            self.menu_item = None
        self.panel.Hide()

    def _evt_mouse_down(self, evt: wx.MouseEvent) -> None:
        self._pressed = True
        self.panel.Refresh()

    def _evt_mouse_up(self, evt: wx.MouseEvent) -> None:
        """The button can only be pressed if we started inside it."""
        if self._pressed:
            self._pressed = False
            self._evt_toggle()

    @override
    def _ui_reassign(self, group_id: str, title: TransToken) -> None:
        """Set the group label."""
        super()._ui_reassign(group_id, title)
        self.menu = wx.Menu() if group_id else self.parent_menu
        self.menu_item = None
        self.title = title
        self.suggested = False
        self.panel.Refresh()

    @override
    def _ui_set_arrow(self, opened: bool, hovered: bool) -> None:
        """Set the arrow glyph."""
        self._opened = opened
        self._hovered = hovered
        self._pressed = False
        self.panel.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        """Draw the header."""
        dc = wx.PaintDC(self.panel)
        native = wx.RendererNative.Get()
        size = wx.Rect(self.panel.GetSize())
        dc.SetFont(FONT_GROUP_HEADER_SUGG if self.suggested else FONT_GROUP_HEADER)
        title = str(self.title)

        required_size = dc.GetTextExtent(title)
        arrow_size = native.GetCollapseButtonSize(self.panel, dc)
        if required_size.height < arrow_size.height:
            required_size.height = arrow_size.height
        if required_size.Height > size.Height or required_size.width > size.width:
            self.panel.SetMinSize(required_size)

        title_rect = dc.DrawLabel(
            str(self.title), wx.NullBitmap, size,
            alignment=wx.ALIGN_CENTRE_HORIZONTAL | wx.ALIGN_CENTRE_VERTICAL,
        )
        dc.SetFont(FONT_GROUP_HEADER)
        arrow_left = size.Width - 8 - arrow_size.width
        native.DrawCollapseButton(
            self.panel, dc,
            wx.Rect(
                arrow_left,
                (size.Height - arrow_size.Height) // 2,
                arrow_size.Width, arrow_size.Height,
            ),
            (self._opened * wx.CONTROL_EXPANDED) |
            (self._hovered * wx.CONTROL_CURRENT) |
            (self._pressed * wx.CONTROL_PRESSED),
        )
        y = size.Height // 2
        dc.SetPen(PEN_GROUP_HEADER)
        dc.DrawLine(4, y, title_rect.Left - 4, y)
        dc.DrawLine(title_rect.Right + 4, y, arrow_left - 4, y)


class SelectorWin(SelectorWinBase[ItemSlot, GroupHeader]):
    """Wx implementation of the selector window."""
    parent: wx.TopLevelWindow
    win: wx.Frame
    split_win: wx.SplitterWindow
    wid_itemlist: wx.ScrolledWindow

    # Border around the selected item icon.
    wid_props_icon: wx.StaticBitmap
    wid_props_name: wx.StaticText
    wid_props_author: wx.StaticText
    wid_props_desc: wx.html.HtmlWindow
    attr_text_labels: dict[AttrDef, wx.StaticText]
    attr_image_labels: dict[AttrDef, wx.StaticBitmap]

    wid_button_reset: wx.Button | None
    wid_button_ok: wx.Button
    wid_button_cancel: wx.Button

    # The textbox on the parent window.
    display: wx.TextCtrl | None
    # The '...' button to open our window.
    disp_btn: wx.Button | None

    wid_samp_button: wx.Button | None

    # The overall sizer for the item list.
    itemlist_sizer: wx.BoxSizer

    # A map from group name -> header widget
    group_widgets: dict[str, GroupHeader]
    # Recycles existing group headers.
    group_cache: WidgetCache[GroupHeader]

    context_menu: wx.Menu
    # The menus for each group.
    context_menus: dict[str, wx.Menu]
    # Item -> its menu item.
    _menu_items: dict[utils.SpecialID, wx.MenuItem]

    norm_font: wx.Font
    # A font for showing suggested items in the context menu
    sugg_font: wx.Font
    # A font for previewing the suggested items
    mouseover_font: wx.Font

    def __init__(self, parent: wx.TopLevelWindow, opt: Options) -> None:
        super().__init__(opt)

        self.parent = parent
        self.context_menus = {}
        self._menu_items = {}
        self.attr_image_labels = {}
        self.attr_text_labels = {}
        self.group_widgets = {}
        self.display = self.disp_btn = None

        closure_self = self  # Avoid making 'self' a direct closure.
        self.group_cache = WidgetCache(lambda wid_id: GroupHeader(closure_self), GroupHeader.hide)

        self.win = wx.Frame(
            parent,
            style=wx.CAPTION | wx.CLIP_CHILDREN | wx.CLOSE_BOX
            | wx.FRAME_FLOAT_ON_PARENT | wx.RESIZE_BORDER | wx.SYSTEM_MENU,
        )
        wid_transtoken.set_win_title(self.win, TRANS_WINDOW_TITLE.format(subtitle=opt.title))

        self.context_menu = wx.Menu()

        self.norm_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.sugg_font = self.norm_font.Bold()
        self.mouseover_font = self.norm_font.Italic()

        panel_outer = wx.Panel(self.win)
        sizer_outer = wx.BoxSizer(wx.VERTICAL)
        panel_outer.SetSizer(sizer_outer)

        wid_label_windesc = wx.StaticText(panel_outer, wx.ID_ANY, "")
        wid_transtoken.set_text(wid_label_windesc, opt.desc)
        wid_label_windesc.SetMinSize((-1, 80))
        sizer_outer.Add(wid_label_windesc, 0, wx.ALL | wx.EXPAND, 2)

        self.splitter = wx.SplitterWindow(panel_outer)
        self.splitter.SetMinimumPaneSize(20)
        self.splitter.SetSashGravity(1.0)
        sizer_outer.Add(self.splitter, 1, wx.EXPAND, 0)

        self.wid_itemlist = wid_itemlist = wx.ScrolledWindow(
            self.splitter,
            style=wx.VSCROLL | wx.ALWAYS_SHOW_SB | wx.BORDER_SUNKEN,
        )
        wid_itemlist.SetBackgroundColour(wx.Colour(img.PETI_ITEM_BG))
        self.wid_panel_info = wx.Panel(self.splitter)
        self.splitter.SplitVertically(wid_itemlist, self.wid_panel_info)

        self.itemlist_sizer = wx.BoxSizer(wx.VERTICAL)
        wid_itemlist.SetSizer(self.itemlist_sizer)
        wid_itemlist.SetScrollRate(0, 10)
        wid_itemlist.Bind(wx.EVT_SIZE, self.evt_window_resized)

        self.sizer_info = sizer_info = wx.BoxSizer(wx.VERTICAL)
        self.wid_panel_info.SetSizer(sizer_info)

        self.wid_props_icon = wx.StaticBitmap(self.wid_panel_info, style=wx.BORDER_RAISED)
        sizer_info.Add(self.wid_props_icon, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 3)

        self.wid_props_name = wx.StaticText(self.wid_panel_info, wx.ID_ANY, "")
        self.wid_props_name.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD, 0, ""))

        name_widget: wx.Sizer | wx.Window
        if self.sampler is not None:
            sizer_name = wx.BoxSizer(wx.HORIZONTAL)
            sizer_name.Add(self.wid_props_name, 1, 0, 0)

            self.wid_samp_button = wx.Button(self.wid_panel_info, style=wx.BU_EXACTFIT)
            sizer_name.Add(self.wid_samp_button, 0, 0, 0)
            name_widget = sizer_name
        else:
            # Add the name widget directly.
            name_widget = self.wid_props_name
            self.wid_samp_button = None

        sizer_info.Add(name_widget, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 1)

        self.wid_props_author = wx.StaticText(self.wid_panel_info)
        sizer_info.Add(self.wid_props_author, 0, wx.ALIGN_CENTER_HORIZONTAL, 0)

        self.wid_props_desc = wx.html.HtmlWindow(self.wid_panel_info, wx.ID_ANY)
        sizer_info.Add(self.wid_props_desc, 1, wx.ALL | wx.EXPAND, 6)

        if self.attrs:
            self.sizer_attrs = wx.GridBagSizer(0, 0)
            sizer_info.Add(self.sizer_attrs, 0, wx.ALL | wx.EXPAND, 4)

            for attr, row, col_type in self._attr_widget_positions():
                desc_text = wx.StaticText(self.wid_panel_info)
                wid_transtoken.set_text(desc_text, TRANS_ATTR_DESC.format(desc=attr.desc))
                attr_wid: wx.Control
                if attr.type.is_image:
                    self.attr_image_labels[attr] = attr_wid = wx.StaticBitmap(self.wid_panel_info)
                    if attr.type is AttrTypes.COLOUR:
                        attr_wid.WindowStyle |= wx.BORDER_RAISED
                else:
                    self.attr_text_labels[attr] = attr_wid = wx.StaticText()
                sizer_attr = wx.BoxSizer(wx.HORIZONTAL)
                sizer_attr.Add(desc_text)
                sizer_attr.Add(attr_wid)

                # Wide ones have their own row, narrow ones are two to a row
                match col_type:
                    case 'wide':
                        self.sizer_attrs.Add(
                            sizer_attr,
                            (row, 0), (1, 3),
                            wx.EXPAND,
                        )
                    case 'left':
                        self.sizer_attrs.Add(
                            sizer_attr,
                            (row, 0), (1, 1),
                            wx.EXPAND,
                        )
                    case 'right':
                        self.sizer_attrs.Add(
                            wx.StaticLine(self.wid_panel_info, style=wx.LI_VERTICAL),
                            (row, 1), (1, 1),
                            wx.EXPAND,
                        )
                        attr_wid.WindowStyle |= wx.ALIGN_RIGHT
                        self.sizer_attrs.Add(
                            sizer_attr,
                            (row, 2), (1, 1),
                            wx.RIGHT | wx.EXPAND
                        )
                    case _:
                        assert_never(col_type)

            self.sizer_attrs.AddGrowableCol(0)
            self.sizer_attrs.AddGrowableCol(2)

        static_line_buttons = wx.StaticLine(self.wid_panel_info, wx.ID_ANY)
        sizer_info.Add(static_line_buttons, 0, wx.ALL | wx.EXPAND, 4)

        sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)
        sizer_info.Add(sizer_buttons, 0, wx.EXPAND, 0)

        self.wid_button_ok = wx.Button(self.wid_panel_info, wx.ID_OK, "")
        sizer_buttons.Add(self.wid_button_ok, 0, 0, 0)
        sizer_buttons.Add((0, 0), 1, wx.EXPAND, 0)

        if self.has_def:
            self.wid_button_reset = wx.Button(self.wid_panel_info, wx.ID_ANY, "")
            wid_transtoken.set_text(self.wid_button_reset, TransToken.ui("Select Suggested"))
            sizer_buttons.Add(self.wid_button_reset, 0, 0, 0)
            sizer_buttons.Add((0, 0), 1, wx.EXPAND, 0)
        else:
            self.wid_button_reset = None

        self.wid_button_cancel = wx.Button(self.wid_panel_info, wx.ID_CANCEL, "")
        sizer_buttons.Add(self.wid_button_cancel, 0, 0, 0)

        on_exit = self.exit
        self.wid_button_cancel.Bind(wx.EVT_BUTTON, on_exit)
        self.win.Bind(wx.EVT_CLOSE, on_exit)

        self.win.Layout()

    async def widget(self, parent: wx.Window) -> wx.Sizer:
        """Create the special textbox used to open the selector window.

        Returns the sizer that should be used to position the widgets.
        """
        if self.display is not None or self.disp_btn is not None:
            raise ValueError('Placed multiple times.')

        def open_window(event: wx.Event) -> None:
            """If readonly, produce an error bell."""
            if self._readonly:
                wx.Bell()
                event.Skip()
            else:
                self.open_win()

        self.display = wx.TextCtrl(parent)
        self.display.SetEditable(False)
        self.display.Bind(wx.EVT_LEFT_DOWN, open_window)
        self.display.Bind(wx.EVT_RIGHT_DOWN, self._evt_show_menu)

        self.disp_btn = wx.Button(parent, label="...", style=wx.BU_EXACTFIT)
        self.disp_btn.Bind(wx.EVT_BUTTON, open_window)
        self.disp_btn.Bind(wx.EVT_RIGHT_DOWN, self._evt_show_menu)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.display, wx.SizerFlags().Proportion(1).Expand())
        sizer.Add(self.disp_btn, wx.SizerFlags())

        # Ensure they're updated correctly.
        self.set_disp()
        self.save()

        return sizer

    def _evt_show_menu(self, evt: wx.Event) -> None:
        """Dislay the context window at the text widget."""
        evt.Skip()
        if not self._readonly and not self._loading and self.display is not None:
            self.display.PopupMenu(self.context_menu)
        else:
            wx.Bell()

    @override
    async def _ui_task(self) -> None:
        """Executed by task()."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._redraw_on_langchange)
            nursery.start_soon(self._update_menu_task)

    async def _redraw_on_langchange(self) -> None:
        """When languages change, the item list needs to be re-drawn."""
        while True:
            await CURRENT_LANG.wait_transition()
            self.wid_itemlist.Refresh()

    def evt_window_resized(self, event: object) -> None:
        """When resizing, we must always force the group headers to redraw."""
        super().evt_window_resized(event)
        for header in self.group_widgets.values():
            header.panel.Refresh()

    async def _update_menu_task(self) -> None:
        """When the item changes, update which menu options are set."""
        last_checked: wx.MenuItem | None = None
        async with aclosing(self.chosen.eventual_values()) as agen:
            async for chosen_id in agen:
                if last_checked is not None:
                    last_checked.Check(False)
                try:
                    last_checked = self._menu_items[chosen_id]
                except KeyError:
                    pass
                else:
                    last_checked.Check()

    @override
    def _ui_win_show(self, /) -> None:
        self.win.Show()
        self.win.Raise()
        self.win.CentreOnScreen()

    @override
    def _ui_win_hide(self, /) -> None:
        if self.modal:
            pass  # TODO?
        self.win.Hide()

    @override
    def _ui_win_get_size(self, /) -> tuple[int, int]:
        size = self.win.GetSize()
        return size.width, size.height

    @override
    def _ui_win_set_size(self, width: int, height: int, /) -> None:
        self.win.SetSize(wx.DefaultCoord, wx.DefaultCoord, width, height)

    @override
    def _ui_calc_columns(self) -> int:
        return (self.wid_itemlist.GetSize().Width - 10) // ITEM_WIDTH

    @override
    async def _ui_reposition_items(self) -> None:
        # If only the '' group is present, force it to be visible, and hide
        # the header.
        no_groups = self.group_order == ['']

        prev_scroll_pos = self.wid_itemlist.GetScrollPos(wx.VERTICAL) / self.wid_itemlist.GetScrollRange(wx.VERTICAL)

        self.itemlist_sizer.Clear(delete_windows=False)
        group_flags = wx.SizerFlags().Expand().Border(wx.ALL, 8)
        row_flags = wx.SizerFlags().Left().Border(wx.TOP | wx.BOTTOM, 2)
        item_flags = wx.SizerFlags().Border(wx.ALL, 2)

        for group_key in self.group_order:
            await trio.lowlevel.checkpoint()
            items = self.grouped_items[group_key]
            group_wid = self.group_widgets[group_key]

            if no_groups:
                group_wid.hide()
            else:
                self.itemlist_sizer.Add(group_wid.panel, group_flags)
                if not self.group_visible.get(group_key):
                    # Hide everything!
                    for item_id in items:
                        await trio.lowlevel.checkpoint()
                        self._id_to_button[item_id].Hide()
                    continue

            # Place each item
            for row in itertools.batched(items, self.column_count):
                await trio.lowlevel.checkpoint()
                row_sizer = wx.BoxSizer(wx.HORIZONTAL)
                self.itemlist_sizer.Add(row_sizer, row_flags)
                for item_id in row:
                    button = self._id_to_button[item_id]
                    button.suggested = item_id in self.suggested
                    button.Show()
                    row_sizer.Add(button, item_flags)

        self.wid_itemlist.SetVirtualSize(10, 10)
        self.itemlist_sizer.Layout()
        self.wid_itemlist.FitInside()
        # Restore the scrollbar position.
        _, pixels_per = self.wid_itemlist.GetScrollPixelsPerUnit()
        self.wid_itemlist.Scroll(
            wx.DefaultCoord,
            round(prev_scroll_pos * self.wid_itemlist.GetVirtualSize().Height / pixels_per),
        )

    @override
    def _ui_button_create(self, ind: int, /) -> ItemSlot:
        slot = ItemSlot(self.wid_itemlist)
        slot.Bind(wx.EVT_LEFT_DOWN, lambda evt: self._evt_button_click(ind))
        return slot

    @override
    def _ui_button_set_text(self, slot: ItemSlot, text: TransToken, /) -> None:
        slot.label = text
        slot.Refresh()

    @override
    def _ui_button_set_img(self, item: ItemSlot, image: img.Handle | None, /) -> None:
        item.slot.set_handle(image)
        item.Refresh()

    @override
    def _ui_button_set_selected(self, item: ItemSlot, selected: bool, /) -> None:
        item.selected = selected
        item.Refresh()

    @override
    def _ui_button_hide(self, item: ItemSlot, /) -> None:
        item.Hide()

    @override
    def _ui_button_scroll_to(self, item: ItemSlot, /) -> None:
        # Scroll-related things is done in scroll units, just convert to pixels
        # for the computations here though.
        _, pixels_per = self.wid_itemlist.GetScrollPixelsPerUnit()
        # This is the size of the viewport.
        view_height = self.wid_itemlist.GetScrollPageSize(wx.VERTICAL) * pixels_per

        # This is relative to the viewport
        y = item.GetPosition().y
        item_height = item.GetMinHeight()

        if 8 <= y <= view_height - item_height - 8:
            return  # Already in view

        # Center in the view. We need to add
        top_off = self.wid_itemlist.GetScrollPos(wx.VERTICAL) * pixels_per

        offset = top_off + y + (item_height - view_height) / 2
        self.wid_itemlist.Scroll(wx.DefaultCoord, round(offset / pixels_per))

    @override
    def _ui_props_set_author(self, author: TransToken, /) -> None:
        wid_transtoken.set_text(self.wid_props_author, author)

    @override
    def _ui_props_set_name(self, name: TransToken, /) -> None:
        wid_transtoken.set_text(self.wid_props_name, name)

    @override
    def _ui_props_set_desc(self, desc: MarkdownData, /) -> None:
        self.wid_props_desc.SetPage(MARKDOWN.convert(desc))

    @override
    def _ui_props_set_icon(self, image: img.Handle, /) -> None:
        WX_IMG.apply(self.wid_props_icon, image)
        self.sizer_info.Layout()

    @override
    def _ui_props_set_samp_button_enabled(self, enabled: bool, /) -> None:
        if self.wid_samp_button is not None:
            self.wid_samp_button.Enabled = enabled

    @override
    def _ui_props_set_samp_button_icon(self, glyph: str, /) -> None:
        if self.wid_samp_button is not None:
            self.wid_samp_button.LabelText = glyph

    @override
    def _ui_attr_set_text(self, attr: AttrDef, text: TransToken, /) -> None:
        wid_transtoken.set_text(self.attr_text_labels[attr], text)

    @override
    def _ui_attr_set_image(self, attr: AttrDef, image: img.Handle, /) -> None:
        WX_IMG.apply(self.attr_image_labels[attr], image)

    @override
    def _ui_attr_set_tooltip(self, attr: AttrDef, tooltip: TransToken, /) -> None:
        wid_transtoken.set_tooltip(self.attr_image_labels[attr], tooltip)

    @override
    def _ui_menu_clear(self) -> None:
        for menu in self.context_menus.values():
            wid_transtoken.clear_stored_menu(menu)
        for item in list(self.context_menu.GetMenuItems()):
            self.context_menu.Remove(item)
        self._menu_items.clear()
        # Ungrouped items appear directly in the menu.
        self.context_menus = {'': self.context_menu}

    @override
    def _ui_menu_add(
        self,
        group: GroupHeader,
        item: utils.SpecialID,
        func: Callable[[], object],
        label: TransToken, /,
    ) -> None:
        """Add the specified item to the group's menu."""
        self._menu_items[item] = menu_item = group.menu.AppendCheckItem(
            wx.ID_ANY, f'<item>:{item}', '',
        )
        wid_transtoken.set_menu_text(menu_item, label)
        group.menu.Bind(wx.EVT_MENU, lambda evt: func(), menu_item)
        menu_item.SetBitmap(RADIO_MENU_BITMAP, True)

    @override
    def _ui_menu_set_font(self, item_id: utils.SpecialID, /, suggested: bool) -> None:
        try:
            menu_item = self._menu_items[item_id]
        except KeyError:
            return

        menu_item.SetFont(self.sugg_font if suggested else self.norm_font)
        data = self._get_data(item_id)
        # Apply the font to the group header as well, if suggested.
        if data.group_id and suggested:
            header = self.group_widgets[data.group_id]
            header.suggested = True
            header.panel.Refresh()
            if header.menu_item is not None:
                header.menu_item.SetFont(self.sugg_font)

    @override
    def _ui_menu_reset_suggested(self) -> None:
        """Reset the fonts for all group widgets. menu_set_font() will then set them."""
        for group_key, header in self.group_widgets.items():
            header.suggested = False
            header.panel.Refresh()
            if header.menu_item is not None:
                header.menu_item.SetFont(self.norm_font)

    @override
    def _ui_group_add(self, group: GroupHeader, name: TransToken) -> None:
        """Add the specified group to the rightclick menu."""
        group.menu_item = item = self.context_menu.AppendSubMenu(group.menu, f'<group>:{name}')
        wid_transtoken.set_menu_text(item, name)

    @override
    def _ui_enable_reset(self, enabled: bool, /) -> None:
        if self.wid_button_reset is not None:
            self.wid_button_reset.Enabled = enabled

    @override
    def _ui_display_set(
        self, *,
        enabled: bool,
        text: TransToken,
        tooltip: TransToken,
        font: DispFont,
    ) -> None:
        if self.display is None or self.disp_btn is None:
            return  # Nothing to do.

        match font:
            case 'normal':
                font_obj = self.norm_font
            case 'suggested':
                font_obj = self.sugg_font
            case 'mouseover':
                font_obj = self.mouseover_font
            case _:
                assert_never(font)

        self.display.SetFont(font_obj)
        wid_transtoken.set_entry_value(self.display, text)
        wid_transtoken.set_tooltip(self.display, tooltip)
        self.display.Enabled = self.disp_btn.Enabled = enabled
