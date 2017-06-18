from tkinter import simpledialog
from loadScreen import surpress_screens
from tk_tools import set_window_icon


class StringDialog(simpledialog._QueryString):
    def body(self, master):
        super().body(master)
        set_window_icon(self)


def ask_string(title, prompt, **kargs):
    with surpress_screens():
        d = StringDialog(title, prompt, **kargs)
        return d.result

ask_string.__doc__ = simpledialog.askstring.__doc__