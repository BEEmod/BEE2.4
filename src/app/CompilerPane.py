"""Implement the pane configuring compiler features.

These can be set and take effect immediately, without needing to export.
"""
from __future__ import annotations

from typing import Union
from tkinter import filedialog, ttk
import tkinter as tk
import base64
import functools
import io
import random

from PIL import Image, ImageTk
from atomicwrites import atomic_write
import attrs
import trio

from srctools import Property, bool_as_int
from srctools.logger import get_logger
from srctools.dmx import Element

import app
from app import SubPane, tk_tools, TK_ROOT, corridor_selector
import config
from app.tooltip import add_tooltip, set_tooltip
from localisation import gettext
import BEE2_config
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

PLAYER_MODELS = {
    'ATLAS': gettext('ATLAS'),
    'PBODY': gettext('P-Body'),
    'SP': gettext('Chell'),
    'PETI': gettext('Bendy'),
}
PLAYER_MODEL_ORDER = ['PETI', 'SP', 'ATLAS', 'PBODY']
PLAYER_MODELS_REV = {value: key for key, value in PLAYER_MODELS.items()}

COMPILE_CFG = BEE2_config.ConfigFile('compile.cfg')
COMPILE_CFG.set_defaults(COMPILE_DEFAULTS)
window: Union[SubPane.SubPane, tk.Tk, None] = None
UI: dict[str, tk.Widget] = {}

chosen_thumb = tk.StringVar(
    value=COMPILE_CFG.get_val('Screenshot', 'Type', 'AUTO')
)
tk_screenshot = None  # The preview image shown

# Location we copy custom screenshots to
SCREENSHOT_LOC = str(utils.conf_location('screenshot.jpg'))

VOICE_PRIORITY_VAR = tk.IntVar(value=COMPILE_CFG.get_bool('General', 'voiceline_priority', False))

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


@config.APP.register
@attrs.frozen(slots=False)
class CompilePaneState(config.Data, conf_name='CompilerPane'):
    """State saved in palettes.

    Note: We specifically do not save/load the following:
        - packfile dumping
        - compile counts
    This is because these are more system-dependent than map dependent.
    """
    sshot_type: str = 'AUTO'
    sshot_cleanup: bool = False
    sshot_cust: bytes = attrs.field(repr=False, default=b'')
    spawn_elev: bool = False
    player_mdl: str = 'PETI'
    use_voice_priority: bool = False

    @classmethod
    def parse_legacy(cls, conf: Property) -> dict[str, CompilePaneState]:
        """Parse legacy config data."""
        # No change from new KV1 format.
        return {'': cls.parse_kv1(
            conf.find_key('CompilerPane', or_blank=True),
            1,
        )}

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> CompilePaneState:
        """Parse Keyvalues1 format data."""
        if 'sshot_data' in data:
            screenshot_parts = b'\n'.join([
                prop.value.encode('ascii')
                for prop in
                data.find_children('sshot_data')
            ])
            screenshot_data = base64.decodebytes(screenshot_parts)
        else:
            screenshot_data = b''

        sshot_type = data['sshot_type', 'AUTO'].upper()
        if sshot_type not in ['AUTO', 'CUST', 'PETI']:
            LOGGER.warning('Unknown screenshot type "{}"!', sshot_type)
            sshot_type = 'AUTO'

        player_mdl = data['player_model', 'PETI'].upper()
        if player_mdl not in PLAYER_MODEL_ORDER:
            LOGGER.warning('Unknown player model "{}"!', player_mdl)
            player_mdl = 'PETI'

        return CompilePaneState(
            sshot_type=sshot_type,
            sshot_cleanup=data.bool('sshot_cleanup', False),
            sshot_cust=screenshot_data,
            spawn_elev=data.bool('spawn_elev', False),
            player_mdl=player_mdl,
            use_voice_priority=data.bool('voiceline_priority', False),
        )

    def export_kv1(self) -> Property:
        """Generate keyvalues1 format data."""
        props = Property('', [
            Property('sshot_type', self.sshot_type),
            Property('sshot_cleanup', bool_as_int(self.sshot_cleanup)),
            Property('spawn_elev', bool_as_int(self.spawn_elev)),
            Property('player_model', self.player_mdl),
            Property('voiceline_priority', bool_as_int(self.use_voice_priority)),
        ])

        # Embed the screenshot in so we can load it later.
        if self.sshot_type == 'CUST':
            # encodebytes() splits it into multiple lines, which we write
            # in individual blocks to prevent having a massively long line
            # in the file.
            props.append(Property(
                'sshot_data',
                [
                    Property('b64', data) for data in
                    base64.encodebytes(self.sshot_cust).decode('ascii').splitlines()
                ]
            ))
        return props

    def export_dmx(self) -> Element:
        """Generate DMX format data."""
        elem = Element('CompilerPaneState', 'DMElement')
        elem['sshot_type'] = self.sshot_type
        elem['sshot_cleanup'] = self.sshot_cleanup
        elem['spawn_elev'] = self.spawn_elev
        elem['player_model'] = self.player_mdl
        elem['voiceline_priority'] = self.use_voice_priority
        if self.sshot_type == 'CUST':
            elem['sshot_data'] = self.sshot_cust
        return elem


DEFAULT_STATE = CompilePaneState()


async def apply_state(state: CompilePaneState) -> None:
    """Apply saved state to the UI and compile config."""
    chosen_thumb.set(state.sshot_type)
    cleanup_screenshot.set(state.sshot_cleanup)

    if state.sshot_type == 'CUST' and state.sshot_cust:
        with atomic_write(SCREENSHOT_LOC, mode='wb', overwrite=True) as f:
            f.write(state.sshot_cust)

    # Refresh these.
    await set_screen_type()
    set_screenshot()

    start_in_elev.set(state.spawn_elev)
    player_model_var.set(PLAYER_MODELS[state.player_mdl])
    VOICE_PRIORITY_VAR.set(state.use_voice_priority)

    COMPILE_CFG['General']['spawn_elev'] = bool_as_int(state.spawn_elev)
    COMPILE_CFG['General']['player_model'] = state.player_mdl
    COMPILE_CFG['General']['voiceline_priority'] = bool_as_int(state.use_voice_priority)

    COMPILE_CFG.save_check()


class LimitCounter:
    """Displays the current status of various compiler limits."""
    def __init__(
        self,
        master: ttk.LabelFrame,
        *,
        maximum: int,
        length: int,
        blurb: str,
        name: str,
    ) -> None:
        self._flasher: Union[trio.CancelScope, None] = None
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

        set_tooltip(self.bar, '{}/{} ({:.2%}):\n{}'.format(
            value,
            self.max,
            value / self.max,
            self.blurb,
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


def find_screenshot(e=None) -> None:
    """Prompt to browse for a screenshot."""
    file_name = filedialog.askopenfilename(
        title='Find Screenshot',
        filetypes=[
            # note: File type description
            (gettext('Image Files'), '*.jpg *.jpeg *.jpe *.jfif *.png *.bmp'
                                     '*.tiff *.tga *.ico *.psd'),
        ],
        initialdir='C:',
    )
    if file_name:
        image = Image.open(file_name).convert('RGB')  # Remove alpha channel if present.
        buf = io.BytesIO()
        image.save(buf, 'png')
        with atomic_write(SCREENSHOT_LOC, mode='wb', overwrite=True) as f:
            f.write(buf.getvalue())

        COMPILE_CFG['Screenshot']['LOC'] = SCREENSHOT_LOC
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState, default=DEFAULT_STATE),
            sshot_cust=buf.getvalue(),
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
        config.APP.get_cur_conf(CompilePaneState, default=DEFAULT_STATE),
        sshot_type=chosen,
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


async def make_widgets(corr: corridor_selector.Selector) -> None:
    """Create the compiler options pane.

    """
    make_setter('Screenshot', 'del_old', cleanup_screenshot)
    make_setter('General', 'vrad_compile_type', vrad_compile_type)

    ttk.Label(window, justify='center', text=gettext(
        "Options on this panel can be changed \n"
        "without exporting or restarting the game."
    )).grid(row=0, column=0, sticky='ew', padx=2, pady=2)

    UI['nbook'] = nbook = ttk.Notebook(window)

    nbook.grid(row=1, column=0, sticky='nsew')
    window.columnconfigure(0, weight=1)
    window.rowconfigure(1, weight=1)

    nbook.enable_traversal()

    map_frame = ttk.Frame(nbook, name='map_settings')
    # note: Tab name
    nbook.add(map_frame, text=gettext('Map Settings'))

    comp_frame = ttk.Frame(nbook, name='comp_settings')
    # note: Tab name
    nbook.add(comp_frame, text=gettext('Compile Settings'))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(make_map_widgets, map_frame, corr)
        nursery.start_soon(make_comp_widgets, comp_frame)


async def make_comp_widgets(frame: ttk.Frame) -> None:
    """Create widgets for the compiler settings pane.

    These are generally things that are aesthetic, and to do with the file and
    compilation process.
    """
    make_setter("General", "packfile_auto_enable", packfile_auto_enable)
    frame.columnconfigure(0, weight=1)

    thumb_frame = ttk.LabelFrame(
        frame,
        text=gettext('Thumbnail'),
        labelanchor=tk.N,
    )
    thumb_frame.grid(row=0, column=0, sticky=tk.EW)
    thumb_frame.columnconfigure(0, weight=1)

    def set_screen() -> None:
        """Event handler when radio buttons are clicked."""
        app.background_run(set_screen_type)

    UI['thumb_auto'] = ttk.Radiobutton(
        thumb_frame,
        text=gettext('Auto'),
        value='AUTO',
        variable=chosen_thumb,
        command=set_screen,
    )

    UI['thumb_peti'] = ttk.Radiobutton(
        thumb_frame,
        text=gettext('PeTI'),
        value='PETI',
        variable=chosen_thumb,
        command=set_screen,
    )

    UI['thumb_custom'] = ttk.Radiobutton(
        thumb_frame,
        text=gettext('Custom:'),
        value='CUST',
        variable=chosen_thumb,
        command=set_screen,
    )

    UI['thumb_label'] = ttk.Label(
        thumb_frame,
        anchor=tk.CENTER,
        cursor=tk_tools.Cursors.LINK,
    )
    UI['thumb_label'].bind(tk_tools.EVENTS['LEFT'], find_screenshot)

    UI['thumb_cleanup'] = ttk.Checkbutton(
        thumb_frame,
        text=gettext('Cleanup old screenshots'),
        variable=cleanup_screenshot,
    )

    UI['thumb_auto'].grid(row=0, column=0, sticky='W')
    UI['thumb_peti'].grid(row=0, column=1, sticky='W')
    UI['thumb_custom'].grid(row=1, column=0, columnspan=2, sticky='NEW')
    UI['thumb_cleanup'].grid(row=3, columnspan=2, sticky='W')
    add_tooltip(UI['thumb_auto'], gettext(
        "Override the map image to use a screenshot automatically taken from "
        "the beginning of a chamber. Press F5 to take a new screenshot. If the "
        "map has not been previewed recently (within the last few hours), the "
        "default PeTI screenshot will be used instead."
    ))
    add_tooltip(
        UI['thumb_peti'],
        gettext("Use the normal editor view for the map preview image.")
    )
    custom_tooltip = gettext(
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

    add_tooltip(UI['thumb_cleanup'], gettext(
        'Automatically delete unused Automatic screenshots. Disable if you want '
        'to keep things in "portal2/screenshots". '
    ))

    if chosen_thumb.get() == 'CUST':
        # Show this if the user has set it before
        UI['thumb_label'].grid(row=2, column=0, columnspan=2, sticky='ew')
    set_screenshot()  # Load the last saved screenshot

    vrad_frame = ttk.LabelFrame(
        frame,
        text=gettext('Lighting:'),
        labelanchor='n',
    )
    vrad_frame.grid(row=1, column=0, sticky='ew')

    UI['light_none'] = ttk.Radiobutton(
        vrad_frame,
        text=gettext('None'),
        value='NONE',
        variable=vrad_compile_type,
    )
    UI['light_none'].grid(row=0, column=0)
    UI['light_fast'] = ttk.Radiobutton(
        vrad_frame,
        text=gettext('Fast'),
        value='FAST',
        variable=vrad_compile_type,
    )
    UI['light_fast'].grid(row=0, column=1)
    UI['light_full'] = ttk.Radiobutton(
        vrad_frame,
        text=gettext('Full'),
        value='FULL',
        variable=vrad_compile_type,
    )
    UI['light_full'].grid(row=0, column=2)

    light_conf_swap =  gettext(  # gettext: Info for toggling lighting via a key.
        "You can hold down Shift during the start of the Lighting stage to "
        "switch to {} lighting on the fly."
    )

    add_tooltip(UI['light_none'], gettext(
        "Compile with no lighting whatsoever. This significantly speeds up "
        "compile times, but there will be no lights, gel will be invisible, "
        "and the map will run in fullbright. \nWhen publishing, this is ignored."
    ) + "\n\n" + light_conf_swap.format(gettext("Fast")))

    add_tooltip(UI['light_fast'], gettext(
        "Compile with lower-quality, fast lighting. This speeds up compile "
        "times, but does not appear as good. Some shadows may appear "
        "wrong.\nWhen publishing, this is ignored."
    ) + "\n\n" + light_conf_swap.format(gettext("Full")))
    add_tooltip(UI['light_full'], gettext(
        "Compile with high-quality lighting. This looks correct, but takes "
        "longer to compute. Use if you're arranging lights.\nWhen "
        "publishing, this is always used."
    ) + "\n\n" + light_conf_swap.format(gettext("Fast")))

    packfile_enable = ttk.Checkbutton(
        frame,
        text=gettext('Enable packing'),
        variable=packfile_auto_enable,
    )
    packfile_enable.grid(row=2, column=0, sticky='ew')
    add_tooltip(packfile_enable, gettext(
        "Disable automatically packing resources in the map. This can speed up building and allows "
        "editing files and running reload commands, but can cause some resources to not work "
        "correctly. Regardless of this setting, packing is enabled when publishing. "
    ))

    packfile_dump_enable_chk = ttk.Checkbutton(
        frame,
        text=gettext('Dump packed files to:'),
        variable=packfile_dump_enable,
        command=set_pack_dump_enabled,
    )

    packfile_frame = ttk.LabelFrame(
        frame,
        labelwidget=packfile_dump_enable_chk,
    )
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

    set_pack_dump_enabled()

    add_tooltip(packfile_dump_enable_chk, gettext(
        "When compiling, dump all files which were packed into the map. "
        "Useful if you're intending to edit maps in Hammer."
    ))

    count_frame = ttk.LabelFrame(
        frame,
        text=gettext('Last Compile:'),
        labelanchor='n',
    )

    count_frame.grid(row=7, column=0, sticky='ew')
    count_frame.columnconfigure(0, weight=1)
    count_frame.columnconfigure(2, weight=1)

    ttk.Label(
        count_frame,
        text=gettext('Entity'),
        anchor='n',
    ).grid(row=0, column=0, columnspan=3, sticky='ew')

    count_entity = LimitCounter(
        count_frame,
        maximum=2048,
        length=120,
        name='entity',
        # i18n: Progress bar description
        blurb=gettext(
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

    ttk.Label(
        count_frame,
        text=gettext('Overlay'),
        anchor='center',
    ).grid(row=2, column=0, sticky='ew')
    count_overlay = LimitCounter(
        count_frame,
        maximum=512,
        length=50,
        name='overlay',
        # i18n: Progress bar description
        blurb=gettext(
            "Overlays are smaller images affixed to surfaces, like signs or "
            "indicator lights. Hiding complex antlines or setting them to "
            "signage will reduce this."
        )
    )
    count_overlay.bar.grid(row=3, column=0, sticky='ew', padx=5)

    UI['refresh_counts'] = SubPane.make_tool_button(
        count_frame,
        'icons/tool_sub',
        lambda: refresh_counts(count_brush, count_entity, count_overlay),
    )
    UI['refresh_counts'].grid(row=3, column=1)
    add_tooltip(UI['refresh_counts'], gettext(
        "Refresh the compile progress bars. Press after a compile has been "
        "performed to show the new values."
    ))

    ttk.Label(
        count_frame,
        text=gettext('Brush'),
        anchor='center',
    ).grid(row=2, column=2, sticky=tk.EW)
    count_brush = LimitCounter(
        count_frame,
        maximum=8192,
        length=50,
        name='brush',
        blurb=gettext(
            "Brushes form the walls or other parts of the test chamber. If this "
            "is high, it may help to reduce the size of the map or remove "
            "intricate shapes."
        )
    )
    count_brush.bar.grid(row=3, column=2, sticky='ew', padx=5)

    refresh_counts(count_brush, count_entity, count_overlay)


async def make_map_widgets(frame: ttk.Frame, corr: corridor_selector.Selector) -> None:
    """Create widgets for the map settings pane.

    These are things which mainly affect the geometry or gameplay of the map.
    """

    frame.columnconfigure(0, weight=1)

    voice_frame = ttk.LabelFrame(
        frame,
        text=gettext('Voicelines:'),
        labelanchor='nw',
    )
    voice_frame.grid(row=1, column=0, sticky='ew')

    def set_voice_priority() -> None:
        """Called when the voiceline priority is changed."""
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState, default=DEFAULT_STATE),
            use_voice_priority=VOICE_PRIORITY_VAR.get() != 0,
        ))
        COMPILE_CFG['General']['voiceline_priority'] = str(VOICE_PRIORITY_VAR.get())
        COMPILE_CFG.save_check()

    voice_priority = ttk.Checkbutton(
        voice_frame,
        text=gettext("Use voiceline priorities"),
        variable=VOICE_PRIORITY_VAR,
        command=set_voice_priority,
    )
    voice_priority.grid(row=0, column=0)
    add_tooltip(voice_priority, gettext(
        "Only choose the highest-priority voicelines. This means more generic "
        "lines will can only be chosen if few test elements are in the map. "
        "If disabled any applicable lines will be used."
    ))

    elev_frame = ttk.LabelFrame(
        frame,
        text=gettext('Spawn at:'),
        labelanchor='n',
    )

    elev_frame.grid(row=2, column=0, sticky='ew')
    elev_frame.columnconfigure(0, weight=1)
    elev_frame.columnconfigure(1, weight=1)

    def elev_changed(state: bool) -> None:
        """Called when an elevator is selected."""
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState, default=DEFAULT_STATE),
            spawn_elev=state,
        ))
        COMPILE_CFG['General']['spawn_elev'] = bool_as_int(state)
        COMPILE_CFG.save_check()

    elev_preview = ttk.Radiobutton(
        elev_frame,
        text=gettext('Entry Door'),
        value=0,
        variable=start_in_elev,
        command=functools.partial(elev_changed, False),
    )
    elev_elevator = ttk.Radiobutton(
        elev_frame,
        text=gettext('Elevator'),
        value=1,
        variable=start_in_elev,
        command=functools.partial(elev_changed, True),
    )

    elev_preview.grid(row=0, column=0, sticky='w')
    elev_elevator.grid(row=0, column=1, sticky='w')

    elev_conf_swap = gettext(
        "You can hold down Shift during the start of the Geometry stage to quickly swap which"
        "location you spawn at on the fly."
    )
    add_tooltip(elev_elevator, gettext(
        "When previewing in SP, spawn inside the entry elevator. Use this to "
        "examine the entry and exit corridors."
    ) + "\n\n" + elev_conf_swap)
    add_tooltip(elev_preview, gettext(
        "When previewing in SP, spawn just before the entry door."
    ) + "\n\n" + elev_conf_swap)

    ttk.Button(
        frame,
        text=gettext('Select Corridors'),
        command=corr.show,
    ).grid(row=3, column=0, sticky='ew')

    model_frame = ttk.LabelFrame(
        frame,
        text=gettext('Player Model (SP):'),
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

    def set_model(_: tk.Event) -> None:
        """Save the selected player model."""
        model = PLAYER_MODELS_REV[player_model_var.get()]
        config.APP.store_conf(attrs.evolve(
            config.APP.get_cur_conf(CompilePaneState, default=DEFAULT_STATE),
            player_mdl=model,
        ))
        COMPILE_CFG['General']['player_model'] = model
        COMPILE_CFG.save()

    player_mdl.bind('<<ComboboxSelected>>', set_model)

    model_frame.columnconfigure(0, weight=1)


async def make_pane(tool_frame: tk.Frame, menu_bar: tk.Menu, corr: corridor_selector.Selector) -> None:
    """Initialise when part of the BEE2."""
    global window
    window = SubPane.SubPane(
        TK_ROOT,
        title=gettext('Compile Options'),
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
    await make_widgets(corr)
    await config.APP.set_and_run_ui_callback(CompilePaneState, apply_state)


def init_application() -> None:
    """Initialise when standalone."""
    global window
    window = TK_ROOT
    window.title(gettext('Compiler Options - {}').format(utils.BEE_VERSION))
    window.resizable(True, False)

    # TODO load async properly.
    import trio
    trio.run(make_widgets)

    TK_ROOT.deiconify()
