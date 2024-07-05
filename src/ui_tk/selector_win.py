"""Tk-specific implementation of the selector window."""
from typing import Final
from typing_extensions import override
from tkinter import ttk, font as tk_font
import tkinter as tk

from collections.abc import Mapping

from app import img
from app.selector_win import (
    SelectorWinBase, AttrDef, Options, NavKeys,
    BTN_PLAY, BTN_STOP, BTN_PREV, BTN_NEXT,
    TRANS_ATTR_DESC,
    TRANS_SUGGESTED, TRANS_SUGGESTED_MAC, TRANS_WINDOW_TITLE,
)
from consts import SEL_ICON_SIZE, SEL_ICON_SIZE_LRG as ICON_SIZE_LRG
from packages import AttrTypes
from transtoken import TransToken
from ui_tk import tk_tools
from ui_tk.img import TK_IMG
from ui_tk.rich_textbox import RichText
from ui_tk.tooltip import add_tooltip
from ui_tk.wid_transtoken import set_text, set_win_title
import utils


__all__ = [
    'AttrDef',  # Re-export
    'SelectorWin',
    'Options',
]

type SuggLabel = ttk.Label | ttk.LabelFrame

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


class SelectorWin(SelectorWinBase[
    ttk.Button,  # ButtonT
    SuggLabel,  # SuggLblT
]):
    """Tk implementation of the selector window."""
    parent: tk.Tk | tk.Toplevel
    win: tk.Toplevel
    pane_win: tk.PanedWindow

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

    def __init__(self, parent: tk.Tk | tk.Toplevel, opt: Options) -> None:
        super().__init__(opt)

        self.win = tk.Toplevel(parent, name='selwin_' + opt.save_id)
        self.win.withdraw()
        self.win.transient(master=parent)
        set_win_title(self.win, TRANS_WINDOW_TITLE.format(subtitle=opt.title))

        # Variable associated with self.display.
        self.disp_label = tk.StringVar()

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
        tk_tools.bind_leftclick(self.prop_icon, self._icon_clicked)

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
                text=BTN_PLAY,
                width=2,
            )
            samp_button.grid(row=0, column=1)
            add_tooltip(samp_button, TransToken.ui("Play a sample of this item."))

            samp_button['command'] = self.sampler.play_sample
            samp_button.state(('disabled',))
        else:
            self.samp_button = samp_button = None

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
        self.attrs = sorted(opt.attributes, key=lambda at: 0 if at.type.is_wide else 1)
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
            attrs_frame.columnconfigure(1, weight=1)

            # Add in all the attribute labels
            index = 0
            for attr in self.attrs:
                attr_frame = ttk.Frame(attrs_frame)
                desc_label = ttk.Label(attr_frame)
                set_text(desc_label, TRANS_ATTR_DESC.format(desc=attr.desc))
                self.attr_labels[attr.id] = attr_label = ttk.Label(attr_frame)

                if attr.type is AttrTypes.COLOR:
                    # A small colour swatch.
                    attr_label.configure(relief='raised')
                    # Show the color value when hovered.
                    add_tooltip(attr_label)

                desc_label.grid(row=0, column=0, sticky='e')
                attr_label.grid(row=0, column=1, sticky='w')
                # Wide ones have their own row, narrow ones are two to a row
                if attr.type.is_wide:
                    if index % 2:  # Row has a single narrow, skip the empty space.
                        index += 1
                    attr_frame.grid(
                        row=index // 2,
                        column=0, columnspan=3,
                        sticky='w',
                    )
                    index += 2
                else:
                    if index % 2:  # Right.
                        ttk.Separator(orient='vertical').grid(row=index // 2, column=1, sticky='NS')
                        attr_frame.grid(
                            row=index // 2,
                            column=2,
                            sticky='E',
                        )
                    else:
                        attr_frame.grid(
                            row=index // 2,
                            column=0,
                            sticky='W',
                        )
                    index += 1

        self.set_disp()
        self.wid_canvas.bind("<Configure>", self.flow_items)

    def _evt_key_navigate(self, event: tk.Event[tk.Misc]) -> None:
        """Handle keyboard control for the window."""
        try:
            key = KEYSYM_TO_NAV[event.keysym]
        except KeyError:
            return
        self.key_navigate(key)
        raise NotImplementedError

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
    def _ui_button_set_pos(self, button: ttk.Button, x: int, y: int) -> None:
        button.place(x=x, y=y)
        button.lift()

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
    def _ui_sugg_create(self, ind: int) -> SuggLabel:
        """Create a label for highlighting suggested buttons."""
        sugg_lbl: SuggLabel
        if utils.MAC:
            # Labelframe doesn't look good here on OSX
            sugg_lbl = ttk.Label(
                self.pal_frame,
                name=f'suggest_label_{ind}',
            )
            set_text(sugg_lbl, TRANS_SUGGESTED_MAC)
        else:
            sugg_lbl = ttk.LabelFrame(
                self.pal_frame,
                name=f'suggest_label_{ind}',
                labelanchor='n',
                height=50,
            )
            set_text(sugg_lbl, TRANS_SUGGESTED)
        return sugg_lbl

    @override
    def _ui_sugg_hide(self, label: SuggLabel) -> None:
        """Hide the suggested button label."""
        label.place_forget()

    @override
    def _ui_sugg_place(self, label: SuggLabel, button: ttk.Button, x: int, y: int) -> None:
        """Place the suggested button label at this position."""
        label.place(x=x, y=y)
        label['width'] = button.winfo_width()

    @override
    def _ui_props_set_author(self, author: TransToken) -> None:
        """Set the author text for the selected item."""
        set_text(self.prop_author, author)

    @override
    def _ui_props_set_name(self, name: TransToken) -> None:
        """Set the name text for the selected item."""
        set_text(self.prop_name, name)

    @override
    def _ui_props_set_icon(self, image: img.Handle, can_preview: bool) -> None:
        """Set the large icon's image, and whether to show a zoom-in cursor."""
        TK_IMG.apply(self.prop_icon, image)
        # Change aspect ratio to match the large icon.
        self.prop_icon_frm.configure(width=image.width, height=image.height)
        if can_preview:
            self.prop_icon['cursor'] = tk_tools.Cursors.ZOOM_IN
        else:
            self.prop_icon['cursor'] = tk_tools.Cursors.REGULAR

    @override
    def _ui_enable_reset(self, enabled: bool) -> None:
        """Set whether the 'reset to default' button can be used."""
        self.prop_reset.state(('!disabled',) if enabled else ('disabled',))
