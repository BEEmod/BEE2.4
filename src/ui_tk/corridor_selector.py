"""Tk implementation of the corridor selector."""
from __future__ import annotations
from typing import Final
from typing_extensions import override

from tkinter import ttk
import tkinter as tk

import trio

from app import WidgetCache, img
from app.corridor_selector import (
    HEIGHT, IMG_ARROW_LEFT, IMG_ARROW_RIGHT, IMG_CORR_BLANK, OPTS_ATTACH,
    OPTS_DIR, OPTS_MODE, TRANS_GROUP_ATTACH, TRANS_GROUP_DIR, TRANS_GROUP_MODE,
    TRANS_HELP, TRANS_NO_OPTIONS, TRANS_ONLY_THIS, TRANS_RAND_OPTION,
    TRANS_TITLE, WIDTH, Icon, OptionRow, Selector,
)
from app.mdown import MarkdownData
from config.corridors import UIState
from corridor import Option
from transtoken import TransToken
import config
import packages
import utils

from . import TK_ROOT, tk_tools, tooltip
from .dragdrop import CanvasPositioner
from .img import TKImages
from .rich_textbox import RichText
from .wid_transtoken import set_text, set_win_title


ICON_CHECK_PADDING: Final = 2 if utils.WIN else 0


class IconUI(Icon):
    """An icon for a corridor."""
    def __init__(self, selector: TkSelector) -> None:
        """Create the widgets."""
        self.label = ttk.Label(selector.canvas, anchor='center')
        self.var = tk.BooleanVar(selector.win)
        self.selector = selector
        self.check = ttk.Checkbutton(
            self.label,
            name='check',
            variable=self.var,
            command=selector.changed_cmd,
        )
        self.check.place(
            x=ICON_CHECK_PADDING,
            y=HEIGHT - ICON_CHECK_PADDING,
            anchor='sw',
        )

        self.label.bind('<Enter>', lambda e: self.selector.evt_hover_enter(self))
        self.label.bind('<Leave>', lambda e: self.selector.evt_hover_exit())
        tk_tools.bind_leftclick(self.label, lambda e: self.selector.evt_selected(self))

    @override
    def set_image(self, handle: img.Handle | None) -> None:
        """Set the image used."""
        self.selector.tk_img.apply(self.label, handle)

    @property
    @override
    def selected(self) -> bool:
        """If the icon is currently selected."""
        return self.var.get()

    @selected.setter
    @override
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


class OptionRowUI(OptionRow):
    """Implementation of the option row."""
    def __init__(self, parent: ttk.Frame) -> None:
        super().__init__()
        self.label = ttk.Label(parent)
        self.combo = ttk.Combobox(parent, state='readonly')
        self._value_order = ()
        self.combo.bind('<<ComboboxSelected>>', self.on_changed)
        tooltip.add_tooltip(self.combo, delay=150)
        tooltip.add_tooltip(self.label)

    @override
    async def display(
        self, row: int, option: Option, remove_event: trio.Event,
        *, task_status: trio.TaskStatus = trio.TASK_STATUS_IGNORED,
    ) -> None:
        """Display the row in the specified position, then remove when the event triggers."""
        set_text(self.label, TransToken.untranslated('{name}: ').format(name=option.name))
        tooltip.set_tooltip(self.label, option.desc)
        tooltip.set_tooltip(self.combo, option.desc)
        self.combo['values'] = [
            str(TRANS_RAND_OPTION),
            *[str(val.name) for val in option.values],
        ]
        self._value_order = [
            utils.ID_RANDOM,
            *[val.id for val in option.values],
        ]
        # Caller has assigned one of our IDs to our AsyncValue, so index() should always succeed.
        self.combo.current(self._value_order.index(self.current.value))

        # Increment the row by one to account for the title.
        self.label.grid(row=row + 1, column=0)
        self.combo.grid(row=row + 1, column=1, sticky='ew')
        # Wait for the signal that the corridor has been deselected, then remove.
        task_status.started()
        await remove_event.wait()
        self.label.grid_forget()
        self.combo.grid_forget()

    def on_changed(self, _: tk.Event) -> None:
        """Apply changes to the combobox."""
        self.current.value = self._value_order[self.combo.current()]


class TkSelector(Selector[IconUI, OptionRowUI]):
    """Corridor selection window."""
    win: tk.Toplevel

    # Widgets to display info about the corridor on the right side.
    wid_image: ttk.Label
    wid_title: ttk.Label
    wid_authors: ttk.Label
    wid_desc: RichText

    def __init__(self, packset: packages.PackagesSet, tk_img: TKImages, cur_style: utils.ObjectID) -> None:
        conf = config.APP.get_cur_conf(UIState)
        super().__init__(conf)
        self.tk_img = tk_img
        self_ref = self
        self.icons = WidgetCache(lambda ind: IconUI(self_ref), lambda ico: ico.set_image(None))

        self.win = tk.Toplevel(TK_ROOT, name='corridor')
        self.win.withdraw()
        close_cmd = self.win.register(self.close_event.set)
        self.win.wm_protocol("WM_DELETE_WINDOW", close_cmd)
        set_win_title(self.win, TRANS_TITLE)

        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)

        frm_left = ttk.Frame(self.win, name='frm_left')
        frm_left.grid(row=0, column=0, sticky='nsew')

        frm_right = ttk.Frame(self.win, name='frm_right')
        frm_right.columnconfigure(0, weight=1)
        frm_right.grid(row=0, column=1, sticky='ns')
        self.frm_img = frm_img = ttk.Frame(frm_right, relief='raised')
        frm_img.grid(row=0, column=0, columnspan=2, sticky='ew')
        frm_img.rowconfigure(1, weight=1)

        # Cache the TK name for the registered command so that we can reuse it.
        self.changed_cmd = self.win.register(self.select_trigger.maybe_trigger)

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

        # Allows scrolling.
        self.right_canv = right_canv = tk.Canvas(
            frm_right,
            highlightthickness=0, name='right_canv',
        )
        right_canv.grid(row=3, column=0, sticky='NSEW')
        frm_right.rowconfigure(3, weight=1)

        self.right_scroll_frm = right_scroll_frm = ttk.Frame(right_canv)
        self.right_frame_winid = right_canv.create_window(0, 0, window=right_scroll_frm, anchor="nw")
        right_scroll_frm.columnconfigure(0, weight=1)
        right_scroll_frm.rowconfigure(0, weight=1)

        self.right_scroll = tk_tools.HidingScroll(
            frm_right,
            orient='vertical',
            name='right_scroll',
            command=right_canv.yview,
        )
        right_canv['yscrollcommand'] = self.right_scroll.set
        self.right_scroll.grid(row=3, column=1, sticky='ns')

        self.wid_desc = RichText(right_scroll_frm, name='desc')
        self.wid_desc.grid(row=0, column=0, sticky='nsew')
        self.wid_options_frm = ttk.Frame(right_scroll_frm)
        self.wid_options_frm.grid(row=1, column=0, sticky='nsew')

        self.wid_options_title = ttk.Label(
            self.wid_options_frm,
            font=("Helvetica", 10, "bold"),
        )
        self.wid_options_title.grid(row=0, column=0, columnspan=2, sticky='ew')
        self.wid_no_options = set_text(ttk.Label(self.wid_options_frm), TRANS_NO_OPTIONS)

        frm_lower_btn = ttk.Frame(frm_right)
        frm_lower_btn.grid(row=4, column=0, columnspan=2)

        self.btn_just_this = ttk.Button(frm_lower_btn, name='just_this', command=self.evt_select_one)
        set_text(self.btn_just_this, TRANS_ONLY_THIS)
        self.btn_just_this.grid(row=0, column=0)

        set_text(
            ttk.Button(frm_lower_btn, name='closer', command=close_cmd),
            TransToken.ui('Close'),
        ).grid(row=0, column=1)

        if conf.width > 0 and conf.height > 0:
            self.win.geometry(f'{conf.width}x{conf.height}')

        button_frm = ttk.Frame(frm_left)
        button_frm.grid(row=0, column=0, columnspan=3)
        self.btn_mode = tk_tools.EnumButton(button_frm, self.state_mode, TRANS_GROUP_MODE, OPTS_MODE)
        self.btn_direction = tk_tools.EnumButton(button_frm, self.state_dir, TRANS_GROUP_DIR, OPTS_DIR)
        self.btn_attach = tk_tools.EnumButton(button_frm, self.state_attach, TRANS_GROUP_ATTACH, OPTS_ATTACH)

        self.btn_mode.frame.grid(row=0, column=0, padx=8)
        self.btn_direction.frame.grid(row=0, column=1, padx=8)
        self.btn_attach.frame.grid(row=0, column=2, padx=8)

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
        self.canvas.bind('<Configure>', self.evt_window_resized)
        self._canv_pos = CanvasPositioner(place_icon, self.canvas, WIDTH, HEIGHT)

        self.help_lbl = ttk.Label(self.canvas)
        set_text(self.help_lbl, TRANS_HELP)
        self.help_lbl_win = self.canvas.create_window(0, 0, anchor='nw', window=self.help_lbl)

        tk_tools.add_mousewheel(self.canvas, frm_left)
        tk_tools.add_mousewheel(right_canv, frm_right)
        self.load_corridors(packset, cur_style)

    @override
    async def ui_task(self) -> None:
        """Task which runs to update the UI."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self.btn_direction.task)
            nursery.start_soon(self.btn_mode.task)
            nursery.start_soon(self.btn_attach.task)

    @override
    def evt_window_resized(self, event: object) -> None:
        """Reshape various frames as required."""
        super().evt_window_resized(event)

        width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self.help_lbl_win, width=width)
        self.help_lbl['wraplength'] = width

        right_width = self.frm_img.winfo_reqwidth()
        if self.right_scroll.winfo_ismapped():
            right_width -= self.right_scroll.winfo_width()
        self.right_canv['scrollregion'] = (
            0, 0,
            right_width,
            self.right_scroll_frm.winfo_reqheight()
        )
        self.right_canv.itemconfigure(self.right_frame_winid, width=right_width)
        self.right_canv['width'] = right_width

    @override
    def _ui_calc_columns(self) -> int:
        """Calculate the required number of columns."""
        return self._canv_pos.calc_columns()

    @override
    async def _ui_reposition_items(self) -> None:
        """Called to reposition the corridors."""
        self.canvas.delete('icons')

        # Items are placed after the help text.
        (x1, y1, x2, y2) = self.canvas.bbox(self.help_lbl_win)
        self._canv_pos.reset(y2 - y1)

        self._canv_pos.place_slots(self.icons.placed, 'icons')
        self._canv_pos.resize_canvas()

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
    def ui_win_getsize(self) -> tuple[int, int]:
        """Fetch the current dimensions, for saving."""
        return self.win.winfo_width(), self.win.winfo_height()

    @override
    def ui_enable_just_this(self, enable: bool) -> None:
        """Set whether the just this button is pressable."""
        self.btn_just_this.state(('!disabled', ) if enable else ('disabled', ))

    @override
    def ui_desc_display(
        self, *,
        title: TransToken,
        authors: TransToken,
        desc: MarkdownData,
        options_title: TransToken,
        show_no_options: bool,
    ) -> None:
        """Display information for a corridor."""
        set_text(self.wid_title, title)
        set_text(self.wid_authors, authors)
        self.wid_desc.set_text(desc)
        disp_lines = self.wid_desc.count(1.0, 'end', 'displaylines', 'update')
        self.wid_desc['height'] = max(6, (disp_lines or 0) + 1)

        set_text(self.wid_options_title, options_title)
        if show_no_options:
            self.wid_no_options.grid(row=1, column=0, columnspan=2)
        else:
            self.wid_no_options.grid_remove()

    @override
    def ui_desc_set_img_state(self, handle: img.Handle | None, left: bool, right: bool) -> None:
        """Set the widget state for the large preview image in the description sidebar."""
        self.tk_img.apply(self.wid_image, handle)
        self.wid_image_left.state(('!disabled', ) if left else ('disabled', ))
        self.wid_image_right.state(('!disabled', ) if right else ('disabled', ))

    @override
    def ui_option_create(self) -> OptionRowUI:
        """Create a new option row."""
        return OptionRowUI(self.wid_options_frm)
