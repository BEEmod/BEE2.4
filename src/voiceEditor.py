from tkinter import *
from tk_root import TK_ROOT
from tkinter import ttk
from tkinter import font

from decimal import Decimal
import os
import functools

from BEE2_config import ConfigFile
import img
import utils

voice_item = None

UI = {}

TABS = {}

QUOTE_FONT = font.nametofont('TkHeadingFont').copy()
QUOTE_FONT['weight'] = 'bold'

SP_IMG = img.png('icons/quote_sp')
COOP_IMG = img.png('icons/quote_coop')

win = Toplevel(TK_ROOT, name='voiceEditor')
win.columnconfigure(0, weight=1)
win.transient(master=TK_ROOT)
win.iconbitmap('../BEE2.ico')
win.protocol("WM_DELETE_WINDOW", win.withdraw)
win.bind("<Escape>", win.withdraw)
win.withdraw()


def init_widgets():
    pane = PanedWindow(
        win,
        orient=VERTICAL,
        sashpad=2,  # Padding above/below panes
        sashwidth=3,  # Width of border
        sashrelief=RAISED,  # Raise the border between panes
        )
    UI['pane'] = pane
    pane.grid(row=1, column=0, sticky='NSEW')
    win.rowconfigure(1, weight=1)

    UI['tabs'] = ttk.Notebook(pane)
    UI['tabs'].enable_traversal()  # Add keyboard shortcuts
    pane.add(UI['tabs'])
    pane.paneconfigure(UI['tabs'], minsize=50)

    trans_frame = ttk.Frame(pane)
    trans_frame.rowconfigure(1, weight=1)
    trans_frame.columnconfigure(0, weight=1)

    ttk.Label(
        trans_frame,
        text='Transcript:',
        ).grid(
            row=0,
            column=0,
            sticky=W,
            )

    trans_inner_frame = ttk.Frame(trans_frame, borderwidth=2, relief='sunken')
    trans_inner_frame.grid(row=1, column=0, sticky='NSEW')
    trans_inner_frame.rowconfigure(0, weight=1)
    trans_inner_frame.columnconfigure(0, weight=1)

    UI['trans'] = Text(
        trans_inner_frame,
        width=10,
        height=4,
        wrap='word',
        relief='flat',
        state='disabled',
        font=('Helvectia', 10),
        )
    UI['trans_scroll'] = ttk.Scrollbar(
        trans_inner_frame,
        orient=VERTICAL,
        command=UI['trans'].yview,
        )
    UI['trans'].tag_config(
        'bold',
        font=('Helvectia', 10, 'bold'),
    )
    UI['trans']['yscrollcommand'] = UI['trans_scroll'].set
    UI['trans_scroll'].grid(row=0, column=1, sticky='NS')
    UI['trans'].grid(row=0, column=0, sticky='NSEW')

    ttk.Button(
        win,
        text='Save',
        command=save,
        ).grid(row=2, column=0)

    # Don't allow resizing the transcript box to be smaller than the
    # original size.
    trans_frame.update_idletasks()
    pane.paneconfigure(trans_frame, minsize=trans_frame.winfo_reqheight())


def quote_sort_func(quote):
    """The quotes will be sorted by their priority value."""
    # Use Decimal so any number of decimal points can be used.
    try:
        return Decimal(quote['priority', '0'])
    except ValueError:
        return Decimal('0')


def show_trans(e):
    """Add the transcript to the list."""
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, END)
    for actor, line in e.widget.transcript:
        text.insert('end', actor, ('bold',))
        text.insert('end', line + '\n\n')
    # Remove the trailing newlines
    text.delete('end-2char', 'end')
    text['state'] = 'disabled'


def check_toggled(var, config_section, quote_id):
    """Update the config file to match the checkbox."""
    config_section[quote_id] = utils.bool_as_int(var.get())


def configure_canv(e):
    canvas = e.widget
    frame = canvas.frame
    canvas['scrollregion'] = (
        0,
        0,
        canvas.winfo_reqwidth(),
        frame.winfo_reqheight(),
        )
    frame['width'] = canvas.winfo_reqwidth()


def save():
    print('Saving Configs!')
    config.save_check()
    config_mid.save_check()
    win.withdraw()


def add_tabs():
    """Add the tabs to the notebook."""
    notebook = UI['tabs']
    # Save the current tab index so we can restore it after.
    try:
        current_tab = notebook.index(notebook.select())
    except TclError:  # .index() will fail if the voice is empty,
        current_tab = None  # in that case abandon remembering the tab.

    # Add or remove tabs so only the correct mode is visible.
    for name, tab in sorted(TABS.items()):
        notebook.add(tab)
        if tab.nb_is_mid:
            # For the midpoint tabs, we use a special image to make
            # sure they are well-distinguished from the other groups.
            notebook.tab(
                tab,
                compound='image',
                image=img.png('icons/mid_quote'),
                )
        else:
            notebook.tab(tab, text=tab.nb_text)

    if current_tab is not None:
        notebook.select(current_tab)


def show(quote_pack):
    """Display the editing window."""
    global voice_item, config, config_mid
    voice_item = quote_pack

    win.title('BEE2 - Configure "' + voice_item.selitem_data.name + '"')
    notebook = UI['tabs']

    quote_data = quote_pack.config

    os.makedirs('config/voice', exist_ok=True)
    config = ConfigFile('voice/' + quote_pack.id + '.cfg')
    config_mid = ConfigFile('voice/MID_' + quote_pack.id + '.cfg')

    # Clear the transcript textbox
    text = UI['trans']
    text['state'] = 'normal'
    text.delete(1.0, END)
    text['state'] = 'disabled'

    # Destroy all the old tabs
    for tab in TABS.values():
        try:
            notebook.forget(tab)
        except TclError as e:
            pass
        tab.destroy()

    TABS.clear()

    for group in quote_data.find_all('quotes', 'group'):
        make_tab(
            group,
            config,
            is_mid=False,
            )

    mid_quotes = list(quote_data.find_all('quotes', 'midchamber'))
    if len(mid_quotes) > 0:
        frame = make_tab(
            mid_quotes[0],
            config_mid,
            is_mid=True,
            )
        frame.nb_text = ''

    config.save()
    config_mid.save()

    add_tabs()

    win.deiconify()
    win.lift(win.winfo_parent())
    utils.center_win(win)  # Center inside the parent


def make_tab(group, config, is_mid=False):
    """Create all the widgets for a tab."""
    group_name = group['name', 'No Name!']
    group_desc = group['desc', '']

    # This is just to hold the canvas and scrollbar
    outer_frame = ttk.Frame(UI['tabs'])
    outer_frame.columnconfigure(0, weight=1)
    outer_frame.rowconfigure(0, weight=1)

    TABS[group_name] = outer_frame
    # We add this attribute so the refresh() method knows all the
    # tab names
    outer_frame.nb_text = group_name
    outer_frame.nb_is_mid = is_mid

    # We need a canvas to make the list scrollable.
    canv = Canvas(
        outer_frame,
        highlightthickness=0,
        )
    scroll = ttk.Scrollbar(
        outer_frame,
        orient=VERTICAL,
        command=canv.yview,
        )
    canv['yscrollcommand'] = scroll.set
    canv.grid(row=0, column=0, sticky='NSEW')
    scroll.grid(row=0, column=1, sticky='NS')

    UI['tabs'].add(outer_frame)

    # This holds the actual elements
    frame = ttk.Frame(
        canv,
        )
    frame.columnconfigure(0, weight=1)
    canv.create_window(0, 0, window=frame, anchor="nw")

    # We do this so we can adjust the scrollregion later in
    # <Configure>.
    canv.frame = frame

    if is_mid:
        group_name = 'Mid - Chamber'
        group_desc = 'Lines played during normal gameplay'

    ttk.Label(
        frame,
        text=group_name,
        anchor='center',
        font='tkHeadingFont',
        ).grid(
            row=0,
            column=0,
            sticky='EW',
            )

    ttk.Label(
        frame,
        text=group_desc + ':',
        ).grid(
            row=1,
            column=0,
            sticky='EW',
            )

    ttk.Separator(frame, orient=HORIZONTAL).grid(
        row=2,
        column=0,
        sticky='EW',
        )

    sorted_quotes = sorted(
        group.find_all('Quote'),
        key=quote_sort_func,
        reverse=True,
        )

    for quote in sorted_quotes:
        ttk.Label(
            frame,
            text=quote['name', 'No Name!'],
            font=QUOTE_FONT,
            ).grid(
                column=0,
                sticky=W,
                )

        for badge, line in find_lines(quote):
            line_id = line['id', line['name']]
            check = ttk.Checkbutton(
                frame,
                text=line['name'],
                compound=LEFT,
                image=badge,
                )
            check.quote_var = IntVar(
                value=config.get_bool(group_name, line_id, True),
                )
            check['variable'] = check.quote_var

            check['command'] = functools.partial(
                check_toggled,
                check.quote_var,
                config[group_name],
                line_id,
                )

            check.transcript = list(get_trans_lines(line))
            check.grid(
                column=0,
                padx=(10, 0),
                sticky=W,
                )
            check.bind("<Enter>", show_trans)
    canv.bind('<Configure>', configure_canv)

    return outer_frame


def find_lines(quote_block):
    """Find the line property blocks in a quote."""
    for prop in quote_block:
        if prop.name == 'line':
            yield None, prop
        elif prop.name == 'line_sp':
            yield SP_IMG, prop
        elif prop.name == 'line_coop':
            yield COOP_IMG, prop


def get_trans_lines(trans_block):
    for prop in trans_block:
        if prop.name == 'trans':
            if ':' in prop.value:
                name, trans = prop.value.split(':', 1)
                yield name.rstrip(), ': "' + trans.lstrip() + '"'
            else:
                yield '', '"' + prop.value + '"'

if __name__ == '__main__':
    import packageLoader
    data = packageLoader.load_packages('packages\\', False)

    TK_ROOT = Tk()
    lab = ttk.Label(TK_ROOT, text='Root Window')
    lab.bind('<Button-1>', lambda e: show(d['BEE2_CAVE_50s']))
    lab.grid()
    init_widgets()
    d = {quote.id: quote for quote in data['QuotePack']}
    print(d)
    show(d['BEE2_GLADOS_CLEAN'])