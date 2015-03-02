'''Displays a loading menu while packages, palettes, etc are being loaded.'''
from tkinter import *  # ui library
from tk_root import TK_ROOT
from tkinter import ttk  # themed ui components that match the OS

STAGES = [
    ('PAK', 'Packages'),
    ('OBJ', 'Loading Objects'),
    ('RES', 'Extracting Resources'),
    ('IMG', 'Loading Images'),
    ('UI', 'Initialising UI'),
    ]
widgets = {}
labels = {}
bar_var = {}
bar_val = {}
maxes = {}
num_images = 0


active = True
# active determines whether the screen is on, and if False stops most
# functions from doing anything.

win = Toplevel(TK_ROOT, cursor='watch')
# this prevents stuff like the title bar, normal borders etc from
# appearing in this window.
win.overrideredirect(1)
win.resizable(False, False)
win.attributes('-topmost', 1)
win.geometry('+200+200')
win.deiconify()

ttk.Label(
    win,
    text='Loading...',
    font=("Helvetica", 12, "bold"),
    ).grid(columnspan=2)
ttk.Separator(
    win,
    orient=HORIZONTAL,
    ).grid(row=1, sticky="EW", columnspan=2)

for ind, (st_id, stage_name) in enumerate(STAGES):
    ttk.Label(
        win,
        text=stage_name + ':',
        ).grid(
            row=ind*2+2,
            columnspan=2,
            sticky="W",
            )
    bar_var[st_id] = IntVar()
    bar_val[st_id] = 0
    maxes[st_id] = 10

    widgets[st_id] = ttk.Progressbar(
        win,
        length=210,
        maximum=1000,
        variable=bar_var[st_id],
        )
    labels[st_id] = ttk.Label(win, text='0/??')
    widgets[st_id].grid(row=ind*2+3, column=0, columnspan=2)
    labels[st_id].grid(row=ind*2+2, column=1, sticky="E")

win.update()
loc_x = (win.winfo_screenwidth()-win.winfo_reqwidth())//2
loc_y = (win.winfo_screenheight()-win.winfo_reqheight())//2
win.geometry('+' + str(loc_x) + '+' + str(loc_y))
win.update()


def length(stage, num):
    if active:
        maxes[stage] = num
        set_nums(stage)


def step(stage):
    if active:
        prog_bar = widgets[stage]
        bar_val[stage] += 1
        bar_var[stage].set(1000*bar_val[stage]/maxes[stage])
        prog_bar.update()
        set_nums(stage)


def set_nums(stage):
    labels[stage]['text'] = str(bar_val[stage]) + '/' + str(maxes[stage])


def skip_stage(stage):
    '''Skip over this stage of the loading process.'''
    if active:
        labels[stage]['text'] = 'Skipped!'
        bar_var[stage].set(1000)
        widgets[stage].update()


def close_window():
    '''Shutdown the loading screen, we're done!'''
    global widgets, maxes, active
    win.destroy()
    del widgets
    del maxes
    active = False

if __name__ == '__main__':
    TK_ROOT.mainloop()