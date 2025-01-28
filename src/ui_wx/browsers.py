"""Windows to allow browsing for sounds and other files."""
from typing import assert_never, override

from collections.abc import Sequence

from wx.dataview import DataViewCtrl, DataViewItem, DataViewModel
import wx.dataview
from srctools import choreo
from srctools.sndscript import Sound

from app.browsers import SoundBrowserBase
from app.gameMan import Game
from packages import PackagesSet
from ui_wx import MAIN_WINDOW

type SoundSeq = Sequence[Sound | str | choreo.Entry]


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
        sizer_checks.Add(self.wid_chk_raw, 0, wx.ALL, 4)
        self.wid_chk_raw.Bind(wx.EVT_CHECKBOX, self._evt_change_raw)

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

    def _evt_change_raw(self, event: wx.Event) -> None:
        self.wid_soundlist.update(
            self._scenes if self.wid_chk_raw.IsChecked() else self._soundscripts
        )

    def _evt_resize_soundlist(self, event: wx.SizeEvent) -> None:
        """Update column size when the listbox changes."""
        self.wid_soundlist.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        event.Skip(True)  # Continue propagating.

    async def _reload(self, packset: PackagesSet, game: Game) -> None:
        await super()._reload(packset, game)
        # Indicate both have been completely changed.
        self.wid_soundlist.update(self._scenes if self.wid_chk_raw.IsChecked() else self._soundscripts)
