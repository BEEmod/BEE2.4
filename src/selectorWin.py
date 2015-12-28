"""
A dialog used to select an item for things like Styles, Quotes, Music.

It appears as a textbox-like widget with a ... button to open the selection window.
Each item has a description, author, and icon.
"""
from tkinter import *  # ui library
from tkinter import font
from tkinter import ttk  # themed ui components that match the OS
from tk_tools import TK_ROOT
from collections import namedtuple
import functools
import math

import img  # png library for TKinter
from richTextBox import tkRichText
import utils
import tk_tools

LOGGER = utils.getLogger(__name__)

ICON_SIZE = 96  # Size of the selector win icons
ITEM_WIDTH = ICON_SIZE + (32 if utils.MAC else 16)
ITEM_HEIGHT = ICON_SIZE + 51

# The larger error icon used if an image is not found
err_icon = img.png('BEE2/error_96', resize_to=ICON_SIZE)

# The two icons used for boolean item attributes
ICON_CHECK = img.png('icons/check')
ICON_CROSS = img.png('icons/cross')


def _NO_OP(*args):
    """The default callback, triggered whenever the chosen item is changed."""
    pass

AttrDef = namedtuple('AttrDef', 'id desc default')

SelitemData = namedtuple(
    'SelitemData',
    'name, short_name, auth, icon, desc, group',
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
    - icon: The image object for the item icon. The icon should be 96x96
      pixels large.
    - ico_file: The file path for the image.
    - desc: A list of tuples, following the richTextBox text format.
    - authors: A list of the item's authors.
    - group: Items with the same group name will be shown together.
    - attrs: a dictionary containing the attribute values for this item.

    - button, win: Set later, the button and window TK objects for this item
    """
    __slots__ = [
        'name',
        'shortName',
        'longName',
        'icon',
        'desc',
        'authors',
        'group',
        'button',
        'win',
        'context_lbl',
        'ico_file',
        'attrs',
        ]

    def __init__(
            self,
            name: str,
            short_name: str,
            long_name: str=None,
            icon=None,
            authors: list=None,
            desc=(('line', ''),),
            group: str=None,
            attributes: dict=None,
            ):
        self.name = name
        self.shortName = short_name
        self.group = group
        self.longName = long_name or short_name
        if len(self.longName) > 20:
            self.context_lbl = self.shortName
        else:
            self.context_lbl = self.longName
        if icon is None:
            self.icon = img.png(
                'BEE2/blank_96',
                error=err_icon,
                resize_to=ICON_SIZE,
            )
            self.ico_file = 'BEE2/blank_96'
        else:
            self.icon = img.png(
                icon,
                error=err_icon,
                resize_to=ICON_SIZE,
            )
            self.ico_file = icon
        self.desc = desc
        self.authors = authors or []
        self.attrs = attributes or {}
        self.button = None
        self.win = None

    def __repr__(self):
        return (
            'Item({nm!r}, {shname!r}, {lname!r}, '
            '{ico!r}, {auth!r}, {desc!r})'.format(
                nm=self.name,
                shname=self.shortName,
                lname=self.longName,
                ico=self.ico_file,
                auth=self.authors,
                desc=self.desc,
            )
        )

    def __str__(self):
        return '<Item:' + self.name + '>'

    @classmethod
    def from_data(cls, obj_id, data: SelitemData, attrs=None):
        """Create a selector Item from a SelitemData tuple."""
        return Item(
            name=obj_id,
            short_name=data.short_name,
            long_name=data.name,
            icon=data.icon,
            authors=data.auth,
            desc=data.desc,
            group=data.group,
            attributes=attrs
        )


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

    :type suggested: Item | None
    """
    def __init__(
            self,
            tk,
            lst,
            has_none=True,
            has_def=True,
            none_desc=(('line', 'Do not add anything.'),),
            none_attrs: dict=utils.EmptyMapping,
            title='BEE2',
            callback=_NO_OP,
            callback_params=(),
            attributes=(),
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
        - none_desc holds an optional description for the <none> Item,
          which can be used to describe what it results in.
        - title is the title of the selector window.
        - callback is a function to be called whenever the selected item
         changes.
        - callback_params is a list of additional values which will be
          passed to the callback function.
          The first arguement to the callback is always the selected item ID.
        - full_context controls if the short or long names are used for the
          context menu.
        - attributes is a list of AttrDef tuples.
          Each tuple should contain an ID, display text, and default value.
          If the values are True or False a check/cross will be displayed,
          otherwise they're a string.
        """
        self.noneItem = Item(
            'NONE',
            '',
            desc=none_desc,
            attributes=dict(none_attrs),
        )
        self.noneItem.icon = img.png('BEE2/none_96')
        self.disp_label = StringVar()
        self.display = None
        self.disp_btn = None
        self.chosen_id = None
        self.callback = callback
        self.callback_params = callback_params
        self.suggested = None
        self.has_def = has_def

        if has_none:
            self.item_list = [self.noneItem] + lst
        else:
            self.item_list = lst
        self.selected = self.item_list[0]
        self.orig_selected = self.selected
        self.parent = tk
        self._readonly = False

        self.win = Toplevel(tk)
        self.win.withdraw()
        self.win.title("BEE2 - " + title)
        self.win.transient(master=tk)
        self.win.resizable(True, True)
        self.win.iconbitmap('../BEE2.ico')
        self.win.protocol("WM_DELETE_WINDOW", self.exit)
        self.win.bind("<Escape>", self.exit)

        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

        # PanedWindow allows resizing the two areas independently.
        self.pane_win = PanedWindow(
            self.win,
            orient=HORIZONTAL,
            sashpad=2,  # Padding above/below panes
            sashwidth=3,  # Width of border
            sashrelief=RAISED,  # Raise the border between panes
        )
        self.pane_win.grid(row=0, column=0, sticky="NSEW")
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(0, weight=1)

        self.wid = {}
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

        utils.add_mousewheel(self.wid_canvas, self.win)

        if utils.MAC:
            # Labelframe doesn't look good here on OSX
            self.sugg_lbl = ttk.Label(
                self.pal_frame,
                # Draw lines with box drawing characters
                text="\u250E\u2500Suggested\u2500\u2512"
            )
        else:
            self.sugg_lbl = ttk.LabelFrame(
                self.pal_frame,
                text="Suggested",
                labelanchor=N,
                height=50,
            )

        # Holds all the widgets which provide info for the current item.
        self.prop_frm = ttk.Frame(self.pane_win, borderwidth=4, relief='raised')
        self.prop_frm.columnconfigure(1, weight=1)

        # Border around the selected item icon.
        self.prop_icon_frm = ttk.Frame(
            self.prop_frm,
            borderwidth=4,
            relief='raised',
            width=ICON_SIZE,
            height=ICON_SIZE,
            )
        self.prop_icon_frm.grid(row=0, column=0, columnspan=4)

        self.prop_icon = ttk.Label(self.prop_icon_frm)
        self.prop_icon.img = img.png('BEE2/blank_96')
        self.prop_icon['image'] = self.prop_icon.img
        self.prop_icon.grid(row=0, column=0)

        self.prop_name = ttk.Label(
            self.prop_frm,
            text="Item",
            justify=CENTER,
            font=("Helvetica", 12, "bold"),
            )
        self.prop_name.grid(row=1, column=0, columnspan=4)
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
            text="OK",
            command=self.save,
            ).grid(
                row=6,
                column=0,
                padx=(8, 8),
                )

        if self.has_def:
            self.prop_reset = ttk.Button(
                self.prop_frm,
                text="Reset to Default",
                command=self.sel_suggested,
                )
            self.prop_reset.grid(
                row=6,
                column=1,
                sticky='EW',
                )

        ttk.Button(
            self.prop_frm,
            text="Cancel",
            command=self.exit,
            ).grid(
                row=6,
                column=2,
                padx=(8, 8),
                )

        self.win.option_add('*tearOff', False)
        self.context_menu = Menu(self.win)

        self.norm_font = font.nametofont('TkMenuFont')

        # Make a font for showing suggested items in the context menu
        self.sugg_font = self.norm_font.copy()
        self.sugg_font['weight'] = font.BOLD

        # Make a font for previewing the suggested item
        self.mouseover_font = self.norm_font.copy()
        self.mouseover_font['slant'] = font.ITALIC
        self.context_var = IntVar()

        # Re-order items appropriately.
        #
        self.item_list.sort(
            # Alphabetical order
            key=lambda it: it.longName
        )
        self.item_list.sort(
            # Sort by group name
            key=lambda it: it.group.casefold() if it.group else ''
        )
        self.item_list.sort(
            # Make non-grouped items go first
            key=lambda it: 2 if it.group else 1
        )

        for ind, item in enumerate(self.item_list):
            if item == self.noneItem:
                item.button = ttk.Button(
                    self.pal_frame,
                    image=item.icon,
                    )
                item.context_lbl = '<None>'
            else:
                item.button = ttk.Button(
                    self.pal_frame,
                    text=item.shortName,
                    image=item.icon,
                    compound='top',
                    )
            self.context_menu.add_radiobutton(
                label=item.context_lbl,
                command=functools.partial(self.sel_item_id, item.name),
                var=self.context_var,
                value=ind,
                )

            item.win = self.win
            utils.bind_leftclick(
                item.button,
                functools.partial(self.sel_item, item),
            )
            utils.bind_leftclick_double(
                item.button,
                self.save,
            )
        self.flow_items(None)
        self.wid_canvas.bind("<Configure>", self.flow_items)

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
            for index, (at_id, desc, value) in enumerate(attributes):
                desc_label = ttk.Label(
                    attr_frame,
                    text=desc,
                )
                self.attr[at_id] = val_label = ttk.Label(
                    attr_frame,
                )
                val_label.default = value
                if isinstance(value, bool):
                    # It's a tick/cross label
                    val_label['image'] = (
                        ICON_CHECK
                        if value else
                        ICON_CROSS,
                    )
                # Position in a 2-wide grid
                desc_label.grid(
                    row=index // 2,
                    column=(index % 2)*2,
                    sticky=E,
                )
                val_label.grid(
                    row=index // 2,
                    column=(index % 2)*2 + 1,
                    sticky=W,
                )
        else:
            self.attr = None

    def widget(self, frame) -> ttk.Entry:
        """Create the special textbox used to open the selector window.

        Use like 'selWin.widget(parent).grid(row=0, column=1)' to create
        and place the textbox.
        """

        self.display = tk_tools.ReadOnlyEntry(
            frame,
            textvariable=self.disp_label,
            cursor=utils.CURSORS['regular'],
        )
        utils.bind_leftclick(
            self.display,
            self.open_win,
        )
        self.display.bind("<Key>", self.set_disp)
        utils.bind_rightclick(
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

        self.save()

        return self.display

    @property
    def readonly(self):
        """Setting the readonly property to True makes the option read-only.

        The window cannot be opened, and all other inputs will fail.
        """
        return self._readonly

    @readonly.setter
    def readonly(self, value):
        self._readonly = bool(value)
        if value:
            new_st = ['disabled']
        else:
            new_st = ['!disabled']

        self.disp_btn.state(new_st)
        self.display.state(new_st)

    def exit(self, _=None):
        """Quit and cancel, choosing the originally-selected item."""
        self.sel_item(self.orig_selected)
        self.save()

    def save(self, _=None):
        """Save the selected item into the textbox."""
        self.win.grab_release()
        self.win.withdraw()
        self.set_disp()
        self.do_callback()

    def set_disp(self, _=None):
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
            self.disp_label.set("<None>")
            self.chosen_id = None
        else:
            self.disp_label.set(self.selected.context_lbl)
            self.chosen_id = self.selected.name
        self.orig_selected = self.selected
        self.context_var.set(self.item_list.index(self.selected))
        return "break"  # stop the entry widget from continuing with this event

    def rollover_suggest(self):
        """Show the suggested item when the  button is moused over."""
        if self.is_suggested() or self.suggested is None:
            # the suggested item is aready the suggested item
            # or no suggested item
            return
        self.display['font'] = self.mouseover_font
        self.disp_label.set(self.suggested.context_lbl)

    def open_win(self, _=None, force_open=False):
        if self._readonly and not force_open:
            TK_ROOT.bell()
            return 'break'  # Tell tk to stop processing this event

        self.win.deiconify()
        self.win.lift(self.parent)
        self.win.grab_set()
        self.win.focus_force()  # Focus here to deselect the textbox

        utils.center_win(self.win, parent=self.parent)

        self.flow_items()
        self.sel_item(self.selected)

    def open_context(self, _):
        """Dislay the context window at the text widget."""
        if not self._readonly:
            self.context_menu.post(
                self.display.winfo_rootx(),
                self.display.winfo_rooty() + self.display.winfo_height())

    def sel_suggested(self):
        """Select the suggested item."""
        if self.suggested is not None:
            self.sel_item(self.suggested)

    def do_callback(self):
        """Call the callback function."""
        self.callback(self.chosen_id, *self.callback_params)

    def sel_item_id(self, it_id):
        """Select the item with the given ID."""
        if it_id == '<NONE>':
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

    def sel_item(self, item: Item, _=None):
        self.prop_name['text'] = item.longName
        if len(item.authors) == 0:
            self.prop_author['text'] = ''
        elif len(item.authors) == 1:
            self.prop_author['text'] = 'Author: ' + item.authors[0]
        else:
            self.prop_author['text'] = 'Authors: ' + ', '.join(item.authors)
        self.prop_icon['image'] = item.icon

        self.prop_desc.set_text(item.desc)

        self.selected.button.state(('!alternate',))
        self.selected = item
        item.button.state(('alternate',))

        if self.has_def:
            if self.suggested is None or self.selected == self.suggested:
                self.prop_reset.state(('disabled',))
            else:
                self.prop_reset.state(('!disabled',))

        if self.attr:
            for attr_id, label in self.attr.items():
                val = item.attrs.get(attr_id, None)
                if val is None:
                    val = label.default
                if isinstance(label.default, bool):
                    label['image'] = (
                        ICON_CHECK
                        if val else
                        ICON_CROSS
                    )
                else:
                    # Display as text. If it's a container, sort alphabetically.
                    if isinstance(val, (list, tuple, set)):
                        val = ', '.join(sorted(val))
                    label['text'] = val


    def flow_items(self, _=None):
        """Reposition all the items to fit in the current geometry.

        Called on the <Configure> event.
        """
        self.pal_frame.update_idletasks()
        self.pal_frame['width'] = self.wid_canvas.winfo_width()
        self.prop_name['wraplength'] = self.prop_desc.winfo_width()
        width = (self.wid_canvas.winfo_width() - 10) // ITEM_WIDTH
        if width < 1:
            width = 1  # we got way too small, prevent division by zero
        num_items = len(self.item_list)
        self.wid_canvas['scrollregion'] = (
            0, 0,
            width*ITEM_WIDTH,
            math.ceil(num_items/width) * ITEM_HEIGHT+20
        )
        self.pal_frame['height'] = (
            math.ceil(num_items/width) * ITEM_HEIGHT+20
        )
        for i, item in enumerate(self.item_list):
            if item == self.suggested:
                self.sugg_lbl.place(
                    x=((i % width) * ITEM_WIDTH + 1),
                    y=((i // width) * ITEM_HEIGHT)
                )
                self.sugg_lbl['width'] = item.button.winfo_width()
            item.button.place(
                x=((i % width) * ITEM_WIDTH + 1),
                y=((i // width) * ITEM_HEIGHT + 20)
            )
            item.button.lift()

    def __contains__(self, obj):
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

    def is_suggested(self):
        """Return whether the current item is the suggested one."""
        return self.suggested == self.selected

    def set_suggested(self, suggested=None):
        """Set the suggested item to the given ID.

        If the ID is None or does not exist, the suggested item will be cleared.
        If the ID is "<NONE>", it will be set to the None item.
        """
        if self.suggested is not None:
            self.context_menu.entryconfig(
                self.item_list.index(self.suggested),
                font=self.norm_font)
            # Remove the font from the last suggested item

        if suggested is None:
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
            self.context_menu.entryconfig(
                self.item_list.index(self.suggested),
                font=self.sugg_font)
        self.set_disp()  # Update the textbox if needed
        self.flow_items()  # Refresh

if __name__ == '__main__':  # test the window if directly executing this file
    lbl = ttk.Label(TK_ROOT, text="I am a demo window.")
    lbl.grid()
    TK_ROOT.geometry("+500+500")

    test_list = [
        Item(
            "SKY_BLACK",
            "Black",
            long_name="Darkness",
            icon="skies/black",
            authors=["Valve"],
            desc=[
                ('line', 'Pure black darkness. Nothing to see here.'),
                ],
            ),
        Item(
            "SKY_BTS",
            "BTS",
            long_name="Behind The Scenes - Factory",
            icon="voices/glados",
            authors=["TeamSpen210"],
            desc=[
                ('line', 'The dark constuction and office areas of Aperture. '
                         'Catwalks extend between different buildings, with '
                         'vactubes and cranes carrying objects throughout '
                         'the facility.'),
                ('rule', ''),
                ('line', 'Abandoned offices can often be found here.'),
                ('bullet', 'This is a bullet point, with a\n second line'),
                ('invert', 'white-on-black text')
                ],
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
        )
    )
    window.widget(TK_ROOT).grid(row=1, column=0, sticky='EW')
    window.set_suggested("SKY_BLACK")

    def swap_read():
        window.readonly = not window.readonly

    ttk.Button(TK_ROOT, text='Readonly', command=swap_read).grid()

    TK_ROOT.deiconify()
    TK_ROOT.mainloop()