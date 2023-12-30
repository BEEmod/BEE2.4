"""Handles the music configuration UI."""
from typing import Any, Dict, Iterable, Optional, List
from tkinter import ttk
import tkinter

from srctools import FileSystemChain, FileSystem
import srctools.logger
import attrs

from app import TK_ROOT
from app.SubPane import SubPane
from app.selector_win import Item as SelItem, SelectorWin, AttrDef as SelAttr
from config.gen_opts import GenOptions
from consts import MusicChannel
from packages import PackagesSet, Music
from transtoken import TransToken
from ui_tk.wid_transtoken import set_text
import config
import packages


BTN_EXPAND = '▽'
BTN_EXPAND_HOVER = '▼'
BTN_CONTRACT = '△'
BTN_CONTRACT_HOVER = '▲'

LOGGER = srctools.logger.get_logger(__name__)

# On 3.8 the ... is invalid syntax
WINDOWS: Dict[MusicChannel, 'SelectorWin[...]'] = {}
SEL_ITEMS: Dict[str, SelItem] = {}
# If the per-channel selector boxes are currently hidden.
is_collapsed: bool = False

filesystem = FileSystemChain()
TRANS_BASE_COLL = TransToken.ui('Music:')
TRANS_BASE_EXP = TransToken.ui('Base:')


def load_filesystems(systems: Iterable[FileSystem[Any]]) -> None:
    """Record the filesystems used for each package, so we can sample sounds."""
    filesystem.systems.clear()
    for system in systems:
        filesystem.add_sys(system, prefix='resources/music_samp/')


def set_suggested(packset: PackagesSet, music_id: str) -> None:
    """Set the music ID that is suggested for the base.

    If sel_item is true, select the suggested item as well.
    """
    if music_id is None or music_id.casefold() == '<none>':
        # No music, special.
        for channel in MusicChannel:
            if channel is MusicChannel.BASE:
                continue
            WINDOWS[channel].set_suggested()
    else:
        music = packset.obj_by_id(Music, music_id)
        for channel in MusicChannel:
            if channel is MusicChannel.BASE:
                continue

            sugg = music.get_suggestion(packset, channel)
            WINDOWS[channel].set_suggested({sugg} if sugg else set())


def export_data(packset: PackagesSet) -> Dict[MusicChannel, Optional[Music]]:
    """Return the data used to export this."""
    base_id = WINDOWS[MusicChannel.BASE].chosen_id
    if base_id is not None:
        base_track = packset.obj_by_id(Music, base_id)
    else:
        base_track = None
    data: Dict[MusicChannel, Optional[Music]] = {
        MusicChannel.BASE: base_track,
    }
    for channel, win in WINDOWS.items():
        if channel is MusicChannel.BASE:
            continue
        # If collapsed, use the suggested track. Otherwise, use the chosen one.
        if is_collapsed:
            if base_track is not None:
                mus_id = base_track.get_suggestion(packset, channel)
            else:
                mus_id = None
        else:
            mus_id = win.chosen_id
        if mus_id is not None:
            data[channel] = packset.obj_by_id(Music, mus_id)
        else:
            data[channel] = None
    return data


def selwin_callback(music_id: Optional[str], channel: MusicChannel) -> None:
    """Callback for the selector windows.

    This saves into the config file the last selected item.
    """
    packset = packages.get_loaded_packages()
    if music_id is None:
        music_id = '<NONE>'
    # If collapsed, the hidden ones follow the base always.
    if channel is channel.BASE:
        set_suggested(packset, music_id)

        # If we have an instance, it's "custom" behaviour, so disable
        # all the subparts.
        try:
            has_inst = bool(packset.obj_by_id(Music, music_id).inst)
        except KeyError:  # <none>
            has_inst = False

        for win_chan, win in WINDOWS.items():
            if win_chan is not channel.BASE:
                win.readonly = has_inst


async def make_widgets(packset: PackagesSet, frame: ttk.LabelFrame, pane: SubPane) -> None:
    """Generate the UI components, and return the base window."""

    def for_channel(packset: PackagesSet, channel: MusicChannel) -> List[SelItem]:
        """Get the items needed for a specific channel."""
        music_list = []
        for music in packset.all_obj(Music):
            if music.provides_channel(channel):
                selitem = SelItem.from_data(
                    music.id,
                    music.selitem_data,
                    music.get_attrs(packset),
                )
                selitem.snd_sample = music.get_sample(packset, channel)
                music_list.append(selitem)
        return music_list

    WINDOWS[MusicChannel.BASE] = SelectorWin(
        TK_ROOT,
        for_channel(packset, MusicChannel.BASE),
        save_id='music_base',
        title=TransToken.ui('Select Background Music - Base'),
        desc=TransToken.ui(
            'This controls the background music used for a map. Expand the dropdown to set tracks '
            'for specific test elements.'
        ),
        has_none=True,
        default_id='VALVE_PETI',
        sound_sys=filesystem,
        none_desc=TransToken.ui(
            'Add no music to the map at all. Testing Element-specific music may still be added.'
        ),
        callback=selwin_callback,
        callback_params=[MusicChannel.BASE],
        attributes=[
            SelAttr.bool('SPEED', TransToken.ui('Propulsion Gel SFX')),
            SelAttr.bool('BOUNCE', TransToken.ui('Repulsion Gel SFX')),
            SelAttr.bool('TBEAM', TransToken.ui('Excursion Funnel Music')),
            SelAttr.bool('TBEAM_SYNC', TransToken.ui('Synced Funnel Music')),
        ],
    )

    WINDOWS[MusicChannel.TBEAM] = SelectorWin(
        TK_ROOT,
        for_channel(packset, MusicChannel.TBEAM),
        save_id='music_tbeam',
        title=TransToken.ui('Select Excursion Funnel Music'),
        desc=TransToken.ui('Set the music used while inside Excursion Funnels.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=TransToken.ui('The regular base track will continue to play normally.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.TBEAM],
        attributes=[
            SelAttr.bool('TBEAM_SYNC', TransToken.ui('Synced Funnel Music')),
        ],
    )

    WINDOWS[MusicChannel.BOUNCE] = SelectorWin(
        TK_ROOT,
        for_channel(packset, MusicChannel.BOUNCE),
        save_id='music_bounce',
        title=TransToken.ui('Select Repulsion Gel Music'),
        desc=TransToken.ui('Select the music played when players jump on Repulsion Gel.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=TransToken.ui('Add no music when jumping on Repulsion Gel.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.BOUNCE],
    )

    WINDOWS[MusicChannel.SPEED] = SelectorWin(
        TK_ROOT,
        for_channel(packset, MusicChannel.SPEED),
        save_id='music_speed',
        title=TransToken.ui('Select Propulsion Gel Music'),
        desc=TransToken.ui('Select music played when players have large amounts of horizontal velocity.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=TransToken.ui('Add no music while running fast.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.SPEED],
    )

    assert set(WINDOWS.keys()) == set(MusicChannel), "Extra channels?"

    # Widgets we want to remove when collapsing.
    exp_widgets: List[tkinter.Widget] = []

    def toggle_btn_enter(event: Optional[tkinter.Event[ttk.Label]] = None) -> None:
        toggle_btn['text'] = BTN_EXPAND_HOVER if is_collapsed else BTN_CONTRACT_HOVER

    def toggle_btn_exit(event: Optional[tkinter.Event[ttk.Label]] = None) -> None:
        toggle_btn['text'] = BTN_EXPAND if is_collapsed else BTN_CONTRACT

    def set_collapsed() -> None:
        """Configure for the collapsed state."""
        global is_collapsed
        is_collapsed = True
        conf = config.APP.get_cur_conf(GenOptions)
        config.APP.store_conf(attrs.evolve(conf, music_collapsed=True))
        set_text(base_lbl, TRANS_BASE_COLL)
        toggle_btn_exit()

        # Set all music to the children - so those are used.
        set_suggested(
            packages.get_loaded_packages(),
            WINDOWS[MusicChannel.BASE].chosen_id,
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
        toggle_btn_exit()
        for wid in exp_widgets:
            wid.grid()
        pane.update_idletasks()
        pane.move()

    def toggle(event: tkinter.Event[ttk.Label]) -> None:
        if is_collapsed:
            set_expanded()
        else:
            set_collapsed()
        pane.update_idletasks()
        pane.move()

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

    if config.APP.get_cur_conf(GenOptions).music_collapsed:
        set_collapsed()
    else:
        set_expanded()
