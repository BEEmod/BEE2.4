from tkinter import *
from tk_root import TK_ROOT
from tkinter import ttk
from tkinter import filedialog

from functools import partial

import img as png

from BEE2_config import ConfigFile, GEN_OPTS
from SubPane import SubPane
import utils

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
        'player_model': 'PETI',
        },
    'Corridor': {
        'sp_entry': '1',
        'sp_exit': '1',
        'coop': '1',
    },
    'Counts': {
        'brush': '0',
        'ent': '0',
        'overlay': '0',
        },
    }

PLAYER_MODELS = {
    'ATLAS': 'ATLAS',
    'PBODY': 'P-Body',
    'SP': 'Chell',
    'PETI': 'Bendy',
}
PLAYER_MODEL_ORDER = ['Bendy', 'Chell', 'ATLAS', 'P-Body']
PLAYER_MODELS_REV = {value: key for key, value in PLAYER_MODELS.items()}

COMPILE_CFG = ConfigFile('compile.cfg')
COMPILE_CFG.set_defaults(COMPILE_DEFAULTS)
window = None
UI = {}

chosen_thumb = StringVar(
    value=COMPILE_CFG.get_val('Screenshot', 'Type', 'AUTO')
)
player_model_var = StringVar(
    value=PLAYER_MODELS.get(
        COMPILE_CFG.get_val('General', 'player_model', 'PETI'),
        PLAYER_MODELS['PETI'],
    )
)
start_in_elev = IntVar(value=0)
cust_file_loc = COMPILE_CFG.get_val('Screenshot', 'Loc', '')
cust_file_loc_var = StringVar(value='')

count_brush = IntVar(value=0)
count_ents = IntVar(value=0)
count_overlay = IntVar(value=0)

CORRIDOR = {}

def set_corr_values(group_name, props):
    """Set the corrdors according to the passed prop_block."""
    count = 7 if group_name == 'sp_entry' else 4
    group = CORRIDOR[group_name] = ['Random'] + [
        str(i) + ': Corridor'
        for i in
        range(1, count+1)
    ]
    for prop in props[group_name]:
        try:
            ind = int(prop.name)
        except ValueError:
            continue

        if 0 < ind <= count:
            group[ind] = '{!r}: {}'.format(ind, prop.value)


def make_corr_combo(frm, corr_name, width):
    set_corr_values(corr_name, {corr_name: []})
    widget = ttk.Combobox(
        frm,
        values=CORRIDOR[corr_name],
        width=width,
        exportselection=0,
    )
    widget['postcommand'] = partial(set_corr_dropdown, corr_name, widget)
    widget.state(['readonly'])
    widget.bind(
        '<<ComboboxSelected>>',
        partial(set_corr, corr_name)
    )
    widget.current(COMPILE_CFG.get_int('Corridor', corr_name))
    return widget


def refresh_counts(reload=True):
    if reload:
        COMPILE_CFG.load()
    count_brush.set(COMPILE_CFG.get_int('Counts', 'brush'))
    count_ents.set(COMPILE_CFG.get_int('Counts', 'ent'))
    count_overlay.set(COMPILE_CFG.get_int('Counts', 'overlay'))


def find_screenshot(_=None):
    global cust_file_loc
    cust_file_loc = ''
    file_name = filedialog.askopenfilename(
        title='Find Game Exe',
        filetypes=[
            ('JPEG Image', '*.jpg *.jpeg *.jpe *.jfif'),
        ],
        initialdir='C:',
    )
    if file_name:
        cust_file_loc = file_name
        COMPILE_CFG['Screenshot']['LOC'] = file_name
        set_screenshot_text()
        UI['thumb_custom'].invoke()
    else:
        cust_file_loc = ''
        cust_file_loc_var.set('')
        COMPILE_CFG['Screenshot']['LOC'] = ''
        # Set to this instead!
        if chosen_thumb.get() == 'CUST':
            UI['thumb_auto'].invoke()
    COMPILE_CFG.save_check()


def set_screenshot_text(_=None):
    if len(cust_file_loc) > 20:
        if cust_file_loc[-18] in r'\/':
            # We don't whant it to start with "../"!
            cust_file_loc_var.set('...' + cust_file_loc[-17:])
        else:
            cust_file_loc_var.set('..' + cust_file_loc[-18:])
    else:
        cust_file_loc_var.set(cust_file_loc)


def set_elev_type():
    COMPILE_CFG['General']['spawn_elev'] = str(start_in_elev.get())
    COMPILE_CFG.save()


def set_screen_type():
    COMPILE_CFG['Screenshot']['type'] = chosen_thumb.get()
    COMPILE_CFG.save()


def set_model(_=None):
    text = player_model_var.get()
    COMPILE_CFG['General']['player_model'] = PLAYER_MODELS_REV[text]
    COMPILE_CFG.save()

def set_corr(corr_name, e):
    COMPILE_CFG['Corridor'][corr_name] = str(e.widget.current())
    COMPILE_CFG.save()

def set_corr_dropdown(corr_name, widget):
    """Set the values in the dropdown when it's opened."""
    widget['values'] = CORRIDOR[corr_name]

def make_pane(tool_frame):
    """Create the compiler options pane.

    """
    global window
    window = SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Compile Opt',
        name='compiler',
        resize_x=True,
        resize_y=False,
        tool_frame=tool_frame,
        tool_img=png.png('icons/win_compiler'),
        tool_col=4,
    )
    window.columnconfigure(0, weight=1)

    thumb_frame = ttk.LabelFrame(
        window,
        text='Thumbnail',
        labelanchor=N,
    )
    thumb_frame.grid(row=0, column=0, sticky=EW)
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
        cursor=utils.CURSORS['regular'],
        textvariable=cust_file_loc_var,
        width=15,
    )
    UI['thumb_custom_file'].bind(utils.EVENTS['LEFT'], find_screenshot)
    UI['thumb_custom_file'].bind("<Key>", set_screenshot_text)

    UI['thumb_custom_btn'] = ttk.Button(
        cust_frame,
        text="...",
        width=1.5,
        command=find_screenshot,
    )

    UI['thumb_auto'].grid(row=0, column=0, sticky=W)
    UI['thumb_peti'].grid(row=0, column=1, sticky=W)
    cust_frame.grid(row=1, column=0, columnspan=2, sticky=EW)
    UI['thumb_custom'].grid(row=0, column=0, sticky=W)
    UI['thumb_custom_file'].grid(row=0, column=1, sticky=EW)
    UI['thumb_custom_btn'].grid(row=0, column=2, sticky=EW)

    elev_frame = ttk.LabelFrame(
        window,
        text='Spawn at:',
        labelanchor=N,
    )

    elev_frame.grid(row=1, column=0, sticky=EW)
    elev_frame.columnconfigure(0, weight=1)
    elev_frame.columnconfigure(1, weight=1)

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
    UI['elev_elevator'].grid(row=0, column=1, sticky=W)

    corr_frame = ttk.LabelFrame(
        window,
        text='Corridor:',
        labelanchor=N,
    )
    corr_frame.grid(row=2, column=0, sticky=EW)
    corr_frame.columnconfigure(0, weight=1)
    corr_frame.columnconfigure(1, weight=1)

    UI['corr_sp_entry'] = make_corr_combo(
        corr_frame,
        'sp_entry',
        width=9,
    )

    UI['corr_sp_exit'] = make_corr_combo(
        corr_frame,
        'sp_exit',
        width=9,
    )

    UI['corr_coop'] = make_corr_combo(
        corr_frame,
        'coop',
        width=9,
    )

    UI['corr_sp_entry'].grid(row=1, column=0, sticky=EW)
    UI['corr_sp_exit'].grid(row=1, column=1, sticky=EW)
    UI['corr_coop'].grid(row=2, column=1, sticky=EW)
    ttk.Label(
        corr_frame,
        text='SP Entry:',
        anchor=CENTER,
    ).grid(row=0, column=0, sticky=EW)
    ttk.Label(
        corr_frame,
        text='SP Exit:',
        anchor=CENTER,
    ).grid(row=0, column=1, sticky=EW)
    ttk.Label(
        corr_frame,
        text='Coop:',
        anchor=CENTER,
    ).grid(row=2, column=0, sticky=EW)

    model_frame = ttk.LabelFrame(
        window,
        text='Player Model (SP):',
        labelanchor=N,
    )
    model_frame.grid(row=3, column=0, sticky=EW)
    UI['player_mdl'] = ttk.Combobox(
        model_frame,
        exportselection=0,
        textvariable=player_model_var,
        values=PLAYER_MODEL_ORDER,
        width=20,
    )
    # Users can only use the dropdown
    UI['player_mdl'].state(['readonly'])
    UI['player_mdl'].grid(row=0, column=0, sticky=EW)

    UI['player_mdl'].bind('<<ComboboxSelected>>', set_model)
    model_frame.columnconfigure(0, weight=1)

    count_frame = ttk.LabelFrame(
        window,
        text='Last Compile:',
        labelanchor=N,
    )

    count_frame.grid(row=4, column=0, sticky=EW)
    count_frame.columnconfigure(0, weight=1)
    count_frame.columnconfigure(2, weight=1)

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
        image=png.png('icons/tool_sub'),
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

    UI['view_logs'] = ttk.Button(
        count_frame,
        text='View Logs',
    )
    UI['view_logs'].grid(row=4, column=0, columnspan=3, sticky=EW)

    refresh_counts(reload=False)

# Set the text to the previously saved value
set_screenshot_text()