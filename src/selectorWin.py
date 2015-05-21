"""
A dialog used to select an item for things like Styles, Quotes, Music.

It appears as a textbox-like widget with a ... button to open the selection window.
Each item has a description, author, and icon.
"""
from tkinter import *  # ui library
from tkinter import font
from tkinter import ttk  # themed ui components that match the OS
import functools
import math

import BEE_png as png  # png library for TKinter
from richTextBox import tkRichText

ICON_SIZE = 96  # Size of the selector win icons
ITEM_WIDTH = ICON_SIZE+16
ITEM_HEIGHT = ICON_SIZE+51

err_icon = png.png('BEE2/error_96', resize_to=96)


def _NO_OP(*args):
    """The default callback, triggered whenever the chosen item is changed."""
    pass


class Item:
    """An item on the panel.

    - name: The item ID, used to distinguish it from others.
    - longName: The full item name. This can be very long. If not set,
      this will be the same as the short name.
    - shortName: A shortened version of the full name. This should be <= 20
      characters.
    - icon: The path for the item icon. The icon should be 96x96 pixels large.
    - desc: A list of tuples, following the richTextBox text format.
    - authors: A list of the item's authors.
    """
    __slots__ = [
        'name',
        'shortName',
        'longName',
        'icon',
        'desc',
        'authors',
        'button',
        'win',
        'context_lbl',
        'ico_file',
        ]

    def __init__(
            self,
            name,
            short_name,
            long_name=None,
            icon=None,
            authors=None,
            desc=(('line', ''),),
            ):
        self.name = name
        self.shortName = short_name
        self.longName = long_name or short_name
        if len(self.longName) > 20:
            self.context_lbl = self.shortName
        else:
            self.context_lbl = self.longName
        if icon is None:
            self.icon = png.png('BEE2/blank_96', error=err_icon, resize_to=96)
            self.ico_file = 'BEE2/blank_96'
        else:
            self.icon = png.png(icon, error=err_icon, resize_to=96)
            self.ico_file = icon
        self.desc = desc
        self.authors = [] if authors is None else authors

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
            lst,
            has_none=True,
            has_def=True,
            none_desc=(('line', 'Do not add anything.'),),
            title='BEE2',
            callback=_NO_OP,
            callback_params=(),
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
        """
        self.noneItem = Item('NONE', '', desc=none_desc)
        self.noneItem.icon = png.png('BEE2/none_96')
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
        self.win.iconbitmap('BEE2.ico')
        self.win.protocol("WM_DELETE_WINDOW", self.exit)
        self.win.bind("<Escape>", self.exit)

        # PanedWindow allows resizing the two areas independently.
        self.pane_win = ttk.Panedwindow(self.win, orient=HORIZONTAL)
        self.pane_win.grid(row=0, column=0, sticky="NSEW")

        self.wid = {}
        shim = ttk.Frame(self.pane_win, relief="sunken")
        self.win.rowconfigure(0, weight=1)
        self.win.columnconfigure(0, weight=1)
        shim.rowconfigure(0, weight=1)
        shim.columnconfigure(0, weight=1)

        # We need to use a canvas to allow scrolling.
        self.wid_canvas = Canvas(shim, highlightthickness=0)
        self.wid_canvas.grid(row=0, column=0, sticky="NSEW")

        # Add another frame inside to place labels on.
        self.pal_frame = ttk.Frame(self.wid_canvas)
        self.wid_canvas.create_window(1, 1, window=self.pal_frame, anchor="nw")

        self.wid_scroll = ttk.Scrollbar(
            shim,
            orient=VERTICAL,
            command=self.wid_canvas.yview,
        )
        self.wid_scroll.grid(row=0, column=1, sticky="NS")
        self.wid_canvas['yscrollcommand'] = self.wid_scroll.set

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
        self.prop_icon.img = png.png('BEE2/blank_96')
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
            height=16,
            font="TkSmallCaptionFont",
            )
        self.prop_desc.grid(
            row=0,
            column=0,
            padx=(2, 0),
            pady=2,
            sticky='NSEW',
            )

        self.prop_scroll = ttk.Scrollbar(
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
                row=5,
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
                row=5,
                column=1,
                sticky='EW',
                )

        ttk.Button(
            self.prop_frm,
            text="Cancel",
            command=self.exit,
            ).grid(
                row=5,
                column=2,
                padx=(8, 8),
                )

        self.win.option_add('*tearOff', False)
        self.context_menu = Menu(self.win)
        # Make a bold version of the context menu font
        self.sugg_font = font.nametofont('TkMenuFont').copy()
        self.sugg_font['weight'] = 'bold'
        self.context_var = IntVar()

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
            item.button.bind(
                "<Button-1>",
                functools.partial(self.sel_item, item),
            )
            item.button.bind("<Double-Button-1>", self.save)
        self.flow_items(None)
        self.wid_canvas.bind("<Configure>", self.flow_items)

        self.pane_win.add(shim, weight=1)
        self.pane_win.add(self.prop_frm)

    def widget(self, frame) -> ttk.Entry:
        """Create the special textbox used to open the selector window.

        Use like 'selWin.widget(parent).grid(row=0, column=1)' to create
        and place the textbox.
        """

        self.display = ttk.Entry(
            frame,
            textvariable=self.disp_label,
            cursor='arrow',
        )
        self.display.bind("<Button-1>", self.open_win)
        self.display.bind("<Key>", self.set_disp)
        self.display.bind("<Button-3>", self.open_context)

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
                self.display['font'] = 'TkMenuFont'

        if self.selected == self.noneItem:
            self.disp_label.set("<None>")
            self.chosen_id = None
        else:
            self.disp_label.set(self.selected.context_lbl)
            self.chosen_id = self.selected.name
        self.orig_selected = self.selected
        self.context_var.set(self.item_list.index(self.selected))
        return "break"  # stop the entry widget from continuing with this event

    def open_win(self, _=None, force_open=False):
        if self._readonly and not force_open:
            TK_ROOT.bell()
            return 'break'  # Tell tk to stop processing this event

        self.win.deiconify()
        self.win.lift(self.parent)
        self.win.grab_set()
        self.win.focus_force()  # Focus here to deselect the textbox
        self.win.geometry(
            '+' + str(self.parent.winfo_rootx()+30) +
            '+' + str(self.parent.winfo_rooty()+30)
        )
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

    def sel_item(self, item, _=None):
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
                font='TkMenuFont')
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
    from tk_root import TK_ROOT
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
                ('line', 'The dark constuction and office areas of Aperture.'
                         'Catwalks extend between different buildings, with'
                         'vactubes and cranes carrying objects throughout'
                         'the facility.'),
                ('rule', ''),
                ('line', 'Abandoned offices can often be found here.')
                ],
            ),
        ]

    window = selWin(
        TK_ROOT,
        test_list,
        has_none=True,
        has_def=True,
        callback=functools.partial(
            print,
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