# coding=utf-8
from tkinter import *
from tkinter import ttk
from tk_root import TK_ROOT

from BEE2_config import GEN_OPTS

import sound
import utils

UI = {}
PLAY_SOUND = BooleanVar(value=True, name='OPT_play_sounds')
SHOW_WIP = BooleanVar(value=False, name='OPT_show_wip_items')
KEEP_WIN_INSIDE = BooleanVar(value=True, name='OPT_keep_win_inside')

def reset_all_win():
    pass

win = Toplevel(TK_ROOT)
win.transient(master=TK_ROOT)
win.iconbitmap('../BEE2.ico')
win.title('BEE2 Options')
win.withdraw()

def show():
    win.deiconify()
    utils.center_win(win)

def load():
    """Load the current settings from config."""
    PLAY_SOUND.set(not GEN_OPTS.get_bool(
        'General',
        'mute_sounds',
        False,
        ))

    SHOW_WIP.set(GEN_OPTS.get_bool(
        'General',
        'show_wip_items',
        False,
        ))

def save():
    """Save settings into the config."""
    sound.muted = not PLAY_SOUND.get()
    GEN_OPTS['General']['mute_sounds'] = utils.bool_as_int(
        not PLAY_SOUND.get()
    )

    GEN_OPTS['General']['show_wip_items'] = utils.bool_as_int(
        SHOW_WIP.get()
    )

    utils.DISABLE_ADJUST = not KEEP_WIN_INSIDE.get()
    GEN_OPTS['General']['keep_win_inside'] = utils.bool_as_int(
        KEEP_WIN_INSIDE.get()
    )


def init_widgets():
    """Create all the widgets."""
    UI['nbook'] = nbook = ttk.Notebook(
        win,

    )
    UI['nbook'].grid(
        row=0,
        column=0,
        padx=5,
        pady=5,
        sticky=NSEW,
    )
    win.columnconfigure(0, weight=1)
    win.rowconfigure(0, weight=1)

    UI['fr_general'] = fr_general = ttk.Frame(
        nbook,
    )
    nbook.add(fr_general, text='General')
    init_gen_tab(fr_general)

    UI['fr_win'] = fr_win = ttk.Frame(
        nbook,
    )
    nbook.add(fr_win, text='Windows')
    init_win_tab(fr_win)

    ok_cancel = ttk.Frame(
        win
    )
    ok_cancel.grid(
        row=1,
        column=0,
        padx=5,
        pady=5,
        sticky=E,
    )

    def ok():
        save()
        win.withdraw()

    def cancel():
        win.withdraw()
        load() # Rollback changes

    UI['ok_btn'] = ok_btn = ttk.Button(
        ok_cancel,
        text='OK',
        command=ok,
    )
    UI['cancel_btn'] = cancel_btn = ttk.Button(
        ok_cancel,
        text='Cancel',
        command=cancel,
    )
    ok_btn.grid(row=0, column=0)
    cancel_btn.grid(row=0, column=1)
    win.protocol("WM_DELETE_WINDOW", cancel)

def init_gen_tab(f):

    if sound.initiallised:
        UI['mute'] = mute = ttk.Checkbutton(
            f,
            variable=PLAY_SOUND,
            text='Play Sounds',
        )
    else:
        UI['mute'] = mute = ttk.Checkbutton(
            f,
            text='Play Sounds',
            state='disabled',
        )
    mute.grid(row=0, column=0, sticky=W)

    UI['show_wip'] = show_wip = ttk.Checkbutton(
        f,
        variable=SHOW_WIP,
        text='Show WIP items',
    )
    show_wip.grid(row=1, column=0, sticky=W)


def init_win_tab(f):
    UI['keep_inside'] = keep_inside = ttk.Checkbutton(
        f,
        variable=KEEP_WIN_INSIDE,
        text='Keep windows inside screen \n'
             '(disable for multi-monitor setups)',
    )
    keep_inside.grid(row=0, column=0, sticky=W)

    UI['reset_win'] = reset_win = ttk.Button(
        f,
        text='Reset All Window Positions',
        # Indirect reference to allow UI to set this later
        command=lambda: reset_all_win(),
    )
    reset_win.grid(row=1, column=0, sticky=EW)
