"""Wx-specific implementation of the selector window."""
from __future__ import annotations
from typing import Final, assert_never
from typing_extensions import override

from collections.abc import Callable, Mapping
from contextlib import aclosing
import math

import wx.html
import trio

from app import WidgetCache, img
from app.mdown import MarkdownData
from app.selector_win import (
    DispFont, SelectorWinBase, AttrDef, Options, NavKeys,
    TRANS_ATTR_DESC, TRANS_SUGGESTED, TRANS_SUGGESTED_MAC, TRANS_WINDOW_TITLE,
)
from consts import SEL_ICON_SIZE, SEL_ICON_SIZE_LRG as ICON_SIZE_LRG
from packages import AttrTypes
from transtoken import TransToken
from ui_wx import MARKDOWN
from ui_wx.img import WX_IMG
from ui_wx.wid_transtoken import set_text, set_win_title, set_menu_text, set_tooltip, set_entry_value
import utils


__all__ = [
    'AttrDef',  # Re-export
    'SelectorWin',
    'Options',
]

ITEM_WIDTH = SEL_ICON_SIZE + (32 if utils.MAC else 16)
ITEM_HEIGHT = SEL_ICON_SIZE + 51

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


# noinspection PyProtectedMember
class GroupHeader:
    """The widget used for group headers."""
    menu_item: wx.MenuItem | None
    def __init__(self, win: SelectorWin) -> None:
        self.parent = win
        self.panel = wx.Panel(win.wid_itemlist)
        # Event functions access the attribute, so this can be changed to reassign.
        self.id = '<unused group>'
        # The right-click cascade widget. Default to the root one, will be reassigned after.
        self.menu = win.context_menu
        self.menu_item = None

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(
            wx.StaticLine(self.panel, wx.HORIZONTAL),
            wx.SizerFlags().Expand().Proportion(1),
        )
        self.title = wx.StaticText(self.panel)
        sizer.Add(self.title, wx.SizerFlags().Border(wx.LEFT | wx.RIGHT, 4))
        sizer.Add(
            wx.StaticLine(self.panel, wx.HORIZONTAL),
            wx.SizerFlags().Expand().Proportion(1),
        )
        self.arrow = wx.StaticText(self.panel)
        sizer.Add(self.arrow)

        # for item in sizer.GetChildren():
        #     item.Window.Bind(wx.EVT_LEFT_DOWN, self._evt_toggle)
        #     item.Window.SetCursor(wx.CURSOR_HAND)
        self.panel.Bind(wx.EVT_LEFT_DOWN, self._evt_toggle)
        self.panel.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.panel.Bind(wx.EVT_ENTER_WINDOW, self._evt_hover_start)
        self.panel.Bind(wx.EVT_LEAVE_WINDOW, self._evt_hover_end)
        self.panel.SetSizer(sizer)

    def hide(self) -> None:
        """Hide the widgets and stop tracking translations."""
        if self.menu_item is not None:
            set_menu_text(self.menu_item, TransToken.BLANK)
            self.menu_item = None
        set_text(self.title, TransToken.BLANK)
        self.panel.Hide()

    def _evt_toggle(self, _: wx.Event) -> None:
        """Toggle the header on or off."""
        self.parent._evt_group_clicked(self.id)

    def _evt_hover_start(self, _: wx.Event) -> None:
        """When hovered over, fill in the triangle."""
        self.parent._evt_group_hover_start(self.id)

    def _evt_hover_end(self, _: wx.Event) -> None:
        """When leaving, hollow the triangle."""
        self.parent._evt_group_hover_end(self.id)


class SelectorWin(SelectorWinBase[wx.Button]):
    """Wx implementation of the selector window."""
    parent: wx.TopLevelWindow
    win: wx.Frame
    split_win: wx.SplitterWindow

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
    _suggest_lbl: list[wx.Panel | wx.StaticBox]

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
        set_win_title(self.win, TRANS_WINDOW_TITLE.format(subtitle=opt.title))

        self.context_menu = wx.Menu()

        self.norm_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.sugg_font = self.norm_font.Bold()
        self.mouseover_font = self.norm_font.Italic()

        panel_outer = wx.Panel(self.win)
        sizer_outer = wx.BoxSizer(wx.VERTICAL)
        panel_outer.SetSizer(sizer_outer)

        wid_label_windesc = wx.StaticText(panel_outer, wx.ID_ANY, "")
        set_text(wid_label_windesc, opt.desc)
        wid_label_windesc.SetMinSize((-1, 80))
        sizer_outer.Add(wid_label_windesc, 0, wx.ALL | wx.EXPAND, 2)

        self.splitter = wx.SplitterWindow(panel_outer)
        self.splitter.SetMinimumPaneSize(20)
        self.splitter.SetSashGravity(1.0)
        sizer_outer.Add(self.splitter, 1, wx.EXPAND, 0)

        self.wid_itemlist = wx.ScrolledWindow(self.splitter)
        self.wid_panel_info = wx.Panel(self.splitter)
        self.splitter.SplitVertically(self.wid_itemlist, self.wid_panel_info)

        sizer_info = wx.BoxSizer(wx.VERTICAL)
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
                set_text(desc_text, TRANS_ATTR_DESC.format(desc=attr.desc))
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
            set_text(self.wid_button_reset, TransToken.ui("Select Suggested"))
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

        self.disp_btn = wx.Button(parent, label="...", style=wx.BU_EXACTFIT)
        self.disp_btn.Bind(wx.EVT_BUTTON, open_window)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.display, wx.SizerFlags().Proportion(1).Expand())
        sizer.Add(self.disp_btn, wx.SizerFlags())

        # Ensure they're updated correctly.
        self.set_disp()
        self.save()

        return sizer

    @override
    def _ui_win_hide(self, /) -> None:
        if self.modal:
            pass  # TODO?
        self.win.Hide()

    @override
    def _ui_win_show(self, /) -> None:
        self.win.Show()
        self.win.Raise()
        self.win.CentreOnScreen()

    @override
    def _ui_win_get_size(self, /) -> tuple[int, int]:
        size = self.win.GetSize()
        return size.width, size.height

    @override
    def _ui_win_set_size(self, width: int, height: int, /) -> None:
        self.win.SetSize(wx.DefaultCoord, wx.DefaultCoord, width, height)

    @override
    async def _ui_reposition_items(self) -> None:
        pass  # TODO

    @override
    def _ui_button_create(self, ind: int, /) -> wx.Button:
        button = wx.Button(self.wid_itemlist)
        button.Bind(wx.EVT_BUTTON, lambda evt: self._evt_button_click(ind))
        button.SetBitmapPosition(wx.TOP)
        return button

    @override
    def _ui_button_set_text(self, button: wx.Button, text: TransToken, /) -> None:
        set_text(button, text)

    @override
    def _ui_button_set_img(self, button: wx.Button, image: img.Handle | None, /) -> None:
        WX_IMG.apply(button, image)

    @override
    def _ui_button_set_selected(self, button: wx.Button, selected: bool, /) -> None:
        pass  # TODO

    @override
    def _ui_button_hide(self, button: wx.Button, /) -> None:
        button.Hide()

    @override
    def _ui_button_scroll_to(self, button: wx.Button, /) -> None:
        pass  # TODO

    @override
    def _ui_props_set_author(self, author: TransToken, /) -> None:
        set_text(self.wid_props_author, author)

    @override
    def _ui_props_set_name(self, name: TransToken, /) -> None:
        set_text(self.wid_props_name, name)

    @override
    def _ui_props_set_desc(self, desc: MarkdownData, /) -> None:
        self.wid_props_desc.SetPage(MARKDOWN.convert(desc))

    @override
    def _ui_props_set_icon(self, image: img.Handle, /) -> None:
        WX_IMG.apply(self.wid_props_icon, image)

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
        set_text(self.attr_text_labels[attr], text)

    @override
    def _ui_attr_set_image(self, attr: AttrDef, image: img.Handle, /) -> None:
        WX_IMG.apply(self.attr_image_labels[attr], image)

    @override
    def _ui_attr_set_tooltip(self, attr: AttrDef, tooltip: TransToken, /) -> None:
        set_tooltip(self.attr_image_labels[attr], tooltip)

    @override
    def _ui_menu_clear(self) -> None:
        for item in list(self.context_menu.GetMenuItems()):
            self.context_menu.Remove(item)
        self._menu_items.clear()
        # Ungrouped items appear directly in the menu.
        self.context_menus = {'': self.context_menu}

        # Reset group widgets, so they can be added again.
        self.group_cache.reset()
        self.group_widgets.clear()

    @override
    def _ui_menu_add(self, group_key: str, item: utils.SpecialID, func: Callable[[], object],
                     label: TransToken, /) -> None:
        """Add the specified item to the group's menu."""
        group = self.group_widgets[group_key]
        self._menu_items[item] = menu = group.menu.AppendRadioItem(wx.ID_ANY, f'<item>:{item}', '')
        set_menu_text(menu, label)
        # group.menu.Bind(wx.EVT_COMMAND, lambda evt: func())  # TODO: How does this work

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
            group = self.group_widgets[data.group_id]
            group.title.SetFont(self.sugg_font)
            if group.menu_item is not None:
                group.menu_item.SetFont(self.sugg_font)

    @override
    def _ui_menu_reset_suggested(self) -> None:
        """Reset the fonts for all group widgets. menu_set_font() will then set them."""
        for group_key, header in self.group_widgets.items():
            header.title.Font = self.norm_font
            if header.menu_item is not None:
                header.menu_item.SetFont(self.norm_font)

    @override
    def _ui_group_create(self, key: str, label: TransToken) -> None:
        if key in self.group_widgets:
            return  # Already present.
        menu = wx.Menu() if key else self.context_menu

        self.group_widgets[key] = group = self.group_cache.fetch()
        group.menu = wx.Menu() if key else self.context_menu
        group.id = key
        group.menu_item = None
        set_text(group.title, label)

    @override
    def _ui_group_add(self, key: str, name: TransToken) -> None:
        """Add the specified group to the rightclick menu."""
        group = self.group_widgets[key]
        group.menu_item = item = self.context_menu.AppendSubMenu(group.menu, f'<group>:{name}')
        set_menu_text(item, name)

    @override
    def _ui_group_hide_unused(self) -> None:
        """Hide any group widgets that are still visible."""
        self.group_cache.reset()

    @override
    def _ui_group_set_arrow(self, key: str, arrow: str) -> None:
        self.group_widgets[key].arrow.SetLabelText(arrow)

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
        set_entry_value(self.display, text)
        set_tooltip(self.display, tooltip)
        self.display.Enabled = self.disp_btn.Enabled = enabled
