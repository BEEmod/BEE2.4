"""Tk-specific implementation of the signage UI."""
from typing_extensions import override

from tkinter import ttk
import tkinter as tk

from app import img
from packages import PakRef, Signage
from transtoken import TransToken
from . import TK_ROOT, tk_tools
from .dragdrop import DragDrop
from .img import TKImages
from .wid_transtoken import set_text, set_win_title

from app.signage_ui import IMG_BLANK, SignageUIBase, TRANS_TITLE, TRANS_SELECTED


class SignageUI(SignageUIBase[tk.Misc]):
    """Tk-specific implementation of the signage UI."""
    __slots__ = ['drag_man']  # Use a slot to override the superclass' property.
    drag_man: DragDrop[PakRef[Signage]]

    def __init__(self, tk_img: TKImages) -> None:
        """Creat the UI."""
        self.window = window = tk.Toplevel(TK_ROOT, name='signageChooser')
        window.withdraw()
        self.drag_man = DragDrop(window, info_cb=self._get_drag_info)
        super().__init__()

        window.resizable(True, True)
        window.protocol("WM_DELETE_WINDOW", self._evt_on_closed)
        set_win_title(window, TRANS_TITLE)

        self.tk_img = tk_img

        frame_selected = ttk.Labelframe(
            window, relief='raised', labelanchor='n',
            name='frame_selected',
        )
        set_text(frame_selected, TRANS_SELECTED)

        canv_all = tk.Canvas(window, name='canv_all')

        scroll = tk_tools.HidingScroll(
            window, orient='vertical',
            command=canv_all.yview,
            name='scrollbar',
        )
        canv_all['yscrollcommand'] = scroll.set

        self.wid_name_label = ttk.Label(window, text='', justify='center', name='lbl_name')
        frame_preview = ttk.Frame(window, relief='raised', borderwidth=4, name='frame_preview')

        frame_selected.grid(row=0, column=0, sticky='nsew')
        ttk.Separator(orient='horizontal', name='sep').grid(row=1, column=0, sticky='ew')
        self.wid_name_label.grid(row=2, column=0)
        frame_preview.grid(row=3, column=0, pady=4)
        canv_all.grid(row=0, column=1, rowspan=4, sticky='nsew')
        scroll.grid(row=0, column=2, rowspan=4, sticky='ns')
        window.columnconfigure(1, weight=1)
        window.rowconfigure(3, weight=1)

        tk_tools.add_mousewheel(canv_all, canv_all, window)

        self.wid_preview_left = ttk.Label(frame_preview, anchor='e', name='left')
        self.wid_preview_right = ttk.Label(frame_preview, anchor='w', name='right')
        tk_img.apply(self.wid_preview_left, IMG_BLANK)
        tk_img.apply(self.wid_preview_right, IMG_BLANK)
        self.wid_preview_left.grid(row=0, column=0)
        self.wid_preview_right.grid(row=0, column=1)

        parent_sel: tk.Misc = frame_selected
        parent_all: tk.Misc = canv_all
        for row, col, slot in self._create_slots(parent_sel, parent_all):
            self.drag_man.slot_grid(slot, row=row, column=col, padx=1, pady=1)

        self.drag_man.flow_slots(canv_all, self.drag_man.sources())
        canv_all.bind('<Configure>', lambda e: self.drag_man.flow_slots(canv_all, self.drag_man.sources()))

    @override
    def ui_win_show(self) -> None:
        """Show the window."""
        self.window.deiconify()
        tk_tools.center_win(self.window, TK_ROOT)

    @override
    def ui_win_hide(self) -> None:
        """Hide the window."""
        self.window.withdraw()

    @override
    def ui_set_preview_name(self, name: TransToken) -> None:
        """Set the text for the preview."""
        set_text(self.wid_name_label, name)

    @override
    def ui_set_preview_img(self, left: img.Handle, right: img.Handle) -> None:
        """Set the images for the preview."""
        self.tk_img.apply(self.wid_preview_left, left)
        self.tk_img.apply(self.wid_preview_right, right)
