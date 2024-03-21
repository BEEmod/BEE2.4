"""Tk implementation of the corridor selector."""
import tkinter as tk
from typing import Final, Optional, Tuple
from typing_extensions import override

from tkinter import ttk

import config
import utils
from app import TK_ROOT, background_run, img, tkMarkdown, tk_tools
from app.corridor_selector import (
    HEIGHT, IMG_ARROW_LEFT, IMG_ARROW_RIGHT, IMG_CORR_BLANK, Icon,
    Selector, TRANS_HELP, WIDTH,
)
from app.richTextBox import tkRichText
from config.corridors import UIState
from corridor import Direction, GameMode, Orient
from transtoken import TransToken
from ui_tk.dragdrop import CanvasPositioner
from ui_tk.img import TKImages
import packages
from ui_tk.wid_transtoken import set_text, set_win_title


ICON_CHECK_PADDING: Final = 2 if utils.WIN else 0


class IconUI(Icon):
    """An icon for a corridor."""
    def __init__(self, selector: 'TkSelector', index: int) -> None:
        """Create the widgets."""
        self.label = ttk.Label(selector.canvas, anchor='center')
        self.var = tk.BooleanVar(selector.win)
        self.check = ttk.Checkbutton(
            self.label,
            name='check',
            variable=self.var,
            command=lambda: background_run(selector.evt_check_changed),
        )
        self.check.place(
            x=ICON_CHECK_PADDING,
            y=HEIGHT - ICON_CHECK_PADDING,
            anchor='sw',
        )

        self.label.bind('<Enter>', lambda e: selector.evt_hover_enter(index))
        self.label.bind('<Leave>', lambda e: selector.evt_hover_exit())
        tk_tools.bind_leftclick(self.label, lambda e: selector.evt_selected(index))

    @property
    @override
    def selected(self) -> bool:
        """If the icon is currently selected."""
        return self.var.get()

    @selected.setter
    def selected(self, value: bool) -> None:
        self.var.set(value)

    @override
    def set_readonly(self, enabled: bool) -> None:
        """Set the checkbox to be readonly."""
        self.check.state(('disabled', ) if enabled else ('!disabled', ))

    @override
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


class TkSelector(Selector[IconUI]):
    """Corridor selection window."""
    win: tk.Toplevel

    # Widgets to display info about the corridor on the right side.
    wid_image: ttk.Label
    wid_title: ttk.Label
    wid_authors: ttk.Label
    wid_desc: tkRichText

    def __init__(self, packset: packages.PackagesSet, tk_img: TKImages) -> None:
        super().__init__()
        self.tk_img = tk_img
        self.sel_count = 0
        self.sel_handle_moving = False

        self.win = tk.Toplevel(TK_ROOT, name='corridor')
        self.win.withdraw()
        self.win.wm_protocol("WM_DELETE_WINDOW", self.hide)
        set_win_title(self.win, TransToken.ui('BEEmod - Select Corridor'))

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

        self.wid_desc = tkRichText(frm_right, name='desc')
        desc_scroll = tk_tools.HidingScroll(
            frm_right,
            orient='vertical',
            name='desc_scroll',
            command=self.wid_desc.yview,
        )
        self.wid_desc['yscrollcommand'] = desc_scroll.set
        self.wid_desc.grid(row=3, column=0, sticky='nsew')
        desc_scroll.grid(row=3, column=1, sticky='ns')
        frm_right.rowconfigure(3, weight=1)

        frm_lower_btn = ttk.Frame(frm_right)
        frm_lower_btn.grid(row=4, column=0, columnspan=2)

        self.btn_just_this = ttk.Button(frm_lower_btn, name='just_this', command=self.evt_select_one)
        set_text(self.btn_just_this, TransToken.ui('Use Only This'))
        self.btn_just_this.grid(row=0, column=0)

        set_text(
            ttk.Button(frm_lower_btn, name='closer', command=self.hide),
            TransToken.ui('Close'),
        ).grid(row=0, column=1)

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

        mode_switch = self.evt_mode_switch
        self.btn_mode.on_changed.register(mode_switch)
        self.btn_direction.on_changed.register(mode_switch)
        self.btn_orient.on_changed.register(mode_switch)

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
        set_text(self.help_lbl, TRANS_HELP)
        self.help_lbl_win = self.canvas.create_window(0, 0, anchor='nw', window=self.help_lbl)

        tk_tools.add_mousewheel(self.canvas, self.win)
        self.load_corridors(packset)

    @override
    async def ui_win_reflow(self) -> None:
        """Called to reposition the corridors."""
        self.canvas.delete('icons')

        pos = CanvasPositioner(place_icon, self.canvas, WIDTH, HEIGHT)

        self.canvas.itemconfigure(self.help_lbl_win, width=pos.width)
        self.help_lbl['wraplength'] = pos.width

        await tk_tools.wait_eventloop()
        (x1, y1, x2, y2) = self.canvas.bbox(self.help_lbl_win)
        pos.yoff += y2 - y1

        pos.place_slots(self.visible_icons(), 'icons')
        pos.resize_canvas()

    @override
    def ui_win_hide(self) -> None:
        """Hide the window."""
        self.win.wm_withdraw()

    @override
    def ui_win_show(self) -> None:
        """Show the window."""
        self.win.deiconify()
        tk_tools.center_win(self.win, TK_ROOT)

    @override
    def ui_win_getsize(self) -> Tuple[int, int]:
        """Fetch the current dimensions, for saving."""
        return self.win.winfo_width(), self.win.winfo_height()

    @override
    def ui_get_buttons(self) -> Tuple[GameMode, Direction, Orient]:
        """Get the current button state."""
        return self.btn_mode.current, self.btn_direction.current, self.btn_orient.current

    @override
    def ui_icon_create(self) -> None:
        """Create a new icon widget, and append it to the list."""
        self.icons.append(IconUI(self, len(self.icons)))

    @override
    def ui_icon_set_img(self, icon: IconUI, handle: Optional[img.Handle]) -> None:
        """Set the image used."""
        self.tk_img.apply(icon.label, handle)

    @override
    def ui_desc_display(
        self,
        title: TransToken,
        authors: TransToken,
        desc: tkMarkdown.MarkdownData,
        enable_just_this: bool,
    ) -> None:
        """Display information for a corridor."""
        set_text(self.wid_title, title)
        set_text(self.wid_authors, authors)
        self.wid_desc.set_text(desc)
        self.btn_just_this.state(('!disabled', ) if enable_just_this else ('disabled', ))

    @override
    def ui_desc_set_img_state(self, handle: Optional[img.Handle], left: bool, right: bool) -> None:
        """Set the widget state for the large preview image in the description sidebar."""
        self.tk_img.apply(self.wid_image, handle)
        self.wid_image_left.state(('!disabled', ) if left else ('disabled', ))
        self.wid_image_right.state(('!disabled', ) if right else ('disabled', ))
