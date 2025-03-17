"""WX implementation of the voice editor."""
from typing import assert_never

from collections.abc import Callable
from configparser import SectionProxy
import html
import io

import srctools
import wx.html

from BEE2_config import ConfigFile
from app.voiceEditor import (
    CRITERIA_ICONS, TRANS_RESPONSE_SHORT, TRANS_TRANSCRIPT_TITLE,
    TabBase, TabContents, TabTypes, Transcript, VoiceEditorBase,
)
from transtoken import TransToken
from ui_wx import MAIN_WINDOW
from ui_wx.img import WX_IMG
from ui_wx.wid_transtoken import set_text, set_tooltip, set_win_title


FONT_TAB_TITLE = wx.Font(20, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
FONT_QUOTE = wx.Font(16, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)


class Tab(TabBase):
    """WX implementation of tabs."""
    def __init__(self, parent: 'VoiceEditor') -> None:
        super().__init__(parent)
        self.panel = wx.Panel(parent.wid_notebook)
        # Permanent sizer.
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel.SetSizer(sizer)
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

        print('Child', self.sizer.GetChildren())
        self.sizer.Clear(delete_windows=True)

        for name, conf_id, lines in contents:
            heading_wid = set_text(wx.StaticText(self.panel), name)
            heading_wid.SetFont(FONT_QUOTE)
            self.sizer.Add(heading_wid, wx.SizerFlags(0).Border(wx.TOP, 4))

            for line in lines:
                line_sizer = wx.BoxSizer(wx.HORIZONTAL)
                self.sizer.Add(line_sizer)
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
                line_sizer.Add(check)
        self.panel.Layout()

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
    def __init__(self) -> None:
        super().__init__()
        self.win = wx.Frame(MAIN_WINDOW)
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
        self.wid_trans = wx.html.HtmlWindow(
            pan_trans,
            style=wx.BORDER_SUNKEN | wx.html.HW_SCROLLBAR_AUTO,
        )
        sizer_trans.Add(self.wid_trans, wx.SizerFlags(1).Expand())

        self.wid_splitter.SplitHorizontally(self.wid_notebook, pan_trans)
        self.win.Layout()

    def _ui_win_show(self, title: TransToken) -> None:
        # Re-add all tabs, reordering if required.
        first_tab = True
        for tab in self.tabs.placed:
            # For the special tabs, we use a special image to make
            # sure they are well-distinguished from the other groups.

            # TODO: Needs wx.ImageList.
            match tab.kind:
                case TabTypes.MIDCHAMBER:
                    self.wid_notebook.AddPage(
                        tab.panel,
                        'TMP MID',
                        # compound='image',
                        # image=TK_IMG.sync_load(IMG_MID),
                        select=first_tab,
                    )
                case TabTypes.RESPONSE:
                    self.wid_notebook.AddPage(
                        tab.panel,
                        # compound='right',
                        # image=TK_IMG.sync_load(IMG_RESP),
                        text=str(TRANS_RESPONSE_SHORT),
                        select=first_tab,
                    )
                case TabTypes.NORMAL:
                    self.wid_notebook.AddPage(
                        tab.panel,
                        text=str(tab.title),
                        select=first_tab,
                    )
                case never:
                    assert_never(never)
            first_tab = False

        set_win_title(self.win, title)
        self.win.Show()
        self.win.Raise()
        self.win.CenterOnScreen()

    def _ui_win_hide(self) -> None:
        self.win.Hide()

    def _ui_show_transcript(self, transcript: Transcript) -> None:
        buf = io.StringIO()
        for actor, line in transcript:
            buf.write(f'<strong>{html.escape(actor)}</strong>{line.translate_html()}<br />\n')
        print('Code: ' + repr(buf.getvalue()))
        self.wid_trans.SetPage(buf.getvalue())

    def _ui_tab_create(self, index: int) -> Tab:
        return Tab(self)

    def _ui_tab_hide(self, tab: Tab) -> None:
        self.wid_notebook.RemovePage(tab.panel)
        tab.sizer.Clear(delete_windows=True)
