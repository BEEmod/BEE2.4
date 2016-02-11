from tkinter import *
from tk_tools import TK_ROOT
from tkinter import ttk
from tkinter import filedialog

from functools import partial
from PIL import Image, ImageTk

import os.path

import img as png

from BEE2_config import ConfigFile, GEN_OPTS
from tooltip import add_tooltip
import SubPane
import utils

MAX_ENTS = 2048
MAX_OVERLAY = 512
MAX_BRUSH = 8192

# The size of PeTI screenshots
PETI_WIDTH = 555
PETI_HEIGHT = 312


COMPILE_DEFAULTS = {
    'Screenshot': {
        'Type': 'AUTO',
        'Loc': '',
        },
    'General': {
        'spawn_elev': 'True',
        'player_model': 'PETI',
        'force_final_light': '0',
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
tk_screenshot = None # The preview image shown

# Location we copy custom screenshots to
SCREENSHOT_LOC = os.path.abspath(os.path.join(
        os.getcwd(),
        '..',
        'config',
        'screenshot.jpg'
    ))

player_model_var = StringVar(
    value=PLAYER_MODELS.get(
        COMPILE_CFG.get_val('General', 'player_model', 'PETI'),
        PLAYER_MODELS['PETI'],
    )
)
start_in_elev = IntVar(
    value=COMPILE_CFG.get_bool('General', 'spawn_elev')
)
cust_file_loc = COMPILE_CFG.get_val('Screenshot', 'Loc', '')
cust_file_loc_var = StringVar(value='')

count_brush = IntVar(value=0)
count_ents = IntVar(value=0)
count_overlay = IntVar(value=0)

vrad_light_type = IntVar(
    value=COMPILE_CFG.get_bool('General', 'vrad_force_full')
)
cleanup_screenshot = IntVar(
    value=COMPILE_CFG.get_bool('Screenshot', 'del_old', True)
)

CORRIDOR = {}


def set_corr_values(group_name, props):
    """Set the corrdors according to the passed prop_block."""
    count = 7 if group_name == 'sp_entry' else 4
    group = CORRIDOR[group_name] = ['Random'] + [
        str(i) + ': Corridor'
        for i in
        range(1, count + 1)
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
    """Prompt to browse for a screenshot."""
    file_name = filedialog.askopenfilename(
        title='Find Game Exe',
        filetypes=[
            ('Image File', '*.jpg *.jpeg *.jpe *.jfif *.png *.bmp'
                           '*.tiff *.tga *.ico *.psd'),
        ],
        initialdir='C:',
    )
    if file_name:
        load_screenshot(file_name)
    COMPILE_CFG.save_check()


def set_screen_type():
    """Set the type of screenshot used."""
    chosen = chosen_thumb.get()
    COMPILE_CFG['Screenshot']['type'] = chosen
    if chosen == 'CUST':
        UI['thumb_label'].grid(row=2, column=0, columnspan=2, sticky='EW')
    else:
        UI['thumb_label'].grid_forget()
    UI['thumb_label'].update()
    # Resize the pane to accommodate the shown/hidden image
    window.geometry('{}x{}'.format(
        window.winfo_width(),
        window.winfo_reqheight(),
    ))

    COMPILE_CFG.save()


def load_screenshot(path):
    """Copy the selected image, changing format if needed."""
    img = Image.open(path)
    resized_img = img.resize(
        # Resize to the same propotions as the original
        # PeTI screenshots.
        (
            img.width,
            int(img.height * PETI_WIDTH / PETI_HEIGHT)
        )
    )
    COMPILE_CFG['Screenshot']['LOC'] = SCREENSHOT_LOC
    resized_img.save(SCREENSHOT_LOC)
    set_screenshot(img)


def set_screenshot(img=None):
    # Make the visible screenshot small
    global tk_screenshot
    if img is None:
        try:
            img = Image.open(SCREENSHOT_LOC)
        except IOError:  # Image doesn't exist!
            # In that case, use a black image
            img = Image.new('RGB', (1, 1), color=(0, 0, 0))
    # Make a smaller image for showing in the UI..
    tk_img = img.resize(
        (
            int(PETI_WIDTH // 3.5),
            int(PETI_HEIGHT // 3.5),
        ),
        Image.LANCZOS
    )
    tk_screenshot = ImageTk.PhotoImage(tk_img)
    UI['thumb_label']['image'] = tk_screenshot


def set_screenshot_cleanup():
    COMPILE_CFG['Screenshot']['del_old'] = str(cleanup_screenshot.get())


def set_elev_type():
    COMPILE_CFG['General']['spawn_elev'] = str(start_in_elev.get())
    COMPILE_CFG.save()


def set_model(_=None):
    """Save the selected player model."""
    text = player_model_var.get()
    COMPILE_CFG['General']['player_model'] = PLAYER_MODELS_REV[text]
    COMPILE_CFG.save()


def set_corr(corr_name, e):
    """Save the chosen corridor when it's changed.

    This is shared by all three dropdowns.
    """
    COMPILE_CFG['Corridor'][corr_name] = str(e.widget.current())
    COMPILE_CFG.save()


def set_corr_dropdown(corr_name, widget):
    """Set the values in the dropdown when it's opened."""
    widget['values'] = CORRIDOR[corr_name]


def set_vrad_type():
    """Set the compile type override for VRAD."""
    COMPILE_CFG['General']['vrad_force_full'] = str(vrad_light_type.get())
    COMPILE_CFG.save()


def make_pane(tool_frame):
    """Create the compiler options pane.

    """
    global window
    window = SubPane.SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Compile Options',
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

    UI['thumb_custom'] = ttk.Radiobutton(
        thumb_frame,
        text='Custom:',
        value='CUST',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    UI['thumb_label'] = ttk.Label(
        thumb_frame,
        anchor=CENTER,
        cursor=utils.CURSORS['link'],
    )
    UI['thumb_label'].bind(
        utils.EVENTS['LEFT'],
        find_screenshot,
    )

    UI['thumb_cleanup'] = ttk.Checkbutton(
        thumb_frame,
        text='Cleanup old screenshots',
        variable=cleanup_screenshot,
        command=set_screenshot_cleanup,
    )

    UI['thumb_auto'].grid(row=0, column=0, sticky='W')
    UI['thumb_peti'].grid(row=0, column=1, sticky='W')
    UI['thumb_custom'].grid(row=1, column=0, columnspan=2, sticky='NEW')
    UI['thumb_cleanup'].grid(row=3, columnspan=2, sticky='W')
    add_tooltip(
        UI['thumb_auto'],
        "Override the map image to use a screenshot automatically taken "
        "from the beginning of a chamber. Press F5 to take a new "
        "screenshot. If the map has not been previewed recently "
        "(within the last few hours), the default PeTI screenshot "
        "will be used instead."
    )
    add_tooltip(
        UI['thumb_peti'],
        "Use the normal editor view for the map preview image."
    )
    custom_tooltip = (
        "Use a custom image for the map preview image. Click the "
        "screenshot to select.\n"
        "Images will be converted to JPEGs if needed."
    )
    add_tooltip(
        UI['thumb_custom'],
        custom_tooltip,
    )

    add_tooltip(
        UI['thumb_label'],
        custom_tooltip,
    )

    add_tooltip(
        UI['thumb_cleanup'],
        'Automatically delete unused Automatic screenshots. '
        'Disable if you want to keep things in "portal2/screenshots". '
    )

    if chosen_thumb.get() == 'CUST':
        # Show this if the user has set it before
        UI['thumb_label'].grid(row=2, column=0, columnspan=2, sticky='EW')
    set_screenshot()  # Load the last saved screenshot

    vrad_frame = ttk.LabelFrame(
        window,
        text='Lighting:',
        labelanchor=N,
    )
    vrad_frame.grid(row=1, column=0, sticky=EW)

    UI['light_fast'] = ttk.Radiobutton(
        vrad_frame,
        text='Fast',
        value=0,
        variable=vrad_light_type,
        command=set_vrad_type,
    )
    UI['light_fast'].grid(row=0, column=0)
    UI['light_full'] = ttk.Radiobutton(
        vrad_frame,
        text='Full',
        value=1,
        variable=vrad_light_type,
        command=set_vrad_type,
    )
    UI['light_full'].grid(row=0, column=1)

    add_tooltip(
        UI['light_fast'],
        "Compile with lower-quality, fast lighting. This speeds "
        "up compile times, but does not appear as good. Some "
        "shadows may appear wrong.\n"
        "When publishing, this is ignored."
    )
    add_tooltip(
        UI['light_full'],
        "Compile with high-quality lighting. This looks correct, "
        "but takes longer to compute. Use if you're arranging lights."
        "When publishing, this is always used."
    )

    elev_frame = ttk.LabelFrame(
        window,
        text='Spawn at:',
        labelanchor=N,
    )

    elev_frame.grid(row=2, column=0, sticky=EW)
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

    add_tooltip(
        UI['elev_elevator'],
        "When previewing in SP, spawn inside the entry elevator. "
        "This also disables the map restarts when you reach the "
        "exit door. Use this to examine the entry and exit corridors."
    )
    add_tooltip(
        UI['elev_preview'],
        "When previewing in SP, spawn just before the entry door. "
        "When you reach the exit door, the map will restart."
    )

    corr_frame = ttk.LabelFrame(
        window,
        text='Corridor:',
        labelanchor=N,
    )
    corr_frame.grid(row=3, column=0, sticky=EW)
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
    model_frame.grid(row=4, column=0, sticky=EW)
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

    count_frame.grid(row=5, column=0, sticky=EW)
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

    UI['refresh_counts'] = SubPane.make_tool_button(
        count_frame,
        png.png('icons/tool_sub', resize_to=16),
        refresh_counts,
    )
    UI['refresh_counts'].grid(row=3, column=1)

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