"""
A widget which displays items in a row with various attributes.

Headings can
be clicked to sort, the item can be enabled/disabled, and info can be shown
via tooltips
"""
from tkinter import ttk
from tkinter import font
import tkinter as tk

import functools

from app.tooltip import add_tooltip, set_tooltip
from app import tk_tools

from typing import List, Iterator, Optional


UP_ARROW = '\u25B3'
DN_ARROW = '\u25BD'
ELLIPSIS = '\u2026'

ROW_HEIGHT = 16
ROW_PADDING = 2

BODY_FONT = font.nametofont('TkDefaultFont')

style = ttk.Style()
style.configure(
    'CheckDetails.TCheckbutton',
    background='white',
)

# An event generated when items are all unchecked.
# Use to disable buttons when needed
EVENT_NO_CHECKS = '<<NoItemsChecked>>'
EVENT_HAS_CHECKS = '<<ItemsChecked>>'


def truncate(text, width):
    """Truncate text to fit in the given space."""
    if BODY_FONT.measure(text) < width:
        return text # No truncation needed!

    # Chop one character off the end at a time
    for ind in range(len(text)-1, 0, -1):
        short = text[:ind] + ELLIPSIS
        if BODY_FONT.measure(short) < width:
            return short
    return ELLIPSIS


class Item:
    """Represents one item in a CheckDetails list.

    """
    def __init__(
            self,
            *values,
            hover_text=None,
            lock_check=False,
            state=False
            ):
        """Initialise an item.
        - values are the text to show in each column, in order.
        - hover_text will set text to show in the tooltip. If not defined,
            tooltips will be used to show any text that does not fit
            in the column width.
        - If lock_check is true, this checkbox cannot be changed.
        - state is the initial state of the checkbox.
        """
        self.values = values
        self.state_var = tk.IntVar(value=bool(state))
        self.master = None  # type: Optional[CheckDetails]
        self.check = None  # type: Optional[ttk.Checkbutton]
        self.locked = lock_check
        self.hover_text = hover_text
        self.val_widgets = []

    def copy(self):
        return Item(self.values)

    def make_widgets(self, master: 'CheckDetails'):
        if self.master is not None:
            # If we let items move between lists, the old widgets will become
            # orphaned!
            raise ValueError(
                "Can't move Item objects between lists!"
            )

        self.master = master
        self.check = ttk.Checkbutton(
            master.wid_frame,
            variable=self.state_var,
            onvalue=1,
            offvalue=0,
            takefocus=False,
            width=0,
            style='CheckDetails.TCheckbutton',
            command=self.master.update_allcheck,
        )
        if self.locked:
            self.check.state(['disabled'])

        self.val_widgets = []
        for value in self.values:
            wid = tk.Label(
                master.wid_frame,
                text=value,
                justify=tk.LEFT,
                anchor=tk.W,
                background='white',
            )
            add_tooltip(wid)
            if self.hover_text:
                set_tooltip(wid, self.hover_text)
                wid.hover_override = True
            else:
                set_tooltip(wid)
                wid.hover_override = False

            if not self.locked:
                # Allow clicking on the row to toggle the checkbox
                wid.bind('<Enter>', self.hover_start, add=True)
                wid.bind('<Leave>', self.hover_stop, add=True)
                tk_tools.bind_leftclick(wid, self.row_click, add=True)
                wid.bind(tk_tools.EVENTS['LEFT_RELEASE'], self.row_unclick, add=True)

            self.val_widgets.append(wid)

        tk_tools.add_mousewheel(
            self.master.wid_canvas,
            self.check,
            *self.val_widgets
        )

    def place(self, check_width, head_pos, y):
        """Position the widgets on the frame."""
        self.check.place(
            x=0,
            y=y,
            width=check_width,
            height=ROW_HEIGHT,
        )
        for text, widget, (x, width) in zip(
                self.values,
                self.val_widgets,
                head_pos
                ):
            widget.place(
                x=x+check_width,
                y=y,
                width=width,
                height=ROW_HEIGHT,
            )
            text = str(text)
            short_text = widget['text'] = truncate(text, width-5)
            if not widget.hover_override:
                set_tooltip(widget, text if short_text != text else '')
            x += width

    def destroy(self):
        """Remove this from the window."""
        self.check.place_forget()
        for wid in self.val_widgets:
            wid.place_forget()

    @property
    def state(self) -> bool:
        return self.state_var.get()

    @state.setter
    def state(self, value: bool):
        self.state_var.set(value)
        self.master.update_allcheck()

    def hover_start(self, e):
        self.check.state(['active'])

    def hover_stop(self, e):
        self.check.state(['!active'])

    def row_click(self, e):
        self.state = not self.state
        self.check.state(['pressed'])

    def row_unclick(self, e):
        self.check.state(['!pressed'])


class CheckDetails(ttk.Frame):
    def __init__(self, parent, items=(), headers=(), add_sizegrip=False):
        """Initialise a CheckDetails pane.

        parent is the parent widget.
        items is a list of Items objects.
        headers is a list of the header strings.
        If add_sizegrip is True, add a sizegrip object between the scrollbars.
        """
        super(CheckDetails, self).__init__(parent)

        self.parent = parent
        self.headers = list(headers)
        self.items = []  # type: List[Item]
        self.sort_ind = None
        self.rev_sort = False  # Should we sort in reverse?

        self.head_check_var = tk.IntVar(value=False)
        self.wid_head_check = ttk.Checkbutton(
            self,
            variable=self.head_check_var,
            command=self.toggle_allcheck,
            takefocus=False,
            width=0,
        )
        self.wid_head_check.grid(row=0, column=0)

        add_tooltip(self.wid_head_check, _("Toggle all checkboxes."))

        def checkbox_enter(e):
            """When hovering over the 'all' checkbox, highlight the others."""
            for item in self.items:
                item.check.state(['active'])
        self.wid_head_check.bind('<Enter>', checkbox_enter)

        def checkbox_leave(e):
            for item in self.items:
                item.check.state(['!active'])
        self.wid_head_check.bind('<Leave>', checkbox_leave)

        self.wid_header = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            sashrelief=tk.RAISED,
            sashpad=2,
            showhandle=False,
        )
        self.wid_header.grid(row=0, column=1, sticky='EW')
        self.wid_head_frames = [0] * len(self.headers)  # type: List[ttk.Frame]
        self.wid_head_label = [0] * len(self.headers)  # type: List[ttk.Label]
        self.wid_head_sort = [0] * len(self.headers)  # type: List[ttk.Label]
        self.make_headers()

        self.wid_canvas = tk.Canvas(
            self,
        )
        self.wid_canvas.grid(row=1, column=0, columnspan=2, sticky='NSEW')
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self.horiz_scroll = ttk.Scrollbar(
            self,
            orient=tk.HORIZONTAL,
            command=self.wid_canvas.xview,
        )
        self.vert_scroll = ttk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self.wid_canvas.yview,
        )
        self.wid_canvas['xscrollcommand'] = self.horiz_scroll.set
        self.wid_canvas['yscrollcommand'] = self.vert_scroll.set

        self.horiz_scroll.grid(row=2, column=0, columnspan=2, sticky='EWS')
        self.vert_scroll.grid(row=1, column=2, sticky='NSE')
        if add_sizegrip and tk_tools.USE_SIZEGRIP:
            self.sizegrip = ttk.Sizegrip(self)
            self.sizegrip.grid(row=2, column=2)
        else:
            self.sizegrip = None

        self.wid_frame = tk.Frame(
            self.wid_canvas,
            background='white',
            border=0
        )
        self.wid_canvas.create_window(0, 0, window=self.wid_frame, anchor='nw')

        self.bind('<Configure>', self.refresh)
        self.bind('<Map>', self.refresh)  # When added to a window, refresh

        self.wid_header.bind('<ButtonRelease-1>', self.refresh)
        self.wid_header.bind('<B1-Motion>', self.refresh)
        self.wid_header.bind('<Configure>', self.refresh)

        self.add_items(*items)

        tk_tools.add_mousewheel(
            self.wid_canvas,

            self.wid_canvas,
            self.wid_frame,
            self.wid_header,
        )

    def make_headers(self):
        """Generate the heading widgets."""

        for i, head_text in enumerate(self.headers):
            self.wid_head_frames[i] = header = ttk.Frame(
                self.wid_header,
                relief=tk.RAISED,
            )

            self.wid_head_label[i] = label = ttk.Label(
                header,
                font='TkHeadingFont',
                text=head_text,
            )
            self.wid_head_sort[i] = sorter = ttk.Label(
                header,
                font='TkHeadingFont',
                text='',
            )
            label.grid(row=0, column=0, sticky='EW')
            sorter.grid(row=0, column=1, sticky='E')
            header.columnconfigure(0, weight=1)
            self.wid_header.add(header)

            def header_enter(_, label=label, sorter=sorter):
                label['background'] = 'lightblue'
                sorter['background'] = 'lightblue'

            def header_leave(_, label=label, sorter=sorter):
                label['background'] = ''
                sorter['background'] = ''

            header.bind('<Enter>', header_enter)
            header.bind('<Leave>', header_leave)
            tk_tools.bind_leftclick(label, functools.partial(self.sort, i))

            # Headers can't become smaller than their initial size -
            # The amount of space to show all the text + arrow
            header.update_idletasks()
            self.wid_header.paneconfig(
                header,
                minsize=header.winfo_reqwidth(),
            )

            sorter['text'] = ''

    def add_items(self, *items):
        for item in items:
            self.items.append(item)
            item.make_widgets(self)
        self.update_allcheck()
        self.refresh()

    def rem_items(self, *items):
        for item in items:
            self.items.remove(item)
            item.destroy()
        self.update_allcheck()
        self.refresh()

    def remove_all(self):
        """Remove all items from the list."""
        for item in self.items:
            item.destroy()
        self.items.clear()
        self.update_allcheck()
        self.refresh()

    def update_allcheck(self):
        """Update the 'all' checkbox to match the state of sub-boxes."""
        num_checked = sum(item.state for item in self.items)
        if num_checked == 0:
            self.head_check_var.set(False)
            self.event_generate(EVENT_NO_CHECKS)
        elif num_checked == len(self.items):
            self.wid_head_check.state(['!alternate'])
            self.head_check_var.set(True)
            self.wid_head_check.state(['!alternate'])
            self.event_generate(EVENT_HAS_CHECKS)
        else:
            # The 'half' state is just visual.
            # Set to true so everything is blanked when next clicking
            self.head_check_var.set(True)
            self.wid_head_check.state(['alternate'])
            self.event_generate(EVENT_HAS_CHECKS)

    def toggle_allcheck(self):
        value = self.head_check_var.get()
        for item in self.items:
            if item.locked:
                continue  # Don't change!

            # We can't use item.state, since that calls update_allcheck()
            # which would infinite-loop.
            item.state_var.set(value)
        if value and self.items:  # Don't enable if we don't have items
            self.event_generate(EVENT_HAS_CHECKS)
        else:
            self.event_generate(EVENT_NO_CHECKS)

    def refresh(self, e=None):
        """Reposition the widgets.

        Must be called when self.items is changed,
        or when window is resized.
        """
        header_sizes = [
            (head.winfo_x(), head.winfo_width())
            for head in
            self.wid_head_frames
        ]

        self.wid_head_check.update_idletasks()
        check_width = self.wid_head_check.winfo_width()
        pos = ROW_PADDING
        for item in self.items:
            item.place(check_width, header_sizes, pos)
            pos += ROW_HEIGHT + ROW_PADDING

        # Disable checkbox if no items are present
        if self.items:
            self.wid_head_check.state(['!disabled'])
        else:
            self.wid_head_check.state(['disabled'])

        self.wid_frame['width'] = width = max(
            self.wid_canvas.winfo_width(),
            sum(header_sizes[-1]) + check_width,
        )
        self.wid_frame['height'] = height = max(
            self.wid_canvas.winfo_height(),
            pos,
        )

        has_scroll_horiz = width > self.wid_canvas.winfo_width()
        has_scroll_vert = height > self.wid_canvas.winfo_height()

        # Re-grid the canvas, sizegrip and scrollbar to fill in gaps
        if self.sizegrip is not None:
            if has_scroll_horiz or has_scroll_vert:
                self.sizegrip.grid()
            else:
                self.sizegrip.grid_remove()

        # If only one, extend the canvas to fill the empty space
        if has_scroll_horiz and not has_scroll_vert:
            self.wid_canvas.grid(
                row=1, column=0, sticky='NSEW',
                columnspan=3,
            )
        elif not has_scroll_horiz and has_scroll_vert:
            self.wid_canvas.grid(
                row=1, column=0, sticky='NSEW',
                columnspan=2, rowspan=2,
            )
        else:
            # Both or neither, just fit in the original space
            self.wid_canvas.grid(
                row=1, column=0, sticky='NSEW',
                columnspan=2,
            )

        if has_scroll_horiz:
            self.horiz_scroll.grid()
        else:
            self.horiz_scroll.grid_remove()

        if has_scroll_vert:
            self.vert_scroll.grid()
        else:
            self.vert_scroll.grid_remove()

        # Set the size of the canvas
        self.wid_frame.update_idletasks()

        self.wid_canvas['scrollregion'] = (0, 0, width, height)

    def sort(self, index, e=None):
        """Click event for headers."""
        if self.sort_ind is not None:
            self.wid_head_sort[self.sort_ind]['text'] = ''
        if self.sort_ind == index:
            self.rev_sort = not self.rev_sort
        else:
            self.rev_sort = False

        self.wid_head_sort[index]['text'] = (
                UP_ARROW if self.rev_sort else DN_ARROW
            )
        self.sort_ind = index

        self.items.sort(
            key=lambda item: item.values[index],
            reverse=self.rev_sort,
        )
        self.refresh()

    def checked(self) -> Iterator[Item]:
        """Yields enabled check items."""
        return (item for item in self.items if item.state_var.get())

    def unchecked(self) -> Iterator[Item]:
        """Yields disabled check items."""
        return (item for item in self.items if not item.state_var.get())


if __name__ == '__main__':
    from app import TK_ROOT
    test_inst = CheckDetails(
        parent=TK_ROOT,
        headers=['Name', 'Author', 'Description'],
        items=[
            Item('Item1', 'Auth1', 'Blah blah blah'),
            Item('Item5', 'Auth3', 'Lorem Ipsum'),
            Item('Item3', 'Auth2', '.........'),
            Item('Item4', 'Auth2', '.........'),
            Item('Item6', 'Sir VeryLongName', '.....'),
            Item('Item2', 'Auth1', '...'),
        ]
    )
    test_inst.grid(sticky='NSEW')
    tk_tools.add_mousewheel(test_inst.wid_canvas, TK_ROOT)

    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.rowconfigure(0, weight=1)
    TK_ROOT.deiconify()
    TK_ROOT.mainloop()