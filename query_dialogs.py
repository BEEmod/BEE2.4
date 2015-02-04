from tkinter import simpledialog


class StringDialog(simpledialog._QueryString):
    def body(self, master):
        super().body(master)
        self.iconbitmap('BEE2.ico')


def ask_string(title, prompt, **kargs):
    d = StringDialog(title, prompt, **kargs)
    return d.result

ask_string.__doc__ = simpledialog.askstring.__doc__