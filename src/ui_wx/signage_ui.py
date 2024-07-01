"""Tk-specific implementation of the signage UI."""
from typing_extensions import override

import wx

from app import img
from packages import PakRef, Signage
from transtoken import TransToken
from .dragdrop import DragDrop
from .img import WXImages
from . import MAIN_WINDOW
from .wid_transtoken import set_text, set_win_title

from app.signage_ui import IMG_BLANK, SignageUIBase, TRANS_TITLE, TRANS_SELECTED


class SignageUI(SignageUIBase[wx.Window]):
    """Tk-specific implementation of the signage UI."""
    __slots__ = ['drag_man']  # Use a slot to override the superclass' property.
    drag_man: DragDrop[PakRef[Signage]]

    def __init__(self, wx_img: WXImages) -> None:
        """Create the UI."""
        self.window = win = wx.Frame(MAIN_WINDOW, style=wx.DEFAULT_FRAME_STYLE)
        win.SetSize((630, 807))
        set_win_title(win, TRANS_TITLE)
        win.Bind(wx.EVT_CLOSE, lambda evt: self._evt_on_closed())

        self.drag_man = DragDrop(win, info_cb=self._get_drag_info)
        self.wx_img = wx_img
        super().__init__()

        panel_main = wx.Panel(win)
        sizer_cols = wx.BoxSizer(wx.HORIZONTAL)
        panel_main.SetSizer(sizer_cols)

        sizer_left = wx.BoxSizer(wx.VERTICAL)
        sizer_cols.Add(sizer_left, 0, wx.EXPAND, 0)

        # Panel holding the selected items.
        panel_select = wx.StaticBox(panel_main, style=wx.ALIGN_CENTRE_HORIZONTAL)
        sizer_select_wrap = wx.StaticBoxSizer(panel_select)
        sizer_left.Add(sizer_select_wrap, 0, wx.ALL | wx.EXPAND, 8)
        set_text(panel_select, TRANS_SELECTED)
        sizer_select = wx.GridSizer(7, 4, 0, 0)
        sizer_select_wrap.Add(sizer_select)

        sizer_left.Add(wx.StaticLine(panel_main), 0, wx.EXPAND, 0)

        self.wid_preview_text = wx.StaticText(panel_main, style=wx.ALIGN_CENTRE_HORIZONTAL | wx.ST_ELLIPSIZE_END)
        sizer_left.Add(self.wid_preview_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 16)

        panel_preview = wx.Panel(panel_main, wx.ID_ANY, style=wx.BORDER_RAISED)
        # panel_preview.SetMinSize((148, 72))
        sizer_left.Add(panel_preview, 0, wx.ALIGN_CENTRE_HORIZONTAL | wx.ALL, 4)
        sizer_preview_vert = wx.BoxSizer(wx.VERTICAL)
        sizer_preview_horiz = wx.BoxSizer(wx.HORIZONTAL)
        panel_preview.SetSizer(sizer_preview_horiz)

        self.wid_preview_left = wx.StaticBitmap(panel_preview, wx.ID_ANY)
        self.wid_preview_right = wx.StaticBitmap(panel_preview)
        wx_img.apply(self.wid_preview_left, IMG_BLANK)
        wx_img.apply(self.wid_preview_right, IMG_BLANK)
        sizer_preview_horiz.Add(self.wid_preview_left, 0, wx.ALL, 2)
        sizer_preview_horiz.Add(self.wid_preview_right, 0, wx.ALL, 2)

        # Panel holding all possible signage.
        self.panel_chooser = wx.ScrolledWindow(panel_main, wx.ID_ANY, style=wx.TAB_TRAVERSAL)
        self.panel_chooser.SetScrollRate(0, 10)
        self.sizer_chooser = wx.WrapSizer(wx.HORIZONTAL)
        self.panel_chooser.SetSizer(self.sizer_chooser)

        sizer_cols.Add(self.panel_chooser, 1, wx.ALL | wx.EXPAND, 4)

        # tk_tools.add_mousewheel(canv_all, canv_all, window)

        flags = wx.SizerFlags().Border()

        for row, col, slot in self._create_chosen_slots(panel_select):
            sizer_select.Add(self.drag_man.slot_widget(slot), flags)

        for slot in self._create_picker_slots(self.panel_chooser):
            self.sizer_chooser.Add(self.drag_man.slot_widget(slot), flags)

    @override
    def ui_win_show(self) -> None:
        """Show the window."""
        self.window.Show()
        self.window.CentreOnParent()

    @override
    def ui_win_hide(self) -> None:
        """Hide the window."""
        self.window.Hide()

    @override
    def ui_set_preview_name(self, name: TransToken) -> None:
        """Set the text for the preview."""
        set_text(self.wid_preview_text, name)

    @override
    def ui_set_preview_img(self, left: img.Handle, right: img.Handle) -> None:
        """Set the images for the preview."""
        self.wx_img.apply(self.wid_preview_left, left)
        self.wx_img.apply(self.wid_preview_right, right)
