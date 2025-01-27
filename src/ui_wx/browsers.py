"""Windows to allow browsing for sounds and other files."""
import wx

from app.browsers import SoundBrowserBase
from ui_wx import MAIN_WINDOW


class SoundBrowser(SoundBrowserBase):

    def __init__(self) -> None:
        super().__init__()

        self.win = wx.Frame(MAIN_WINDOW)

        panel_main = wx.Panel(self.win, wx.ID_ANY)
        sizer_main = wx.BoxSizer(wx.VERTICAL)

        lbl_header = wx.StaticText(panel_main, wx.ID_ANY, "Sounds:")
        sizer_main.Add(lbl_header, 0, wx.LEFT | wx.RIGHT, 7)

        self.wid_soundlist = wx.ListBox(panel_main, wx.ID_ANY, choices=["soundb", "sounda"], style=wx.LB_ALWAYS_SB | wx.LB_SINGLE | wx.LB_SORT)
        sizer_main.Add(self.wid_soundlist, 1, wx.BOTTOM | wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        sizer_info = wx.FlexGridSizer(4, 2, 0, 0)
        sizer_main.Add(sizer_info, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 32)

        lbl_snd_name = wx.StaticText(panel_main, wx.ID_ANY, "Sound Name: ")
        sizer_info.Add(lbl_snd_name, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT | wx.ALL, 0)

        self.wid_text_name = wx.TextCtrl(panel_main, wx.ID_ANY, "")
        sizer_info.Add(self.wid_text_name, 0, wx.EXPAND, 0)

        lbl_snd_file = wx.StaticText(panel_main, wx.ID_ANY, "Sound File: ", style=wx.ALIGN_RIGHT)
        sizer_info.Add(lbl_snd_file, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT, 0)

        self.wid_text_sound = wx.TextCtrl(panel_main, wx.ID_ANY, "")
        self.wid_text_sound.Enable(False)
        sizer_info.Add(self.wid_text_sound, 0, wx.EXPAND, 0)

        lbl_source = wx.StaticText(panel_main, wx.ID_ANY, "Source File: ")
        sizer_info.Add(lbl_source, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT, 0)

        self.wid_text_source = wx.TextCtrl(panel_main, wx.ID_ANY, "")
        self.wid_text_source.Enable(False)
        sizer_info.Add(self.wid_text_source, 0, wx.ALL | wx.EXPAND, 0)

        lbl_filter = wx.StaticText(panel_main, wx.ID_ANY, "Filter: ")
        sizer_info.Add(lbl_filter, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT, 0)

        self.wid_text_filter = wx.TextCtrl(panel_main, wx.ID_ANY, "")
        sizer_info.Add(self.wid_text_filter, 0, wx.EXPAND, 0)

        sizer_checks = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_checks, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 0)

        self.wid_chk_autoplay = wx.CheckBox(panel_main, wx.ID_ANY, "Autoplay Sounds")
        sizer_checks.Add(self.wid_chk_autoplay, 0, wx.ALL, 4)

        self.wid_chk_raw = wx.CheckBox(panel_main, wx.ID_ANY, "Raw sounds")
        self.wid_chk_raw.Value = True
        sizer_checks.Add(self.wid_chk_raw, 0, wx.ALL, 4)

        sizer_btn = wx.BoxSizer(wx.HORIZONTAL)
        sizer_main.Add(sizer_btn, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 8)

        self.btn_ok = wx.Button(panel_main, wx.ID_OK, "")
        sizer_btn.Add(self.btn_ok, 0, wx.LEFT | wx.RIGHT, 8)

        self.btn_cancel = wx.Button(panel_main, wx.ID_CANCEL, "")
        sizer_btn.Add(self.btn_cancel, 0, wx.LEFT | wx.RIGHT, 8)

        self.btn_preview = wx.Button(panel_main, wx.ID_ANY, "Preview")
        sizer_btn.Add(self.btn_preview, 0, wx.LEFT | wx.RIGHT, 8)

        sizer_info.AddGrowableCol(1)

        panel_main.SetSizer(sizer_main)
        self.win.Layout()

    def _ui_show_window(self) -> None:
        self.win.Show()
        self.win.CentreOnScreen()

    def _ui_hide_window(self) -> None:
        self.win.Hide()
