"""
A widget which displays items in a row with various attributes.

Headings can
be clicked to sort, the item can be enabled/disabled, and info can be shown
via tooltips
"""
from tkinter import ttk
import tkinter as tk

import utils
import tk_tools

UP_ARROW = '\u25B3'
DN_ARROW = '\u25BD'


class Item:
    """Represents one item in a CheckDetails list.

    """
    def __init__(self, *values):
        self.values = values
        self.state_var = None
        self.widget = None
        self.check = None
        self.master = None

    def make_widgets(self, master):
        if self.master is not None:
            # If we let items move between lists, the old widgets will become
            # orphaned!
            raise ValueError(
                "Can't move Item objects between lists!"
            )

        self.master = master
        self.state_var = tk.BooleanVar(value=False)
        self.check = ttk.Checkbutton(
            master.wid_canvas,
            variable=self.state_var,
        )

    @property
    def state(self) -> bool:
        return self.state_var.get()

    @state.setter
    def state(self, value: bool):
        self.state_var.set(value)
        self.master.update_allcheck()


class CheckDetails(ttk.Frame):
    def __init__(self, parent, items=(), headers=()):
        super(CheckDetails, self).__init__(parent)

        self.parent = parent
        self.headers = list(headers)
        self.items = []

        self.head_check_var = tk.IntVar(value=0)
        self.wid_head_check = ttk.Checkbutton(
            self,
            takefocus=False,
            variable=self.head_check_var,
            onvalue=1,
            offvalue=0,
        )
        self.wid_head_check.grid(row=0, column=0)

        self.wid_header = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            sashrelief=tk.RAISED,
            sashpad=2,
            showhandle=False,
        )
        self.wid_header.grid(row=0, column=1, sticky='EW')
        self.wid_head_label = [0] * len(self.headers)
        self.wid_head_sort = [0] * len(self.headers)
        self.make_headers()

        self.wid_canvas = tk.Canvas(
            self,
            relief=tk.SUNKEN,
            background='white',
        )
        self.wid_canvas.grid(row=1, column=0, columnspan=2, sticky='NSEW')
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        self.horiz_scroll = tk_tools.HidingScroll(
            self,
            orient=tk.HORIZONTAL,
            command=self.wid_canvas.xview,
        )
        self.vert_scroll = tk_tools.HidingScroll(
            self,
            orient=tk.VERTICAL,
            command=self.wid_canvas.yview,
        )
        self.wid_canvas['xscrollcommand'] = self.horiz_scroll.set
        self.wid_canvas['yscrollcommand'] = self.vert_scroll.set

        self.horiz_scroll.grid(row=2, column=0, columnspan=2, sticky='EW')
        self.vert_scroll.grid(row=1, column=1, sticky='NS')

        self.wid_frame = ttk.Frame(
            self.wid_canvas,
        )
        self.wid_canvas.create_window(0, 0, window=self.wid_frame, anchor='nw')

        self.bind('<Configure>', self.refresh)
        utils.add_mousewheel(self.wid_canvas, self)

        for item in items:
            self.add_item(item)

    def make_headers(self):
        """Generate the heading widgets."""

        for i, head_text in enumerate(self.headers):
            header = ttk.Frame(
                self.wid_header,
                relief=tk.RAISED,
            )

            self.wid_head_label[i] = label = ttk.Label(
                header,
                text=head_text,
            )
            self.wid_head_sort[i] = sorter = ttk.Label(
                header,
                text='',
            )
            label.grid(row=0, column=0, sticky='EW')
            sorter.grid(row=0, column=1, sticky='E')
            header.columnconfigure(0, weight=1)
            self.wid_header.add(header)

            def header_enter(e, wid=label):
                wid['background'] = 'lightblue'

            def header_leave(_, wid=label):
                wid['background'] = ''

            header.bind('<Enter>', header_enter)
            header.bind('<Leave>', header_leave)

            # Headers can't become smaller than their initial size -
            # The amount of space to show all the text + arrow
            header.update_idletasks()
            self.wid_header.paneconfig(
                header,
                minsize=header.winfo_reqwidth(),
            )

            sorter['text'] = ''

    def add_item(self, item):
        self.items.append(item)
        item.make_widgets(self)

    def rem_item(self, item):
        self.items.remove(item)

    def update_allcheck(self):
        """Update the 'all' checkbox to match the state of sub-boxes."""
        self.head_check_var.set(
            any(item.state for item in self.items)
        )

    def refresh(self, _=None):
        """Reposition the widgets.

        Must be called when self.items or _wid_rows is changed,
        or when window is resized.
        """

        # Set the size of the canvas
        self.wid_frame.update_idletasks()

        self.wid_canvas['scrollregion'] = (
            0,
            0,
            self.wid_frame.winfo_reqwidth(),
            self.wid_frame.winfo_reqheight(),
        )


if __name__ == '__main__':
    root = tk.Tk()
    test_inst = CheckDetails(
        parent=root,
        headers=['Name', 'Author', 'Description'],
        items=[
            Item('Item1', 'Auth1'),
            Item('Item2', 'Auth1'),
            Item('Item3', 'Auth2'),
        ]
    )
    test_inst.grid(sticky='NSEW')
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    root.mainloop()