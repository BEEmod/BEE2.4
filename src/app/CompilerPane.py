"""Implement the pane configuring compiler features.

These can be set and take effect immediately, without needing to export.
"""
from __future__ import annotations
import tkinter as tk
from tkinter import filedialog
from tkinter import ttk
from typing import Optional, Union
import base64

from PIL import Image, ImageTk
from atomicwrites import atomic_write

from srctools import Property
from srctools.logger import get_logger

from packages import CORRIDOR_COUNTS, CorrDesc
from app import selector_win, TK_ROOT
from app.tooltip import add_tooltip, set_tooltip
from app import tkMarkdown, SubPane, img, tk_tools
from BEE2_config import ConfigFile, option_handler
import utils


LOGGER = get_logger(__name__)

# The size of PeTI screenshots
PETI_WIDTH = 555
PETI_HEIGHT = 312

CORRIDOR: dict[str, selector_win.selWin] = {}
CORRIDOR_DATA: dict[tuple[str, int], CorrDesc] = {}

CORRIDOR_DESC = tkMarkdown.convert('', None)

COMPILE_DEFAULTS = {
    'Screenshot': {
        'Type': 'AUTO',
        'Loc': '',
    },
    'General': {
        'spawn_elev': 'True',
        'player_model': 'PETI',
        'force_final_light': '0',
        'use_voice_priority': '1',
        'packfile_dump_dir': '',
        'packfile_dump_enable': '0',
    },
    'Corridor': {
        'sp_entry': '1',
        'sp_exit': '1',
        'coop': '1',
    },
    'Counts': {
        'brush': '0',
        'overlay': '0',

        'entity': '0',

        'max_brush': '8192',
        'max_overlay': '512',
        'max_entity': '2048',
    },
    'CorridorNames': {},
}

PLAYER_MODELS = {
    'ATLAS': _('ATLAS'),
    'PBODY': _('P-Body'),
    'SP': _('Chell'),
    'PETI': _('Bendy'),
}
PLAYER_MODEL_ORDER = ['PETI', 'SP', 'ATLAS', 'PBODY']
PLAYER_MODELS_REV = {value: key for key, value in PLAYER_MODELS.items()}

COMPILE_CFG = ConfigFile('compile.cfg')
COMPILE_CFG.set_defaults(COMPILE_DEFAULTS)
window: Union[SubPane.SubPane, tk.Tk, None] = None
UI: dict[str, tk.Widget] = {}

chosen_thumb = tk.StringVar(
    value=COMPILE_CFG.get_val('Screenshot', 'Type', 'AUTO')
)
tk_screenshot = None  # The preview image shown

# Location we copy custom screenshots to
SCREENSHOT_LOC = str(utils.conf_location('screenshot.jpg'))

VOICE_PRIORITY_VAR = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'use_voice_priority', True))

player_model_var = tk.StringVar(
    value=PLAYER_MODELS.get(
        COMPILE_CFG.get_val('General', 'player_model', 'PETI'),
        PLAYER_MODELS['PETI'],
    )
)
start_in_elev = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'spawn_elev'))
cust_file_loc = COMPILE_CFG.get_val('Screenshot', 'Loc', '')
cust_file_loc_var = tk.StringVar(value='')

packfile_dump_enable = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'packfile_dump_enable'))

count_brush = tk.IntVar(value=0)
count_entity = tk.IntVar(value=0)
count_overlay = tk.IntVar(value=0)

# Controls flash_count()
count_brush.should_flash = False
count_entity.should_flash = False
count_overlay.should_flash = False

# The data for the 3 progress bars -
# (variable, config_name, default_max, description)
COUNT_CATEGORIES = [
    (
        count_brush, 'brush', 8192,
        # i18n: Progress bar description
        _("Brushes form the walls or other parts of the test chamber. If this "
          "is high, it may help to reduce the size of the map or remove "
          "intricate shapes.")
    ),
    (
        count_entity, 'entity', 2048,
        # i18n: Progress bar description
        _("Entities are the things in the map that have functionality. Removing "
          "complex moving items will help reduce this. Items have their entity "
          "count listed in the item description window.\n\n"
          "This isn't completely accurate, some entity types are counted here "
          "but don't affect the ingame limit, while others may generate additional "
          "entities at runtime."),
    ),
    (
        count_overlay, 'overlay', 512,
        # i18n: Progress bar description
        _("Overlays are smaller images affixed to surfaces, like signs or "
          "indicator lights. Hiding complex antlines or setting them to signage "
          "will reduce this.")
    ),
]

vrad_light_type = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'vrad_force_full'))
cleanup_screenshot = tk.IntVar(value=COMPILE_CFG.get_bool('Screenshot', 'del_old', True))


@option_handler('CompilerPane')
def save_load_compile_pane(props: Optional[Property]=None) -> Optional[Property]:
    """Save/load compiler options from the palette.

    Note: We specifically do not save/load the following:
        - packfile dumping
        - compile counts
    This is because these are more system-dependent than map dependent.
    """
    if props is None:  # Saving
        corr_prop = Property('corridor', [])
        props = Property('', [
            Property('sshot_type', chosen_thumb.get()),
            Property('sshot_cleanup', str(cleanup_screenshot.get())),
            Property('spawn_elev', str(start_in_elev.get())),
            Property('player_model', PLAYER_MODELS_REV[player_model_var.get()]),
            Property('use_voice_priority', str(VOICE_PRIORITY_VAR.get())),
            corr_prop,
        ])
        for group, win in CORRIDOR.items():
            corr_prop[group] = win.chosen_id or '<NONE>'

        # Embed the screenshot in so we can load it later.
        if chosen_thumb.get() == 'CUST':
            # encodebytes() splits it into multiple lines, which we write
            # in individual blocks to prevent having a massively long line
            # in the file.
            with open(SCREENSHOT_LOC, 'rb') as f:
                screenshot_data = base64.encodebytes(f.read())
            props.append(Property(
                'sshot_data',
                [
                    Property('b64', data)
                    for data in
                    screenshot_data.decode('ascii').splitlines()
                ]
            ))

        return props

    # else: Loading

    chosen_thumb.set(props['sshot_type', chosen_thumb.get()])
    cleanup_screenshot.set(props.bool('sshot_cleanup', cleanup_screenshot.get()))

    if 'sshot_data' in props:
        screenshot_parts = b'\n'.join([
            prop.value.encode('ascii')
            for prop in
            props.find_children('sshot_data')
        ])
        screenshot_data = base64.decodebytes(screenshot_parts)
        with atomic_write(SCREENSHOT_LOC, mode='wb', overwrite=True) as f:
            f.write(screenshot_data)

    # Refresh these.
    set_screen_type()
    set_screenshot()

    start_in_elev.set(props.bool('spawn_elev', start_in_elev.get()))

    try:
        player_mdl = props['player_model']
    except LookupError:
        pass
    else:
        player_model_var.set(PLAYER_MODELS[player_mdl])
        COMPILE_CFG['General']['player_model'] = player_mdl

    VOICE_PRIORITY_VAR.set(props.bool('use_voice_priority', VOICE_PRIORITY_VAR.get()))

    corr_prop = props.find_key('corridor', [])
    for group, win in CORRIDOR.items():
        try:
            sel_id = corr_prop[group]
        except LookupError:
            "No config option, ok."
        else:
            win.sel_item_id(sel_id)
            COMPILE_CFG['Corridor'][group] = '0' if sel_id == '<NONE>' else sel_id

    COMPILE_CFG.save_check()
    return None


def load_corridors() -> None:
    """Parse corridors out of the config file."""
    corridor_conf = COMPILE_CFG['CorridorNames']
    config = {}
    for group, length in CORRIDOR_COUNTS.items():
        for i in range(1, length + 1):
            config[group, i] = CorrDesc(
                name=corridor_conf.get('{}_{}_name'.format(group, i), ''),
                icon=utils.PackagePath.parse(corridor_conf.get('{}_{}_icon'.format(group, i), img.PATH_ERROR), 'special'),
                desc=corridor_conf.get('{}_{}_desc'.format(group, i), ''),
            )
    set_corridors(config)


def set_corridors(config: dict[tuple[str, int], CorrDesc]) -> None:
    """Set the corridor data based on the passed in config."""
    CORRIDOR_DATA.clear()
    CORRIDOR_DATA.update(config)

    default_icon = img.Handle.builtin('BEE2/corr_generic', 64, 64)

    corridor_conf = COMPILE_CFG['CorridorNames']

    for group, length in CORRIDOR_COUNTS.items():
        selector = CORRIDOR[group]
        for item in selector.item_list:
            if item.name == '<NONE>':
                continue  # No customisation for this.
            ind = int(item.name)

            data = config[group, ind]

            corridor_conf['{}_{}_name'.format(group, ind)] = data.name
            corridor_conf['{}_{}_desc'.format(group, ind)] = data.desc
            corridor_conf['{}_{}_icon'.format(group, ind)] = str(data.icon)

            # Note: default corridor description
            desc = data.name or _('Corridor')
            item.longName = item.shortName = item.context_lbl = item.name + ': ' + desc

            if data.icon:
                item.large_icon = img.Handle.parse_uri(
                    data.icon,
                    *selector_win.ICON_SIZE_LRG,
                )
                item.icon = img.Handle.parse_uri(
                    data.icon,
                    selector_win.ICON_SIZE, selector_win.ICON_SIZE,
                )
            else:
                item.icon = item.large_icon = default_icon

            if data.desc:
                item.desc = tkMarkdown.convert(data.desc, None)
            else:
                item.desc = CORRIDOR_DESC

        selector.refresh()
        selector.set_disp()

    COMPILE_CFG.save_check()


def make_corr_wid(corr_name: str, title: str) -> None:
    """Create the corridor widget and items."""
    length = CORRIDOR_COUNTS[corr_name]

    CORRIDOR[corr_name] = sel = selector_win.selWin(
        TK_ROOT,
        [
            selector_win.Item(
                str(i),
                'INVALID: ' + str(i),
            )
            for i in range(1, length + 1)
        ],
        title=title,
        none_desc=_(
            'Randomly choose a corridor. '
            'This is saved in the puzzle data '
            'and will not change.'
        ),
        none_icon=img.Handle.builtin('BEE2/random', 96, 96),
        none_name=_('Random'),
        callback=sel_corr_callback,
        callback_params=[corr_name],
    )

    chosen_corr = COMPILE_CFG.get_int('Corridor', corr_name)
    if chosen_corr == 0:
        sel.sel_item_id('<NONE>')
    else:
        sel.sel_item_id(str(chosen_corr))


def sel_corr_callback(sel_item: str, corr_name: str) -> None:
    """Callback for saving the result of selecting a corridor."""
    COMPILE_CFG['Corridor'][corr_name] = sel_item or '0'
    COMPILE_CFG.save_check()


def flash_count() -> None:
    """Flash the counter between 0 and 100 when on."""
    should_cont = False

    for var in (count_brush, count_entity, count_overlay):
        if not getattr(var, 'should_flash', False):
            continue  # Abort when it shouldn't be flashing

        if var.get() == 0:
            var.set(100)
        else:
            var.set(0)

        should_cont = True

    if should_cont:
        TK_ROOT.after(750, flash_count)


def refresh_counts(reload: bool = True) -> None:
    """Set the last-compile limit display."""
    if reload:
        COMPILE_CFG.load()

    # Don't re-run the flash function if it's already on.
    run_flash = not (
        count_entity.should_flash or
        count_overlay.should_flash or
        count_brush.should_flash
    )

    for bar_var, name, default, tip_blurb in COUNT_CATEGORIES:
        value = COMPILE_CFG.get_int('Counts', name)

        if name == 'entity':
            # The in-engine entity limit is different to VBSP's limit
            # (that one might include prop_static, lights etc).
            max_value = default
        else:
            # Use or to ensure no divide-by-zero occurs..
            max_value = COMPILE_CFG.get_int('Counts', 'max_' + name) or default

        # If it's hit the limit, make it continuously scroll to draw
        # attention to the bar.
        if value >= max_value:
            bar_var.should_flash = True
        else:
            bar_var.should_flash = False
            bar_var.set(100 * value / max_value)

        set_tooltip(UI['count_' + name], '{}/{} ({:.2%}):\n{}'.format(
            value,
            max_value,
            value / max_value,
            tip_blurb,
        ))

    if run_flash:
        flash_count()


def set_pack_dump_dir(path: str) -> None:
    """Run when the packfile dump path is changed."""
    COMPILE_CFG['General']['packfile_dump_dir'] = path
    COMPILE_CFG.save_check()


def set_pack_dump_enabled() -> None:
    """Run when the packfile enable checkbox is modified."""
    is_enabled = packfile_dump_enable.get()
    COMPILE_CFG['General']['packfile_dump_enable'] = str(is_enabled)
    COMPILE_CFG.save_check()

    if is_enabled:
        UI['packfile_filefield'].grid()
    else:
        UI['packfile_filefield'].grid_remove()


def find_screenshot(e=None) -> None:
    """Prompt to browse for a screenshot."""
    file_name = filedialog.askopenfilename(
        title='Find Screenshot',
        filetypes=[
            # note: File type description
            (_('Image Files'), '*.jpg *.jpeg *.jpe *.jfif *.png *.bmp'
                               '*.tiff *.tga *.ico *.psd'),
        ],
        initialdir='C:',
    )
    if file_name:
        image = Image.open(file_name).convert('RGB')  # Remove alpha channel if present.
        COMPILE_CFG['Screenshot']['LOC'] = SCREENSHOT_LOC
        image.save(SCREENSHOT_LOC)
        set_screenshot(image)
    COMPILE_CFG.save_check()


def set_screen_type() -> None:
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

    COMPILE_CFG.save_check()


def set_screenshot(image: Image=None) -> None:
    """Show the screenshot on the UI."""
    # Make the visible screenshot small
    global tk_screenshot
    if image is None:
        try:
            image = Image.open(SCREENSHOT_LOC)
        except IOError:  # Image doesn't exist!
            # In that case, use a black image
            image = Image.new('RGB', (1, 1), color=(0, 0, 0))
    # Make a smaller image for showing in the UI..
    tk_img = image.resize(
        (
            int(PETI_WIDTH // 3.5),
            int(PETI_HEIGHT // 3.5),
        ),
        Image.LANCZOS
    )
    tk_screenshot = ImageTk.PhotoImage(tk_img)
    UI['thumb_label']['image'] = tk_screenshot


def make_setter(section: str, config: str, variable: tk.Variable) -> None:
    """Create a callback which sets the given config from a variable."""
    def callback(var_name: str, var_ind: str, cback_name: str) -> None:
        """Automatically called when the variable is written to."""
        COMPILE_CFG[section][config] = str(variable.get())
        COMPILE_CFG.save_check()

    variable.trace_add('write', callback)


def make_widgets() -> None:
    """Create the compiler options pane.

    """
    make_setter('General', 'use_voice_priority', VOICE_PRIORITY_VAR)
    make_setter('General', 'spawn_elev', start_in_elev)
    make_setter('Screenshot', 'del_old', cleanup_screenshot)
    make_setter('General', 'vrad_force_full', vrad_light_type)

    ttk.Label(window, justify='center', text=_(
        "Options on this panel can be changed \n"
        "without exporting or restarting the game."
    )).grid(row=0, column=0, sticky='ew', padx=2, pady=2)

    UI['nbook'] = nbook = ttk.Notebook(window)

    nbook.grid(row=1, column=0, sticky='nsew')
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)

    nbook.enable_traversal()

    map_frame = ttk.Frame(nbook)
    # note: Tab name
    nbook.add(map_frame, text=_('Map Settings'))
    make_map_widgets(map_frame)

    comp_frame = ttk.Frame(nbook)
    # note: Tab name
    nbook.add(comp_frame, text=_('Compile Settings'))
    make_comp_widgets(comp_frame)


def make_comp_widgets(frame: ttk.Frame):
    """Create widgets for the compiler settings pane.

    These are generally things that are aesthetic, and to do with the file and
    compilation process.
    """
    frame.columnconfigure(0, weight=1)

    thumb_frame = ttk.LabelFrame(
        frame,
        text=_('Thumbnail'),
        labelanchor=tk.N,
    )
    thumb_frame.grid(row=0, column=0, sticky=tk.EW)
    thumb_frame.columnconfigure(0, weight=1)

    UI['thumb_auto'] = ttk.Radiobutton(
        thumb_frame,
        text=_('Auto'),
        value='AUTO',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    UI['thumb_peti'] = ttk.Radiobutton(
        thumb_frame,
        text=_('PeTI'),
        value='PETI',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    UI['thumb_custom'] = ttk.Radiobutton(
        thumb_frame,
        text=_('Custom:'),
        value='CUST',
        variable=chosen_thumb,
        command=set_screen_type,
    )

    UI['thumb_label'] = ttk.Label(
        thumb_frame,
        anchor=tk.CENTER,
        cursor=tk_tools.Cursors.LINK,
    )
    UI['thumb_label'].bind(tk_tools.EVENTS['LEFT'], find_screenshot)

    UI['thumb_cleanup'] = ttk.Checkbutton(
        thumb_frame,
        text=_('Cleanup old screenshots'),
        variable=cleanup_screenshot,
    )

    UI['thumb_auto'].grid(row=0, column=0, sticky='W')
    UI['thumb_peti'].grid(row=0, column=1, sticky='W')
    UI['thumb_custom'].grid(row=1, column=0, columnspan=2, sticky='NEW')
    UI['thumb_cleanup'].grid(row=3, columnspan=2, sticky='W')
    add_tooltip(
        UI['thumb_auto'],
        _("Override the map image to use a screenshot automatically taken "
          "from the beginning of a chamber. Press F5 to take a new "
          "screenshot. If the map has not been previewed recently "
          "(within the last few hours), the default PeTI screenshot "
          "will be used instead.")
    )
    add_tooltip(
        UI['thumb_peti'],
        _("Use the normal editor view for the map preview image.")
    )
    custom_tooltip = _(
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
        _('Automatically delete unused Automatic screenshots. '
          'Disable if you want to keep things in "portal2/screenshots". ')
    )

    if chosen_thumb.get() == 'CUST':
        # Show this if the user has set it before
        UI['thumb_label'].grid(row=2, column=0, columnspan=2, sticky='ew')
    set_screenshot()  # Load the last saved screenshot

    vrad_frame = ttk.LabelFrame(
        frame,
        text=_('Lighting:'),
        labelanchor='n',
    )
    vrad_frame.grid(row=1, column=0, sticky='ew')

    UI['light_fast'] = ttk.Radiobutton(
        vrad_frame,
        text=_('Fast'),
        value=0,
        variable=vrad_light_type,
    )
    UI['light_fast'].grid(row=0, column=0)
    UI['light_full'] = ttk.Radiobutton(
        vrad_frame,
        text=_('Full'),
        value=1,
        variable=vrad_light_type,
    )
    UI['light_full'].grid(row=0, column=1)

    add_tooltip(
        UI['light_fast'],
        _("Compile with lower-quality, fast lighting. This speeds "
          "up compile times, but does not appear as good. Some "
          "shadows may appear wrong.\n"
          "When publishing, this is ignored.")
    )
    add_tooltip(
        UI['light_full'],
        _("Compile with high-quality lighting. This looks correct, "
          "but takes longer to compute. Use if you're arranging lights.\n"
          "When publishing, this is always used.")
    )

    packfile_enable = ttk.Checkbutton(
        frame,
        text=_('Dump packed files to:'),
        variable=packfile_dump_enable,
        command=set_pack_dump_enabled,
    )

    packfile_frame = ttk.LabelFrame(
        frame,
        labelwidget=packfile_enable,
    )
    packfile_frame.grid(row=2, column=0, sticky='ew')

    UI['packfile_filefield'] = packfile_filefield = tk_tools.FileField(
        packfile_frame,
        is_dir=True,
        loc=COMPILE_CFG.get_val('General', 'packfile_dump_dir', ''),
        callback=set_pack_dump_dir,
    )
    packfile_filefield.grid(row=0, column=0, sticky='ew')
    packfile_frame.columnconfigure(0, weight=1)
    ttk.Frame(packfile_frame).grid(row=1)

    set_pack_dump_enabled()

    add_tooltip(
        packfile_enable,
        _("When compiling, dump all files which were packed into the map. Useful"
          " if you're intending to edit maps in Hammer.")
    )

    count_frame = ttk.LabelFrame(
        frame,
        text=_('Last Compile:'),
        labelanchor='n',
    )

    count_frame.grid(row=7, column=0, sticky='ew')
    count_frame.columnconfigure(0, weight=1)
    count_frame.columnconfigure(2, weight=1)

    ttk.Label(
        count_frame,
        text=_('Entity'),
        anchor='n',
    ).grid(row=0, column=0, columnspan=3, sticky='ew')

    UI['count_entity'] = ttk.Progressbar(
        count_frame,
        maximum=100,
        variable=count_entity,
        length=120,
    )
    UI['count_entity'].grid(
        row=1,
        column=0,
        columnspan=3,
        sticky='ew',
        padx=5,
    )

    ttk.Label(
        count_frame,
        text=_('Overlay'),
        anchor='center',
    ).grid(row=2, column=0, sticky='ew')
    UI['count_overlay'] = ttk.Progressbar(
        count_frame,
        maximum=100,
        variable=count_overlay,
        length=50,
    )
    UI['count_overlay'].grid(row=3, column=0, sticky='ew', padx=5)

    UI['refresh_counts'] = SubPane.make_tool_button(
        count_frame,
        'icons/tool_sub',
        refresh_counts,
    )
    UI['refresh_counts'].grid(row=3, column=1)
    add_tooltip(
        UI['refresh_counts'],
        _("Refresh the compile progress bars. Press after a compile has been "
          "performed to show the new values."),
    )

    ttk.Label(
        count_frame,
        text=_('Brush'),
        anchor='center',
    ).grid(row=2, column=2, sticky=tk.EW)
    UI['count_brush'] = ttk.Progressbar(
        count_frame,
        maximum=100,
        variable=count_brush,
        length=50,
    )
    UI['count_brush'].grid(row=3, column=2, sticky='ew', padx=5)

    for wid_name in ('count_overlay', 'count_entity', 'count_brush'):
        # Add in tooltip logic to the widgets.
        add_tooltip(UI[wid_name])

    refresh_counts(reload=False)


def make_map_widgets(frame: ttk.Frame):
    """Create widgets for the map settings pane.

    These are things which mainly affect the geometry or gameplay of the map.
    """

    frame.columnconfigure(0, weight=1)

    voice_frame = ttk.LabelFrame(
        frame,
        text=_('Voicelines:'),
        labelanchor='nw',
    )
    voice_frame.grid(row=1, column=0, sticky='ew')

    voice_priority = ttk.Checkbutton(
        voice_frame,
        text=_("Use voiceline priorities"),
        variable=VOICE_PRIORITY_VAR,
    )
    voice_priority.grid(row=0, column=0)
    add_tooltip(
        voice_priority,
        _("Only choose the highest-priority voicelines. This means more "
          "generic lines will can only be chosen if few test elements are in "
          "the map. If disabled any applicable lines will be used."),
    )

    elev_frame = ttk.LabelFrame(
        frame,
        text=_('Spawn at:'),
        labelanchor='n',
    )

    elev_frame.grid(row=2, column=0, sticky='ew')
    elev_frame.columnconfigure(0, weight=1)
    elev_frame.columnconfigure(1, weight=1)

    elev_preview = ttk.Radiobutton(
        elev_frame,
        text=_('Entry Door'),
        value=0,
        variable=start_in_elev,
    )
    elev_elevator = ttk.Radiobutton(
        elev_frame,
        text=_('Elevator'),
        value=1,
        variable=start_in_elev,
    )

    elev_preview.grid(row=0, column=0, sticky='w')
    elev_elevator.grid(row=0, column=1, sticky='w')

    add_tooltip(
        elev_elevator,
        _("When previewing in SP, spawn inside the entry elevator. "
          "Use this to examine the entry and exit corridors.")
    )
    add_tooltip(
        elev_preview,
        _("When previewing in SP, spawn just before the entry door.")
    )

    corr_frame = ttk.LabelFrame(
        frame,
        width=18,
        text=_('Corridor:'),
        labelanchor='n',
    )
    corr_frame.grid(row=3, column=0, sticky='ew')
    corr_frame.columnconfigure(1, weight=1)

    make_corr_wid('sp_entry', _('Singleplayer Entry Corridor'))  # i18n: corridor selector window title.
    make_corr_wid('sp_exit', _('Singleplayer Exit Corridor'))  # i18n: corridor selector window title.
    make_corr_wid('coop', _('Coop Exit Corridor'))  # i18n: corridor selector window title.

    load_corridors()

    CORRIDOR['sp_entry'].widget(corr_frame).grid(row=0, column=1, sticky='ew')
    CORRIDOR['sp_exit'].widget(corr_frame).grid(row=1, column=1, sticky='ew')
    CORRIDOR['coop'].widget(corr_frame).grid(row=2, column=1, sticky='ew')

    ttk.Label(
        corr_frame,
        text=_('SP Entry:'),
        anchor='e',
    ).grid(row=0, column=0, sticky='ew', padx=2)
    ttk.Label(
        corr_frame,
        text=_('SP Exit:'),
        anchor='e',
    ).grid(row=1, column=0, sticky='ew', padx=2)
    ttk.Label(
        corr_frame,
        text=_('Coop Exit:'),
        anchor='e',
    ).grid(row=2, column=0, sticky='ew', padx=2)

    model_frame = ttk.LabelFrame(
        frame,
        text=_('Player Model (SP):'),
        labelanchor='n',
    )
    model_frame.grid(row=4, column=0, sticky='ew')
    player_mdl = ttk.Combobox(
        model_frame,
        exportselection=False,
        textvariable=player_model_var,
        values=[PLAYER_MODELS[mdl] for mdl in PLAYER_MODEL_ORDER],
        width=20,
    )
    # Users can only use the dropdown
    player_mdl.state(['readonly'])
    player_mdl.grid(row=0, column=0, sticky=tk.EW)

    def set_model(e: tk.Event) -> None:
        """Save the selected player model."""
        text = player_model_var.get()
        COMPILE_CFG['General']['player_model'] = PLAYER_MODELS_REV[text]
        COMPILE_CFG.save()

    player_mdl.bind('<<ComboboxSelected>>', set_model)

    model_frame.columnconfigure(0, weight=1)


def make_pane(tool_frame: tk.Frame, menu_bar: tk.Menu) -> None:
    """Initialise when part of the BEE2."""
    global window
    window = SubPane.SubPane(
        TK_ROOT,
        title=_('Compile Options'),
        name='compiler',
        menu_bar=menu_bar,
        resize_x=True,
        resize_y=False,
        tool_frame=tool_frame,
        tool_img='icons/win_compiler',
        tool_col=4,
    )
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    make_widgets()


def init_application() -> None:
    """Initialise when standalone."""
    global window
    window = TK_ROOT
    window.title(_('Compiler Options - {}').format(utils.BEE_VERSION))
    window.resizable(True, False)

    make_widgets()

    TK_ROOT.deiconify()
