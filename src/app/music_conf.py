"""Handles the music configuration UI."""
from tkinter import ttk
import tkinter

from contextlib import aclosing

from srctools import FileSystemChain
import attrs
import srctools.logger
import trio

from config.gen_opts import GenOptions
from consts import MusicChannel
from packages import PackagesSet, Music, SelitemData, AttrDef
from transtoken import TransToken
from ui_tk.selector_win import SelectorWin, Options as SelectorOptions
from ui_tk.wid_transtoken import set_text
from ui_tk.subpane import SubPane
from ui_tk import TK_ROOT
import config
import packages
import utils


BTN_EXPAND = '▽'
BTN_EXPAND_HOVER = '▼'
BTN_CONTRACT = '△'
BTN_CONTRACT_HOVER = '▲'

LOGGER = srctools.logger.get_logger(__name__)

WINDOWS: dict[MusicChannel, SelectorWin] = {}
# If the per-channel selector boxes are currently hidden.
is_collapsed: bool = False

TRANS_BASE_COLL = TransToken.ui('Music:')
TRANS_BASE_EXP = TransToken.ui('Base:')

DATA_NONE_BASE = SelitemData.build(
    small_icon=packages.NONE_ICON,
    short_name=TransToken.BLANK,
    long_name=packages.TRANS_NONE_NAME,
    desc=TransToken.ui(
        'Add no music to the map at all. Testing Element-specific music may still be added.'
    ),
)
DATA_NONE_FUNNEL = SelitemData.build(
    small_icon=packages.NONE_ICON,
    short_name=TransToken.BLANK,
    long_name=packages.TRANS_NONE_NAME,
    desc=TransToken.ui('The regular base track will continue to play normally.'),
)
DATA_NONE_BOUNCE = SelitemData.build(
    small_icon=packages.NONE_ICON,
    short_name=TransToken.BLANK,
    long_name=packages.TRANS_NONE_NAME,
    desc=TransToken.ui('Add no music when jumping on Repulsion Gel.'),
)
DATA_NONE_SPEED = SelitemData.build(
    small_icon=packages.NONE_ICON,
    short_name=TransToken.BLANK,
    long_name=packages.TRANS_NONE_NAME,
    desc=TransToken.ui('Add no music while running fast.'),
)


def set_suggested(packset: PackagesSet, music_id: utils.SpecialID) -> None:
    """Set the music ID that is suggested for the base.

    If sel_item is true, select the suggested item as well.
    """
    music: Music | None = None
    if music_id != utils.ID_NONE:
        try:
            music = packset.obj_by_id(Music, music_id)
        except KeyError:
            # Base doesn't exist, just unlock all and don't suggest anything.
            pass

    for channel in MusicChannel:
        if channel is MusicChannel.BASE:
            continue
        if music is not None:
            sugg = music.get_suggestion(packset, channel)
            WINDOWS[channel].set_suggested([sugg] if sugg != utils.ID_NONE else ())
        else:
            WINDOWS[channel].set_suggested()


def export_data(packset: PackagesSet) -> Music.ExportInfo:
    """Return the data used to export this."""
    base_id = WINDOWS[MusicChannel.BASE].chosen.value
    if base_id == utils.ID_NONE:
        base_track = None
    else:
        try:
            base_track = packset.obj_by_id(Music, base_id)
        except KeyError:
            # Ignore here, error will be raised during actual export.
            base_track = None

    data: dict[MusicChannel, utils.SpecialID] = {
        MusicChannel.BASE: base_id,
    }
    for channel, win in WINDOWS.items():
        if channel is MusicChannel.BASE:
            continue
        # If collapsed, use the suggested track. Otherwise, use the chosen one.
        if is_collapsed:
            if base_track is not None:
                mus_id = base_track.get_suggestion(packset, channel)
            else:
                mus_id = utils.ID_NONE
        else:
            mus_id = win.chosen.value
        data[channel] = mus_id
    return data


async def filesys_update_task(filesys: FileSystemChain) -> None:
    """When packages reload, update the filesystem."""
    packset: PackagesSet
    async with aclosing(packages.LOADED.eventual_values()) as agen:
        async for packset in agen:
            filesys.systems.clear()
            for pack in packset.packages.values():
                filesys.add_sys(pack.fsys, prefix='resources/music_samp/')


async def make_widgets(
    core_nursery: trio.Nursery,
    frame: ttk.LabelFrame, pane: SubPane,
    *, task_status: trio.TaskStatus = trio.TASK_STATUS_IGNORED,
) -> None:
    """Generate the UI components, and return the base window."""
    filesystem = FileSystemChain()
    core_nursery.start_soon(filesys_update_task, filesystem)
    WINDOWS[MusicChannel.BASE] = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=Music.music_for_channel(MusicChannel.BASE),
        func_get_data=Music.selector_data_getter(DATA_NONE_BASE),
        save_id='music_base',
        title=TransToken.ui('Select Background Music - Base'),
        desc=TransToken.ui(
            'This controls the background music used for a map. Expand the dropdown to set tracks '
            'for specific test elements.'
        ),
        default_id=utils.obj_id('VALVE_PETI'),
        func_get_sample=Music.sample_getter_func(MusicChannel.BASE),
        sound_sys=filesystem,
        func_get_attr=Music.get_base_selector_attrs,
        attributes=[
            AttrDef.bool('SPEED', TransToken.ui('Propulsion Gel SFX')),
            AttrDef.bool('BOUNCE', TransToken.ui('Repulsion Gel SFX')),
            AttrDef.bool('TBEAM', TransToken.ui('Excursion Funnel Music')),
            AttrDef.bool('TBEAM_SYNC', TransToken.ui('Synced Funnel Music')),
        ],
    ))
    await trio.lowlevel.checkpoint()

    WINDOWS[MusicChannel.TBEAM] = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=Music.music_for_channel(MusicChannel.TBEAM),
        func_get_data=Music.selector_data_getter(DATA_NONE_FUNNEL),
        save_id='music_tbeam',
        title=TransToken.ui('Select Excursion Funnel Music'),
        desc=TransToken.ui('Set the music used while inside Excursion Funnels.'),
        func_get_sample=Music.sample_getter_func(MusicChannel.TBEAM),
        sound_sys=filesystem,
        func_get_attr=Music.get_funnel_selector_attrs,
        attributes=[
            AttrDef.bool('TBEAM_SYNC', TransToken.ui('Synced Funnel Music')),
        ],
    ))
    await trio.lowlevel.checkpoint()

    WINDOWS[MusicChannel.BOUNCE] = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=Music.music_for_channel(MusicChannel.BOUNCE),
        func_get_data=Music.selector_data_getter(DATA_NONE_BOUNCE),
        save_id='music_bounce',
        title=TransToken.ui('Select Repulsion Gel Music'),
        desc=TransToken.ui('Select the music played when players jump on Repulsion Gel.'),
        func_get_sample=Music.sample_getter_func(MusicChannel.BOUNCE),
        sound_sys=filesystem,
    ))
    await trio.lowlevel.checkpoint()

    WINDOWS[MusicChannel.SPEED] = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=Music.music_for_channel(MusicChannel.SPEED),
        func_get_data=Music.selector_data_getter(DATA_NONE_SPEED),
        save_id='music_speed',
        title=TransToken.ui('Select Propulsion Gel Music'),
        desc=TransToken.ui('Select music played when players have large amounts of horizontal velocity.'),
        func_get_sample=Music.sample_getter_func(MusicChannel.SPEED),
        sound_sys=filesystem,
    ))
    await trio.lowlevel.checkpoint()

    for win in WINDOWS.values():
        core_nursery.start_soon(win.task)

    assert set(WINDOWS.keys()) == set(MusicChannel), "Extra channels?"
    await trio.lowlevel.checkpoint()

    # Widgets we want to remove when collapsing.
    exp_widgets: list[tkinter.Widget] = []
    btn_hover = False

    def toggle_btn_enter(event: object = None, /) -> None:
        nonlocal btn_hover
        btn_hover = True
        toggle_btn['text'] = BTN_EXPAND_HOVER if is_collapsed else BTN_CONTRACT_HOVER

    def toggle_btn_exit(event: object = None, /) -> None:
        nonlocal btn_hover
        btn_hover = False
        toggle_btn['text'] = BTN_EXPAND if is_collapsed else BTN_CONTRACT

    def set_collapsed() -> None:
        """Configure for the collapsed state."""
        global is_collapsed
        is_collapsed = True
        conf = config.APP.get_cur_conf(GenOptions)
        config.APP.store_conf(attrs.evolve(conf, music_collapsed=True))
        set_text(base_lbl, TRANS_BASE_COLL)
        toggle_btn['text'] = BTN_EXPAND_HOVER if btn_hover else BTN_EXPAND

        # Set all music to the children - so those are used.
        set_suggested(
            packages.get_loaded_packages(),
            WINDOWS[MusicChannel.BASE].chosen.value,
        )

        for wid in exp_widgets:
            wid.grid_remove()

    def set_expanded() -> None:
        """Configure for the expanded state."""
        global is_collapsed
        is_collapsed = False
        conf = config.APP.get_cur_conf(GenOptions)
        config.APP.store_conf(attrs.evolve(conf, music_collapsed=False))
        set_text(base_lbl, TRANS_BASE_EXP)
        toggle_btn['text'] = BTN_CONTRACT_HOVER if btn_hover else BTN_CONTRACT
        for wid in exp_widgets:
            wid.grid()
        pane.win.update_idletasks()  # TODO replace by async
        pane.resize()

    def toggle(event: tkinter.Event[ttk.Label]) -> None:
        if is_collapsed:
            set_expanded()
        else:
            set_collapsed()
        pane.win.update_idletasks()  # TODO replace by async
        pane.resize()

    await trio.lowlevel.checkpoint()

    frame.columnconfigure(2, weight=1)

    base_lbl = ttk.Label(frame)
    base_lbl.grid(row=0, column=1)

    toggle_btn = ttk.Label(frame, text=' ')
    toggle_btn.bind('<Enter>', toggle_btn_enter)
    toggle_btn.bind('<Leave>', toggle_btn_exit)
    toggle_btn.bind('<ButtonPress-1>', toggle)
    toggle_btn.grid(row=0, column=0)

    for row, channel in enumerate(MusicChannel):
        btn = await WINDOWS[channel].widget(frame)
        if row:
            exp_widgets.append(btn)
        btn.grid(row=row, column=2, sticky='EW')

    for row, text in enumerate([
        TransToken.ui('Funnel:'),
        TransToken.ui('Bounce:'),
        TransToken.ui('Speed:'),
    ], start=1):
        label = ttk.Label(frame)
        set_text(label, text)
        exp_widgets.append(label)
        label.grid(row=row, column=1, sticky='EW')
    await trio.lowlevel.checkpoint()

    if config.APP.get_cur_conf(GenOptions).music_collapsed:
        set_collapsed()
    else:
        set_expanded()

    async with aclosing(WINDOWS[MusicChannel.BASE].chosen.eventual_values()) as agen:
        task_status.started()
        async for music_id in agen:
            # This saves into the config file the last selected item.
            packset = packages.get_loaded_packages()
            # If collapsed, the hidden ones follow the base always.
            set_suggested(packset, music_id)

            if music_id == utils.ID_NONE:
                disable_children = False  # We allow test element music by itself.
            else:
                # If we have an instance, it's "custom" behaviour, so disable
                # all the sub-channels.
                try:
                    disable_children = bool(packset.obj_by_id(Music, music_id).inst)
                except KeyError:  # Unknown, assume instances are allowed.
                    disable_children = False

            for win_chan, win in WINDOWS.items():
                if win_chan is not MusicChannel.BASE:
                    win.readonly = disable_children
