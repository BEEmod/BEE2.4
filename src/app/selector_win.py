"""
A dialog used to select an item for things like Styles, Quotes, Music.

It appears as a textbox-like widget with a ... button to open the selection window.
Each item has a description, author, and icon.
"""
from __future__ import annotations

from tkinter import *  # ui library
from tkinter import font as tk_font
from tkinter import ttk  # themed ui components that match the OS

from collections import defaultdict
from enum import Enum
import functools
import operator
import math
from typing import Optional, Union, Iterable, Mapping, Callable, Any

import attr

from app.richTextBox import tkRichText
from app.tkMarkdown import MarkdownData
from app.tooltip import add_tooltip, set_tooltip
from packages import SelitemData
from srctools import Vec, EmptyMapping
import srctools.logger
from srctools.filesys import FileSystemChain
from app import tkMarkdown, tk_tools, sound, img, TK_ROOT
from consts import SEL_ICON_SIZE as ICON_SIZE, SEL_ICON_SIZE_LRG as ICON_SIZE_LRG
import utils


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

if __name__ == '__main__':
    import gettext
    gettext.NullTranslations().install(['ngettext'])


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


class AttrTypes(Enum):
    """The type of labels used for selectoritem attributes."""
    STR = STRING = 'string'  # Normal text
    LIST = 'list'  # A sequence, joined by commas
    BOOL = 'bool'  # A yes/no checkmark
    COLOR = COLOUR = 'color'  # A Vec 0-255 RGB colour


AttrValues =  Union[str, list, bool, Vec]


@attr.define
class AttrDef:
    """Configuration for attributes shown on selector labels."""
    id: str
    desc: str
    default: AttrValues
    type: AttrTypes

    @classmethod
    def string(cls, attr_id: str, desc='', default: str='') -> AttrDef:
        """Alternative constructor for string-type attrs."""
        if desc != '' and not desc.endswith(': '):
            desc += ': '
        return AttrDef(attr_id, desc, default, AttrTypes.STRING)

    @classmethod
    def list(cls, attr_id: str, desc='', default: list=None) -> AttrDef:
        """Alternative constructor for list-type attrs."""
        if default is None:
            default = []
        if desc != '' and not desc.endswith(': '):
            desc += ': '
        return AttrDef(attr_id, desc, default, AttrTypes.LIST)

    @classmethod
    def bool(cls, attr_id: str, desc='', default: bool=False) -> AttrDef:
        """Alternative constructor for bool-type attrs."""
        if desc != '' and not desc.endswith(': '):
            desc += ': '
        return AttrDef(attr_id, desc, default, AttrTypes.BOOL)

    @classmethod
    def color(cls, attr_id: str, desc='', default: Vec=None) -> AttrDef:
        """Alternative constructor for color-type attrs."""
        if default is None:
            default = Vec(255, 255, 255)
        if desc != '' and not desc.endswith(': '):
            desc += ': '
        return AttrDef(attr_id, desc, default, AttrTypes.COLOR)


class GroupHeader(ttk.Frame):
    """The widget used for group headers."""
    def __init__(self, win: selWin, title: str) -> None:
        self.parent = win
        super().__init__(
            win.pal_frame,
        )

        self.sep_left = ttk.Separator(self)
        self.sep_left.grid(row=0, column=0, sticky=EW)
        self.columnconfigure(0, weight=1)

        self.title = ttk.Label(
            self,
            text=title,
            font=win.norm_font,
            width=len(title) + 2,
            anchor=CENTER,
        )
        self.title.grid(row=0, column=1)

        self.sep_right = ttk.Separator(self)
        self.sep_right.grid(row=0, column=2, sticky=EW)
        self.columnconfigure(2, weight=1)

        self.arrow = ttk.Label(
            self,
            text=GRP_EXP,
            width=2,
        )
        self.arrow.grid(row=0, column=3)

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

    def toggle(self, _: Event = None) -> None:
        """Toggle the header on or off."""
        self.visible = not self._visible

    def hover_start(self, _: Event = None) -> None:
        """When hovered over, fill in the triangle."""
        self.arrow['text'] = (
            GRP_EXP_HOVER
            if self._visible else
            GRP_COLL_HOVER
        )

    def hover_end(self, _: Event = None) -> None:
        """When leaving, hollow the triangle."""
        self.arrow['text'] = (
            GRP_EXP
            if self._visible else
            GRP_COLL
        )


class Item:
    """An item on the panel.

    - name: The item ID, used to distinguish it from others.
    - longName: The full item name. This can be very long. If not set,
      this will be the same as the short name.
    - shortName: A shortened version of the full name. This should be <= 20
      characters.
    - context_lbl: The text shown on the rightclick menu. This is either
      the short or long name, depending on the size of the long name.
    - icon: The image handle for the item icon. The icon should be 96x96
      pixels large.
    - large_icon: If set, a different handle to use for the 192x192 icon.
    - desc: A MarkdownData value containing the description.
    - authors: A list of the item's authors.
    - group: Items with the same group name will be shown together.
    - attrs: a dictionary containing the attribute values for this item.
    - button, Set later, the button TK object for this item
    """
    __slots__ = [
        'name',
        'shortName',
        'longName',
        'icon',
        'large_icon',
        'desc',
        'authors',
        'group',
        'sort_key',
        'button',
        'snd_sample',
        'attrs',
        '_selector',
        '_context_lbl',
        '_context_ind',
    ]
    desc: MarkdownData

    def __init__(
        self,
        name,
        short_name: str,
        long_name: Optional[str] = None,
        icon: Optional[img.Handle]=None,
        large_icon: Optional[img.Handle] = None,
        authors: Iterable[str]=(),
        desc: Union[MarkdownData, str] = MarkdownData(),
        group: str = '',
        sort_key: Optional[str] = None,
        attributes: Mapping[str, AttrValues] = EmptyMapping,
        snd_sample: Optional[str] = None,
    ):
        self.name = name
        self.shortName = short_name
        self.group = group or ''
        self.longName = long_name or short_name
        self.sort_key = sort_key
        if len(self.longName) > 20:
            self._context_lbl = self.shortName
        else:
            self._context_lbl = self.longName

        if icon is not None:
            self.icon = icon
        else:
            self.icon = img.Handle.color(img.PETI_ITEM_BG, ICON_SIZE, ICON_SIZE)
        self.large_icon = large_icon

        if isinstance(desc, str):
            self.desc = tkMarkdown.convert(desc, None)
        else:
            self.desc = desc

        self.snd_sample = snd_sample
        self.authors: list[str] = list(authors)
        self.attrs: dict[str, AttrValues] = dict(attributes)
        # The button widget for this item.
        self.button: Optional[ttk.Button] = None
        # The selector window we belong to.
        self._selector: Optional[selWin] = None
        # The position on the menu this item is located at.
        # This is needed to change the font.
        self._context_ind: Optional[int] = None

    def __repr__(self) -> str:
        return f'<Item:{self.name}>'

    @property
    def context_lbl(self) -> str:
        """The text displayed on the rightclick menu."""
        return self._context_lbl

    @context_lbl.setter
    def context_lbl(self, value: str) -> None:
        """Update the context menu whenver this is set."""
        self._context_lbl = value
        if self._selector and self._context_ind:
            self._selector.context_menus[self.group.casefold()].entryconfigure(
                self._context_ind,
                label=value,
            )

    @classmethod
    def from_data(cls, obj_id, data: SelitemData, attrs: Mapping[str, AttrValues] = None) -> Item:
        """Create a selector Item from a SelitemData tuple."""
        return Item(
            name=obj_id,
            short_name=data.short_name,
            long_name=data.name,
            icon=data.icon,
            large_icon=data.large_icon,
            authors=data.auth,
            desc=data.desc,
            group=data.group,
            sort_key=data.sort_key,
            attributes=attrs,
        )

    def _on_click(self, _: Event = None) -> None:
        """Handle clicking on the item.

        If it's already selected, save and close the window.
        """
        if self._selector.selected is self:
            self._selector.save()
        else:
            self._selector.sel_item(self)

    def set_pos(self, x: int = None, y: int = None) -> None:
        """Place the item on the palette."""
        if x is None or y is None:
            # Remove from the window.
            self.button.place_forget()
        else:
            self.button.place(x=x, y=y)
            self.button.lift()  # Force a particular stacking order for widgets

    def copy(self) -> Item:
        """Duplicate an item."""
        item = Item.__new__(Item)
        item.name = self.name
        item.shortName = self.shortName
        item.longName = self.longName
        item.icon = self.icon
        item.large_icon = self.large_icon
        item.desc = self.desc.copy()
        item.authors = self.authors.copy()
        item.group = self.group
        item.sort_key = self.sort_key
        item.snd_sample = self.snd_sample
        item._context_lbl = self._context_lbl
        item.attrs = self.attrs

        item._selector = item.button = None
        return item


class selWin:
    """The selection window for skyboxes, music, goo and voice packs.

    Optionally an aditional 'None' item can be added, which indicates
    that no item is to be used.
    The string "<NONE>" is used for the none item's ID.

    Attributes:
    - selected_id: The currently-selected item ID. If set to None, the
      None Item is chosen.
    - callback: A function called whenever an item is chosen. The first
      argument is the selected ID.
    - callback_params: A list of additional parameters given to the callback.

    - wid: The Toplevel window for this selector dialog.
    - suggested: The Item which is suggested by the style.
    """
    def __init__(
        self,
        tk,
        lst: list[Item],
        *,  # Make all keyword-only for readability
        has_none=True,
        has_def=True,
        sound_sys: FileSystemChain=None,
        modal=False,
        # i18n: 'None' item description
        none_desc=_('Do not add anything.'),
        none_attrs=EmptyMapping,
        none_icon: img.Handle = img.Handle.parse_uri(img.PATH_NONE, ICON_SIZE, ICON_SIZE),
        # i18n: 'None' item name.
        none_name: str = _("<None>"),
        title: str = 'BEE2',
        desc: str = '',
        readonly_desc: str = '',
        callback: Callable[..., None]=None,
        callback_params: Iterable[Any]=(),
        attributes: Iterable[AttrDef]=(),
    ):
        """Create a window object.

        Read from .selected_id to get the currently-chosen Item name, or None
        if the <none> Item is selected.
        Args:
        - tk: Must be a Toplevel window, either the tk() root or another
        window if needed.
        - lst: A list of Item objects, defining the visible items.
        - If has_none is True, a <none> item will be added to the beginning
          of the list.
        - If has_def is True, the 'Reset to Default' button will appear,
          which resets to the suggested item.
        - If snd_sample_sys is set, a '>' button will appear next to names
          to play the associated audio sample for the item.
          The value should be a FileSystem to look for samples in.
        - none_desc holds an optional description for the <none> Item,
          which can be used to describe what it results in.
        - none_icon allows changing the icon for the <none> Item.
        - none_name allows setting the name shown for the <none> Item.
        - title is the title of the selector window.
        - callback is a function to be called whenever the selected item
         changes.
        - callback_params is a list of additional values which will be
          passed to the callback function.
          The first argument to the callback is always the selected item ID.
        - full_context controls if the short or long names are used for the
          context menu.
        - attributes is a list of AttrDef tuples.
          Each tuple should contain an ID, display text, and default value.
          If the values are True or False a check/cross will be displayed,
          otherwise they're a string.
        - desc is descriptive text to display on the window, and in the widget
          tooltip.
        - readonly_desc will be displayed on the widget tooltip when readonly.
        - modal: If True, the window will block others while open.
        """
        self.noneItem = Item(
            name='<NONE>',
            short_name='',
            icon=none_icon,
            desc=none_desc,
            attributes=dict(none_attrs),
        )
        self.noneItem.context_lbl = none_name

        # The textbox on the parent window.
        self.display: Optional[tk_tools.ReadOnlyEntry] = None

        # Variable associated with self.display.
        self.disp_label = StringVar()

        # The '...' button to open our window.
        self.disp_btn: Optional[ttk.Button] = None

        # ID of the currently chosen item
        self.chosen_id = None

        # Callback function, and positional arguments to pass
        if callback is not None:
            self.callback = callback
            self.callback_params = list(callback_params)
        else:
            self.callback = None
            self.callback_params = ()

        # Item object for the currently suggested item.
        self.suggested = None

        # Should we have the 'reset to default' button?
        self.has_def = has_def
        self.description = desc
        self.readonly_description = readonly_desc

        if has_none:
            self.item_list = [self.noneItem] + lst
        else:
            self.item_list = lst
        try:
            self.selected = self.item_list[0]  # type: Item
        except IndexError:
            LOGGER.error('No items for window "{}"!', title)
            # We crash without items, forcefully add the None item in so at
            # least this works.
            self.item_list = [self.noneItem]
            self.selected = self.noneItem

        self.orig_selected = self.selected
        self.parent = tk
        self._readonly = False
        self.modal = modal

        self.win = Toplevel(tk)
        self.win.withdraw()
        self.win.title("BEE2 - " + title)
        self.win.transient(master=tk)

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
        self.group_widgets: dict[str, GroupHeader] = {}
        # A map from folded name -> display name
        self.group_names = {}
        self.grouped_items: dict[str, list[Item]] = {}
        # A list of folded group names in the display order.
        self.group_order: list[str] = []

        # The maximum number of items that fits per row (set in flow_items)
        self.item_width = 1

        if desc:
            self.desc_label = ttk.Label(
                self.win,
                text=desc,
                justify=LEFT,
                anchor=W,
                width=5,  # Keep a small width, so this doesn't affect the
                # initial window size.
            )
            self.desc_label.grid(row=0, column=0, sticky='EW')
        else:
            self.desc_label = None

        # PanedWindow allows resizing the two areas independently.
        self.pane_win = PanedWindow(
            self.win,
            orient=HORIZONTAL,
            sashpad=2,  # Padding above/below panes
            sashwidth=3,  # Width of border
            sashrelief=RAISED,  # Raise the border between panes
        )
        self.pane_win.grid(row=1, column=0, sticky="NSEW")
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(1, weight=1)

        shim = ttk.Frame(self.pane_win, relief="sunken")
        shim.rowconfigure(0, weight=1)
        shim.columnconfigure(0, weight=1)

        # We need to use a canvas to allow scrolling.
        self.wid_canvas = Canvas(shim, highlightthickness=0)
        self.wid_canvas.grid(row=0, column=0, sticky="NSEW")

        # Add another frame inside to place labels on.
        self.pal_frame = ttk.Frame(self.wid_canvas)
        self.wid_canvas.create_window(1, 1, window=self.pal_frame, anchor="nw")

        self.wid_scroll = tk_tools.HidingScroll(
            shim,
            orient=VERTICAL,
            command=self.wid_canvas.yview,
        )
        self.wid_scroll.grid(row=0, column=1, sticky="NS")
        self.wid_canvas['yscrollcommand'] = self.wid_scroll.set

        tk_tools.add_mousewheel(self.wid_canvas, self.win)

        if utils.MAC:
            # Labelframe doesn't look good here on OSX
            self.sugg_lbl = ttk.Label(
                self.pal_frame,
                # Draw lines with box drawing characters
                text="\u250E\u2500" + _("Suggested") + "\u2500\u2512",
            )
        else:
            self.sugg_lbl = ttk.LabelFrame(
                self.pal_frame,
                text=_("Suggested"),
                labelanchor=N,
                height=50,
            )

        # Holds all the widgets which provide info for the current item.
        self.prop_frm = ttk.Frame(self.pane_win, borderwidth=4, relief='raised')
        self.prop_frm.columnconfigure(1, weight=1)

        # Border around the selected item icon.
        width, height = ICON_SIZE_LRG
        self.prop_icon_frm = ttk.Frame(
            self.prop_frm,
            borderwidth=4,
            relief='raised',
            width=width,
            height=height,
        )
        self.prop_icon_frm.grid(row=0, column=0, columnspan=4)

        self.prop_icon = ttk.Label(self.prop_icon_frm)
        img.apply(self.prop_icon, img.Handle.color(img.PETI_ITEM_BG, *ICON_SIZE_LRG)),
        self.prop_icon.grid(row=0, column=0)
        self.prop_icon_frm.configure(dict(zip(('width', 'height'), ICON_SIZE_LRG)))

        name_frame = ttk.Frame(self.prop_frm)

        self.prop_name = ttk.Label(
            name_frame,
            text="Item",
            justify=CENTER,
            font=("Helvetica", 12, "bold"),
        )
        name_frame.grid(row=1, column=0, columnspan=4)
        name_frame.columnconfigure(0, weight=1)
        self.prop_name.grid(row=0, column=0)

        # For music items, add a '>' button to play sound samples
        if sound_sys is not None and sound.has_sound():
            self.samp_button = samp_button = ttk.Button(
                name_frame,
                text=BTN_PLAY,
                width=2,
            )
            samp_button.grid(row=0, column=1)
            add_tooltip(
                samp_button,
                _("Play a sample of this item."),
            )

            # On start/stop, update the button label.
            self.sampler = sound.SamplePlayer(
                stop_callback=functools.partial(operator.setitem, samp_button, 'text', BTN_PLAY),
                start_callback=functools.partial(operator.setitem, samp_button, 'text', BTN_STOP),
                system=sound_sys,
            )
            samp_button['command'] = self.sampler.play_sample
            tk_tools.bind_leftclick(self.prop_icon, self.sampler.play_sample)
            samp_button.state(('disabled',))
        else:
            self.sampler = None

        # If we have a sound sampler, hold the system open while the window
        # is so it doesn't snap open/closed while finding files.
        self.sampler_held_open = False

        self.prop_author = ttk.Label(self.prop_frm, text="Author")
        self.prop_author.grid(row=2, column=0, columnspan=4)

        self.prop_desc_frm = ttk.Frame(self.prop_frm, relief="sunken")
        self.prop_desc_frm.grid(row=4, column=0, columnspan=4, sticky="NSEW")
        self.prop_desc_frm.rowconfigure(0, weight=1)
        self.prop_desc_frm.columnconfigure(0, weight=1)
        self.prop_frm.rowconfigure(4, weight=1)

        self.prop_desc = tkRichText(
            self.prop_desc_frm,
            width=40,
            height=4,
            font="TkSmallCaptionFont",
        )
        self.prop_desc.grid(
            row=0,
            column=0,
            padx=(2, 0),
            pady=2,
            sticky='NSEW',
        )

        self.prop_scroll = tk_tools.HidingScroll(
            self.prop_desc_frm,
            orient=VERTICAL,
            command=self.prop_desc.yview,
        )
        self.prop_scroll.grid(
            row=0,
            column=1,
            sticky="NS",
            padx=(0, 2),
            pady=2,
        )
        self.prop_desc['yscrollcommand'] = self.prop_scroll.set

        ttk.Button(
            self.prop_frm,
            text=_("OK"),
            command=self.save,
        ).grid(
            row=6,
            column=0,
            padx=(8, 8),
            )

        if self.has_def:
            self.prop_reset = ttk.Button(
                self.prop_frm,
                text=_("Reset to Default"),
                command=self.sel_suggested,
            )
            self.prop_reset.grid(
                row=6,
                column=1,
                sticky='EW',
            )

        ttk.Button(
            self.prop_frm,
            text=_("Cancel"),
            command=self.exit,
        ).grid(
            row=6,
            column=2,
            padx=(8, 8),
        )

        self.win.option_add('*tearOff', False)
        self.context_menu = Menu(self.win)

        self.norm_font: tk_font.Font = tk_font.nametofont('TkMenuFont')

        # Make a font for showing suggested items in the context menu
        self.sugg_font: tk_font.Font = self.norm_font.copy()
        self.sugg_font['weight'] = tk_font.BOLD

        # Make a font for previewing the suggested item
        self.mouseover_font: tk_font.Font = self.norm_font.copy()
        self.mouseover_font['slant'] = tk_font.ITALIC

        # The headers for the context menu
        self.context_menus: dict[str, Menu] = {}
        # The widget used to control which menu option is selected.
        self.context_var = StringVar()

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

        if attributes:
            attr_frame = ttk.Frame(self.prop_frm)
            attr_frame.grid(
                row=5,
                column=0,
                columnspan=3,
                sticky=EW,
            )

            self.attr = {}
            # Add in all the attribute labels
            for index, attrib in enumerate(attributes):
                desc_label = ttk.Label(
                    attr_frame,
                    text=attrib.desc,
                )
                self.attr[attrib.id] = val_label = ttk.Label(
                    attr_frame,
                )
                val_label.default = attrib.default
                val_label.type = attrib.type
                if attrib.type is AttrTypes.BOOL:
                    # It's a tick/cross label
                    if attrib.default:
                        img.apply(val_label, ICON_CHECK)
                    else:
                        img.apply(val_label, ICON_CROSS)
                elif attrib.type is AttrTypes.COLOR:
                    # A small colour swatch.
                    val_label.configure(relief=RAISED)
                    # Show the color value when hovered.
                    add_tooltip(val_label)

                # Position in a 2-wide grid
                desc_label.grid(
                    row=index // 2,
                    column=(index % 2) * 2,
                    sticky=E,
                )
                val_label.grid(
                    row=index // 2,
                    column=(index % 2) * 2 + 1,
                    sticky=W,
                )
        else:
            self.attr = None

        self.refresh()
        self.wid_canvas.bind("<Configure>", self.flow_items)

    def widget(self, frame: Misc) -> ttk.Entry:
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
            width=1.5,
            command=self.open_win,
        )
        self.disp_btn.pack(side=RIGHT)

        add_tooltip(self.display, self.description, show_when_disabled=True)

        # Set this property again, which updates the description if we actually
        # are readonly.
        self.readonly = self._readonly

        self.save()

        return self.display

    @property
    def readonly(self) -> bool:
        """Setting the readonly property to True makes the option read-only.

        The window cannot be opened, and all other inputs will fail.
        """
        return self._readonly

    @readonly.setter
    def readonly(self, value: bool) -> None:
        self._readonly = bool(value)
        if self.display is None:
            # Widget hasn't been added yet, stop.
            # We update in the widget() method.
            return

        if value:
            new_st = ['disabled']
            set_tooltip(self.display, self.readonly_description)
        else:
            new_st = ['!disabled']
            set_tooltip(self.display, self.description)

        self.disp_btn.state(new_st)
        self.display.state(new_st)

    def refresh(self) -> None:
        """Rebuild the menus and options based on the item list."""
        # Sort alphabetically, preferring a sort key if present.
        self.item_list.sort(key=lambda it: (it is not self.noneItem, it.sort_key or it.longName))
        grouped_items = defaultdict(list)
        # If the item is groupless, use 'Other' for the header.
        self.group_names = {'':  _('Other')}
        # Ungrouped items appear directly in the menu.
        self.context_menus = {'': self.context_menu}

        # First clear off the menu.
        self.context_menu.delete(0, 'end')

        for item in self.item_list:
            # noinspection PyProtectedMember
            if item._selector is not None and item._selector is not self:
                raise ValueError(f'Item {item} reused on a different selector!')
            item._selector = self

            if item.button is None:  # New, create the button widget.
                if item is self.noneItem:
                    item.button = ttk.Button(self.pal_frame)
                    item.context_lbl = item.context_lbl
                else:
                    item.button = ttk.Button(
                        self.pal_frame,
                        text=item.shortName,
                        compound='top',
                    )

                # noinspection PyProtectedMember
                tk_tools.bind_leftclick(item.button, item._on_click)

            group_key = item.group.strip().casefold()
            grouped_items[group_key].append(item)

            if group_key not in self.group_names:
                self.group_names[group_key] = item.group
            if group_key not in self.group_widgets:
                self.group_widgets[group_key] = GroupHeader(self, self.group_names[group_key])

            try:
                menu = self.context_menus[group_key]
            except KeyError:
                self.context_menus[group_key] = menu = Menu(
                    self.context_menu,
                )

            menu.add_radiobutton(
                label=item.context_lbl,
                command=functools.partial(self.sel_item_id, item.name),
                variable=self.context_var,
                value=item.name,
            )
            item._context_ind = len(grouped_items[group_key]) - 1

        # Convert to a normal dictionary, after adding all items.
        self.grouped_items = dict(grouped_items)

        # Figure out the order for the groups - alphabetical.
        # Note - empty string should sort to the beginning!
        self.group_order[:] = sorted(self.grouped_items.keys())

        for (key, menu) in sorted(self.context_menus.items(), key=operator.itemgetter(0)):
            if key == '':
                # Don't add the ungrouped menu to itself!
                continue
            self.context_menu.add_cascade(
                menu=menu,
                label=self.group_names[key],
            )
            # Set a custom attribute to keep track of the menu's index.
            # The one at the end is the one we just added.
            menu._context_index = self.context_menu.index('end')
        self.flow_items()

    def exit(self, _: Event = None) -> None:
        """Quit and cancel, choosing the originally-selected item."""
        self.sel_item(self.orig_selected)
        self.save()

    def save(self, _: Event = None) -> None:
        """Save the selected item into the textbox."""
        # Stop sample sounds if they're playing
        if self.sampler is not None:
            self.sampler.stop()

            # And close the reference we opened in open_win().
            if self.sampler_held_open is True:
                self.sampler_held_open = False
                self.sampler.system.close_ref()

        for item in self.item_list:
            if item.button is not None:
                img.apply(item.button, None)

        if self.modal:
            self.win.grab_release()
        self.win.withdraw()
        self.set_disp()
        self.do_callback()

    def set_disp(self, _: Event = None) -> str:
        """Set the display textbox."""
        # Bold the text if the suggested item is selected (like the
        # context menu). We check for truthness to ensure it's actually
        # initialised.
        if self.display:
            if self.is_suggested():
                self.display['font'] = self.sugg_font
            else:
                self.display['font'] = self.norm_font

        if self.selected == self.noneItem:
            self.chosen_id = None
        else:
            self.chosen_id = self.selected.name

        self.disp_label.set(self.selected.context_lbl)
        self.orig_selected = self.selected
        self.context_var.set(self.selected.name)
        return "break"  # stop the entry widget from continuing with this event

    def rollover_suggest(self) -> None:
        """Show the suggested item when the button is moused over."""
        if self.is_suggested() or self.suggested is None:
            # the suggested item is aready the suggested item
            # or no suggested item
            return
        self.display['font'] = self.mouseover_font
        self.disp_label.set(self.suggested.context_lbl)

    def open_win(self, _: Event = None, *, force_open=False) -> object:
        """Display the window."""
        if self._readonly and not force_open:
            TK_ROOT.bell()
            return 'break'  # Tell tk to stop processing this event

        for item in self.item_list:
            if item.button is not None:
                img.apply(item.button, item.icon)

        self.win.deiconify()
        self.win.lift(self.parent)
        if self.modal:
            self.win.grab_set()
        self.win.focus_force()  # Focus here to deselect the textbox

        # If we have a sound sampler, hold the system open while the window
        # is so it doesn't snap open/closed while finding files.
        if self.sampler is not None and self.sampler_held_open is False:
            self.sampler_held_open = True
            self.sampler.system.open_ref()

        utils.center_win(self.win, parent=self.parent)

        self.sel_item(self.selected)
        self.win.after(2, self.flow_items)

    def open_context(self, _: Event = None) -> None:
        """Dislay the context window at the text widget."""
        if not self._readonly:
            self.context_menu.post(
                self.display.winfo_rootx(),
                self.display.winfo_rooty() + self.display.winfo_height())

    def sel_suggested(self) -> None:
        """Select the suggested item."""
        if self.suggested is not None:
            self.sel_item(self.suggested)

    def do_callback(self) -> None:
        """Call the callback function."""
        if self.callback is not None:
            self.callback(self.chosen_id, *self.callback_params)

    def sel_item_id(self, it_id: str) -> bool:
        """Select the item with the given ID."""
        if self.selected.name == it_id:
            return True

        if it_id == '<NONE>':
            # No none item, pretend it doesn't exist...
            if self.noneItem not in self.item_list:
                return False
            self.sel_item(self.noneItem)
            self.set_disp()
            self.do_callback()
            return True
        else:
            for item in self.item_list:
                if item.name == it_id:
                    self.sel_item(item)
                    self.set_disp()
                    self.do_callback()
                    return True
            return False

    def sel_item(self, item: Item, event: Event = None) -> None:
        """Select the specified item."""
        from app.optionWindow import DEV_MODE
        self.prop_name['text'] = item.longName
        if len(item.authors) == 0:
            self.prop_author['text'] = ''
        else:
            self.prop_author['text'] = ngettext(
                'Author: {}', 'Authors: {}', len(item.authors),
            ).format(
                ', '.join(item.authors)
            )

        # We have a large icon, use it.
        icon = item.large_icon if item.large_icon is not None else item.icon
        img.apply(self.prop_icon, icon)
        self.prop_icon_frm.configure(width=icon.width, height=icon.height)

        if DEV_MODE.get():
            # Show the ID of the item in the description
            if item is self.noneItem:
                text = tkMarkdown.convert('**ID:** *NONE*', None)
            else:
                text = tkMarkdown.convert(f'**ID:** {item.name}', None)
            self.prop_desc.set_text(tkMarkdown.join(
                text,
                tkMarkdown.MarkdownData.text('\n'),
                item.desc,
            ))
        else:
            self.prop_desc.set_text(item.desc)

        self.selected.button.state(('!alternate',))
        self.selected = item
        item.button.state(('alternate',))
        self.scroll_to(item)

        if self.sampler:
            is_playing = self.sampler.is_playing
            self.sampler.stop()

            self.sampler.cur_file = item.snd_sample
            if self.sampler.cur_file:
                self.samp_button.state(('!disabled',))

                if is_playing:
                    # Start the sampler again, so it plays the current item!
                    self.sampler.play_sample()
            else:
                self.samp_button.state(('disabled',))

        if self.has_def:
            if self.suggested is None or self.selected == self.suggested:
                self.prop_reset.state(('disabled',))
            else:
                self.prop_reset.state(('!disabled',))

        if self.attr:
            # Set the attribute items.
            for attr_id, label in self.attr.items():
                val = item.attrs.get(attr_id, label.default)

                if label.type is AttrTypes.BOOL:
                    if val:
                        img.apply(label, ICON_CHECK)
                    else:
                        img.apply(label, ICON_CROSS)
                elif label.type is AttrTypes.COLOR:
                    img.apply(label, img.Handle.color(val, 16, 16))
                    # Display the full color when hovering..
                    # i18n: Tooltip for colour swatch.
                    set_tooltip(label, _('Color: R={r}, G={g}, B={b}').format(
                        r=int(val.x), g=int(val.y), b=int(val.z),
                    ))
                elif label.type is AttrTypes.LIST:
                    # Join the values (in alphabetical order)
                    label['text'] = ', '.join(sorted(val))
                elif label.type is AttrTypes.STRING:
                    # Just a string.
                    label['text'] = str(val)
                else:
                    raise ValueError(
                        'Invalid attribute type: "{}"'.format(label.type)
                    )

    def key_navigate(self, event: Event) -> None:
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

        # A list of groups names, in the order that they're visible onscreen
        # (skipping hidden ones).
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

        cur_group_name = self.selected.group.casefold()
        cur_group = self.grouped_items[cur_group_name]

        # The index in the current group for an item
        item_ind = cur_group.index(self.selected)
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

    def _offset_select(self, group_list: list[str], group_ind: int, item_ind: int, is_vert: bool=False) -> None:
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

        # Go back a group..
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

        # Go forward a group..
        elif item_ind >= len(cur_group):
            #  Last group - can't go forward further!
            if group_ind == len(group_list):
                self.sel_item(cur_group[-1])
            else:
                # Recurse to check the next group..
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

    def flow_items(self, _: Event = None) -> None:
        """Reposition all the items to fit in the current geometry.

        Called on the <Configure> event.
        """
        self.pal_frame.update_idletasks()
        self.pal_frame['width'] = self.wid_canvas.winfo_width()
        self.prop_name['wraplength'] = self.prop_desc.winfo_width()
        if self.desc_label is not None:
            self.desc_label['wraplength'] = self.win.winfo_width()

        width = (self.wid_canvas.winfo_width() - 10) // ITEM_WIDTH
        if width < 1:
            width = 1  # we got way too small, prevent division by zero
        self.item_width = width

        # The offset for the current group
        y_off = 0

        # Hide suggestion indicator if the item's not visible.
        self.sugg_lbl.place_forget()

        for group_key in self.group_order:
            items = self.grouped_items[group_key]
            group_wid = self.group_widgets[group_key]  # type: GroupHeader
            group_wid.place(
                x=0,
                y=y_off,
                width=width * ITEM_WIDTH,
            )
            group_wid.update_idletasks()
            y_off += group_wid.winfo_reqheight()

            if not group_wid.visible:
                # Hide everything!
                for item in items:  # type: Item
                    item.set_pos()
                continue

            # Place each item
            for i, item in enumerate(items):  # type: int, Item
                if item == self.suggested:
                    self.sugg_lbl.place(
                        x=(i % width) * ITEM_WIDTH + 1,
                        y=(i // width) * ITEM_HEIGHT + y_off,
                    )
                    self.sugg_lbl['width'] = item.button.winfo_width()
                item.set_pos(
                    x=(i % width) * ITEM_WIDTH + 1,
                    y=(i // width) * ITEM_HEIGHT + y_off + 20,
                )
                item.button['text'] = item.shortName

            # Increase the offset by the total height of this item section
            y_off += math.ceil(len(items) / width) * ITEM_HEIGHT + 5

        # Set the size of the canvas and frame to the amount we've used
        self.wid_canvas['scrollregion'] = (
            0, 0,
            width * ITEM_WIDTH,
            y_off,
        )
        self.pal_frame['height'] = y_off

    def scroll_to(self, item: Item) -> None:
        """Scroll to an item so it's visible."""
        canvas = self.wid_canvas

        height = canvas.bbox(ALL)[3]  # Returns (x, y, width, height)

        bottom, top = canvas.yview()
        # The sizes are returned in fractions, but we use the pixel values
        # for accuracy
        bottom *= height
        top *= height

        y = item.button.winfo_y()

        if bottom <= y - 8 and y + ICON_SIZE + 8 <= top:
            return  # Already in view

        # Center in the view
        canvas.yview_moveto(
            (y - (top - bottom) // 2)
            / height
        )

    def __contains__(self, obj: Union[str, Item]) -> bool:
        """Determine if the given SelWinItem or item ID is in this item list."""
        if obj == '<None>':
            return self.noneItem in self.item_list
        elif isinstance(obj, Item):
            return obj in self.item_list
        else:
            for item in self.item_list:
                if item.name == obj:
                    return True
            return False

    def is_suggested(self) -> bool:
        """Return whether the current item is the suggested one."""
        return self.suggested == self.selected

    def _set_context_font(self, item, new_font: tk_font.Font) -> None:
        """Set the font of an item, and its parent group."""

        if item.group:
            group_key = item.group.casefold()
            menu = self.context_menus[group_key]

            # Apply the font to the group header as well.
            self.group_widgets[group_key].title['font'] = new_font

            # Also highlight the menu
            # noinspection PyUnresolvedReferences, PyProtectedMember
            self.context_menu.entryconfig(
                menu._context_index,  # Use a custom attr to keep track of this...
                font=new_font,
            )
        else:
            menu = self.context_menu
        # noinspection PyProtectedMember
        menu.entryconfig(item._context_ind, font=new_font)

    def set_suggested(self, suggested: Optional[str] = None) -> None:
        """Set the suggested item to the given ID.

        If the ID is None or does not exist, the suggested item will be cleared.
        If the ID is "<NONE>", it will be set to the None item.
        """
        if self.suggested is not None:
            self._set_context_font(self.suggested, self.norm_font)
            # Remove the font from the last suggested item

        if suggested is None or suggested == '':
            self.suggested = None
        elif suggested == "<NONE>":
            self.suggested = self.noneItem
        else:
            for item in self.item_list:
                if item.name == suggested:
                    self.suggested = item
                    break
            else:  # Not found
                self.suggested = None

        if self.suggested is not None:
            self._set_context_font(self.suggested, self.sugg_font)
        self.set_disp()  # Update the textbox if needed
        # Reposition all our items, but only if we're visible.
        if self.win.winfo_ismapped():
            self.flow_items()


def test() -> None:
    """Setup a window with dummy data."""
    from BEE2_config import GEN_OPTS
    from packages import find_packages, PACKAGE_SYS
    from utils import PackagePath
    # Setup images to read from packages.
    print('Loading packages for images.')
    GEN_OPTS.load()
    find_packages(GEN_OPTS['Directories']['package'])
    img.load_filesystems(PACKAGE_SYS)
    print('Done.')

    lbl = ttk.Label(TK_ROOT, text="I am a demo window.")
    lbl.grid()
    TK_ROOT.geometry("+500+500")

    test_list = [
        Item(
            "SKY_BLACK",
            "Black",
            long_name="Darkness",
            icon=img.Handle.color((125, 0, 92), ICON_SIZE, ICON_SIZE),
            authors=["Valve"],
            desc='Pure black darkness. Nothing to see here.',
            attributes={
                'test_color': Vec(255, 32, 32),
                'astr': 'Dark',
                'test_bool_1': False,
                'test_bool_2': True,
            },
        ),
        Item(
            "SKY_BTS",
            "BTS",
            long_name="Behind The Scenes - Factory",
            icon=img.Handle.parse_uri(PackagePath("valve_clean_style", "voices/glados"), ICON_SIZE, ICON_SIZE),
            authors=["TeamSpen210"],

            desc='The dark constuction and office areas of Aperture.  '
                 'Catwalks extend between different buildings, with '
                 'vactubes and cranes carrying objects throughout '
                 'the facility.  \n'
                 'Abandoned offices can often be found here.\n\n'
                 '* This is a bullet point, with a\n second line'
                 '> white-on-black text',
            attributes={
                'test_color': Vec(40, 53, 64),
                'astr': 'Machinery',
                'test_bool_1': True,
                'test_bool_2': False,
                'listy': ['Chair', 'Panel', 'Turret']
            },
        ),
    ]

    window = selWin(
        TK_ROOT,
        test_list,
        has_none=True,
        has_def=True,
        callback=functools.partial(
            LOGGER.info,
            'Selected:',
        ),
        attributes=[
            AttrDef.color('test_color', "I'm a color.", Vec(128, 128, 128)),
            AttrDef.bool('test_bool_1', "'I'm a bool", False),
            AttrDef.bool('test_bool_2', "'I'm a bool", True),
            AttrDef.string('astr', 'Hi'),
            AttrDef.list('listy', 'Desc', ['a', 'b', 'c']),
        ],
    )
    window.widget(TK_ROOT).grid(row=1, column=0, sticky='EW')
    window.set_suggested("SKY_BLACK")

    def swap_read() -> None:
        """Toggle readonly."""
        window.readonly = not window.readonly

    ttk.Button(TK_ROOT, text='Readonly', command=swap_read).grid()

    TK_ROOT.deiconify()
    TK_ROOT.mainloop()
