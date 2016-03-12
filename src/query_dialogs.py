from tkinter import simpledialog
from loadScreen import surpress_screens


class StringDialog(simpledialog._QueryString):
    def body(self, master):
        super().body(master)
        self.iconbitmap('../BEE2.ico')


def ask_string(title, prompt, **kargs):
    with surpress_screens():
        d = StringDialog(title, prompt, **kargs)
        return d.result

ask_string.__doc__ = simpledialog.askstring.__doc__