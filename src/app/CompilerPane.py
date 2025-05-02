"""Implement the pane configuring compiler features.

These can be set and take effect immediately, without needing to export.
"""
from __future__ import annotations

from typing import TypedDict, cast
from tkinter import filedialog, ttk
import tkinter as tk
from contextlib import aclosing
import functools
import io
import random

from PIL import Image, ImageTk
from srctools import AtomicWriter, bool_as_int
from srctools.logger import get_logger
import attrs
import trio
import trio_util

from config.compile_pane import CompilePaneState, PLAYER_MODEL_LEGACY_IDS
from config.player import AvailablePlayer
from transtoken import TransToken, CURRENT_LANG
from ui_tk import tk_tools, wid_transtoken, TK_ROOT
from ui_tk.img import TKImages
from ui_tk.subpane import SubPane
from ui_tk.tk_tools import ComboBoxMap, make_tool_button
from ui_tk.tooltip import add_tooltip, set_tooltip
from app.SubPane import CONF_COMPILER as PANE_CONF
import BEE2_config
import app
import async_util
import config
import consts
import packages
import utils


LOGGER = get_logger(__name__)

# The size of PeTI screenshots
PETI_WIDTH = 555
PETI_HEIGHT = 312

COMPILE_DEFAULTS: dict[str, dict[str, str]] = {
    'Screenshot': {
        'Type': 'AUTO',
        'Loc': '',
    },
    'General': {
        'spawn_elev': 'True',
        'player_model': 'PETI',
        'force_final_light': '0',
        'voiceline_priority': '0',
        'packfile_dump_dir': '',
        'packfile_dump_enable': '0',
        'packfile_auto_enable': '1',
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


class _WidgetsDict(TypedDict):
    """TODO: Remove."""
    refresh_counts: ttk.Button
    packfile_filefield: tk_tools.FileField
    nbook: ttk.Notebook

    thumb_auto: ttk.Radiobutton
    thumb_peti: ttk.Radiobutton
    thumb_custom: ttk.Radiobutton
    thumb_label: ttk.Label
    thumb_cleanup: ttk.Checkbutton

    light_none: ttk.Radiobutton
    light_fast: ttk.Radiobutton
    light_full: ttk.Radiobutton


def _read_player_model() -> utils.ObjectID:
    """Read the current player model from the config."""
    model_id = COMPILE_CFG.get_val('General', 'player_model_id', '')
    if model_id:
        try:
            return utils.obj_id(model_id, 'Player Model')
        except ValueError as exc:
            LOGGER.exception('Invalid player model ID:', exc_info=exc)
            return consts.DEFAULT_PLAYER
    legacy = COMPILE_CFG.get_val('General', 'player_model', 'PETI')
    try:
        return PLAYER_MODEL_LEGACY_IDS[legacy.upper()]
    except KeyError:
        LOGGER.warning('Unknown legacy player model "{}"', legacy)
        return consts.DEFAULT_PLAYER


COMPILE_CFG = BEE2_config.ConfigFile('compile.cfg')
COMPILE_CFG.set_defaults(COMPILE_DEFAULTS)
PANE: SubPane
window: tk.Toplevel | tk.Tk
UI: _WidgetsDict = cast(_WidgetsDict, {})

chosen_thumb = tk.StringVar(
    value=COMPILE_CFG.get_val('Screenshot', 'Type', 'AUTO')
)
tk_screenshot: ImageTk.PhotoImage | None = None  # The preview image shown

# Location we copy custom screenshots to
SCREENSHOT_LOC = str(utils.conf_location('screenshot.jpg'))

VOICE_PRIORITY_VAR = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'voiceline_priority', False))

player_model = trio_util.AsyncValue(_read_player_model())
del _read_player_model

start_in_elev = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'spawn_elev'))
cust_file_loc = COMPILE_CFG.get_val('Screenshot', 'Loc', '')
cust_file_loc_var = tk.StringVar(value='')

packfile_dump_enable = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'packfile_dump_enable'))
packfile_auto_enable = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'packfile_auto_enable', True))

# vrad_light_type = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'vrad_force_full'))
# Checks if vrad_force_full is defined, if it is, sets vrad_compile_type to true and
# removes vrad_force_full as it is no longer used.
if COMPILE_CFG.get_bool('General', 'vrad_force_full'):
    vrad_compile_type = tk.StringVar(
        value=COMPILE_CFG.get_val('General', 'vrad_compile_type', 'FULL')
    )
    COMPILE_CFG.remove_option('General', 'vrad_force_full')
else:
    vrad_compile_type = tk.StringVar(
        value=COMPILE_CFG.get_val('General', 'vrad_compile_type', 'FAST')
    )

cleanup_screenshot = tk.IntVar(value=COMPILE_CFG.get_bool('Screenshot', 'del_old', True))

TRANS_SCREENSHOT_FILETYPE = TransToken.ui('Image Files')   # note: File type description
TRANS_TAB_MAP = TransToken.ui('Map Settings')
TRANS_TAB_COMPILE = TransToken.ui('Compile Settings')

TRANS_SCREENSHOT_TOOLTIP = TransToken.ui(
    "Use a custom image for the map preview image. Click the "
    "screenshot to select.\n"
    "Images will be converted to JPEGs if necessary."
)
TRANS_SCREENSHOT_FILENAME = TransToken.ui('Filename: {path}')


async def apply_state_task() -> None:
    """Apply saved state to the UI and compile config."""
    def save_screenshot(data: bytes) -> None:
        with AtomicWriter(SCREENSHOT_LOC, is_bytes=True) as f:
            f.write(data)

    state: CompilePaneState
    with config.APP.get_ui_channel(CompilePaneState) as channel:
        async for state in channel:
            chosen_thumb.set(state.sshot_type)
            cleanup_screenshot.set(state.sshot_cleanup)

            if state.sshot_type == 'CUST' and state.sshot_cust:
                await trio.to_thread.run_sync(save_screenshot, state.sshot_cust)
            # Refresh these.
            await set_screen_type()
            set_screenshot()

            start_in_elev.set(state.spawn_elev)
            player_model.value = state.player_mdl
            COMPILE_CFG['General']['spawn_elev'] = bool_as_int(state.spawn_elev)
            COMPILE_CFG['General']['player_model_id'] = state.player_mdl
            COMPILE_CFG['General']['voiceline_priority'] = bool_as_int(state.use_voice_priority)

            COMPILE_CFG.save_check()


class LimitCounter:
    """Displays the current status of various compiler limits."""

    # i18n: Tooltip format for compiler limit bars.
    TOOLTIP = TransToken.ui('{count}/{max} ({frac:0.##%}):\n{blurb}')

    def __init__(
        self,
        master: ttk.LabelFrame,
        *,
        maximum: int,
        length: int,
        blurb: TransToken,
        name: str,
    ) -> None:
        self._flasher: trio.CancelScope | None = None
        self.var = tk.IntVar()
        self.max = maximum
        self.name = name
        self.blurb = blurb
        self.cur_count = 0

        self.bar = ttk.Progressbar(
            master,
            maximum=100,
            variable=self.var,
            length=length,
        )
        # Add tooltip logic.
        add_tooltip(self.bar)

    def update(self, value: int) -> None:
        """Apply the value to the counter."""
        # If it's hit the limit, make it continuously scroll to draw
        # attention to the bar.
        if value >= self.max:
            if self._flasher is None:
                app.background_run(self._flash)
        else:
            if self._flasher is not None:
                self._flasher.cancel()
            self._flasher = None
            self.cur_count = round(100 * value / self.max)
            self.var.set(self.cur_count)

        set_tooltip(self.bar, self.TOOLTIP.format(
            count=value,
            max=self.max,
            frac=value / self.max,
            blurb=self.blurb,
        ))

    async def _flash(self) -> None:
        """Flash the display."""
        if self._flasher is not None:
            self._flasher.cancel()
        with trio.CancelScope() as self._flasher:
            while True:
                self.var.set(100)
                await trio.sleep(random.uniform(0.5, 0.75))
                self.var.set(0)
                await trio.sleep(random.uniform(0.5, 0.75))
        # noinspection PyUnreachableCode
        self.var.set(self.cur_count)


def refresh_counts(*counters: LimitCounter) -> None:
    """Set the last-compile limit display."""
    COMPILE_CFG.load()
    for limit_counter in counters:
        value = COMPILE_CFG.get_int('Counts', limit_counter.name)

        # The in-engine entity limit is different to VBSP's limit
        # (that one might include prop_static, lights etc).
        max_value = COMPILE_CFG.get_int('Counts', 'max_' + limit_counter.name)
        if limit_counter.name != 'entity' and max_value != 0:
            limit_counter.max = max_value

        limit_counter.update(value)


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


def find_screenshot(e: tk.Event[ttk.Label] | None = None) -> None:
    """Prompt to browse for a screenshot."""
    file_name = filedialog.askopenfilename(
        title='Find Screenshot',
        filetypes=[
            (
                str(TRANS_SCREENSHOT_FILETYPE),
                '*.jpg *.jpeg *.jpe *.jfif *.png *.bmp *.tiff *.tga *.ico *.psd'
            ),
        ],
    )
    if file_name:
        image = Image.open(file_name).convert('RGB')  # Remove alpha channel if present.
        buf = io.BytesIO()
        image.save(buf, format='jpeg', quality=95, subsampling=0)
        with AtomicWriter(SCREENSHOT_LOC, is_bytes=True) as f:
            f.write(buf.getvalue())

        COMPILE_CFG['Screenshot']['LOC'] = SCREENSHOT_LOC
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState),
            sshot_cust=buf.getvalue(),
            sshot_cust_fname=file_name,
        ))
        set_screenshot(image)
        COMPILE_CFG.save_check()


async def set_screen_type() -> None:
    """Set the type of screenshot used."""
    chosen = chosen_thumb.get()
    COMPILE_CFG['Screenshot']['type'] = chosen
    if chosen == 'CUST':
        UI['thumb_label'].grid(row=2, column=0, columnspan=2, sticky='EW')
    else:
        UI['thumb_label'].grid_forget()
    await tk_tools.wait_eventloop()
    # Resize the pane to accommodate the shown/hidden image
    window.geometry(f'{window.winfo_width()}x{window.winfo_reqheight()}')
    config.APP.store_conf(attrs.evolve(
        config.APP.get_cur_conf(CompilePaneState),
        sshot_type=chosen,
    ))
    COMPILE_CFG.save_check()


def set_screenshot(image: Image.Image | None = None) -> None:
    """Show the screenshot on the UI."""
    # Make the visible screenshot small
    global tk_screenshot
    if image is None:
        try:
            image = Image.open(SCREENSHOT_LOC)
        except OSError:  # Image doesn't exist!
            # In that case, use a black image
            image = Image.new('RGB', (1, 1), color=(0, 0, 0))
    # Make a smaller image for showing in the UI...
    tk_img = image.resize(
        (
            int(PETI_WIDTH // 3.5),
            int(PETI_HEIGHT // 3.5),
        ),
        Image.LANCZOS
    )
    tk_screenshot = ImageTk.PhotoImage(tk_img)
    UI['thumb_label']['image'] = tk_screenshot
    conf = config.APP.get_cur_conf(CompilePaneState)
    if conf.sshot_cust_fname:
        set_tooltip(UI['thumb_label'], TransToken.untranslated('{a}\n{b}').format(
            a=TRANS_SCREENSHOT_TOOLTIP,
            b=TRANS_SCREENSHOT_FILENAME.format(path=conf.sshot_cust_fname)
        ))
    else:
        set_tooltip(UI['thumb_label'], TRANS_SCREENSHOT_TOOLTIP)


def make_setter(section: str, config: str, variable: tk.IntVar | tk. StringVar) -> None:
    """Create a callback which sets the given config from a variable."""
    def callback(var_name: str, var_ind: str, cback_name: str) -> None:
        """Automatically called when the variable is written to."""
        COMPILE_CFG[section][config] = str(variable.get())
        COMPILE_CFG.save_check()

    variable.trace_add('write', callback)


async def make_widgets(
    tk_img: TKImages,
    *,
    task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create the compiler options pane.

    """
    make_setter('Screenshot', 'del_old', cleanup_screenshot)
    make_setter('General', 'vrad_compile_type', vrad_compile_type)

    reload_lbl = ttk.Label(window, justify='center')
    wid_transtoken.set_text(reload_lbl, TransToken.ui(
        "Options on this panel can be changed \n"
        "without exporting or restarting the game."
    ))
    reload_lbl.grid(row=0, column=0, sticky='ew', padx=2, pady=2)

    UI['nbook'] = nbook = ttk.Notebook(window)

    nbook.grid(row=1, column=0, sticky='nsew')
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)

    nbook.enable_traversal()

    map_frame = ttk.Frame(nbook, name='map_settings')
    nbook.add(map_frame, text='Map')

    comp_frame = ttk.Frame(nbook, name='comp_settings')
    nbook.add(comp_frame, text='Comp')

    def update_label(e: tk.Event[tk.Misc]) -> None:
        """Force the top label to wrap."""
        reload_lbl['wraplength'] = window.winfo_width() - 10

    async with trio.open_nursery() as nursery:
        async with trio.open_nursery() as start_nursery:
            start_nursery.start_soon(nursery.start, make_map_widgets, map_frame)
            start_nursery.start_soon(nursery.start, make_comp_widgets, comp_frame, tk_img)

        window.bind('<Configure>', update_label, add='+')
        task_status.started()
        while True:
            # Update tab names whenever languages update.
            nbook.tab(0, text=str(TRANS_TAB_MAP))
            nbook.tab(1, text=str(TRANS_TAB_COMPILE))
            await CURRENT_LANG.wait_transition()


async def make_comp_widgets(
    frame: ttk.Frame, tk_img: TKImages,
    *,
    task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create widgets for the compiler settings pane.

    These are generally things that are aesthetic, and to do with the file and
    compilation process.
    """
    await trio.lowlevel.checkpoint()
    make_setter("General", "packfile_auto_enable", packfile_auto_enable)
    frame.columnconfigure(0, weight=1)

    thumb_frame = ttk.LabelFrame(frame, labelanchor=tk.N)
    wid_transtoken.set_text(thumb_frame, TransToken.ui('Thumbnail'))
    thumb_frame.grid(row=0, column=0, sticky=tk.EW)
    thumb_frame.columnconfigure(0, weight=1)

    screen_event = trio.Event()

    def set_screen() -> None:
        """Event handler when radio buttons are clicked."""
        screen_event.set()

    UI['thumb_auto'] = wid_transtoken.set_text(ttk.Radiobutton(
        thumb_frame,
        value='AUTO',
        variable=chosen_thumb,
        command=set_screen,
    ), TransToken.ui('Screenshot'))

    UI['thumb_peti'] = wid_transtoken.set_text(ttk.Radiobutton(
        thumb_frame,
        value='PETI',
        variable=chosen_thumb,
        command=set_screen,
    ), TransToken.ui('Editor View'))

    UI['thumb_custom'] = wid_transtoken.set_text(ttk.Radiobutton(
        thumb_frame,
        value='CUST',
        variable=chosen_thumb,
        command=set_screen,
    ), TransToken.ui('Custom:'))
    await trio.lowlevel.checkpoint()

    UI['thumb_label'] = ttk.Label(
        thumb_frame,
        anchor=tk.CENTER,
        cursor=tk_tools.Cursors.LINK,
    )
    UI['thumb_label'].bind(tk_tools.EVENTS['LEFT'], find_screenshot)

    UI['thumb_cleanup'] = wid_transtoken.set_text(
        ttk.Checkbutton(thumb_frame, variable=cleanup_screenshot),
        TransToken.ui('Cleanup old screenshots'),
    )

    await trio.lowlevel.checkpoint()
    UI['thumb_auto'].grid(row=0, column=0, sticky='W')
    UI['thumb_peti'].grid(row=0, column=1, sticky='W')
    UI['thumb_custom'].grid(row=1, column=0, columnspan=2, sticky='NEW')
    UI['thumb_cleanup'].grid(row=3, columnspan=2, sticky='W')
    add_tooltip(UI['thumb_auto'], TransToken.ui(
        "Override the map image to use a screenshot automatically taken from "
        "the beginning of a chamber. Press F5 to take a new screenshot. If the "
        "map has not been previewed recently (within the last few hours), the "
        "default PeTI screenshot will be used instead."
    ))
    add_tooltip(UI['thumb_peti'], TransToken.ui("Use the normal editor view for the map preview image."))
    add_tooltip(UI['thumb_custom'], TRANS_SCREENSHOT_TOOLTIP)
    add_tooltip(UI['thumb_label'], TRANS_SCREENSHOT_TOOLTIP)

    add_tooltip(UI['thumb_cleanup'], TransToken.ui(
        'Automatically delete unused Automatic screenshots. Disable if you want '
        'to keep things in "portal2/screenshots". '
    ))
    await trio.lowlevel.checkpoint()

    if chosen_thumb.get() == 'CUST':
        # Show this if the user has set it before
        UI['thumb_label'].grid(row=2, column=0, columnspan=2, sticky='ew')
    set_screenshot()  # Load the last saved screenshot

    vrad_frame = ttk.LabelFrame(frame, labelanchor='n')
    wid_transtoken.set_text(vrad_frame, TransToken.ui('Lighting:'))
    vrad_frame.grid(row=1, column=0, sticky='ew')

    await trio.lowlevel.checkpoint()
    UI['light_none'] = wid_transtoken.set_text(ttk.Radiobutton(
        vrad_frame,
        value='NONE',
        variable=vrad_compile_type,
    ), TransToken.ui('None'))
    UI['light_none'].grid(row=0, column=0)
    UI['light_fast'] = wid_transtoken.set_text(ttk.Radiobutton(
        vrad_frame,
        value='FAST',
        variable=vrad_compile_type,
    ), TransToken.ui('Fast'))
    UI['light_fast'].grid(row=0, column=1)
    UI['light_full'] = wid_transtoken.set_text(ttk.Radiobutton(
        vrad_frame,
        value='FULL',
        variable=vrad_compile_type,
    ), TransToken.ui('Full'))
    UI['light_full'].grid(row=0, column=2)

    await trio.lowlevel.checkpoint()

    light_conf_swap = TransToken.ui(  # i18n: Info for toggling lighting via a key.
        "{desc}\n\n"
        "You can hold down Shift during the start of the Lighting stage to "
        "switch to {keymode} lighting on the fly."
    )

    add_tooltip(UI['light_none'], light_conf_swap.format(
        desc=TransToken.ui(
            "Compile with no lighting whatsoever. This significantly speeds up "
            "compile times, but there will be no lights, gel will be invisible, "
            "and the map will run in fullbright. \nWhen publishing, this is ignored."
        ), keymode=TransToken.ui("Fast"),
    ))
    add_tooltip(UI['light_fast'], light_conf_swap.format(
        desc=TransToken.ui(
            "Compile with lower-quality, fast lighting. This speeds up compile "
            "times, but does not appear as good. Some shadows may appear "
            "wrong.\nWhen publishing, this is ignored."
        ), keymode=TransToken.ui("Full"),
    ))
    add_tooltip(UI['light_full'], light_conf_swap.format(
        desc=TransToken.ui(
            "Compile with high-quality lighting. This looks correct, but takes "
            "longer to compute. Use if you're arranging lights.\nWhen "
            "publishing, this is always used."
        ), keymode=TransToken.ui("Fast"),
    ))
    await trio.lowlevel.checkpoint()

    packfile_enable = wid_transtoken.set_text(ttk.Checkbutton(
        frame,
        variable=packfile_auto_enable,
    ), TransToken.ui('Enable packing'))
    packfile_enable.grid(row=2, column=0, sticky='ew')
    add_tooltip(packfile_enable, TransToken.ui(
        "Disable automatically packing resources in the map. This can speed up building and allows "
        "editing files and running reload commands, but can cause some resources to not work "
        "correctly. Regardless of this setting, packing is enabled when publishing. "
    ))

    packfile_dump_enable_chk = wid_transtoken.set_text(ttk.Checkbutton(
        frame,
        variable=packfile_dump_enable,
        command=set_pack_dump_enabled,
    ), TransToken.ui('Dump packed files to:'))

    packfile_frame = ttk.LabelFrame(frame, labelwidget=packfile_dump_enable_chk)
    packfile_frame.grid(row=3, column=0, sticky='ew')

    UI['packfile_filefield'] = packfile_filefield = tk_tools.FileField(
        packfile_frame,
        is_dir=True,
        loc=COMPILE_CFG.get_val('General', 'packfile_dump_dir', ''),
        callback=set_pack_dump_dir,
    )
    packfile_filefield.grid(row=0, column=0, sticky='ew')
    packfile_frame.columnconfigure(0, weight=1)
    ttk.Frame(packfile_frame).grid(row=1)
    await trio.lowlevel.checkpoint()

    set_pack_dump_enabled()

    add_tooltip(packfile_dump_enable_chk, TransToken.ui(
        "When compiling, dump all files which were packed into the map. "
        "Useful if you're intending to edit maps in Hammer."
    ))

    count_frame = ttk.LabelFrame(frame, labelanchor='n')
    wid_transtoken.set_text(count_frame, TransToken.ui('Last Compile:'))

    count_frame.grid(row=7, column=0, sticky='ew')
    count_frame.columnconfigure(0, weight=1)
    count_frame.columnconfigure(2, weight=1)

    wid_transtoken.set_text(
        ttk.Label(count_frame, anchor='n'),
        TransToken.ui('Entity'),
    ).grid(row=0, column=0, columnspan=3, sticky='ew')
    await trio.lowlevel.checkpoint()

    count_entity = LimitCounter(
        count_frame,
        maximum=2048,
        length=120,
        name='entity',
        # i18n: Progress bar description
        blurb=TransToken.ui(
            "Entities are the things in the map that have functionality. "
            "Removing complex moving items will help reduce this. Items have "
            "their entity count listed in the item description window.\n\nThis "
            "isn't completely accurate, some entity types are counted here but "
            "don't affect the ingame limit, while others may generate "
            "additional entities at runtime."
        )
    )
    count_entity.bar.grid(
        row=1,
        column=0,
        columnspan=3,
        sticky='ew',
        padx=5,
    )

    await trio.lowlevel.checkpoint()
    wid_transtoken.set_text(
        ttk.Label(count_frame, anchor='center'),
        TransToken.ui('Overlay'),
    ).grid(row=2, column=0, sticky='ew')
    count_overlay = LimitCounter(
        count_frame,
        maximum=512,
        length=50,
        name='overlay',
        # i18n: Progress bar description
        blurb=TransToken.ui(
            "Overlays are smaller images affixed to surfaces, like signs or "
            "indicator lights. Hiding complex antlines or setting them to "
            "signage will reduce this."
        )
    )
    count_overlay.bar.grid(row=3, column=0, sticky='ew', padx=5)

    await trio.lowlevel.checkpoint()
    UI['refresh_counts'] = make_tool_button(
        count_frame, tk_img,
        'icons/tool_sub',
        lambda: refresh_counts(count_brush, count_entity, count_overlay),
    )
    UI['refresh_counts'].grid(row=3, column=1)
    add_tooltip(UI['refresh_counts'], TransToken.ui(
        "Refresh the compile progress bars. Press after a compile has been "
        "performed to show the new values."
    ))

    wid_transtoken.set_text(
        ttk.Label(count_frame, anchor='center'),
        TransToken.ui('Brush'),
    ).grid(row=2, column=2, sticky=tk.EW)
    count_brush = LimitCounter(
        count_frame,
        maximum=8192,
        length=50,
        name='brush',
        blurb=TransToken.ui(
            "Brushes form the walls or other parts of the test chamber. If this "
            "is high, it may help to reduce the size of the map or remove "
            "intricate shapes."
        )
    )
    count_brush.bar.grid(row=3, column=2, sticky='ew', padx=5)

    await trio.lowlevel.checkpoint()
    refresh_counts(count_brush, count_entity, count_overlay)
    task_status.started()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(packfile_filefield.task)
        while True:
            await screen_event.wait()
            screen_event = trio.Event()
            await set_screen_type()


async def make_map_widgets(
    frame: ttk.Frame,
    *,
    task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create widgets for the map settings pane.

    These are things which mainly affect the geometry or gameplay of the map.
    """
    frame.columnconfigure(0, weight=1)

    voice_frame = ttk.LabelFrame(frame, labelanchor='nw')
    wid_transtoken.set_text(voice_frame, TransToken.ui('Voicelines:'))
    voice_frame.grid(row=1, column=0, sticky='ew')

    def set_voice_priority() -> None:
        """Called when the voiceline priority is changed."""
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState),
            use_voice_priority=VOICE_PRIORITY_VAR.get() != 0,
        ))
        COMPILE_CFG['General']['voiceline_priority'] = str(VOICE_PRIORITY_VAR.get())
        COMPILE_CFG.save_check()

    voice_priority = ttk.Checkbutton(
        voice_frame,
        variable=VOICE_PRIORITY_VAR,
        command=set_voice_priority,
    )
    wid_transtoken.set_text(voice_priority, TransToken.ui("Use voiceline priorities"))
    voice_priority.grid(row=0, column=0)
    add_tooltip(voice_priority, TransToken.ui(
        "Only choose the highest-priority voicelines. This means more generic "
        "lines will only be chosen if few test elements are in the map. "
        "If disabled a random applicable lines will be used."
    ))

    elev_frame = ttk.LabelFrame(frame, labelanchor='n')
    wid_transtoken.set_text(elev_frame, TransToken.ui('Spawn at:'))
    elev_frame.grid(row=2, column=0, sticky='ew')
    elev_frame.columnconfigure(0, weight=1)
    elev_frame.columnconfigure(1, weight=1)

    def elev_changed(state: bool) -> None:
        """Called when an elevator is selected."""
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState),
            spawn_elev=state,
        ))
        COMPILE_CFG['General']['spawn_elev'] = bool_as_int(state)
        COMPILE_CFG.save_check()

    elev_preview = ttk.Radiobutton(
        elev_frame,
        value=0,
        variable=start_in_elev,
        command=functools.partial(elev_changed, False),
    )
    elev_elevator = ttk.Radiobutton(
        elev_frame,
        value=1,
        variable=start_in_elev,
        command=functools.partial(elev_changed, True),
    )

    wid_transtoken.set_text(elev_preview, TransToken.ui('Entry Door'))
    wid_transtoken.set_text(elev_elevator, TransToken.ui('Elevator'))
    elev_preview.grid(row=0, column=0, sticky='w')
    elev_elevator.grid(row=0, column=1, sticky='w')

    add_tooltip(elev_elevator, TransToken.ui(
        "When previewing in SP, spawn inside the entry elevator. Use this to "
        "examine the entry and exit corridors.\n\n"
        "You can hold down Shift during the start of the Geometry stage to quickly swap which "
        "location you spawn at on the fly."
    ))
    add_tooltip(elev_preview, TransToken.ui(
        "When previewing in SP, spawn just before the entry door.\n\n"
        "You can hold down Shift during the start of the Geometry stage to quickly swap which "
        "location you spawn at on the fly."
    ))

    model_frame = ttk.LabelFrame(frame, labelanchor='n')
    wid_transtoken.set_text(model_frame, TransToken.ui('Player Model (SP):'))
    model_frame.grid(row=4, column=0, sticky='ew')

    # Load an initial set of models from saved config. If standalone this is all we'll ever have.
    initial_models = config.APP.get_cur_conf_type(AvailablePlayer)

    models = []
    for conf_id, model in initial_models:
        try:
            model_id =  utils.obj_id(conf_id, 'Player Model')
        except ValueError as exc:
            LOGGER.exception('Invalid player model ID:', exc_info=exc)
        else:
            # The name here was translated from the last save.
            models.append((model_id, TransToken.untranslated(model.name)))
    if not models:
        # No conf, hardcode just the PeTI model. This should be immediately replaced and
        # then will never happen again, so don't bother translating.
        models.append((consts.DEFAULT_PLAYER, TransToken.untranslated('Bendy')))

    player_mdl_combo = tk_tools.ComboBoxMap(
        model_frame,
        name='model_combo',
        current=player_model,
        values=models,
    )
    player_mdl_combo.widget['width'] = 20
    player_mdl_combo.grid(row=0, column=0, sticky=tk.EW)

    async def save_player_task() -> None:
        """Save changes whenever they occur."""
        async with aclosing(player_model.eventual_values()) as agen:
            async for model in agen:
                config.APP.store_conf(attrs.evolve(
                    config.APP.get_cur_conf(CompilePaneState),
                    player_mdl=model,
                ))
                COMPILE_CFG['General']['player_model_id'] = model
                COMPILE_CFG.save()

    model_frame.columnconfigure(0, weight=1)
    task_status.started()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(player_mdl_combo.task)
        nursery.start_soon(save_player_task)
        nursery.start_soon(load_player_task, player_mdl_combo)


async def load_player_task(model_combo: ComboBoxMap[utils.ObjectID]) -> None:
    """Load player model definitions from packages."""
    while True:
        async with async_util.iterval_cancelling(packages.LOADED) as packset:
            # If standalone, this will stall forever since packages never load.
            await packset.ready(packages.PlayerModel).wait()
            model_combo.update(
                (model.id, model.name)
                for model in sorted(
                    packset.all_obj(packages.PlayerModel),
                    key=lambda model: str(model.name),
               )
            )
            LOGGER.debug('Updated player model list.')
            while True:
                # Store the translated versions, discard extras, then wait for translation change.
                to_discard = set(dict(config.APP.get_cur_conf_type(AvailablePlayer)))
                for mdl in packset.all_obj(packages.PlayerModel):
                    config.APP.store_conf(AvailablePlayer(str(mdl.name)), mdl.id)
                    to_discard.discard(mdl.id)
                for mdl_id in to_discard:
                    config.APP.discard_conf(AvailablePlayer, mdl_id)
                await CURRENT_LANG.wait_transition()


async def make_pane(
    tool_frame: tk.Frame | ttk.Frame,
    tk_img: TKImages,
    menu_bar: tk.Menu,
    *,
    task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Initialise when part of the BEE2."""
    global PANE, window
    PANE = SubPane(
        TK_ROOT, tk_img, PANE_CONF,
        menu_bar=menu_bar,
        tool_frame=tool_frame,
    )
    window = PANE.win
    window.columnconfigure(0, weight=1)
    window.rowconfigure(0, weight=1)
    async with trio.open_nursery() as nursery:
        await nursery.start(make_widgets, tk_img)
        nursery.start_soon(apply_state_task)
        task_status.started()


async def init_application(nursery: trio.Nursery) -> None:
    """Initialise when standalone."""
    global window
    from ui_tk.img import TK_IMG
    from app import _APP_QUIT_SCOPE
    window = TK_ROOT
    wid_transtoken.set_win_title(window, TransToken.ui(
        'Compiler Options - {ver}',
    ).format(ver=utils.BEE_VERSION))
    window.resizable(True, False)

    with _APP_QUIT_SCOPE:
        await nursery.start(make_widgets, TK_IMG)

        TK_ROOT.deiconify()
        tk_tools.center_onscreen(TK_ROOT)
        await trio.sleep_forever()
