"""
A widget which displays items in a row with various attributes.

Headings can
be clicked to sort, the item can be enabled/disabled, and info can be shown
via tooltips
"""
from __future__ import annotations
from typing import overload
from tkinter import ttk, font
import tkinter as tk

from collections.abc import Iterable, Iterator
import functools

import attrs

from .tooltip import add_tooltip, set_tooltip
from .wid_transtoken import TransToken, set_text
from . import tk_tools


UP_ARROW = '\u25B3'
DN_ARROW = '\u25BD'
ELLIPSIS = '\u2026'

ROW_HEIGHT = 16
ROW_PADDING = 2

BODY_FONT = font.nametofont('TkDefaultFont')

style = ttk.Style()
style.configure('CheckDetails.TCheckbutton', background='white')

# An event generated when items are all unchecked.
# Use to disable buttons when needed
EVENT_NO_CHECKS = '<<NoItemsChecked>>'
EVENT_HAS_CHECKS = '<<ItemsChecked>>'

TRANS_ELLIPSIS = TransToken.untranslated(ELLIPSIS)


def truncate(text: str, width: int) -> TransToken | None:
    """Truncate text to fit in the given space."""
    if BODY_FONT.measure(text) < width:
        return None  # No truncation needed!

    # Chop one character off the end at a time
    for ind in reversed(range(len(text))):
        short = text[:ind] + ELLIPSIS
        if BODY_FONT.measure(short) < width:
            return TransToken.untranslated(short)
    return TRANS_ELLIPSIS


@attrs.define
class Header:
    """Holds widgets for the header."""
    frame: ttk.Frame
    label: ttk.Label
    sorter: ttk.Label

    def evt_enter(self, _: tk.Event) -> None:
        """Highlight header when hovering to invite clicks."""
        self.label['background'] = 'lightblue'
        self.sorter['background'] = 'lightblue'

    def evt_leave(self, _: tk.Event) -> None:
        """Reset header after the mouse leaves."""
        self.label['background'] = ''
        self.sorter['background'] = ''


class Item[UserT]:
    """Represents one item in a CheckDetails list."""
    user: UserT
    @overload
    def __init__(
        self: Item[None],
        *values: TransToken,
        hover_text: TransToken = TransToken.BLANK,
        lock_check: bool = False,
        state: bool = False,
    ) -> None: ...
    @overload
    def __init__(
        self: Item[UserT],
        *values: TransToken,
        hover_text: TransToken = TransToken.BLANK,
        lock_check: bool = False,
        state: bool = False,
        user: UserT,
    ) -> None: ...
    def __init__(
        self,
        *values: TransToken,
        hover_text: TransToken = TransToken.BLANK,
        lock_check: bool = False,
        state: bool = False,
        user: UserT | None = None,
    ) -> None:
        """Initialise an item.
        - values are the text to show in each column, in order.
        - hover_text will set text to show in the tooltip. If not defined,
            tooltips will be used to show any text that does not fit
            in the column width.
        - If lock_check is true, this checkbox cannot be changed.
        - state is the initial state of the checkbox.
        - user can be set to any value.
        """
        self.values = values
        self.state_var = tk.BooleanVar(value=bool(state))
        self.master: CheckDetails[UserT] | None = None
        self.check: ttk.Checkbutton | None = None
        self.locked = lock_check
        self.hover_text = hover_text  # Readonly.
        self.val_widgets: list[tk.Label] = []
        if user is not None:
            self.user = user

    def make_widgets(self, master: CheckDetails[UserT]) -> None:
        """Create the widgets for this item."""
        if self.master is not None:
            # If we let items move between lists, the old widgets will become
            # orphaned!
            raise ValueError("Can't move Item objects between lists!")

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
                justify=tk.LEFT,
                anchor=tk.W,
                background='white',
            )
            set_text(wid, value)
            add_tooltip(wid, self.hover_text)

            if not self.locked:
                # Allow clicking on the row to toggle the checkbox
                tk_tools.link_checkmark(self.check, wid)

            self.val_widgets.append(wid)

        tk_tools.add_mousewheel(
            self.master.wid_canvas,
            self.check,
            *self.val_widgets
        )

    def place(self, check_width: int, head_pos: list[tuple[int, int]], y: int) -> None:
        """Position the widgets on the frame."""
        self.check.place(x=0, y=y, width=check_width, height=ROW_HEIGHT)
        for text, widget, (x, width) in zip(self.values, self.val_widgets, head_pos):
            widget.place(
                x=x+check_width,
                y=y,
                width=width,
                height=ROW_HEIGHT,
            )
            short_text = truncate(str(text), width-5)
            if short_text is None:
                set_text(widget, text)
                set_tooltip(widget, self.hover_text)
            else:
                set_text(widget, short_text)
                set_tooltip(widget, self.hover_text or text)
            x += width

    def destroy(self) -> None:
        """Remove this from the window."""
        self.check.place_forget()
        for wid in self.val_widgets:
            wid.place_forget()

    @property
    def state(self) -> bool:
        """Return whether the checkbox is checked."""
        return self.state_var.get()

    @state.setter
    def state(self, value: bool) -> None:
        self.state_var.set(value)
        self.master.update_allcheck()


class CheckDetails[UserT](ttk.Frame):
    """A widget which displays items in a row with various attributes."""
    def __init__(
        self,
        parent: tk.Misc,
        items: Iterable[Item[UserT]] = (),
        headers: Iterable[TransToken] = (),
        add_sizegrip: bool = False,
    ) -> None:
        """Initialise a CheckDetails pane.

        parent is the parent widget.
        items is a list of Items objects.
        headers is a list of the header strings.
        If add_sizegrip is True, add a sizegrip object between the scrollbars.
        """
        super().__init__(parent)

        self.parent = parent
        self.items: list[Item[UserT]] = []
        self.sort_ind: int | None = None
        self.rev_sort = False  # Should we sort in reverse?

        self.head_check_var = tk.BooleanVar(value=False)
        self.wid_head_check = ttk.Checkbutton(
            self,
            variable=self.head_check_var,
            command=self.toggle_allcheck,
            takefocus=False,
            width=0,
        )
        self.wid_head_check.grid(row=0, column=0)

        add_tooltip(self.wid_head_check, TransToken.ui("Toggle all checkboxes."))

        def checkbox_enter(_: tk.Event) -> None:
            """When hovering over the 'all' checkbox, highlight the others."""
            for item in self.items:
                item.check.state(['active'])
        self.wid_head_check.bind('<Enter>', checkbox_enter)

        def checkbox_leave(_: tk.Event) -> None:
            """When leaving, reset the checkboxes."""
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
        self.headers: list[Header] = [
            self._make_header(ind, text)
            for ind, text in enumerate(headers)
        ]

        self.wid_canvas = tk.Canvas(self)
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
            border=0,
        )
        self.wid_canvas.create_window(0, 0, window=self.wid_frame, anchor='nw')

        refresh_cmd = self.register(self.refresh)

        self.bind('<Configure>', refresh_cmd)
        self.bind('<Map>', refresh_cmd)  # When added to a window, refresh

        self.wid_header.bind('<ButtonRelease-1>', refresh_cmd)
        self.wid_header.bind('<B1-Motion>', refresh_cmd)
        self.wid_header.bind('<Configure>', refresh_cmd)

        self.add_items(*items)

        tk_tools.add_mousewheel(
            self.wid_canvas,

            self.wid_canvas,
            self.wid_frame,
            self.wid_header,
        )

    def _make_header(self, ind: int, text: TransToken) -> Header:
        """Generate the heading widgets."""
        frame = ttk.Frame(self.wid_header, relief=tk.RAISED)
        label = ttk.Label(frame, font='TkHeadingFont')
        sorter = ttk.Label(frame, font='TkHeadingFont', text='')
        header = Header(frame, label, sorter)
        set_text(label, text)

        label.grid(row=0, column=0, sticky='EW')
        sorter.grid(row=0, column=1, sticky='E')
        frame.columnconfigure(0, weight=1)
        self.wid_header.add(frame)

        frame.bind('<Enter>', header.evt_enter)
        frame.bind('<Leave>', header.evt_leave)
        tk_tools.bind_leftclick(label, functools.partial(self.sort, ind))

        # Headers can't become smaller than their initial size -
        # The amount of space to show all the text + arrow
        frame.update_idletasks()
        self.wid_header.paneconfig(frame, minsize=frame.winfo_reqwidth())
        sorter['text'] = ''
        return header

    def add_items(self, *items: Item[UserT]) -> None:
        """Add items to the details list."""
        for item in items:
            self.items.append(item)
            item.make_widgets(self)
        self.update_allcheck()
        self.refresh()

    def rem_items(self, *items: Item[UserT]) -> None:
        """Remove items from the details list."""
        for item in items:
            self.items.remove(item)
            item.destroy()
        self.update_allcheck()
        self.refresh()

    def remove_all(self) -> None:
        """Remove all items from the list."""
        for item in self.items:
            item.destroy()
        self.items.clear()
        self.update_allcheck()
        self.refresh()

    def update_allcheck(self) -> None:
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

    def toggle_allcheck(self) -> None:
        """The 'all' checkbox was pressed, toggle everything."""
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

    def refresh(self, _: tk.Event[tk.Misc] | None = None) -> None:
        """Reposition the widgets.

        Must be called when `self.items` is changed,
        or when window is resized.
        """
        # Don't bother if the window isn't actually visible.
        if not self.winfo_ismapped():
            return
        header_sizes = [
            (header.frame.winfo_x(), header.frame.winfo_width())
            for header in self.headers
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

    def sort(self, index: int, _: tk.Event) -> None:
        """Click event for headers."""
        if self.sort_ind is not None:
            self.headers[self.sort_ind].sorter['text'] = ''
        if self.sort_ind == index:
            self.rev_sort = not self.rev_sort
        else:
            self.rev_sort = False

        self.headers[index].sorter['text'] = UP_ARROW if self.rev_sort else DN_ARROW
        self.sort_ind = index

        self.items.sort(key=lambda item: item.values[index].token, reverse=self.rev_sort)
        self.refresh()

    def checked(self) -> Iterator[Item[UserT]]:
        """Yields enabled check items."""
        for item in self.items:
            if item.state_var.get():
                yield item

    def unchecked(self) -> Iterator[Item[UserT]]:
        """Yields disabled check items."""
        for item in self.items:
            if not item.state_var.get():
                yield item


if __name__ == '__main__':
    from ui_tk import TK_ROOT
    tt = TransToken.untranslated
    test_inst = CheckDetails[None](
        parent=TK_ROOT,
        headers=[tt('Name'), tt('Author'), tt('Description')],
        items=[
            Item(tt('Item1'), tt('Auth1'), tt('Blah blah blah')),
            Item(tt('Item5'), tt('Auth3'), tt('Lorem Ipsum')),
            Item(tt('Item3'), tt('Auth2'), tt('.........')),
            Item(tt('Item4'), tt('Auth2'), tt('.........')),
            Item(tt('Item6'), tt('Sir VeryLongName'), tt('.....')),
            Item(tt('Item2'), tt('Auth1'), tt('...')),
        ]
    )
    test_inst.grid(sticky='NSEW')
    tk_tools.add_mousewheel(test_inst.wid_canvas, TK_ROOT)

    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.rowconfigure(0, weight=1)
    TK_ROOT.deiconify()
    TK_ROOT.mainloop()
