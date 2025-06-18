"""Windows to allow browsing for sounds and other files."""
from typing import override

from tkinter import ttk
import tkinter as tk

from app.browsers import (
    SOUND_TYPES, TRANS_SND_AUTOPLAY, TRANS_SND_FILTER, TRANS_SND_HEADING,
    TRANS_SND_NAME, TRANS_SND_TYPE,
    AllowedSounds, SoundBrowserBase, SoundSeq, TRANS_SND_FIlE, AnySound, TRANS_SND_PREVIEW,
)
from transtoken import TransToken
from ui_tk import TK_ROOT, tk_tools
from ui_tk.wid_transtoken import set_text, set_win_title


class SoundBrowser(SoundBrowserBase):
    """Tk-specific sound browser implementation."""

    def __init__(self) -> None:
        super().__init__()
        self.win = tk.Toplevel(TK_ROOT)
        self.win.withdraw()
        outer = ttk.Frame(self.win)
        outer.grid(sticky='NSEW', padx=4, pady=4)
        self.win.grid_columnconfigure(0, weight=1)
        self.win.grid_rowconfigure(0, weight=1)

        set_text(ttk.Label(outer), TRANS_SND_HEADING).grid(row=0, column=0)

        listbox_holder = ttk.Frame(outer, relief='sunken')
        listbox_holder.grid(row=1, column=0, sticky='NSEW')
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)
        self._item_data: SoundSeq = ()
        self.wid_items = tk.Listbox(
            listbox_holder,
            exportselection=False,
        )
        self.scrollbar = ttk.Scrollbar(listbox_holder, command=self.wid_items.yview)
        self.wid_items['yscrollcommand'] = self.scrollbar.set
        self.wid_items.bind('<<ListboxSelect>>', self._evt_select)
        listbox_holder.grid_rowconfigure(0, weight=1)
        listbox_holder.grid_columnconfigure(0, weight=1)
        self.wid_items.grid(row=0, column=0, sticky='NSEW')
        self.scrollbar.grid(row=0, column=1, sticky='NS')

        props_frame = ttk.Frame(outer)
        props_frame.grid(row=2, column=0, pady=(4, 1), sticky='EW')
        props_frame.grid_columnconfigure(1, weight=1)

        set_text(ttk.Label(props_frame), TRANS_SND_NAME).grid(row=0, column=0)
        self.wid_name_var = tk.StringVar(self.win)
        self.wid_name = ttk.Entry(props_frame, textvariable=self.wid_name_var)
        self.wid_name.grid(row=0, column=1, sticky='EW')

        set_text(ttk.Label(props_frame), TRANS_SND_FIlE).grid(row=1, column=0)
        self.wid_file = ttk.Label(
            props_frame,
            background='white',
            foreground='black',
            relief='solid',
        )
        self.wid_file.grid(row=1, column=1, sticky='EW')

        set_text(ttk.Label(props_frame), TRANS_SND_TYPE).grid(row=2, column=0)
        self.wid_type = tk_tools.ComboBoxMap(props_frame, 'snd_type', self.mode, ())
        self.wid_type.grid(row=2, column=1, sticky='EW')

        set_text(ttk.Label(props_frame), TRANS_SND_FILTER).grid(row=3, column=0)
        self.wid_filter_var = tk.StringVar(self.win)
        self.wid_filter = ttk.Entry(props_frame, textvariable=self.wid_filter_var)
        self.wid_filter_var.trace_add("write", self._evt_filter_changed)
        self.wid_filter.grid(row=3, column=1, sticky='EW')

        self.wid_autoplay_var = tk.BooleanVar(self.win, self.autoplay_enabled.value)
        self.wid_autoplay = ttk.Checkbutton(outer, variable=self.wid_autoplay_var)
        set_text(self.wid_autoplay, TRANS_SND_AUTOPLAY).grid(row=3, column=0)

        btn_frame = ttk.Frame(outer)
        btn_frame.grid(row=4, column=0)
        btn_ok = ttk.Button(btn_frame, command=self._evt_ok)
        set_text(btn_ok, TransToken.ui('Ok')).grid(row=0, column=0)
        btn_cancel = ttk.Button(btn_frame, command=self._evt_cancel)
        set_text(btn_cancel, TransToken.ui('Cancel')).grid(row=0, column=1)
        btn_preview = ttk.Button(btn_frame, command=self._evt_preview)
        set_text(btn_preview, TRANS_SND_PREVIEW).grid(row=0, column=2)

    def _evt_filter_changed(self, *_: str) -> None:
        self.filter.value = self.wid_filter.get()

    def _evt_autoplay_changed(self) -> None:
        self.autoplay_enabled.value = self.wid_autoplay_var.get()

    @override
    def _ui_set_allowed(self, allowed: AllowedSounds, title: TransToken) -> None:
        self.wid_type.update([
            (kind, token)
            for kind, token in SOUND_TYPES
            if kind in allowed
        ])
        set_win_title(self.win, title)

    @override
    async def _ui_set_items(self, items: SoundSeq) -> None:
        self.wid_items.delete(0, 'end')
        for sound in items:
            self.wid_items.insert('end', self.path_for(sound))
        self._item_data = items

    @override
    def _ui_get_selected(self) -> AnySound | None:
        try:
            [sel_ind] = self.wid_items.curselection()
            return self._item_data[sel_ind]
        # Value if unpack fails (no selection), index if out of range.
        except (ValueError, IndexError):
            return None

    @override
    def _ui_get_name(self) -> str:
        return self.wid_name.get()

    @override
    def _ui_set_props(self, name: str, file: str) -> None:
        self.wid_name_var.set(name)
        self.wid_file['text'] = file

    @override
    def _ui_show_window(self) -> None:
        self.win.deiconify()
        tk_tools.center_onscreen(self.win)

    @override
    def _ui_hide_window(self) -> None:
        self.win.withdraw()
