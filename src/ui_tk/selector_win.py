"""Tk-specific implementation of the selector window."""
from typing import Final, assert_never
from typing_extensions import override

from tkinter import ttk, font as tk_font
import tkinter as tk

from collections.abc import Callable, Mapping
from contextlib import aclosing
import math

import trio

from app import WidgetCache, img
from app.mdown import MarkdownData
from app.selector_win import (
    DispFont, GroupHeaderBase, SelectorWinBase, AttrDef, Options, NavKeys,
    TRANS_ATTR_DESC, TRANS_SUGGESTED, TRANS_SUGGESTED_MAC, TRANS_WINDOW_TITLE,
)
from consts import SEL_ICON_SIZE, SEL_ICON_SIZE_LRG as ICON_SIZE_LRG
from packages import AttrTypes
from transtoken import TransToken
from ui_tk import tk_tools
from ui_tk.img import TK_IMG
from ui_tk.rich_textbox import RichText
from ui_tk.tooltip import add_tooltip, set_tooltip
from ui_tk.wid_transtoken import set_stringvar, set_text, set_win_title, set_menu_text
import utils


__all__ = [
    'AttrDef',  # Re-export
    'SelectorWin',
    'Options',
]

ITEM_WIDTH = SEL_ICON_SIZE + (32 if utils.MAC else 16)
ITEM_HEIGHT = SEL_ICON_SIZE + 51

KEYSYM_TO_NAV: Final[Mapping[str, NavKeys]] = {
    'Up': NavKeys.UP,
    'Down': NavKeys.DOWN,
    'Left': NavKeys.LEFT,
    'Right': NavKeys.RIGHT,

    'Home': NavKeys.HOME,
    'End': NavKeys.END,

    'Return': NavKeys.ENTER,
    'space': NavKeys.PLAY_SOUND,
    # Page up/down is 'Prior' / 'Next'
}


class GroupHeader(GroupHeaderBase):
    """The widget used for group headers."""
    def __init__(self, win: 'SelectorWin') -> None:
        super().__init__(win)
        self.parent_menu = win.context_menu
        self.frame = frame = ttk.Frame(win.pal_frame)
        self.menu = win.context_menu
        self.menu_pos = -1

        sep_left = ttk.Separator(frame)
        sep_left.grid(row=0, column=0, sticky='EW')
        frame.columnconfigure(0, weight=1)

        self.title = ttk.Label(frame, font='TkMenuFont', anchor='center')
        self.title.grid(row=0, column=1)

        sep_right = ttk.Separator(frame)
        sep_right.grid(row=0, column=2, sticky='EW')
        frame.columnconfigure(2, weight=1)

        self.arrow = ttk.Label(
            frame,
            text='',
            width=2,
        )
        self.arrow.grid(row=0, column=10)

        # For the mouse events to work, we need to bind on all the children too.
        widgets = frame.winfo_children()
        widgets.append(frame)
        for wid in widgets:
            tk_tools.bind_leftclick(wid, self._evt_toggle)
            wid['cursor'] = tk_tools.Cursors.LINK
        frame.bind('<Enter>', self._evt_hover_start)
        frame.bind('<Leave>', self._evt_hover_end)

    def hide(self) -> None:
        """Hide the widgets and stop tracking translations."""
        super().hide()
        set_text(self.title, TransToken.BLANK)
        self.menu_pos = -1
        self.frame.place_forget()

    @override
    def _ui_reassign(self, group_id: str, title: TransToken) -> None:
        """Set the group label."""
        super()._ui_reassign(group_id, title)
        set_text(self.title, title)
        self.menu = tk.Menu(self.parent_menu) if group_id else self.parent_menu
        self.menu_pos = -1

    @override
    def _ui_set_arrow(self, arrow: str) -> None:
        """Set the arrow glyph."""
        self.arrow['text'] = arrow


class SelectorWin(SelectorWinBase[ttk.Button, GroupHeader]):
    """Tk implementation of the selector window."""
    parent: tk.Tk | tk.Toplevel
    win: tk.Toplevel
    pane_win: tk.PanedWindow
    desc_label: ttk.Label
    wid_canvas: tk.Canvas
    pal_frame: ttk.Frame

    wid_scroll: tk_tools.HidingScroll
    # Holds all the widgets which provide info for the current item.
    prop_frm: ttk.Frame
    # Border around the selected item icon.
    prop_icon_frm: ttk.Frame
    prop_icon: ttk.Label
    prop_name: ttk.Label

    prop_author: ttk.Label
    prop_desc_frm: ttk.Frame
    prop_desc: RichText
    prop_scroll: tk_tools.HidingScroll
    prop_reset: ttk.Button
    attr_labels: dict[AttrDef, ttk.Label]

    # Variable associated with self.display.
    disp_label: tk.StringVar
    # The textbox on the parent window.
    display: tk_tools.ReadOnlyEntry | None
    # The '...' button to open our window.
    disp_btn: ttk.Button | None

    samp_button: ttk.Button | None
    _suggest_lbl: WidgetCache[ttk.Label | ttk.LabelFrame]

    context_menu: tk.Menu
    # The menus for each group.
    context_menus: dict[str, tk.Menu]
    # The widget used to control which menu option is selected.
    context_var: tk.StringVar

    norm_font: tk_font.Font
    # A font for showing suggested items in the context menu
    sugg_font: tk_font.Font
    # A font for previewing the suggested items
    mouseover_font: tk_font.Font

    def __init__(self, parent: tk.Tk | tk.Toplevel, opt: Options) -> None:
        super().__init__(opt)

        self.parent = parent
        self.win = tk.Toplevel(parent, name='selwin_' + opt.save_id)
        self.win.withdraw()
        self.win.transient(master=parent)
        set_win_title(self.win, TRANS_WINDOW_TITLE.format(subtitle=opt.title))

        # Variable associated with self.display.
        self.disp_label = tk.StringVar()
        self.display = self.disp_btn = None

        # Allow resizing in X and Y.
        self.win.resizable(True, True)

        tk_tools.set_window_icon(self.win)

        # Run our quit command when the exit button is pressed, or Escape
        # on the keyboard.
        self.win.protocol("WM_DELETE_WINDOW", self.exit)
        self.win.bind("<Escape>", self.exit)

        # Allow navigating with arrow keys.
        self.win.bind("<KeyPress>", self._evt_key_navigate)

        self.desc_label = ttk.Label(
            self.win,
            name='desc_label',
            justify='left',
            anchor='w',
            width=5,  # Keep a small width, so this doesn't affect the
            # initial window size.
        )
        set_text(self.desc_label, opt.desc)
        self.desc_label.grid(row=0, column=0, sticky='EW')

        # PanedWindow allows resizing the two areas independently.
        self.pane_win = tk.PanedWindow(
            self.win,
            name='area_panes',
            orient='horizontal',
            sashpad=2,  # Padding above/below panes
            sashwidth=3,  # Width of border
            sashrelief='raised',  # Raise the border between panes
        )
        self.pane_win.grid(row=1, column=0, sticky="NSEW")
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(1, weight=1)

        shim = ttk.Frame(self.pane_win, relief="sunken")
        shim.rowconfigure(0, weight=1)
        shim.columnconfigure(0, weight=1)

        # We need to use a canvas to allow scrolling.
        self.wid_canvas = tk.Canvas(shim, highlightthickness=0, name='pal_canvas')
        self.wid_canvas.grid(row=0, column=0, sticky="NSEW")

        # Add another frame inside to place labels on.
        self.pal_frame = ttk.Frame(self.wid_canvas)
        self.wid_canvas.create_window(1, 1, window=self.pal_frame, anchor="nw")

        self.wid_scroll = tk_tools.HidingScroll(
            shim,
            name='scrollbar',
            orient='vertical',
            command=self.wid_canvas.yview,
        )
        self.wid_scroll.grid(row=0, column=1, sticky="NS")
        self.wid_canvas['yscrollcommand'] = self.wid_scroll.set

        tk_tools.add_mousewheel(self.wid_canvas, self.win)

        # Holds all the widgets which provide info for the current item.
        self.prop_frm = ttk.Frame(self.pane_win, name='prop_frame', borderwidth=4, relief='raised')
        self.prop_frm.columnconfigure(1, weight=1)

        # Border around the selected item icon.
        width, height = ICON_SIZE_LRG
        self.prop_icon_frm = ttk.Frame(
            self.prop_frm,
            name='prop_icon_frame',
            borderwidth=4,
            relief='raised',
            width=width,
            height=height,
        )
        self.prop_icon_frm.grid(row=0, column=0, columnspan=4)

        self.prop_icon = ttk.Label(self.prop_icon_frm, name='prop_icon')
        self.prop_icon.grid(row=0, column=0)
        self.prop_icon_frm.configure(dict(zip(('width', 'height'), ICON_SIZE_LRG, strict=True)))
        tk_tools.bind_leftclick(self.prop_icon, self._evt_icon_clicked)

        name_frame = ttk.Frame(self.prop_frm)

        self.prop_name = ttk.Label(
            name_frame,
            name='prop_name',
            text="",
            justify='center',
            anchor='center',
            font=("Helvetica", 12, "bold"),
        )
        name_frame.grid(row=1, column=0, columnspan=4)
        name_frame.columnconfigure(0, weight=1)
        self.prop_name.grid(row=0, column=0, sticky='ew')

        # For music items, add a '>' button to play sound samples
        if self.sampler is not None:
            self.samp_button = samp_button = ttk.Button(
                name_frame,
                name='sample_button',
                width=2,
            )
            samp_button.grid(row=0, column=1)
            add_tooltip(samp_button, TransToken.ui("Play a sample of this item."))

            samp_button['command'] = self.sampler.play_sample
            samp_button.state(('disabled',))
        else:
            self.samp_button = None

        self.prop_author = ttk.Label(self.prop_frm, text="Author: person")
        self.prop_author.grid(row=2, column=0, columnspan=4)

        self.prop_desc_frm = ttk.Frame(self.prop_frm, relief="sunken")
        self.prop_desc_frm.grid(row=4, column=0, columnspan=4, sticky="nsew")
        self.prop_desc_frm.rowconfigure(0, weight=1)
        self.prop_desc_frm.columnconfigure(0, weight=1)
        self.prop_frm.rowconfigure(4, weight=1)

        self.prop_desc = RichText(
            self.prop_desc_frm,
            name='prop_desc',
            width=40,
            height=4,
            font="TkSmallCaptionFont",
        )
        self.prop_desc.grid(
            row=0,
            column=0,
            padx=(2, 0),
            pady=2,
            sticky='nsew',
        )

        self.prop_scroll = tk_tools.HidingScroll(
            self.prop_desc_frm,
            name='desc_scroll',
            orient='vertical',
            command=self.prop_desc.yview,
        )
        self.prop_scroll.grid(
            row=0,
            column=1,
            sticky="ns",
            padx=(0, 2),
            pady=2,
        )
        self.prop_desc['yscrollcommand'] = self.prop_scroll.set

        set_text(ttk.Button(
            self.prop_frm,
            name='btn_ok',
            command=self.save,
        ), TransToken.ui('OK')).grid(row=6, column=0, padx=(8, 8))

        if self.has_def:
            self.prop_reset = ttk.Button(
                self.prop_frm,
                name='btn_suggest',
                command=self.sel_suggested,
            )
            set_text(self.prop_reset, TransToken.ui("Select Suggested"))
            self.prop_reset.grid(
                row=6,
                column=1,
                sticky='ew',
            )

        set_text(ttk.Button(
            self.prop_frm,
            name='btn_cancel',
            command=self.exit,
        ), TransToken.ui("Cancel")).grid(row=6, column=2, padx=(8, 8))

        self.win.option_add('*tearOff', False)
        self.context_menu = tk.Menu(self.win)

        self.norm_font = tk_font.nametofont('TkMenuFont')

        # Make a font for showing suggested items in the context menu
        self.sugg_font = self.norm_font.copy()
        self.sugg_font['weight'] = tk_font.BOLD

        # Make a font for previewing the suggested items
        self.mouseover_font = self.norm_font.copy()
        self.mouseover_font['slant'] = tk_font.ITALIC

        # The headers for the context menu
        self.context_menus = {}
        # The widget used to control which menu option is selected.
        self.context_var = tk.StringVar()
        group_self = self  # Avoid making 'self' a direct closure.
        self.group_cache = WidgetCache(lambda wid_id: GroupHeader(group_self), GroupHeader.hide)

        if utils.MAC:
            def make_suggest_label(ind: int) -> ttk.Label | ttk.LabelFrame:
                """A labelframe doesn't look good on OSX."""
                sugg_lbl = ttk.Label(
                    self.pal_frame,
                    name=f'suggest_label_{ind}',
                )
                set_text(sugg_lbl, TRANS_SUGGESTED_MAC)
                return sugg_lbl
        else:
            def make_suggest_label(ind: int) -> ttk.Label | ttk.LabelFrame:
                """Use a labelframe to add a nice line connecting this to the icon."""
                sugg_lbl = ttk.LabelFrame(
                    self.pal_frame,
                    name=f'suggest_label_{ind}',
                    labelanchor='n',
                    height=50,
                )
                set_text(sugg_lbl, TRANS_SUGGESTED)
                return sugg_lbl

        self._suggest_lbl = WidgetCache(make_suggest_label, tk.Widget.place_forget)

        self.pane_win.add(shim)
        self.pane_win.add(self.prop_frm)

        # Force a minimum size for the two parts
        self.pane_win.paneconfigure(shim, minsize=100, stretch='always')
        self.prop_frm.update_idletasks()  # Update reqwidth()
        self.pane_win.paneconfigure(
            self.prop_frm,
            minsize=200,
            stretch='never',
        )

        # Wide before short.
        self.attr_labels = {}
        if self.attrs:
            attrs_frame = ttk.Frame(self.prop_frm)
            attrs_frame.grid(
                row=5,
                column=0,
                columnspan=3,
                sticky='ew',
                padx=5,
            )
            attrs_frame.columnconfigure(0, weight=1)
            attrs_frame.columnconfigure(2, weight=1)

            for attr, row, col_type in self._attr_widget_positions():
                attr_frame = ttk.Frame(attrs_frame)
                desc_label = ttk.Label(attr_frame)
                set_text(desc_label, TRANS_ATTR_DESC.format(desc=attr.desc))
                self.attr_labels[attr] = attr_label = ttk.Label(attr_frame)

                if attr.type is AttrTypes.COLOUR:
                    # A small colour swatch.
                    attr_label.configure(relief='raised')
                    # Show the color value when hovered.
                    add_tooltip(attr_label)

                desc_label.grid(row=0, column=0, sticky='e')
                attr_label.grid(row=0, column=1, sticky='w')
                # Wide ones have their own row, narrow ones are two to a row
                match col_type:
                    case 'wide':
                        attr_frame.grid(
                            row=row,
                            column=0, columnspan=3,
                            sticky='w',
                        )
                    case 'left':
                        attr_frame.grid(
                            row=row,
                            column=0,
                            sticky='w',
                        )
                    case 'right':
                        ttk.Separator(attrs_frame, orient='vertical').grid(row=row, column=1, sticky='NS')
                        attr_frame.grid(
                            row=row,
                            column=2,
                            sticky='e',
                        )
                    case _:
                        assert_never(col_type)

        self.set_disp()
        # Late binding!
        self.wid_canvas.bind("<Configure>", lambda e: self.items_dirty.set())

    async def widget(self, frame: tk.Misc) -> ttk.Entry:
        """Create the special textbox used to open the selector window."""
        def open_window(event: object = None) -> str:
            """If readonly, produce an error bell."""
            if self._readonly:
                self.win.bell()
                return 'break'
            else:
                self.open_win()
            return ''

        self.display = tk_tools.ReadOnlyEntry(
            frame,
            textvariable=self.disp_label,
            cursor=tk_tools.Cursors.REGULAR,
        )
        tk_tools.bind_leftclick(self.display, open_window)
        set_disp = self.set_disp

        def on_key(_: object) -> str:
            """Prevent typing in the display by reverting, then cancelling the event."""
            set_disp()
            return 'break'

        self.display.bind("<Key>", on_key)
        tk_tools.bind_rightclick(
            self.display,
            self._evt_open_context,
        )

        self.disp_btn = ttk.Button(
            self.display,
            text="...",
            width=1.5,  # type: ignore
            command=open_window,
        )
        self.disp_btn.pack(side='right')

        add_tooltip(self.display, self.description, show_when_disabled=True)

        # Set this property again, which updates the description if we actually
        # are readonly.
        self.set_disp()
        self.save()

        return self.display

    def _evt_open_context(self, _: object = None) -> None:
        """Dislay the context window at the text widget."""
        if not self._readonly and not self._loading and self.display is not None:
            self.context_menu.post(
                self.display.winfo_rootx(),
                self.display.winfo_rooty() + self.display.winfo_height())

    def _evt_key_navigate(self, event: tk.Event[tk.Misc]) -> None:
        """Handle keyboard control for the window."""
        try:
            key = KEYSYM_TO_NAV[event.keysym]
        except KeyError:
            return
        self.key_navigate(key)
        raise NotImplementedError

    @override
    async def _ui_task(self) -> None:
        """Executed by task()."""
        async with aclosing(self.chosen.eventual_values()) as agen:
            async for chosen_id in agen:
                self.context_var.set(chosen_id)

    @override
    def _ui_win_hide(self) -> None:
        if self.modal:
            self.win.grab_release()
        self.win.withdraw()

    @override
    def _ui_win_show(self, /) -> None:
        """Show the window, centred on the parent."""
        self.win.deiconify()
        self.win.lift()

        if self.modal:
            self.win.grab_set()
        self.win.focus_force()  # Focus here to deselect the textbox

        tk_tools.center_win(self.win, parent=self.parent)

    @override
    def _ui_win_get_size(self, /) -> tuple[int, int]:
        """Get the current size, for storing in configs."""
        return self.win.winfo_width(), self.win.winfo_height()

    @override
    def _ui_win_set_size(self, width: int, height: int) -> None:
        """Apply size from configs."""
        self.win.geometry(f'{width}x{height}')

    @override
    async def _ui_reposition_items(self) -> None:
        """Reposition all the items to fit in the current geometry.

        Called whenever items change or the window is resized.
        """
        self.pal_frame.update_idletasks()
        self.pal_frame['width'] = self.wid_canvas.winfo_width()
        self.desc_label['wraplength'] = self.win.winfo_width() - 10

        width = (self.wid_canvas.winfo_width() - 10) // ITEM_WIDTH
        if width < 1:
            width = 1  # we got way too small, prevent division by zero
        self.item_width = width

        # The offset for the current group
        y_off = 0

        self._suggest_lbl.reset()

        # If only the '' group is present, force it to be visible, and hide
        # the header.
        no_groups = self.group_order == ['']

        for group_key in self.group_order:
            await trio.lowlevel.checkpoint()
            items = self.grouped_items[group_key]
            group_wid = self.group_widgets[group_key]

            if no_groups:
                group_wid.frame.place_forget()
            else:
                group_wid.frame.place(
                    x=0,
                    y=y_off,
                    width=width * ITEM_WIDTH,
                )
                group_wid.frame.update_idletasks()
                y_off += group_wid.frame.winfo_reqheight()

                if not self.group_visible.get(group_key):
                    # Hide everything!
                    for item_id in items:
                        await trio.lowlevel.checkpoint()
                        self._ui_button_hide(self._id_to_button[item_id])
                    continue

            # Place each item
            for i, item_id in enumerate(items):
                await trio.lowlevel.checkpoint()
                button = self._id_to_button[item_id]
                if item_id in self.suggested:
                    sugg_lbl = self._suggest_lbl.fetch()
                    sugg_lbl.place(
                        x=(i % width) * ITEM_WIDTH + 1,
                        y=(i // width) * ITEM_HEIGHT + y_off,
                    )
                    sugg_lbl['width'] = button.winfo_width()
                button.place(
                    x=(i % width) * ITEM_WIDTH + 1,
                    y=(i // width) * ITEM_HEIGHT + y_off + 20,
                )
                button.lift()  # Over the suggested label.

            # Increase the offset by the total height of this item section
            y_off += math.ceil(len(items) / width) * ITEM_HEIGHT + 5

        # Set the size of the canvas and frame to the amount we've used
        self.wid_canvas['scrollregion'] = (
            0, 0,
            width * ITEM_WIDTH,
            y_off,
        )
        self.pal_frame['height'] = y_off
        self._suggest_lbl.hide_unused()

    @override
    def _ui_button_create(self, ind: int) -> ttk.Button:
        button = ttk.Button(self.pal_frame)
        tk_tools.bind_leftclick(button, lambda evt: self._evt_button_click(ind))
        return button

    @override
    def _ui_button_set_text(self, button: ttk.Button, text: TransToken) -> None:
        set_text(button, text)
        if text is TransToken.BLANK:
            # Special items have no text.
            button['compound'] = 'none'
        else:
            button['compound'] = 'top'

    @override
    def _ui_button_set_img(self, button: ttk.Button, image: img.Handle | None) -> None:
        TK_IMG.apply(button, image)

    @override
    def _ui_button_set_selected(self, button: ttk.Button, selected: bool) -> None:
        """Set whether the button should be highlighted as if selected."""
        button.state(('alternate',) if selected else ('!alternate', ))

    @override
    def _ui_button_hide(self, button: ttk.Button) -> None:
        button.place_forget()

    @override
    def _ui_button_scroll_to(self, button: ttk.Button) -> None:
        """Scroll to an item so it's visible."""
        height = self.wid_canvas.bbox('all')[3]  # Returns (x, y, width, height)

        bottom, top = self.wid_canvas.yview()
        # The sizes are returned in fractions, but we use the pixel values
        # for accuracy
        bottom *= height
        top *= height

        y = button.winfo_y()

        if bottom <= y - 8 and y + SEL_ICON_SIZE + 8 <= top:
            return  # Already in view

        # Center in the view
        self.wid_canvas.yview_moveto(
            (y - (top - bottom) // 2)
            / height
        )

    @override
    def _ui_attr_set_text(self, attr: AttrDef, text: TransToken, /) -> None:
        """Set the value of a text-style attribute widget."""
        set_text(self.attr_labels[attr], text)

    @override
    def _ui_attr_set_image(self, attr: AttrDef, image: img.Handle, /) -> None:
        """Set the image for an image-style attribute widget."""
        TK_IMG.apply(self.attr_labels[attr], image)

    @override
    def _ui_attr_set_tooltip(self, attr: AttrDef, tooltip: TransToken, /) -> None:
        """Set the hover tooltip. This only applies to image-style widgets."""
        set_tooltip(self.attr_labels[attr], tooltip)

    @override
    def _ui_props_set_author(self, author: TransToken) -> None:
        """Set the author text for the selected item."""
        set_text(self.prop_author, author)

    @override
    def _ui_props_set_name(self, name: TransToken) -> None:
        """Set the name text for the selected item."""
        set_text(self.prop_name, name)

    @override
    def _ui_props_set_desc(self, desc: MarkdownData) -> None:
        """Set the description for the selected item."""
        self.prop_desc.set_text(desc)

    @override
    def _ui_props_set_icon(self, image: img.Handle) -> None:
        """Set the large icon's image, and whether to show a zoom-in cursor."""
        TK_IMG.apply(self.prop_icon, image)
        # Change aspect ratio to match the large icon.
        self.prop_icon_frm.configure(width=image.width, height=image.height)

    @override
    def _ui_props_set_samp_button_enabled(self, enabled: bool, /) -> None:
        """Set whether the sample button is enabled."""
        assert self.samp_button is not None
        self.samp_button.state(('!disabled',) if enabled else ('disabled',))

    @override
    def _ui_props_set_samp_button_icon(self, glyph: str, /) -> None:
        """Set the icon in the play-sample button. These don't translate since it's a symbol."""
        assert self.samp_button is not None
        self.samp_button['text'] = glyph

    @override
    def _ui_menu_clear(self) -> None:
        """Remove all items from the main context menu."""
        self.context_menu.delete(0, 'end')
        self._menu_index.clear()
        # Ungrouped items appear directly in the menu.
        self.context_menus = {'': self.context_menu}

    @override
    def _ui_menu_set_font(self, item_id: utils.SpecialID, suggested: bool) -> None:
        """Set the font of an item, and its parent group."""
        try:
            menu_ind = self._menu_index[item_id]
        except KeyError:
            return
        new_font = self.sugg_font if suggested else self.norm_font
        data = self._get_data(item_id)
        if data.group_id:
            group = self.group_widgets[data.group_id]
            menu = group.menu

            # Apply the font to the group header as well, if suggested.
            if suggested:
                group.title['font'] = new_font

                # Also highlight the menu
                # noinspection PyUnresolvedReferences
                self.context_menu.entryconfig(
                    group.menu_pos,
                    font=new_font,
                )
        else:
            menu = self.context_menu
        menu.entryconfig(menu_ind, font=new_font)

    @override
    def _ui_menu_reset_suggested(self) -> None:
        """Reset the fonts for all group widgets. menu_set_font() will then set them."""
        for group_key, header in self.group_widgets.items():
            header.title['font'] = self.norm_font
            if header.menu_pos >= 0:
                self.context_menu.entryconfig(header.menu_pos, font=self.norm_font)

    @override
    def _ui_menu_add(self, group: GroupHeader, item: utils.SpecialID, func: Callable[[], object], label: TransToken, /) -> None:
        """Add a radio-selection menu option for this item."""
        group.menu.add_radiobutton(
            command=func,
            variable=self.context_var,
            value=item,
        )
        set_menu_text(group.menu, label)
        menu_pos = group.menu.index('end')
        assert menu_pos is not None, "Didn't add to the menu?"
        self._menu_index[item] = menu_pos

    @override
    def _ui_group_add(self, group: GroupHeader, name: TransToken) -> None:
        """Add the specified group to the rightclick menu."""
        self.context_menu.add_cascade(menu=group.menu)
        set_menu_text(self.context_menu, name)
        # Track the menu's index. The one at the end is the one we just added.
        menu_pos = self.context_menu.index('end')
        assert menu_pos is not None, "Didn't add to the menu?"
        group.menu_pos = menu_pos

    @override
    def _ui_enable_reset(self, enabled: bool) -> None:
        """Set whether the 'reset to default' button can be used."""
        self.prop_reset.state(('!disabled',) if enabled else ('disabled',))

    @override
    def _ui_display_set(
        self, *,
        enabled: bool,
        text: TransToken,
        tooltip: TransToken,
        font: DispFont,
    ) -> None:
        """Set the state of the display textbox and button."""
        if self.display is None or self.disp_btn is None:
            return  # Nothing to do.

        match font:
            case 'normal':
                font_obj = self.norm_font
            case 'suggested':
                font_obj = self.sugg_font
            case 'mouseover':
                font_obj = self.mouseover_font
            case _:
                assert_never(font)

        if str(self.display['font']) != str(font_obj):
            # Changing the font causes a flicker, so only set it
            # when the font is actually different.
            self.display['font'] = font_obj
        set_tooltip(self.display, tooltip)
        set_stringvar(self.disp_label, text)

        state = ('!disabled', ) if enabled else ('disabled', )
        self.disp_btn.state(state)
        self.display.state(state)
