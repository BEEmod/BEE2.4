"""Windows to allow browsing for sounds and other files."""
from typing import assert_never, override

import wx.dataview
from srctools import choreo
from srctools.sndscript import Sound

from app.browsers import AllowedSounds, SOUND_TYPES, SoundBrowserBase, SoundSeq
from ui_wx import MAIN_WINDOW


class SoundsList(wx.ListCtrl):
    """Implements required methods to allow accessing the internal lists directly."""
    def __init__(self, parent: wx.Panel, style: int) -> None:
        super().__init__(parent, style=style | wx.LC_REPORT | wx.LC_VIRTUAL)
        self.data: SoundSeq = ()

    def update(self, data: SoundSeq) -> None:
        """Set the data list used."""
        self.data = data
        self.SetItemCount(len(data))
        self.RefreshItems(0, len(data))

    @override
    def OnGetItemText(self, item: int, column: int) -> str:
        match self.data[item]:
            case Sound() as sndscript:
                return sndscript.name
            case choreo.Entry() as scene:
                return scene.filename
            case str() as raw:
                return raw
            case err:
                assert_never(err)


class SoundBrowser(SoundBrowserBase):
    def __init__(self) -> None:
        super().__init__()

        self.win = wx.Frame(MAIN_WINDOW)

        panel_main = wx.Panel(self.win, wx.ID_ANY)
        sizer_main = wx.BoxSizer(wx.VERTICAL)

        lbl_header = wx.StaticText(panel_main, wx.ID_ANY, "Sounds:")
        sizer_main.Add(lbl_header, 0, wx.LEFT | wx.RIGHT, 7)

        self.wid_soundlist = SoundsList(
            panel_main,
            style=wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_NO_HEADER,
        )
        self.wid_soundlist.AppendColumn('Sound', wx.LIST_FORMAT_LEFT)
        sizer_main.Add(self.wid_soundlist, 1, wx.BOTTOM | wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        self.wid_soundlist.Bind(wx.EVT_SIZE, self._evt_resize_soundlist)

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

        lbl_type = wx.StaticText(panel_main, wx.ID_ANY, "Sound Type: ")
        sizer_info.Add(lbl_type, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT, 0)

        self.wid_type = wx.Choice(panel_main)
        self.wid_type.Bind(wx.EVT_CHOICE, self._evt_set_type)
        sizer_info.Add(self.wid_type, 0, wx.ALL | wx.EXPAND, 0)

        lbl_filter = wx.StaticText(panel_main, wx.ID_ANY, "Filter: ")
        sizer_info.Add(lbl_filter, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALIGN_RIGHT, 0)

        self.wid_text_filter = wx.TextCtrl(panel_main, wx.ID_ANY)
        self.wid_text_filter.Bind(wx.EVT_TEXT, self._evt_filter_changed)
        sizer_info.Add(self.wid_text_filter, 0, wx.EXPAND, 0)

        self.wid_chk_autoplay = wx.CheckBox(panel_main, wx.ID_ANY, "Autoplay Sounds")
        sizer_main.Add(self.wid_chk_autoplay, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 0)

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

    def _ui_set_allowed(self, allowed: AllowedSounds) -> None:
        self.wid_type.Clear()
        i = 0
        for kind, token in SOUND_TYPES:
            if kind in allowed:
                self.wid_type.Append(str(token), kind)
                if self.mode.value is kind:
                    self.wid_type.SetSelection(i)
                i += 1

    def _evt_set_type(self, event: wx.CommandEvent) -> None:
        chosen = self.wid_type.GetClientData(self.wid_type.GetSelection())
        self.mode.value = chosen

    def _evt_filter_changed(self, event: wx.Event):
        self.filter.value = self.wid_text_filter.Value

    def _evt_resize_soundlist(self, event: wx.SizeEvent) -> None:
        """Update column size when the listbox changes."""
        self.wid_soundlist.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        event.Skip(True)  # Continue propagating.

    async def _ui_set_items(self, items: SoundSeq) -> None:
        self.wid_soundlist.update(items)
