"""TK implementation of the quote pack editor."""
from tkinter import ttk
from tkinter.font import nametofont as tk_nametofont
import tkinter as tk

from app.voiceEditor import TRANS_TRANSCRIPT_TITLE, VoiceEditorBase
from transtoken import TransToken
from ui_tk import TK_ROOT, tk_tools
from ui_tk.wid_transtoken import set_text

ACTOR_FONT = tk_nametofont('TkDefaultFont').copy()
ACTOR_FONT['weight'] = 'bold'


class VoiceEditor(VoiceEditorBase):
    """TK implementation of the quote pack editor."""
    def __init__(self) -> None:
        """Create the editor."""
        super().__init__()

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
