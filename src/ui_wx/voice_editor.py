from collections.abc import Callable
from configparser import SectionProxy

import srctools
import wx.html

from BEE2_config import ConfigFile
from app.voiceEditor import (
    CRITERIA_ICONS, TRANS_TRANSCRIPT_TITLE, TabBase, TabContents, TabTypes, Transcript,
    VoiceEditorBase,
)
from transtoken import TransToken
from ui_wx.img import WX_IMG
from ui_wx.wid_transtoken import set_text, set_tooltip


FONT_TAB_TITLE = wx.Font(20, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
FONT_QUOTE = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)


class Tab(TabBase):
    """WX implementation of tabs."""
    def __init__(self, parent: 'VoiceEditor') -> None:
        super().__init__(parent)
        self.panel = wx.Panel(parent.wid_notebook)
        # Permanent sizer.
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.wid_title = wx.StaticText(self.panel, style=wx.ALIGN_CENTRE_HORIZONTAL)
        self.wid_title.SetFont(FONT_TAB_TITLE)
        sizer.Add(self.wid_title, wx.SizerFlags(0).Expand())
        self.wid_desc = wx.StaticText(self.panel)
        sizer.Add(self.wid_desc, wx.SizerFlags(0).Expand())
        sizer.Add(wx.StaticLine(self.panel))

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.sizer, wx.SizerFlags(1).Expand())

    def _ui_reconfigure(
        self,
        kind: TabTypes,
        config: ConfigFile,
        title: TransToken, desc: TransToken,
        contents: TabContents,
    ) -> None:
        set_text(self.wid_title, title)
        set_text(self.wid_desc, desc)

        self.sizer.Clear(delete_windows=True)

        outer_row = 10
        for name, conf_id, lines in contents:
            heading_wid = set_text(wx.StaticText(self.panel), name)
            heading_wid.SetFont(FONT_QUOTE)
            self.sizer.Add(heading_wid, wx.SizerFlags(0).Border(wx.TOP, 4))

            for line in lines:
                line_sizer = wx.BoxSizer(wx.HORIZONTAL)
                line_sizer.AddSpacer(4)  # Indent the line.
                for criteria in line.criterion:
                    icon = wx.StaticBitmap(self.panel)
                    WX_IMG.apply(icon, CRITERIA_ICONS[criteria])
                    set_tooltip(icon, criteria.tooltip)
                    line_sizer.Add(icon)

                check = wx.CheckBox(self.panel)
                check.SetValue(config.get_bool(conf_id, line.id, True))
                set_text(check, line.name)
                check.Bind(wx.EVT_CHECKBOX, self.evt_check_toggled(
                    check,
                    config[conf_id],
                    line.id,
                ))
                check.Bind(wx.EVT_ENTER_WINDOW, self.evt_show_line_trans(line))

    @staticmethod
    def evt_check_toggled(
        check: wx.CheckBox,
        config_section: SectionProxy, quote_id: str,
    ) -> Callable[[wx.CommandEvent], None]:
        """Handle toggling the checkbox."""
        def func(e: wx.CommandEvent) -> None:
            config_section[quote_id] = srctools.bool_as_int(check.IsChecked())
        return func


class VoiceEditor(VoiceEditorBase[Tab]):
    """WX implementation of the voice editor."""
    def __init__(self, parent: wx.Frame) -> None:
        super().__init__()
        self.win = wx.Frame(parent)
        self.win.Bind(wx.EVT_CLOSE, self._evt_close)

        self.wid_splitter = wx.SplitterWindow(self.win)
        self.wid_splitter.SetMinimumPaneSize(80)
        self.wid_splitter.SetSashGravity(0.0)

        self.wid_notebook = wx.Notebook(self.wid_splitter)

        pan_trans = wx.Panel(self.wid_splitter)
        sizer_trans = wx.BoxSizer(wx.VERTICAL)
        pan_trans.SetSizer(sizer_trans)

        lbl_trans = set_text(wx.StaticText(pan_trans), TRANS_TRANSCRIPT_TITLE)
        sizer_trans.Add(lbl_trans, wx.SizerFlags(0).DoubleBorder(wx.ALL))
        self.wid_trans = wx.html.HtmlWindow(pan_trans, flags=wx.BORDER_SUNKEN)
        sizer_trans.Add(self.wid_trans, wx.SizerFlags(1).Expand())

        self.wid_splitter.SplitVertically(self.wid_notebook, pan_trans)
        self.win.Layout()

    def _ui_win_show(self, title: TransToken) -> None:
        pass

    def _ui_win_hide(self) -> None:
        pass

    def _ui_show_transcript(self, transcript: Transcript) -> None:
        pass

    def _ui_tab_create(self, index: int) -> Tab:
        pass

    def _ui_tab_hide(self, tab: Tab) -> None:
        pass
