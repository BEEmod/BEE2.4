"""
A widget which displays items in a row with various attributes.

Headings can
be clicked to sort, the item can be enabled/disabled, and info can be shown
via tooltips
"""
from tkinter import ttk
import tkinter as tk
import tk_tools


class Item:
    """Represents one item in a CheckDetails list.

    """
    def __init__(self, *values):
        self.values = values
        self.state = tk.BooleanVar(value=False)


class _ItemRow:
    """Holds the widgets displayed in each row.
    """
    def __init__(self, master: 'CheckDetails', item: 'Item'):
        self.widget = master
        self.item = item
        self.check = ttk.Checkbutton(
            master.wid_canvas,
        )


class CheckDetails(ttk.Frame):
    def __init__(self, parent, items=(), headers=()):
        super(CheckDetails, self).__init__(parent)

        self.parent = parent
        self.headers = list(headers)
        self.items = []
        # The widgets used for rows
        self._wid_rows = {}

        self.wid_canvas = tk.Canvas(
            self,
        )
        self.wid_canvas.grid(row=0, column=0, sticky='NSEW')
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

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

        self.horiz_scroll.grid(row=1, column=0, sticky='EW')
        self.vert_scroll.grid(row=0, column=1, sticky='NS')

        for item in items:
            self.add_item(item)

    def add_item(self, item):
        self.items.append(item)
        self._wid_rows[item] = _ItemRow(self, item)

    def rem_item(self, item):
        self.items.remove(item)
        del self._wid_rows[item]

    def refresh(self):
        """Reposition the widgets."""
        pass


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
    test_inst.grid()
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    root.mainloop()