"""TK implementation of the quote pack editor."""
from configparser import SectionProxy
from typing import assert_never, override

from tkinter import ttk
from tkinter.font import nametofont as tk_nametofont
import tkinter as tk

import functools

import srctools

from BEE2_config import ConfigFile
from app.voiceEditor import (
    CRITERIA_ICONS, IMG_MID, IMG_RESP, TRANS_RESPONSE_SHORT, TRANS_TRANSCRIPT_TITLE, TabBase,
    TabContents, TabTypes,
    Transcript, VoiceEditorBase,
)
from transtoken import TransToken

from . import TK_ROOT, tk_tools
from .img import TK_IMG
from .tooltip import add_tooltip
from .wid_transtoken import set_text, set_win_title


ACTOR_FONT = tk_nametofont('TkDefaultFont').copy()
ACTOR_FONT['weight'] = 'bold'

QUOTE_FONT = tk_nametofont('TkHeadingFont').copy()
QUOTE_FONT['weight'] = 'bold'


class Tab(TabBase):
    """TK implementation of a tab."""
    frame: ttk.Frame
    # Widgets for the contents of a tab, which all need to be destroyed next time.
    widgets: list[tk.Widget]

    def __init__(self, parent: 'VoiceEditor') -> None:
        """Create all the widgets for a tab."""
        super().__init__(parent)

        # This is just to hold the canvas and scrollbar
        self.frame = ttk.Frame(parent.wid_tabs)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # We need a canvas to make the list scrollable.
        self.canvas = canv = tk.Canvas(self.frame, highlightthickness=0)
        scroll = tk_tools.HidingScroll(
            self.frame,
            orient='vertical',
            command=canv.yview,
            )
        canv['yscrollcommand'] = scroll.set
        canv.grid(row=0, column=0, sticky='NSEW')
        scroll.grid(row=0, column=1, sticky='NS')

        # This holds the actual elements
        self.inner_frame = ttk.Frame(canv)
        self.inner_frame.columnconfigure(0, weight=1)
        canv.create_window(0, 0, window=self.inner_frame, anchor="nw")

        self.wid_title = ttk.Label(self.inner_frame, anchor='center', font='tkHeadingFont')
        self.wid_title.grid(row=0, column=0, sticky='EW')
        self.wid_desc = ttk.Label(self.inner_frame)
        self.wid_desc.grid(row=1, column=0, sticky='EW')

        ttk.Separator(self.inner_frame, orient=tk.HORIZONTAL).grid(
            row=2,
            column=0,
            sticky='EW',
        )
        canv.bind('<Configure>', self._configure_canv)

        self.widgets = []

    def _configure_canv(self, _: object) -> None:
        """Allow resizing the windows."""
        width = self.canvas.winfo_reqwidth()
        self.canvas['scrollregion'] = (
            0, 0,
            width, self.inner_frame.winfo_reqheight(),
        )
        self.inner_frame['width'] = width

    @override
    def _ui_reconfigure(
        self,
        kind: TabTypes,
        config: ConfigFile,
        title: TransToken,
        desc: TransToken,
        contents: TabContents,
    ) -> None:
        set_text(self.wid_title, title)
        set_text(self.wid_desc, desc)
        for wid in self.widgets:
            wid.destroy()
        self.widgets.clear()

        outer_row = 10
        for name, conf_id, lines in contents:
            heading_wid = set_text(ttk.Label(self.inner_frame, font=QUOTE_FONT), name)
            self.widgets.append(heading_wid)
            heading_wid.grid(row=outer_row, column=0, sticky='W')
            outer_row += 1

            for line in lines:
                line_frame = ttk.Frame(self.inner_frame)
                line_frame.grid(
                    row=outer_row,
                    column=0,
                    padx=(10, 0),
                    sticky='W',
                )
                outer_row += 1
                self.widgets.append(line_frame)
                x = 0
                for x, criteria in enumerate(line.criterion):
                    label = ttk.Label(line_frame, padding=0)
                    TK_IMG.apply(label, CRITERIA_ICONS[criteria])
                    label.grid(row=0, column=x)
                    add_tooltip(label, criteria.tooltip)

                x += 1  # Position after the badges
                line_frame.columnconfigure(x, weight=1)

                quote_var = tk.BooleanVar(value=config.get_bool(conf_id, line.id, True))
                check = ttk.Checkbutton(
                    line_frame,
                    variable=quote_var,
                    command=functools.partial(
                        self.check_toggled,
                        var=quote_var,
                        config_section=config[conf_id],
                        quote_id=line.id,
                    )
                )
                set_text(check, line.name)
                check.grid(row=0, column=x)
                check.bind("<Enter>", self.evt_show_line_trans(line))

    @staticmethod
    def check_toggled(var: tk.BooleanVar, config_section: SectionProxy, quote_id: str) -> None:
        """Update the config file to match the checkbox."""
        config_section[quote_id] = srctools.bool_as_int(var.get())


class VoiceEditor(VoiceEditorBase[Tab]):
    """TK implementation of the quote pack editor."""
    wid_trans: tk.Text

    def __init__(self) -> None:
        """Create the editor."""
        super().__init__()
        self.win = tk.Toplevel(TK_ROOT, name='voiceEditor')
        self.win.withdraw()

        self.win.columnconfigure(0, weight=1)
        self.win.transient(master=TK_ROOT)
        tk_tools.set_window_icon(self.win)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", self.close)

        pane = tk.PanedWindow(
            self.win,
            orient='vertical',
            sashpad=2,  # Padding above/below panes
            sashwidth=3,  # Width of border
            sashrelief='raised',  # Raise the border between panes
            )
        pane.grid(row=1, column=0, sticky='NSEW')
        self.win.rowconfigure(1, weight=1)

        self.wid_tabs = ttk.Notebook(pane)
        self.wid_tabs.enable_traversal()  # Add keyboard shortcuts
        pane.add(self.wid_tabs)
        pane.paneconfigure(self.wid_tabs, minsize=50)

        trans_frame = ttk.Frame(pane)
        trans_frame.rowconfigure(1, weight=1)
        trans_frame.columnconfigure(0, weight=1)

        set_text(ttk.Label(trans_frame), TRANS_TRANSCRIPT_TITLE).grid(row=0, column=0, sticky='W')

        trans_inner_frame = ttk.Frame(trans_frame, borderwidth=2, relief='sunken')
        trans_inner_frame.grid(row=1, column=0, sticky='NSEW')
        trans_inner_frame.rowconfigure(0, weight=1)
        trans_inner_frame.columnconfigure(0, weight=1)

        self.wid_trans = tk.Text(
            trans_inner_frame,
            width=10,
            height=4,
            wrap='word',
            relief='flat',
            state='disabled',
            font='TkDefaultFont',
            )
        trans_scroll = tk_tools.HidingScroll(
            trans_inner_frame,
            orient='vertical',
            command=self.wid_trans.yview,
            )
        self.wid_trans.tag_config('actor', font=ACTOR_FONT)
        self.wid_trans['yscrollcommand'] = trans_scroll.set
        trans_scroll.grid(row=0, column=1, sticky='NS')
        self.wid_trans.grid(row=0, column=0, sticky='NSEW')

        set_text(ttk.Button(self.win, command=self.save), TransToken.ui('Save')).grid(row=2, column=0)

        # Don't allow resizing the transcript box to be smaller than the
        # original size.
        trans_frame.update_idletasks()
        pane.paneconfigure(trans_frame, minsize=trans_frame.winfo_reqheight())

    def _ui_win_show(self, title: TransToken) -> None:
        # Re-add all tabs, reordering if required.
        first_tab: ttk.Frame | None = None
        for tab in self.tabs.placed:
            self.wid_tabs.add(tab.frame)
            if first_tab is None:
                first_tab = tab.frame
            # For the special tabs, we use a special image to make
            # sure they are well-distinguished from the other groups
            match tab.kind:
                case TabTypes.MID | TabTypes.MIDCHAMBER:
                    self.wid_tabs.insert(
                        tk.END,
                        tab.frame,
                        compound='image',
                        image=TK_IMG.sync_load(IMG_MID),
                    )
                case TabTypes.RESPONSE | TabTypes.RESP:
                    self.wid_tabs.insert(
                        tk.END,
                        tab.frame,
                        compound='right',
                        image=TK_IMG.sync_load(IMG_RESP),
                        text=str(TRANS_RESPONSE_SHORT),
                    )
                case TabTypes.NORM:
                    self.wid_tabs.insert(
                        tk.END,
                        tab.frame,
                        compound='text',
                        text=str(tab.title),
                    )
                case never:
                    assert_never(never)

        if first_tab is not None:
            self.wid_tabs.select(first_tab)

        set_win_title(self.win, title)
        self.win.grab_set()

        self.win.deiconify()
        tk_tools.center_win(self.win)  # Center inside the parent
        self.win.lift()

    def _ui_win_hide(self) -> None:
        self.win.grab_release()
        self.win.wm_withdraw()

    @override
    def _ui_show_transcript(self, transcript: Transcript) -> None:
        self.wid_trans['state'] = 'normal'
        self.wid_trans.delete(1.0, tk.END)
        for actor, line in transcript:
            self.wid_trans.insert('end', actor, ('actor',))
            self.wid_trans.insert('end', str(line) + '\n\n')
        # Remove the trailing newlines
        self.wid_trans.delete('end-2char', 'end')
        self.wid_trans['state'] = 'disabled'

    @override
    def _ui_tab_create(self, index: int) -> Tab:
        """Create a tab."""
        return Tab(self)

    @override
    def _ui_tab_hide(self, tab: Tab) -> None:
        """Hide a tab."""
        self.wid_tabs.hide(tab.frame)
        # Destroy the widgets specific to this iteration of tab.
        for wid in tab.widgets:
            wid.destroy()
        tab.widgets.clear()
