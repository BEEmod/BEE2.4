from tkinter import *
from tk_root import TK_ROOT
from tkinter import ttk
from tkinter import filedialog

from os import path

import tkinter_png as png

from BEE2_config import ConfigFile, GEN_OPTS
from SubPane import SubPane

MAX_ENTS = 2048
MAX_OVERLAY = 512
MAX_BRUSH = 8192


COMPILE_DEFAULTS = {
    'Screenshot': {
        'Type': 'AUTO',
        'Loc': '',
        },
    'General': {
        'spawn_elev': 'True',
        },
    'Counts': {
        'brush': '0',
        'ent': '0',
        'overlay': '0',
        },
    }

COMPILE_CFG = ConfigFile('compile.cfg')
COMPILE_CFG.set_defaults(COMPILE_DEFAULTS)
window = None
UI = {}

chosen_thumb = StringVar(
    value=COMPILE_CFG.get_val('Screenshot', 'Type', 'AUTO')
)
start_in_elev = IntVar(value=0)
cust_file_loc = COMPILE_CFG.get_val('Screenshot', 'Loc', '')
cust_file_loc_var = StringVar(value=cust_file_loc)

count_brush = IntVar(value=0)
count_ents = IntVar(value=0)
count_overlay = IntVar(value=0)


def refresh_counts(reload=True):
    if reload:
        COMPILE_CFG.load()
    count_brush.set(COMPILE_CFG.get_int('Counts', 'brush'))
    count_ents.set(COMPILE_CFG.get_int('Counts', 'ent'))
    count_overlay.set(COMPILE_CFG.get_int('Counts', 'overlay'))


def find_screenshot(_=None):
    global cust_file_loc
    file_name = filedialog.askopenfilename(
        title='Find Game Exe',
        filetypes=[
            ('JPEG Image', '*.jpg *.jpeg *.jpe *.jfif'),
        ],
        initialdir='C:',
    )
    if file_name:
        chosen_thumb.set('CUST')
        cust_file_loc = file_name
        COMPILE_CFG['Screenshot']['LOC'] = file_name
        COMPILE_CFG.save()
        set_screenshot_text()
    else:
        cust_file_loc = ''
        COMPILE_CFG['Screenshot']['LOC'] = ''
        COMPILE_CFG.save()


def set_screenshot_text(_=None):
    cust_file_loc_var.set(path.basename(cust_file_loc))


def set_elev_type():
    COMPILE_CFG['General']['spawn_elev'] = 'True' if start_in_elev else 'False'
    COMPILE_CFG.save()


def set_screen_type():
    COMPILE_CFG['Screenshot']['type'] = chosen_thumb.get()
    COMPILE_CFG.save()


def make_pane(tool_frame):
    """Create the compiler options pane.

    """
    global window
    window = SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Compile Options',
        name='compiler',
        resize_x=False,
        resize_y=False,
        tool_frame=tool_frame,
        tool_img=png.loadPng('icons/win_compiler'),
        tool_col=3,
    )
    window.columnconfigure(0, weight=1)

    UI['Game_label'] = ttk.Label(window, text='Game: ', font='TkHeadingFont')
    UI['Game_label'].grid(row=0, column=0, sticky=EW)

    thumb_frame = ttk.LabelFrame(
        window,
        text='Thumbnail',
        labelanchor=N,
    )
    thumb_frame.grid(row=1, column=0, sticky=EW)
    thumb_frame.columnconfigure(0, weight=1)

    UI['thumb_auto'] = ttk.Radiobutton(
        thumb_frame,
        text='Auto',
        value='AUTO',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    UI['thumb_peti'] = ttk.Radiobutton(
        thumb_frame,
        text='PeTI',
        value='PETI',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    cust_frame = ttk.Frame(thumb_frame)
    cust_frame.columnconfigure(1, weight=1)

    UI['thumb_custom'] = ttk.Radiobutton(
        cust_frame,
        text='',
        value='CUST',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    UI['thumb_custom_file'] = ttk.Entry(
        cust_frame,
        cursor='arrow',
        textvariable=cust_file_loc_var,
        width=15,
    )
    UI['thumb_custom_file'].bind("<Button-1>", find_screenshot)
    UI['thumb_custom_file'].bind("<Key>", set_screenshot_text)

    UI['thumb_custom_btn'] = ttk.Button(
        cust_frame,
        text="...",
        width=1.5,
        command=find_screenshot,
    )

    UI['thumb_auto'].grid(row=0, column=0, sticky=W)
    UI['thumb_peti'].grid(row=1, column=0, sticky=W)
    cust_frame.grid(row=2, column=0, sticky=EW)
    UI['thumb_custom'].grid(row=0, column=0, sticky=W)
    UI['thumb_custom_file'].grid(row=0, column=1, sticky=EW)
    UI['thumb_custom_btn'].grid(row=0, column=2, sticky=EW)

    elev_frame = ttk.LabelFrame(
        window,
        text='Spawn at:',
        labelanchor=N,
    )

    elev_frame.grid(row=2, column=0, sticky=EW)

    UI['elev_preview'] = ttk.Radiobutton(
        elev_frame,
        text='Entry Door',
        value=0,
        variable=start_in_elev,
        command=set_elev_type,
    )

    UI['elev_elevator'] = ttk.Radiobutton(
        elev_frame,
        text='Elevator',
        value=1,
        variable=start_in_elev,
        command=set_elev_type,
    )

    UI['elev_preview'].grid(row=0, column=0, sticky=W)
    UI['elev_elevator'].grid(row=1, column=0, sticky=W)

    UI['view_logs'] = ttk.Button(
        window,
        text='View Logs',

    )

    UI['view_logs'].grid(row=3, column=0)

    count_frame = ttk.LabelFrame(
        window,
        text='Last Compile:',
        labelanchor=N,
    )

    count_frame.grid(row=3, column=0)

    ttk.Label(
        count_frame,
        text='Entity',
        anchor=N,
    ).grid(row=0, column=0, columnspan=3, sticky=EW)

    UI['count_ent'] = ttk.Progressbar(
        count_frame,
        maximum=MAX_ENTS,
        variable=count_ents,
        length=120,
    )
    UI['count_ent'].grid(
        row=1,
        column=0,
        columnspan=3,
        sticky=EW,
        padx=5,
    )


    ttk.Label(
        count_frame,
        text='Overlay',
        anchor=CENTER,
    ).grid(row=2, column=0, sticky=EW)
    UI['count_over'] = ttk.Progressbar(
        count_frame,
        maximum=MAX_OVERLAY,
        variable=count_overlay,
        length=50,
    )
    UI['count_over'].grid(row=3, column=0, sticky=EW, padx=5)

    ttk.Button(
        count_frame,
        image=png.loadPng('icons/tool_sub'),
        command=refresh_counts,
    ).grid(row=3, column=1)


    ttk.Label(
        count_frame,
        text='Brush',
        anchor=CENTER,
    ).grid(row=2, column=2, sticky=EW)
    UI['count_brush'] = ttk.Progressbar(
        count_frame,
        maximum=MAX_BRUSH,
        variable=count_brush,
        length=50,
    )
    UI['count_brush'].grid(row=3, column=2, sticky=EW, padx=5)

    refresh_counts(reload=False)