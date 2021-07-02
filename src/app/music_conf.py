"""Handles the music configuration UI."""
from typing import Dict, Iterable, Optional, List
from tkinter import ttk
import tkinter

from srctools import FileSystemChain, FileSystem
import srctools.logger

from app.selector_win import Item as SelItem, selWin as SelectorWin, AttrDef as SelAttr
from app.SubPane import SubPane
from app import TK_ROOT
from BEE2_config import GEN_OPTS
from consts import MusicChannel
from packages import Music

BTN_EXPAND = '▽'
BTN_EXPAND_HOVER = '▼'
BTN_CONTRACT = '△'
BTN_CONTRACT_HOVER = '▲'

LOGGER = srctools.logger.get_logger(__name__)

WINDOWS: Dict[MusicChannel, SelectorWin] = {}
SEL_ITEMS: Dict[str, SelItem] = {}
# If the per-channel selector boxes are currently hidden.
is_collapsed: bool = False

filesystem = FileSystemChain()


def load_filesystems(systems: Iterable[FileSystem]):
    """Record the filesystems used for each package, so we can sample sounds."""
    for system in systems:
        filesystem.add_sys(system, prefix='resources/music_samp/')


def set_suggested(music_id: str, *, sel_item: bool=False) -> None:
    """Set the music ID that is suggested for the base.

    If sel_item is true, select the suggested item as well.
    """
    if music_id is None or music_id.casefold() == '<none>':
        # No music, special.
        for channel in MusicChannel:
            if channel is MusicChannel.BASE:
                continue
            if sel_item:
                WINDOWS[channel].sel_item_id('<none>')
            WINDOWS[channel].set_suggested()
    else:
        music = Music.by_id(music_id)
        for channel in MusicChannel:
            if channel is MusicChannel.BASE:
                continue

            sugg = music.get_suggestion(channel)
            if sel_item:
                WINDOWS[channel].sel_item_id(sugg)
            WINDOWS[channel].set_suggested(sugg)


def export_data() -> Dict[MusicChannel, Optional[Music]]:
    """Return the data used to export this."""
    return {
        channel:
            None if
            win.chosen_id is None
            else Music.by_id(win.chosen_id)
        for channel, win in WINDOWS.items()
    }


def selwin_callback(music_id: Optional[str], channel: MusicChannel) -> None:
    """Callback for the selector windows.

    This saves into the config file the last selected item.
    """
    if music_id is None:
        music_id = '<NONE>'
    GEN_OPTS['Last_Selected']['music_' + channel.name.casefold()] = music_id
    # If collapsed, the hidden ones follow the base always.
    if channel is channel.BASE:
        set_suggested(music_id, sel_item=is_collapsed)

        # If we have an instance, it's "custom" behaviour, and so disable
        # all the subparts.
        try:
            has_inst = bool(Music.by_id(music_id).inst)
        except KeyError:  # <none>
            has_inst = False

        for win_chan, win in WINDOWS.items():
            if win_chan is not channel.BASE:
                win.readonly = has_inst


def load_selitems() -> None:
    """Load the selector items early, to correspond with the loadscreen order."""
    for item in Music.all():
        SEL_ITEMS[item.id] = SelItem.from_data(
            item.id,
            item.selitem_data,
            item.get_attrs()
        )


def make_widgets(frame: ttk.LabelFrame, pane: SubPane) -> SelectorWin:
    """Generate the UI components, and return the base window."""

    def for_channel(channel: MusicChannel) -> List[SelItem]:
        """Get the items needed for a specific channel."""
        music_list = []
        for music in Music.all():
            if music.provides_channel(channel):
                selitem = SEL_ITEMS[music.id].copy()
                selitem.snd_sample = music.get_sample(channel)
                music_list.append(selitem)
        return music_list

    # This gets overwritten when making windows.
    last_selected = {
        channel: GEN_OPTS.get_val(
            'Last_Selected',
            'music_' + channel.name.casefold(),
            '<NONE>',
        ) for channel in MusicChannel
    }

    base_win = WINDOWS[MusicChannel.BASE] = SelectorWin(
        TK_ROOT,
        for_channel(MusicChannel.BASE),
        title=_('Select Background Music - Base'),
        desc=_('This controls the background music used for a map. Expand '
               'the dropdown to set tracks for specific test elements.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=_('Add no music to the map at all. Testing Element-specific '
                    'music may still be added.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.BASE],
        attributes=[
            SelAttr.bool('SPEED', _('Propulsion Gel SFX')),
            SelAttr.bool('BOUNCE', _('Repulsion Gel SFX')),
            SelAttr.bool('TBEAM', _('Excursion Funnel Music')),
            SelAttr.bool('TBEAM_SYNC', _('Synced Funnel Music')),
        ],
    )

    WINDOWS[MusicChannel.TBEAM] = SelectorWin(
        TK_ROOT,
        for_channel(MusicChannel.TBEAM),
        title=_('Select Excursion Funnel Music'),
        desc=_('Set the music used while inside Excursion Funnels.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=_('Have no music playing when inside funnels.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.TBEAM],
        attributes=[
            SelAttr.bool('TBEAM_SYNC', _('Synced Funnel Music')),
        ],
    )

    WINDOWS[MusicChannel.BOUNCE] = SelectorWin(
        TK_ROOT,
        for_channel(MusicChannel.BOUNCE),
        title=_('Select Repulsion Gel Music'),
        desc=_('Select the music played when players jump on Repulsion Gel.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=_('Add no music when jumping on Repulsion Gel.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.BOUNCE],
    )

    WINDOWS[MusicChannel.SPEED] = SelectorWin(
        TK_ROOT,
        for_channel(MusicChannel.SPEED),
        title=_('Select Propulsion Gel Music'),
        desc=_('Select music played when players have large amounts of horizontal velocity.'),
        has_none=True,
        sound_sys=filesystem,
        none_desc=_('Add no music while running fast.'),
        callback=selwin_callback,
        callback_params=[MusicChannel.SPEED],
    )

    assert set(WINDOWS.keys()) == set(MusicChannel), "Extra channels?"

    # Widgets we want to remove when collapsing.
    exp_widgets: list[tkinter.Widget] = []

    def toggle_btn_enter(event=None):
        toggle_btn['text'] = BTN_EXPAND_HOVER if is_collapsed else BTN_CONTRACT_HOVER

    def toggle_btn_exit(event=None):
        toggle_btn['text'] = BTN_EXPAND if is_collapsed else BTN_CONTRACT

    def set_collapsed() -> None:
        """Configure for the collapsed state."""
        global is_collapsed
        is_collapsed = True
        GEN_OPTS['Last_Selected']['music_collapsed'] = '1'
        base_lbl['text'] = _('Music: ')
        toggle_btn_exit()

        # Set all music to the children - so those are used.
        set_suggested(WINDOWS[MusicChannel.BASE].chosen_id, sel_item=True)

        for wid in exp_widgets:
            wid.grid_remove()

    def set_expanded() -> None:
        """Configure for the expanded state."""
        global is_collapsed
        is_collapsed = False
        GEN_OPTS['Last_Selected']['music_collapsed'] = '0'
        base_lbl['text'] = _('Base: ')
        toggle_btn_exit()
        for wid in exp_widgets:
            wid.grid()
        pane.update_idletasks()
        pane.move()

    def toggle(event: tkinter.Event) -> None:
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
        btn = WINDOWS[channel].widget(frame)
        if row:
            exp_widgets.append(btn)
        btn.grid(row=row, column=2, sticky='EW')

    for row, text in enumerate([
        _('Funnel:'),
        _('Bounce:'),
        _('Speed:'),
    ], start=1):
        label = ttk.Label(frame, text=text)
        exp_widgets.append(label)
        label.grid(row=row, column=1, sticky='EW')

    if GEN_OPTS.get_bool('Last_Selected', 'music_collapsed', True):
        set_collapsed()
    else:
        set_expanded()

    for channel, win in WINDOWS.items():
        win.sel_item_id(last_selected[channel])

    return base_win
