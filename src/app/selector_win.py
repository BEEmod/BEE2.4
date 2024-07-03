"""
A dialog used to select an item for things like Styles, Quotes, Music.

It appears as a textbox-like widget with a ... button to open the selection window.
Each item has a description, author, and icon.
"""
from __future__ import annotations

from tkinter import font as tk_font
from tkinter import ttk
import tkinter as tk

from contextlib import aclosing
from collections.abc import Callable, Container, Iterable, Sequence
from collections import defaultdict
from enum import Enum
import functools
import math
import random

from srctools import Vec, EmptyMapping
from srctools.filesys import FileSystemChain

from trio_util import AsyncValue
import trio
import srctools.logger

from ui_tk.rich_textbox import RichText
from app import tkMarkdown, sound, img, DEV_MODE
from ui_tk.tooltip import add_tooltip, set_tooltip
from ui_tk.img import TK_IMG
from ui_tk.wid_transtoken import set_menu_text, set_text, set_win_title, set_stringvar
from ui_tk import TK_ROOT, tk_tools
from packages import SelitemData, AttrTypes, AttrDef as AttrDef, AttrMap
from consts import (
    SEL_ICON_SIZE as ICON_SIZE,
    SEL_ICON_SIZE_LRG as ICON_SIZE_LRG,
)
from transtoken import CURRENT_LANG, TransToken
from config.last_sel import LastSelected
from config.windows import SelectorState
import utils
import config
import packages


LOGGER = srctools.logger.get_logger(__name__)
ITEM_WIDTH = ICON_SIZE + (32 if utils.MAC else 16)
ITEM_HEIGHT = ICON_SIZE + 51

# The two icons used for boolean item attributes
ICON_CHECK = img.Handle.builtin('icons/check', 16, 16)
ICON_CROSS = img.Handle.builtin('icons/cross', 16, 16)

# Arrows used to indicate the state of the group - collapsed or expanded
GRP_COLL = '◁'
GRP_COLL_HOVER = '◀'
GRP_EXP = '▽'
GRP_EXP_HOVER = '▼'

BTN_PLAY = '▶'
BTN_STOP = '■'
BTN_PREV = '⟨'
BTN_NEXT = '⟩'


class NAV_KEYS(Enum):
    """Enum representing keys used for shifting through items.

    The value is the TK key-sym value.
    """
    UP = 'Up'
    DOWN = 'Down'
    LEFT = 'Left'
    RIGHT = 'Right'

    DN = DOWN
    LF = LEFT
    RT = RIGHT

    PG_UP = 'Prior'
    PG_DOWN = 'Next'

    HOME = 'Home'
    END = 'End'

    ENTER = 'Return'

    # Space plays the current item.
    PLAY_SOUND = 'space'


# Callbacks used to get the info for items in the window.
type GetterFunc[T] = Callable[[packages.PackagesSet, utils.SpecialID], T]

TRANS_ATTR_DESC = TransToken.untranslated('{desc}: ')
TRANS_ATTR_COLOR = TransToken.ui('Color: R={r}, G={g}, B={b}')  # i18n: Tooltip for colour swatch.
TRANS_WINDOW_TITLE = TransToken.ui('BEE2 - {subtitle}')  # i18n: Window titles.
TRANS_PREVIEW_TITLE = TransToken.ui('Preview - {item}')  # i18n: Preview window.
TRANS_SUGGESTED = TransToken.ui("Suggested")
# Labelframe doesn't look good for the suggested display, use box drawing characters instead.
TRANS_SUGGESTED_MAC = TransToken.untranslated("\u250E\u2500{sugg}\u2500\u2512").format(sugg=TRANS_SUGGESTED)
# If the item is groupless, use 'Other' for the header.
TRANS_GROUPLESS = TransToken.ui('Other')
TRANS_AUTHORS = TransToken.ui_plural('Author: {authors}', 'Authors: {authors}')
TRANS_NO_AUTHORS = TransToken.ui('Authors: Unknown')
TRANS_DEV_ITEM_ID = TransToken.untranslated('**ID:** {item}')
TRANS_LOADING = TransToken.ui('Loading...')

async def _update_sampler_task(sampler: sound.SamplePlayer, button: ttk.Button) -> None:
    """Update the sampler's display."""
    async with aclosing(sampler.is_playing.eventual_values()) as agen:
        async for is_playing in agen:
            button['text'] = BTN_STOP if is_playing else BTN_PLAY


async def _store_results_task(chosen: AsyncValue[utils.SpecialID], save_id: str) -> None:
    """Store configured results when changed."""
    async with aclosing(chosen.eventual_values()) as agen:
        async for item_id in agen:
            config.APP.store_conf(LastSelected(item_id), save_id)



class GroupHeader(tk_tools.LineHeader):
    """The widget used for group headers."""
    def __init__(self, win: SelectorWin, title: TransToken, menu: tk.Menu) -> None:
        self.parent = win
        self.menu = menu  # The rightclick cascade widget.
        self.menu_pos = -1
        super().__init__(win.pal_frame, title)

        self.arrow = ttk.Label(
            self,
            text=GRP_EXP,
            width=2,
        )
        self.arrow.grid(row=0, column=10)

        self._visible = True

        # For the mouse events to work, we need to bind on all the children too.
        widgets = self.winfo_children()
        widgets.append(self)
        for wid in widgets:
            tk_tools.bind_leftclick(wid, self.toggle)
            wid['cursor'] = tk_tools.Cursors.LINK
        self.bind('<Enter>', self.hover_start)
        self.bind('<Leave>', self.hover_end)

    @property
    def visible(self) -> bool:
        """Check if the contents are visible."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        """Set if the contents are visible."""
        value = bool(value)
        if value == self._visible:
            return  # Don't do anything..

        self._visible = value
        self.hover_start()  # Update arrow icon
        self.parent.flow_items()

    def toggle(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """Toggle the header on or off."""
        self.visible = not self._visible

    def hover_start(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """When hovered over, fill in the triangle."""
        self.arrow['text'] = (
            GRP_EXP_HOVER
            if self._visible else
            GRP_COLL_HOVER
        )

    def hover_end(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """When leaving, hollow the triangle."""
        self.arrow['text'] = (
            GRP_EXP
            if self._visible else
            GRP_COLL
        )


class PreviewWindow:
    """Displays images previewing the selected item."""
    img: Sequence[img.Handle]
    def __init__(self) -> None:
        self.win = tk.Toplevel(TK_ROOT, name='selectorPreview')
        self.win.withdraw()
        self.win.resizable(False, False)

        # Don't destroy the window when closed.
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self.win.bind("<Escape>", self.hide)

        self.display = ttk.Label(self.win)
        self.display.grid(row=0, column=1, sticky='nsew')
        self.win.columnconfigure(1, weight=1)
        self.win.rowconfigure(0, weight=1)

        self.parent: SelectorWin | None = None

        self.prev_btn = ttk.Button(
            self.win, text=BTN_PREV, command=functools.partial(self.cycle, -1))
        self.next_btn = ttk.Button(
            self.win, text=BTN_NEXT, command=functools.partial(self.cycle, +1))

        self.img = ()
        self.index = 0

    def show(self, parent: SelectorWin, data: SelitemData) -> None:
        """Show the window."""
        self.win.transient(parent.win)
        set_win_title(self.win, TRANS_PREVIEW_TITLE.format(item=data.name))

        self.parent = parent
        self.index = 0
        self.img = data.previews
        TK_IMG.apply(self.display, self.img[0])

        if len(self.img) > 1:
            self.prev_btn.grid(row=0, column=0, sticky='ns')
            self.next_btn.grid(row=0, column=2, sticky='ns')
        else:
            self.prev_btn.grid_remove()
            self.next_btn.grid_remove()

        self.win.deiconify()
        self.win.lift()
        tk_tools.center_win(self.win, parent.win)
        if parent.modal:
            parent.win.grab_release()
            self.win.grab_set()

    def hide(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """Swap grabs if the parent is modal."""
        if self.parent is not None and self.parent.modal:
            self.win.grab_release()
            self.parent.win.grab_set()
        self.win.withdraw()

    def cycle(self, off: int) -> None:
        """Switch to a new image."""
        self.index = (self.index + off) % len(self.img)
        TK_IMG.apply(self.display, self.img[self.index])


_PREVIEW = PreviewWindow()


class SelectorWin:
    """The selection window for skyboxes, music, goo and voice packs.

    Optionally an aditional 'None' item can be added, which indicates
    that no item is to be used.
    The string "<NONE>" is used for the none item's ID.

    Attributes:
    - chosen_id: The currently-selected item ID. If set to None, the
      None Item is chosen.
    - chosen: The currently-selected item.
    - selected: The item currently selected in the window, not the actually chosen one.

    - wid: The Toplevel window for this selector dialog.
    - suggested: The Item which is suggested by the style.
    """
    # Callback functions used to retrieve the data for the window.
    func_get_attr: GetterFunc[AttrMap]
    func_get_data: GetterFunc[SelitemData]  # TODO: Maybe auto-catch KeyError for this to simplify user code?
    func_get_sample: GetterFunc[str] | None
    func_get_ids: Callable[[packages.PackagesSet], Iterable[utils.SpecialID]]

    # Packages currently loaded for the window.
    _packset: packages.PackagesSet

    # The textbox on the parent window.
    display: tk_tools.ReadOnlyEntry | None
    # Variable associated with self.display.
    disp_label: tk.StringVar

    # The '...' button to open our window.
    disp_btn: ttk.Button | None

    # Currently suggested item objects. This would be a set, but we want to randomly pick.
    suggested: list[utils.SpecialID]
    # While the user hovers over the "suggested" button, cycle through random items. But we
    # want to apply that specific item when clicked.
    _suggested_rollover: utils.SpecialID | None
    _suggest_lbl: list[ttk.Label | ttk.LabelFrame]

    # Should we have the 'reset to default' button?
    has_def: bool
    description: TransToken
    readonly_description: TransToken
    # If set, force textbox to display this when readonly.
    readonly_override: TransToken | None


    # The selected item is the one clicked on inside the window, while chosen
    # is the one actually chosen.
    chosen: AsyncValue[utils.SpecialID]
    selected: utils.SpecialID
    parent: tk.Tk | tk.Toplevel
    _readonly: bool
    _loading: bool  # This overrides readonly.
    modal: bool
    win: tk.Toplevel
    attrs: list[AttrDef]
    attr_labels: dict[str, ttk.Label]

    # Current list of item IDs we display.
    item_list: list[utils.SpecialID]
    # A map from group name -> header widget
    group_widgets: dict[str, GroupHeader]
    # A map from folded name -> display name
    group_names: dict[str, TransToken]
    # Group name -> items in that group.
    grouped_items: dict[str, list[utils.SpecialID]]
    # A list of casefolded group names in the display order.
    group_order: list[str]
    # Maps item ID to the menu position.
    _menu_index: dict[utils.SpecialID, int]

    # Buttons we have constructed, corresponding to the same in the item list.
    _item_buttons: list[ttk.Button]
    # And a lookup from ID -> button
    _id_to_button: dict[utils.SpecialID, ttk.Button]

    # The maximum number of items that fits per row (set in flow_items)
    item_width: int

    # The ID used to persist our window state across sessions.
    save_id: str
    store_last_selected: bool
    # Indicate that flow_items() should restore state.
    first_open: bool

    desc_label: ttk.Label
    pane_win: tk.PanedWindow
    wid_canvas: tk.Canvas
    pal_frame: ttk.Frame
    wid_scroll: tk_tools.HidingScroll
    # Holds all the widgets which provide info for the current item.
    prop_frm: ttk.Frame
    # Border around the selected item icon.
    prop_icon_frm: ttk.Frame
    prop_icon: ttk.Label
    prop_name: ttk.Label

    samp_button: ttk.Button | None
    sampler: sound.SamplePlayer | None

    prop_author: ttk.Label
    prop_desc_frm: ttk.Frame
    prop_desc: RichText
    prop_scroll: tk_tools.HidingScroll
    prop_reset: ttk.Button
    context_menu: tk.Menu
    norm_font: tk_font.Font
    # A font for showing suggested items in the context menu
    sugg_font: tk_font.Font
    # A font for previewing the suggested items
    mouseover_font: tk_font.Font

    # The headers for the context menu
    context_menus: dict[str, tk.Menu]
    # The widget used to control which menu option is selected.
    context_var: tk.StringVar

    @classmethod
    async def create(
        cls,
        parent: tk.Tk | tk.Toplevel,
        *,  # Make all keyword-only for readability
        func_get_data: GetterFunc[SelitemData],
        func_get_ids: Callable[[packages.PackagesSet], Iterable[utils.SpecialID]],
        save_id: str,  # Required!
        store_last_selected: bool = True,
        has_def: bool = True,
        sound_sys: FileSystemChain | None = None,
        func_get_sample: GetterFunc[str] | None = None,
        modal: bool = False,
        default_id: utils.SpecialID = utils.ID_NONE,
        title: TransToken = TransToken.untranslated('???'),
        desc: TransToken = TransToken.BLANK,
        readonly_desc: TransToken = TransToken.BLANK,
        readonly_override: TransToken | None = None,
        attributes: Iterable[AttrDef] = (),
        func_get_attr: GetterFunc[AttrMap] = lambda packset, item_id: EmptyMapping,
        task_status: trio.TaskStatus[SelectorWin],
    ) -> None:
        """Create a selector window object.

        Read from .selected_id to get the currently-chosen Item name, or None
        if the <none> Item is selected.
        Args:
        - parent: Must be a Toplevel window, either the tk() root or another
        window if needed.
        - func_get_data: Function to get the data for an ID. Should fetch a cached result, will
          be called for every item.
        - func_get_ids: Called to retrieve the list of item IDs.
        - save_id: The ID used to save/load the window state.
        - store_last_selected: If set, save/load the selected ID.
        - lst: A list of Item objects, defining the visible items.
        - If `has_def` is True, the 'Reset to Default' button will appear,
          which resets to the suggested item.
        - `default_id` is the item to initially select, if no previous one is set.
        - If snd_sample_sys is set, a '>' button will appear next to names
          to play the associated audio sample for the item.
          The value should be a FileSystem to look for samples in.
        - title is the title of the selector window.
        - full_context controls if the short or long names are used for the
          context menu.
        - attributes is a list of AttrDef tuples.
          Each tuple should contain an ID, display text, and default value.
          If the values are True or False a check/cross will be displayed,
          otherwise they're a string.
        - desc is descriptive text to display on the window, and in the widget
          tooltip.
        - readonly_desc will be displayed on the widget tooltip when readonly.
        - readonly_override, if set will override the textbox when readonly.
        - modal: If True, the window will block others while open.
        """
        self = cls()

        # self.noneItem.context_lbl = self.noneItem.data.name
        self.func_get_attr = func_get_attr
        self.func_get_sample = func_get_sample
        self.func_get_data = func_get_data
        self.func_get_ids = func_get_ids

        self.parent = parent
        self._readonly = False
        self._loading = False
        self.modal = modal

        # The textbox on the parent window.
        self.display = None

        # Variable associated with self.display.
        self.disp_label = tk.StringVar()

        # The '...' button to open our window.
        self.disp_btn = None

        # Currently suggested item objects. This would be a set, but we want to randomly pick.
        self.suggested = []
        # While the user hovers over the "suggested" button, cycle through random items. But we
        # want to apply that specific item when clicked.
        self._suggested_rollover = None
        self._suggest_lbl = []

        # Should we have the 'reset to default' button?
        self.has_def = has_def
        self.description = desc
        self.readonly_description = readonly_desc
        self.readonly_override = readonly_override

        prev_state = config.APP.get_cur_conf(
            LastSelected,
            save_id,
            default=LastSelected(default_id),
        )
        if store_last_selected:
            config.APP.store_conf(prev_state, save_id)

        self.selected = prev_state.id
        self.chosen = AsyncValue(self.selected)

        self._packset = packages.get_loaded_packages()  # TODO, handle reload
        self.item_list = list(func_get_ids(self._packset))

        self.win = tk.Toplevel(parent, name='selwin_' + save_id)
        self.win.withdraw()
        self.win.transient(master=parent)
        set_win_title(self.win, TRANS_WINDOW_TITLE.format(subtitle=title))
        self._item_buttons = []
        self._id_to_button = {}
        self._menu_index = {}

        # Allow resizing in X and Y.
        self.win.resizable(True, True)

        tk_tools.set_window_icon(self.win)

        # Run our quit command when the exit button is pressed, or Escape
        # on the keyboard.
        self.win.protocol("WM_DELETE_WINDOW", self.exit)
        self.win.bind("<Escape>", self.exit)

        # Allow navigating with arrow keys.
        self.win.bind("<KeyPress>", self.key_navigate)

        # A map from group name -> header widget
        self.group_widgets = {}
        # A map from folded name -> display name
        self.group_names = {}
        self.grouped_items = {}
        # A list of casefolded group names in the display order.
        self.group_order = []

        # The maximum number of items that fits per row (set in flow_items)
        self.item_width = 1

        # The ID used to persist our window state across sessions.
        self.save_id = save_id.casefold()
        self.store_last_selected = store_last_selected
        # Indicate that flow_items() should restore state.
        self.first_open = True

        self.desc_label = ttk.Label(
            self.win,
            name='desc_label',
            justify='left',
            anchor='w',
            width=5,  # Keep a small width, so this doesn't affect the
            # initial window size.
        )
        set_text(self.desc_label, desc)
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
        if sound_sys is not None and sound.has_sound() and func_get_sample is not None:
            self.samp_button = samp_button = ttk.Button(
                name_frame,
                name='sample_button',
                text=BTN_PLAY,
                width=2,
            )
            samp_button.grid(row=0, column=1)
            add_tooltip(samp_button, TransToken.ui("Play a sample of this item."))

            self.sampler = sound.SamplePlayer(system=sound_sys)
            samp_button['command'] = self.sampler.play_sample
            samp_button.state(('disabled',))
        else:
            self.sampler = self.samp_button = samp_button = None

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
        self.attrs = sorted(attributes, key=lambda at: 0 if at.type.is_wide else 1)
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
        self.refresh()
        self.wid_canvas.bind("<Configure>", self.flow_items)

        async with trio.open_nursery() as nursery:
            if self.sampler is not None and samp_button is not None:
                nursery.start_soon(_update_sampler_task, self.sampler, samp_button)
            if self.store_last_selected:
                nursery.start_soon(self._load_selected_task)
                nursery.start_soon(_store_results_task, self.chosen, self.save_id)

            task_status.started(self)

    def __repr__(self) -> str:
        return f'<SelectorWin "{self.save_id}">'

    async def widget(self, frame: tk.Misc) -> ttk.Entry:
        """Create the special textbox used to open the selector window.

        Use like 'selWin.widget(parent).grid(row=0, column=1)' to create
        and place the textbox.
        """

        self.display = tk_tools.ReadOnlyEntry(
            frame,
            textvariable=self.disp_label,
            cursor=tk_tools.Cursors.REGULAR,
        )
        tk_tools.bind_leftclick(
            self.display,
            self.open_win,
        )
        self.display.bind("<Key>", self.set_disp)
        tk_tools.bind_rightclick(
            self.display,
            self.open_context,
        )

        self.disp_btn = ttk.Button(
            self.display,
            text="...",
            width=1.5,  # type: ignore
            command=self.open_win,
        )
        self.disp_btn.pack(side='right')

        add_tooltip(self.display, self.description, show_when_disabled=True)

        # Set this property again, which updates the description if we actually
        # are readonly.
        self.readonly = self._readonly
        self.save()

        return self.display

    @property
    def chosen_id(self) -> utils.SpecialID:
        """The currently selected item, or None if none is selected."""
        return self.chosen.value

    @property
    def readonly(self) -> bool:
        """Setting the readonly property to True makes the option read-only.

        The window cannot be opened, and all other inputs will fail.
        """
        return self._readonly

    @readonly.setter
    def readonly(self, value: bool) -> None:
        self._readonly = bool(value)

    def _apply_load_readonly_state(self) -> None:
        """Update the display box to account for readonly/loading state."""
        if self.display is None or self.disp_btn is None:
            # Widget hasn't been added yet, stop.
            # We update in the widget() method.
            return

        if self._loading:
            new_st = ['disabled']
            set_tooltip(self.display, TransToken.BLANK)
            set_stringvar(self.disp_label, TRANS_LOADING)
        elif self._readonly:
            new_st = ['disabled']
            set_tooltip(self.display, self.readonly_description)
            if self.readonly_override is not None:
                set_stringvar(self.disp_label, self.readonly_override)
            else:
                data = self._get_data(self.chosen.value)
                set_stringvar(self.disp_label, data.context_lbl)
        else:
            new_st = ['!disabled']
            set_tooltip(self.display, self.description)
            data = self._get_data(self.chosen.value)
            set_stringvar(self.disp_label, data.context_lbl)

        self.disp_btn.state(new_st)
        self.display.state(new_st)

    def _get_data(self, item_id: utils.SpecialID) -> SelitemData:
        """Call func_get_data, handling KeyError."""
        try:
            return self.func_get_data(self._packset, item_id)
        except KeyError:
            LOGGER.warning('ID "{}" does not exist', item_id)
            return packages.SEL_DATA_MISSING

    def refresh(self) -> None:
        """Rebuild the menus and options based on the item list."""
        get_data = self._get_data

        def sort_func(item_id: utils.SpecialID) -> str:
            """Sort the item list. Special items go to the start, otherwise sort by the sort key."""
            if utils.special_id(item_id):
                return f'0{item_id}'
            else:
                return f'1{get_data(item_id).sort_key}'

        self.item_list.sort(key=sort_func)
        grouped_items = defaultdict(list)
        self.group_names = {'':  TRANS_GROUPLESS}
        # Ungrouped items appear directly in the menu.
        self.context_menus = {'': self.context_menu}
        self._menu_index.clear()
        self._id_to_button.clear()

        # First clear off the menu.
        self.context_menu.delete(0, 'end')

        for button in self._item_buttons:
            button.place_forget()

        while len(self._item_buttons) < len(self.item_list):
            button = ttk.Button(self.pal_frame)
            tk_tools.bind_leftclick(button, functools.partial(
                SelectorWin._evt_button_click, self, len(self._item_buttons),
            ))
            self._item_buttons.append(button)

        for item_id, button in zip(self.item_list, self._item_buttons, strict=False):
            data = self.func_get_data(self._packset, item_id)
            self._id_to_button[item_id] = button
            # Special icons have no text.
            button['compound'] = 'none' if utils.is_special_id(item_id) else 'top'
            if utils.is_special_id(item_id):
                button['compound'] = 'none'
                set_text(button, TransToken.BLANK)
            else:
                button['compound'] = 'top'
                set_text(button, data.short_name)

            group_key = data.group_id
            grouped_items[group_key].append(item_id)

            if group_key not in self.group_names:
                self.group_names[group_key] = data.group
            try:
                group = self.group_widgets[group_key]
            except KeyError:
                self.group_widgets[group_key] = group = GroupHeader(
                    self,
                    self.group_names[group_key],
                    tk.Menu(self.context_menu) if group_key else self.context_menu,
                )
            group.menu.add_radiobutton(
                command=functools.partial(self.sel_item_id, item_id),
                variable=self.context_var,
                value=item_id,
            )
            set_menu_text(group.menu, data.context_lbl)
            menu_pos = group.menu.index('end')
            assert menu_pos is not None, "Didn't add to the menu?"
            self._menu_index[item_id] = menu_pos

        # Convert to a normal dictionary, after adding all items.
        self.grouped_items = dict(grouped_items)

        # Figure out the order for the groups - alphabetical.
        # Note - empty string should sort to the beginning!
        self.group_order[:] = sorted(self.grouped_items.keys())

        for group_key in self.group_order:
            if group_key == '':
                # Don't add the ungrouped menu to itself!
                continue
            group = self.group_widgets[group_key]
            self.context_menu.add_cascade(menu=group.menu)
            set_menu_text(self.context_menu, self.group_names[group_key])
            # Track the menu's index. The one at the end is the one we just added.
            menu_pos = self.context_menu.index('end')
            assert menu_pos is not None, "Didn't add to the menu?"
            group.menu_pos = menu_pos
        if self.win.winfo_ismapped():
            self.flow_items()

    def exit(self, _: object = None) -> None:
        """Quit and cancel, choosing the originally-selected item."""
        self.selected = self.chosen.value
        self.save()

    def save(self, _: object = None) -> None:
        """Save the selected item, close the window.."""
        # Stop sample sounds if they're playing
        if self.sampler is not None:
            self.sampler.stop()

        for button in self._item_buttons:
            # Un-press everything, clear icons to allow them to unload.
            button.state(('!alternate', '!pressed', '!active'))
            TK_IMG.apply(button, None)

        if not self.first_open:  # We've got state to store.
            state = SelectorState(
                open_groups={
                    grp_id: grp.visible
                    for grp_id, grp in self.group_widgets.items()
                },
                width=self.win.winfo_width(),
                height=self.win.winfo_height(),
            )
            config.APP.store_conf(state, self.save_id)

        if self.modal:
            self.win.grab_release()
        self.win.withdraw()
        self.choose_item(self.selected)
        self.prop_desc.set_text('')  # Free resources used.

    def set_disp(self, _: object = None) -> str:
        """Set the display textbox."""
        chosen = self.chosen.value
        # Bold the text if the suggested item is selected (like the
        # context menu).
        if self.display is not None:
            if self.is_suggested():
                self.display['font'] = self.sugg_font
            else:
                self.display['font'] = self.norm_font

        self._suggested_rollover = None  # Discard the rolled over item.
        self._apply_load_readonly_state()
        self.context_var.set(chosen)
        return "break"  # stop the entry widget from continuing with this event

    def _evt_button_click(self, index: int, _: object) -> None:
        """Handle clicking on an item.

        If it's already selected, save and close the window.
        """
        try:
            item_id = self.item_list[index]
        except IndexError:
            return  # Shouldn't be visible.
        if item_id == self.selected:
            self.save()
        else:
            self.sel_item_id(item_id)

    def rollover_suggest(self) -> None:
        """Pick a suggested item when the button is moused over, and keep cycling."""
        if self.can_suggest():
            if self.display is not None:
                self.display['font'] = self.mouseover_font
            self._pick_suggested(force=True)

    def _pick_suggested(self, force: bool = False) -> None:
        """Randomly select a suggested item."""
        if self.suggested and (force or self._suggested_rollover is not None):
            self._suggested_rollover = random.choice(self.suggested)
            data = self._get_data(self._suggested_rollover)
            set_stringvar(self.disp_label, data.context_lbl)
            self.win.after(1000, self._pick_suggested)

    async def _load_selected_task(self) -> None:
        """When configs change, load new items."""
        selected: LastSelected
        with config.APP.get_ui_channel(LastSelected, self.save_id) as channel:
            async for selected in channel:
                self.sel_item_id(selected.id)
                self.save()

    def _icon_clicked(self, _: tk.Event[tk.Misc]) -> None:
        """When the large image is clicked, either show the previews or play sounds."""
        if self.sampler:
            self.sampler.play_sample()
            return
        data = self._get_data(self.selected)
        if data.previews:
            _PREVIEW.show(self, data)

    def open_win(self, _: object = None) -> object:
        """Display the window."""
        if self._readonly:
            TK_ROOT.bell()
            return 'break'  # Tell tk to stop processing this event

        for item_id, button in zip(self.item_list, self._item_buttons, strict=False):
            TK_IMG.apply(button, self._get_data(item_id).icon)

        # Restore configured states.
        if self.first_open:
            self.first_open = False
            try:
                state = config.APP.get_cur_conf(SelectorState, self.save_id)
            except KeyError:
                pass
            else:
                LOGGER.debug(
                    'Restoring saved selectorwin state "{}" = {}',
                    self.save_id, state,
                )
                for grp_id, is_open in state.open_groups.items():
                    try:
                        self.group_widgets[grp_id].visible = is_open
                    except KeyError:  # Stale config, ignore.
                        LOGGER.warning(
                            '({}): invalid selectorwin group: "{}"',
                            self.save_id, grp_id,
                        )
                if state.width > 0 or state.height > 0:
                    width = state.width if state.width > 0 else self.win.winfo_reqwidth()
                    height = state.height if state.height > 0 else self.win.winfo_reqheight()
                    self.win.geometry(f'{width}x{height}')

        self.win.deiconify()
        self.win.lift()

        if self.modal:
            self.win.grab_set()
        self.win.focus_force()  # Focus here to deselect the textbox

        tk_tools.center_win(self.win, parent=self.parent)

        self.sel_item(self.chosen.value)
        self.win.after(2, self.flow_items)
        return None

    def open_context(self, _: object = None) -> None:
        """Dislay the context window at the text widget."""
        if not self._readonly and not self._loading and self.display is not None:
            self.context_menu.post(
                self.display.winfo_rootx(),
                self.display.winfo_rooty() + self.display.winfo_height())

    def sel_suggested(self) -> None:
        """Select the suggested item."""
        # Pick the hovered item.
        if self._suggested_rollover is not None:
            self.choose_item(self._suggested_rollover)
        # Not hovering, but we have some, randomly pick.
        elif self.suggested:
            # Do not re-pick the same item if we can avoid it.
            if self.selected in self.suggested and len(self.suggested) > 1:
                pool = self.suggested.copy()
                pool.remove(self.selected)
            else:
                pool = self.suggested
            self.choose_item(random.choice(pool))

    def sel_item_id(self, it_id: str) -> bool:
        """Select the item with the given ID."""
        item_id = utils.special_id(it_id)
        if item_id in self.item_list:
            self.choose_item(item_id)
            return True
        return False

    def choose_item(self, item_id: utils.SpecialID) -> None:
        """Set the current item to this one."""
        self.sel_item(item_id)
        self.chosen.value = item_id
        self.set_disp()
        if self.store_last_selected:
            config.APP.store_conf(LastSelected(item_id), self.save_id)

    def sel_item(self, item_id: utils.SpecialID, _: object = None) -> None:
        """Select the specified item in the UI, but don't actually choose it."""
        data = self._get_data(item_id)

        set_text(self.prop_name, data.name)
        if utils.is_special_id(item_id):
            set_text(self.prop_author, TransToken.BLANK)
        elif len(data.auth) == 0:
            set_text(self.prop_author, TRANS_NO_AUTHORS)
        else:
            set_text(self.prop_author, TRANS_AUTHORS.format(
                authors=TransToken.list_and(TransToken.untranslated(auth) for auth in data.auth),
                n=len(data.auth),
            ))

        # Change aspect ratio to match the large icon.
        TK_IMG.apply(self.prop_icon, data.large_icon)
        self.prop_icon_frm.configure(width=data.large_icon.width, height=data.large_icon.height)

        if data.previews and not self.sampler:
            self.prop_icon['cursor'] = tk_tools.Cursors.ZOOM_IN
        else:
            self.prop_icon['cursor'] = tk_tools.Cursors.REGULAR

        if DEV_MODE.value:
            # Show the ID of the item in the description
            text = tkMarkdown.convert(TRANS_DEV_ITEM_ID.format(
                item=f'`{', '.join(data.packages)}`:`{item_id}`' if data.packages else f'`{item_id}`',
            ), None)
            self.prop_desc.set_text(tkMarkdown.join(
                text,
                tkMarkdown.MarkdownData.text('\n'),
                data.desc,
            ))
        else:
            self.prop_desc.set_text(data.desc)

        try:
            self._id_to_button[self.selected].state(('!alternate', ))
        except KeyError:
            pass
        try:
            self._id_to_button[item_id].state(('alternate', ))
        except KeyError:
            # Should never happen, but don't crash..
            LOGGER.warning('No button for item {}??', item_id)

        self.selected = item_id
        self.scroll_to(item_id)

        if self.sampler:
            assert self.samp_button is not None
            assert self.func_get_sample is not None
            is_playing = self.sampler.is_playing.value
            self.sampler.stop()

            self.sampler.cur_file = self.func_get_sample(self._packset, item_id)
            if self.sampler.cur_file:
                self.samp_button.state(('!disabled',))

                if is_playing:
                    # Start the sampler again, so it plays the current item!
                    self.sampler.play_sample()
            else:
                self.samp_button.state(('disabled',))

        if self.has_def:
            if self.can_suggest():
                self.prop_reset.state(('!disabled',))
            else:
                self.prop_reset.state(('disabled',))

        # Set the attribute items.
        item_attrs = self.func_get_attr(self._packset, item_id)
        for attr in self.attrs:
            val = item_attrs.get(attr.id, attr.default)
            attr_label = self.attr_labels[attr.id]

            if attr.type is AttrTypes.BOOL:
                TK_IMG.apply(attr_label, ICON_CHECK if val else ICON_CROSS)
            elif attr.type is AttrTypes.COLOR:
                assert isinstance(val, Vec)
                TK_IMG.apply(attr_label, img.Handle.color(val, 16, 16))
                # Display the full color when hovering...
                set_tooltip(attr_label, TRANS_ATTR_COLOR.format(
                    r=int(val.x), g=int(val.y), b=int(val.z),
                ))
            elif attr.type.is_list:
                # Join the values (in alphabetical order)
                assert isinstance(val, Iterable) and not isinstance(val, Vec), repr(val)
                children = [
                    txt if isinstance(txt, TransToken) else TransToken.untranslated(txt)
                    for txt in val
                ]
                if attr.type is AttrTypes.LIST_AND:
                    set_text(attr_label, TransToken.list_and(children, sort=True))
                else:
                    set_text(attr_label, TransToken.list_or(children, sort=True))
            elif attr.type is AttrTypes.STRING:
                # Just a string.
                if not isinstance(val, TransToken):
                    val = TransToken.untranslated(str(val))
                set_text(attr_label, val)
            else:
                raise ValueError(f'Invalid attribute type: "{attr.type}"')

    def key_navigate(self, event: tk.Event[tk.Misc]) -> None:
        """Navigate using arrow keys.

        Allowed keys are set in NAV_KEYS
        """
        try:
            key = NAV_KEYS(event.keysym)
        except (ValueError, AttributeError):
            LOGGER.debug(
                'Invalid nav-key in event: {}',
                event.__dict__
            )
            return

        if key is NAV_KEYS.PLAY_SOUND:
            if self.sampler is not None:
                self.sampler.play_sample()
            return
        elif key is NAV_KEYS.ENTER:
            self.save()
            return

        cur_group_name = self._get_data(self.selected).group_id
        cur_group = self.grouped_items[cur_group_name]
        # Force the current group to be visible, so you can see what's
        # happening.
        self.group_widgets[cur_group_name].visible = True

        # A list of groups names, in the order that they're visible onscreen
        # (skipping hidden ones). Force-include
        ordered_groups = [
            group_name
            for group_name in self.group_order
            if self.group_widgets[group_name].visible
        ]

        if not ordered_groups:
            return  # No visible items!

        if key is NAV_KEYS.HOME:
            self._offset_select(
                ordered_groups,
                group_ind=-1,
                item_ind=0,
            )
            return
        elif key is NAV_KEYS.END:
            self._offset_select(
                ordered_groups,
                group_ind=len(ordered_groups),
                item_ind=0,
            )
            return

        # The index in the current group for an item
        try:
            item_ind = cur_group.index(self.selected)
        except IndexError:
            return  # Not present?
        # The index in the visible groups
        group_ind = ordered_groups.index(cur_group_name)

        if key is NAV_KEYS.LF:
            item_ind -= 1
        elif key is NAV_KEYS.RT:
            item_ind += 1
        elif key is NAV_KEYS.UP:
            item_ind -= self.item_width
        elif key is NAV_KEYS.DN:
            item_ind += self.item_width

        self._offset_select(
            ordered_groups,
            group_ind,
            item_ind,
            key is NAV_KEYS.UP or key is NAV_KEYS.DN,
        )

    def _offset_select(self, group_list: list[str], group_ind: int, item_ind: int, is_vert: bool = False) -> None:
        """Helper for key_navigate(), jump to the given index in a group.

        group_list is sorted list of group names.
        group_ind is the index of the current group, and item_ind is the index
        in that group to move to.
        If the index is above or below, it will jump to neighbouring groups.
        """
        if group_ind < 0:  # Jump to the first item, out of bounds
            first_group = self.grouped_items[self.group_order[0]]
            self.sel_item(first_group[0])
            return
        elif group_ind >= len(group_list):  # Ditto, last group
            last_group = self.grouped_items[self.group_order[-1]]
            self.sel_item(last_group[-1])
            return

        cur_group = self.grouped_items[group_list[group_ind]]

        # Go back a group...
        if item_ind < 0:
            if group_ind == 0:  # First group - can't go back further!
                self.sel_item(cur_group[0])
            else:
                prev_group = self.grouped_items[group_list[group_ind - 1]]
                if is_vert:
                    # Jump to the same horizontal position..
                    row_num = math.ceil(len(prev_group) / self.item_width)
                    item_ind += row_num * self.item_width
                    if item_ind >= len(prev_group):
                        # The last row is missing an item at this spot.
                        # Jump back another row again.
                        item_ind -= self.item_width
                else:
                    item_ind += len(prev_group)
                # Recurse to check the previous group..
                self._offset_select(
                    group_list,
                    group_ind - 1,
                    item_ind,
                )

        # Go forward a group...
        elif item_ind >= len(cur_group):
            #  Last group - can't go forward further!
            if group_ind == len(group_list):
                self.sel_item(cur_group[-1])
            else:
                # Recurse to check the next group...
                if is_vert:
                    # We just jump to the same horizontal position.
                    item_ind %= self.item_width
                else:
                    item_ind -= len(cur_group)

                self._offset_select(
                    group_list,
                    group_ind + 1,
                    item_ind,
                )

        else:  # Within this group
            self.sel_item(cur_group[item_ind])

    def flow_items(self, _: object = None) -> None:
        """Reposition all the items to fit in the current geometry.

        Called on the <Configure> event.
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

        # Hide suggestion indicators if they end up unused.
        for lbl in self._suggest_lbl:
            lbl.place_forget()
        suggest_ind = 0

        # If only the '' group is present, force it to be visible, and hide
        # the header.
        no_groups = self.group_order == ['']

        for group_key in self.group_order:
            items = self.grouped_items[group_key]
            group_wid = self.group_widgets[group_key]

            if no_groups:
                group_wid.place_forget()
            else:
                group_wid.place(
                    x=0,
                    y=y_off,
                    width=width * ITEM_WIDTH,
                )
                group_wid.update_idletasks()
                y_off += group_wid.winfo_reqheight()

                if not group_wid.visible:
                    # Hide everything!
                    for item_id in items:
                        self._id_to_button[item_id].place_forget()
                    continue

            # Place each item
            for i, item_id in enumerate(items):
                button = self._id_to_button[item_id]
                if item_id in self.suggested:
                    # Reuse an existing suggested label.
                    try:
                        sugg_lbl = self._suggest_lbl[suggest_ind]
                    except IndexError:
                        # Not enough, make more.
                        if utils.MAC:
                            # Labelframe doesn't look good here on OSX
                            sugg_lbl = ttk.Label(
                                self.pal_frame,
                                name=f'suggest_label_{suggest_ind}',
                            )
                            set_text(sugg_lbl, TRANS_SUGGESTED_MAC)
                        else:
                            sugg_lbl = ttk.LabelFrame(
                                self.pal_frame,
                                name=f'suggest_label_{suggest_ind}',
                                labelanchor='n',
                                height=50,
                            )
                            set_text(sugg_lbl, TRANS_SUGGESTED)
                        self._suggest_lbl.append(sugg_lbl)
                    suggest_ind += 1
                    sugg_lbl.place(
                        x=(i % width) * ITEM_WIDTH + 1,
                        y=(i // width) * ITEM_HEIGHT + y_off,
                    )
                    sugg_lbl['width'] = button.winfo_width()
                button.place(
                    x=(i % width) * ITEM_WIDTH + 1,
                    y=(i // width) * ITEM_HEIGHT + y_off + 20,
                )
                button.lift()

            # Increase the offset by the total height of this item section
            y_off += math.ceil(len(items) / width) * ITEM_HEIGHT + 5

        # Set the size of the canvas and frame to the amount we've used
        self.wid_canvas['scrollregion'] = (
            0, 0,
            width * ITEM_WIDTH,
            y_off,
        )
        self.pal_frame['height'] = y_off

    def scroll_to(self, item_id: utils.SpecialID) -> None:
        """Scroll to an item so it's visible."""
        try:
            button = self._id_to_button[item_id]
        except KeyError:
            return  # Can't scroll to something that doesn't exist.

        canvas = self.wid_canvas

        height = canvas.bbox('all')[3]  # Returns (x, y, width, height)

        bottom, top = canvas.yview()
        # The sizes are returned in fractions, but we use the pixel values
        # for accuracy
        bottom *= height
        top *= height

        y = button.winfo_y()

        if bottom <= y - 8 and y + ICON_SIZE + 8 <= top:
            return  # Already in view

        # Center in the view
        canvas.yview_moveto(
            (y - (top - bottom) // 2)
            / height
        )

    def is_suggested(self) -> bool:
        """Return whether the current item is a suggested one."""
        return self.chosen.value in self.suggested

    def can_suggest(self) -> bool:
        """Check if a new item can be suggested."""
        if not self.suggested:
            return False
        if len(self.suggested) > 1:
            return True
        # If we suggest one item which is selected, that's
        # pointless.
        return self.suggested != [self.chosen.value]

    def _set_context_font(self, item_id: utils.SpecialID, suggested: bool) -> None:
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

    def set_suggested(self, suggested: Container[str] = ()) -> None:
        """Set the suggested items to the set of IDs.

        If it is empty, the suggested ID will be cleared.
        """
        self.suggested.clear()
        # Reset all the header fonts, if any item in that group is highlighted it'll
        # re-bold it.
        for group_key, header in self.group_widgets.items():
            header.title['font'] = self.norm_font
            if header.menu_pos >= 0:
                self.context_menu.entryconfig(header.menu_pos, font=self.norm_font)

        for item_id in self.item_list:
            if item_id in suggested:
                self._set_context_font(item_id, True)
                self.suggested.append(item_id)
            else:
                self._set_context_font(item_id, False)

        self.set_disp()  # Update the textbox if necessary.
        # Reposition all our items, but only if we're visible.
        if self.win.winfo_ismapped():
            self.flow_items()
