"""Tk implementation of the corridor selector."""
import tkinter as tk
from typing import Final, Optional

from tkinter import ttk

import config
import utils
from app import TK_ROOT, img, localisation, tk_tools
from app.corridor_selector import (
    HEIGHT, IMG_ARROW_LEFT, IMG_ARROW_RIGHT, IMG_CORR_BLANK, Icon,
    Selector, WIDTH,
)
from app.richTextBox import tkRichText
from config.corridors import UIState
from corridor import Direction, GameMode, Orient
from transtoken import TransToken
from ui_tk.dragdrop import CanvasPositioner
from ui_tk.img import TKImages
import packages


ICON_CHECK_PADDING: Final = 2 if utils.WIN else 0


class IconUI(Icon):
    """An icon for a corridor."""
    def __init__(self, parent: tk.Canvas) -> None:
        """Create the widgets."""
        self.label = ttk.Label(parent, anchor='center')
        self.var = tk.BooleanVar(parent)
        self.check = ttk.Checkbutton(self.label, variable=self.var)
        self.check.place(
            x=-ICON_CHECK_PADDING,
            y=WIDTH - ICON_CHECK_PADDING,
            anchor='sw',
        )

    @property
    def selected(self) -> bool:
        """If the icon is currently selected."""
        return self.var.get()

    @selected.setter
    def selected(self, value: bool) -> None:
        self.var.set(value)

    def set_highlight(self, enabled: bool) -> None:
        """Change the highlight state."""
        self.label['background'] = tk_tools.LABEL_HIGHLIGHT_BG if enabled else ''


def place_icon(canv: tk.Canvas, icon: IconUI, x: int, y: int, tag: str) -> None:
    """Position an icon on the canvas."""
    canv.create_window(
        x, y,
        width=WIDTH,
        height=HEIGHT,
        anchor='nw',
        window=icon.label,
        tags=(tag,),
    )


class TkSelector(Selector):
    """Corridor selection window."""
    win: tk.Toplevel

    # Widgets to display info about the corridor on the right side.
    wid_image: ttk.Label
    wid_title: ttk.Label
    wid_authors: ttk.Label
    wid_desc: tkRichText

    def __init__(self, packset: packages.PackagesSet, tk_img: TKImages) -> None:
        super().__init__(packset, tk_img)
        self.tk_img = tk_img
        self.sel_count = 0
        self.sel_handle_moving = False

        self.win = tk.Toplevel(TK_ROOT, name='corridor')
        self.win.withdraw()
        self.win.wm_protocol("WM_DELETE_WINDOW", self.hide)
        localisation.set_win_title(self.win, TransToken.ui('BEEmod - Select Corridor'))

        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)

        frm_left = ttk.Frame(self.win, name='frm_left')
        frm_left.grid(row=0, column=0, sticky='nsew')

        frm_right = ttk.Frame(self.win, name='frm_right')
        frm_right.columnconfigure(0, weight=1)
        frm_right.grid(row=0, column=1, sticky='ns')
        frm_img = ttk.Frame(frm_right, relief='raised', width=2)
        frm_img.grid(row=0, column=0, sticky='ew')

        sel_img = self._sel_img
        self.wid_image_left = ttk.Button(frm_img, name='imgLeft', command=lambda: sel_img(-1))
        self.wid_image = ttk.Label(frm_img, name='img')
        self.wid_image_right = ttk.Button(frm_img, name='imgRight', command=lambda: sel_img(1))

        self.wid_image_left.grid(row=0, column=0, sticky='ns')
        self.wid_image.grid(row=0, column=1, sticky='nsew')
        self.wid_image_right.grid(row=0, column=2, sticky='ns')

        tk_tools.bind_mousewheel(self.wid_image, sel_img)

        tk_img.apply(self.wid_image_left, IMG_ARROW_LEFT)
        tk_img.apply(self.wid_image, IMG_CORR_BLANK)
        tk_img.apply(self.wid_image_right, IMG_ARROW_RIGHT)
        self.tk_img = tk_img

        self.wid_title = ttk.Label(
            frm_right,
            name='title',
            justify='center',
            anchor='center',
            font=("Helvetica", 12, "bold"),
            text='',
        )
        self.wid_title.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.wid_authors = ttk.Label(
            frm_right,
            name='authors',
            justify='center',
            anchor='center',
            text='',
        )
        self.wid_authors.grid(row=2, column=0, columnspan=2, sticky='ew')

        self.wid_desc = tkRichText(frm_right)
        desc_scroll = tk_tools.HidingScroll(frm_right, orient='vertical',
                                            command=self.wid_desc.yview)
        self.wid_desc['yscrollcommand'] = desc_scroll.set
        self.wid_desc.grid(row=3, column=0, sticky='nsew')
        desc_scroll.grid(row=3, column=1, sticky='ns')
        frm_right.rowconfigure(3, weight=1)

        localisation.set_text(
            ttk.Button(frm_right, name='closer', command=self.hide),
            TransToken.ui('Close'),
        ).grid(row=4, column=0, columnspan=2)

        conf = config.APP.get_cur_conf(UIState, default=UIState())
        if conf.width > 0 and conf.height > 0:
            self.win.geometry(f'{conf.width}x{conf.height}')

        button_frm = ttk.Frame(frm_left)
        button_frm.grid(row=0, column=0, columnspan=3)
        self.btn_mode = tk_tools.EnumButton(
            button_frm, conf.last_mode,
            (GameMode.SP, TransToken.ui('SP')),
            (GameMode.COOP, TransToken.ui('Coop')),
        )
        self.btn_direction = tk_tools.EnumButton(
            button_frm, conf.last_direction,
            (Direction.ENTRY, TransToken.ui('Entry')),
            (Direction.EXIT, TransToken.ui('Exit')),
        )
        self.btn_orient = tk_tools.EnumButton(
            button_frm, conf.last_orient,
            (Orient.FLAT, TransToken.ui('Flat')),
            (Orient.UP, TransToken.ui('Upward')),
            (Orient.DN, TransToken.ui('Downward')),
        )
        self.btn_mode.frame.grid(row=0, column=0, padx=8)
        self.btn_direction.frame.grid(row=0, column=1, padx=8)
        self.btn_orient.frame.grid(row=0, column=2, padx=8)

        refresh = self.refresh
        self.btn_mode.on_changed.register(refresh)
        self.btn_direction.on_changed.register(refresh)
        self.btn_orient.on_changed.register(refresh)

        canv_frame = ttk.Frame(frm_left, name='canv_frame', relief="sunken")
        canv_frame.grid(row=1, column=0, columnspan=3, sticky='nsew', ipadx=8, ipady=8)
        canv_frame.rowconfigure(0, weight=1)
        canv_frame.columnconfigure(0, weight=1)
        frm_left.columnconfigure(0, weight=1)
        frm_left.rowconfigure(1, weight=1)

        self.canvas = tk.Canvas(canv_frame)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(canv_frame, orient='vertical', command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.canvas['yscrollcommand'] = scrollbar.set

        # Avoid making self a cell var.
        self.canvas.bind('<Configure>', tk_tools.make_handler(self.evt_resized))

        self.help_lbl = ttk.Label(self.canvas)
        localisation.set_text(self.help_lbl, TransToken.ui(
            "Drag corridors to the 'selected' and 'unused' areas to specify which are used. "
            "Ingame, a random corridor from the 'selected' group will be picked for each map."
        ))
        self.help_lbl_win = self.canvas.create_window(0, 0, anchor='nw', window=self.help_lbl)

        tk_tools.add_mousewheel(self.canvas, self.win)
        self.load_corridors(packset)

    async def reflow(self) -> None:
        """Called to reposition the corridors."""
        self.canvas.delete('slots')

        pos = CanvasPositioner(place_icon, self.canvas, WIDTH, HEIGHT)

        self.canvas.itemconfigure(self.help_lbl_win, width=pos.width)
        self.help_lbl['wraplength'] = pos.width

        await tk_tools.wait_eventloop()
        (x1, y1, x2, y2) = self.canvas.bbox(self.help_lbl_win)
        pos.yoff += y2 - y1

        pos.place_slots(self.icons, 'slots')
        pos.resize_canvas()

    def ui_icon_set_img(self, icon: IconUI, handle: Optional[img.Handle]) -> None:
        """Set the image used."""
        self.tk_img.apply(icon.label, handle)
