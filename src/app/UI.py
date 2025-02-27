"""Main UI module, brings everything together."""
from typing import TypedDict, cast, assert_never

from tkinter import ttk
import tkinter as tk

from collections.abc import Callable
from contextlib import aclosing
import functools

import srctools.logger
import trio
import trio_util

import exporting
from app import lifecycle, paletteLoader, quit_app
from app.SubPane import CONF_EXPORT_OPTS, CONF_PALETTE
from async_util import EdgeTrigger, run_as_task
from BEE2_config import GEN_OPTS
from app.dialogs import Dialogs
from loadScreen import MAIN_UI as LOAD_UI
import packages
from packages import PakRef
import utils
from config.gen_opts import AfterExport
from config.last_sel import LastSelected
from config.windows import WindowState
import config
from transtoken import TransToken
from app import (
    img,
    itemconfig,
    voiceEditor,
    gameMan,
    packageMan,
    StyleVarPane,
    CompilerPane,
    item_search,
    optionWindow,
    backup as backup_win,
    signage_ui,
    paletteUI,
    music_conf,
)
from app.errors import Result as ErrorResult
from app.menu_bar import MenuBar
from trio_util import AsyncValue
from ui_tk.item_picker import ItemPicker, ItemsBG
from ui_tk.selector_win import SelectorWin, AttrDef as SelAttr, Options as SelectorOptions
from ui_tk.context_win import ContextWin
from ui_tk.corridor_selector import TkSelector
from ui_tk.dialogs import DIALOG, TkDialogs
from ui_tk.img import TKImages, TK_IMG
from ui_tk import tk_tools, tooltip, wid_transtoken, TK_ROOT
from ui_tk.signage_ui import SignageUI
from ui_tk.subpane import SubPane
import consts


LOGGER = srctools.logger.get_logger(__name__)


# Icon shown while items are being moved elsewhere.
ICO_MOVING = img.Handle.builtin('BEE2/item_moving', 64, 64)
ICO_GEAR = img.Handle.sprite('icons/gear', 10, 10)
ICO_GEAR_DIS = img.Handle.sprite('icons/gear_disabled', 10, 10)
IMG_BLANK = img.Handle.background(64, 64)

TRANS_EXPORTED = TransToken.ui('Selected Items and Style successfully exported!')
TRANS_EXPORTED_TITLE = TransToken.ui('BEE2 - Export Complete')
TRANS_MAIN_TITLE = TransToken.ui('BEEMOD {version} - {game}')


# These panes and a dict mapping object type to them.
skybox_win: SelectorWin
voice_win: SelectorWin
style_win: SelectorWin
elev_win: SelectorWin
suggest_windows: dict[type[packages.SelPakObject], SelectorWin] = {}

context_win: ContextWin
sign_ui: SignageUI
item_picker: ItemPicker

DATA_NO_VOICE = packages.SelitemData.build(
    short_name=TransToken.BLANK,
    long_name=packages.TRANS_NONE_NAME,
    small_icon=packages.NONE_ICON,
    desc=TransToken.ui('Add no extra voice lines, only Multiverse Cave if enabled.')
)
DATA_RAND_ELEV = packages.SelitemData.build(
    short_name=TransToken.BLANK,
    long_name=TransToken.ui('Random'),
    small_icon=img.Handle.builtin('BEE2/random', 96, 96),
    desc=TransToken.ui('Choose a random video.'),
)


class _WindowsDict(TypedDict):
    """TODO: Remove."""
    opt: SubPane
    pal: SubPane


# Holds the TK Toplevels, frames, widgets and menus
windows: _WindowsDict = cast(_WindowsDict, {})


async def create_selectors(core_nursery: trio.Nursery) -> None:
    """Create the main selector windows."""
    global skybox_win, voice_win, style_win, elev_win
    await trio.lowlevel.checkpoint()

    # Defaults match Clean Style, if not found it uses the first item.
    skybox_win = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=packages.Skybox.selector_id_getter(False),
        func_get_data=packages.Skybox.selector_data_getter(None),
        save_id='skyboxes',
        title=TransToken.ui('Select Skyboxes'),
        desc=TransToken.ui(
            'The skybox decides what the area outside the chamber is like. It chooses the colour '
            'of sky (seen in some items), the style of bottomless pit (if present), as well as '
            'color of "fog" (seen in larger chambers).'
        ),
        default_id=packages.CLEAN_STYLE,
        attributes=[
            SelAttr.bool('3D', TransToken.ui('3D Skybox'), False),
            SelAttr.color('COLOR', TransToken.ui('Fog Color')),
        ],
    ))
    core_nursery.start_soon(skybox_win.task)
    await trio.lowlevel.checkpoint()

    voice_win = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=packages.QuotePack.selector_id_getter(True),
        func_get_data=packages.QuotePack.selector_data_getter(DATA_NO_VOICE),
        save_id='voicelines',
        title=TransToken.ui('Select Additional Voice Lines'),
        desc=TransToken.ui(
            'Voice lines choose which extra voices play as the player enters or exits a chamber. '
            'They are chosen based on which items are present in the map. The additional '
            '"Multiverse" Cave lines are controlled separately in Style Properties.'
        ),
        default_id=utils.obj_id('BEE2_GLADOS_CLEAN'),
        func_get_attr=packages.QuotePack.get_selector_attrs,
        attributes=[
            SelAttr.list_and('CHAR', TransToken.ui('Characters'), ['??']),
            SelAttr.bool('TURRET', TransToken.ui('Turret Shoot Monitor'), False),
            SelAttr.bool('MONITOR', TransToken.ui('Monitor Visuals'), False),
        ],
    ))
    core_nursery.start_soon(voice_win.task)
    await trio.lowlevel.checkpoint()

    style_win = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=packages.Style.selector_id_getter(False),
        func_get_data=packages.Style.selector_data_getter(None),
        save_id='styles',
        default_id=packages.CLEAN_STYLE,
        title=TransToken.ui('Select Style'),
        desc=TransToken.ui(
            'The Style controls many aspects of the map. It decides the materials used for walls, '
            'the appearance of entrances and exits, the design for most items as well as other '
            'settings.\n\nThe style broadly defines the time period a chamber is set in.'
        ),
        func_get_attr=packages.Style.get_selector_attrs,
        has_def=False,
        # Selecting items changes much of the gui - don't allow when other
        # things are open...
        modal=True,
        attributes=[
            SelAttr.bool('VID', TransToken.ui('Elevator Videos'), default=True),
            SelAttr.string('CORR_OPTS', TransToken.ui('Corridor')),
        ]
    ))
    core_nursery.start_soon(style_win.task)
    await trio.lowlevel.checkpoint()

    elev_win = SelectorWin(TK_ROOT, SelectorOptions(
        func_get_ids=packages.Elevator.selector_id_getter(True),
        func_get_data=packages.Elevator.selector_data_getter(DATA_RAND_ELEV),
        save_id='elevators',
        title=TransToken.ui('Select Elevator Video'),
        desc=TransToken.ui(
            'Set the video played on the video screens in modern Aperture elevator rooms. Not all '
            'styles feature these. If set to "None", a random video will be selected each time the '
            'map is played, like in the default PeTI.'
        ),
        readonly_desc=TransToken.ui('This style does not have a elevator video screen.'),
        # i18n: Text when elevators are not present in the style.
        readonly_override=TransToken.ui('<Not Present>'),
        has_def=True,
        func_get_attr=packages.Elevator.get_selector_attrs,
        attributes=[
            SelAttr.bool('ORIENT', TransToken.ui('Multiple Orientations')),
        ]
    ))
    core_nursery.start_soon(elev_win.task)
    await trio.lowlevel.checkpoint()

    suggest_windows[packages.QuotePack] = voice_win
    suggest_windows[packages.Skybox] = skybox_win
    suggest_windows[packages.Elevator] = elev_win


def reposition_panes() -> None:
    """Position all the panes in the default places around the main window."""
    comp_win = CompilerPane.PANE
    opt_win = windows['opt']
    pal_win = windows['pal']
    # The x-pos of the right side of the main window
    xpos = min(
        TK_ROOT.winfo_screenwidth()
        - itemconfig.PANE.win.winfo_reqwidth(),

        TK_ROOT.winfo_rootx()
        + TK_ROOT.winfo_reqwidth()
        + 25
        )
    # The x-pos for the palette and compiler panes
    pal_x = TK_ROOT.winfo_rootx() - comp_win.win.winfo_reqwidth() - 25
    pal_win.move(
        x=pal_x,
        y=(TK_ROOT.winfo_rooty() - 50),
        height=max(
            TK_ROOT.winfo_reqheight() -
            comp_win.win.winfo_reqheight() -
            25,
            30,
        ),
        width=comp_win.win.winfo_reqwidth(),
    )
    comp_win.move(
        x=pal_x,
        y=pal_win.win.winfo_y() + pal_win.win.winfo_reqheight(),
    )
    opt_win.move(
        x=xpos,
        y=TK_ROOT.winfo_rooty()-40,
        width=itemconfig.PANE.win.winfo_reqwidth(),
    )
    itemconfig.PANE.move(
        x=xpos,
        y=TK_ROOT.winfo_rooty() + opt_win.win.winfo_reqheight() + 25,
    )


def reset_panes() -> None:
    """Reset the position of all panes."""
    reposition_panes()
    windows['pal'].save_conf()
    windows['opt'].save_conf()
    itemconfig.PANE.save_conf()
    CompilerPane.PANE.save_conf()


def fetch_export_info() -> exporting.ExportInfo | None:
    """Fetch the required information for performing an export."""

    # The chosen items on the palette.
    # TODO: Make ItemPos use SubItemRef
    pal_data: paletteUI.ItemPos = item_picker.get_items()
    # Group palette data by each item ID, so it can easily determine which items are actually
    # on the palette at all.
    pal_by_item: dict[str, dict[int, tuple[paletteUI.HorizInd, paletteUI.VertInd]]] = {}
    for pos, (item_id, subkey) in pal_data.items():
        pal_by_item.setdefault(item_id.casefold(), {})[subkey] = pos

    conf = config.APP.get_cur_conf(config.gen_opts.GenOptions)
    packset = packages.get_loaded_packages()
    game = gameMan.selected_game.value
    if game is None:
        LOGGER.warning('Could not export: No game set?')
        return None
    try:
        chosen_style = packset.obj_by_id(packages.Style, style_win.chosen.value)
    except KeyError:
        LOGGER.warning('Could not export: Style "{style}" does not exist?')
        return None

    return exporting.ExportInfo(
        # Specify the 'chosen item' for each object type
        packages.Music.export_info(music_conf.export_data(packset)),
        packages.Skybox.export_info(skybox_win.chosen.value),
        packages.QuotePack.export_info(voice_win.chosen.value),
        packages.Elevator.export_info(elev_win.chosen.value),
        packages.Item.export_info(pal_by_item),
        packages.StyleVar.export_info(StyleVarPane.export_data(chosen_style)),
        packages.Signage.export_info(signage_ui.export_data()),

        game=game,
        packset=packset,
        style=chosen_style,
        should_refresh=not conf.preserve_resources,
    )


async def export_complete_task(
    export_rec: trio.MemoryReceiveChannel[lifecycle.ExportResult],
    pal_ui: paletteUI.PaletteUI,
    dialog: Dialogs,
) -> None:
    """Run actions after an export completes.
    """
    info: exporting.ExportInfo
    result: ErrorResult
    async with export_rec:
        async for info, result in export_rec:
            if result is ErrorResult.FAILED or result is ErrorResult.CANCELLED:
                continue

            # Recompute, in case the trigger was busy with another export?
            pal_by_item = info.selected(packages.Item.export_info)
            pal_data = {
                pos: (utils.obj_id(item_id), subkey)
                for item_id, item_data in pal_by_item.items()
                for subkey, pos in item_data.items()
            }
            conf = config.APP.get_cur_conf(config.gen_opts.GenOptions)

            try:
                last_export = pal_ui.palettes[paletteUI.UUID_EXPORT]
            except KeyError:
                last_export = pal_ui.palettes[paletteUI.UUID_EXPORT] = paletteUI.Palette(
                    '',
                    pal_data,
                    # This makes it lookup the translated name
                    # instead of using a configured one.
                    trans_name='LAST_EXPORT',
                    uuid=paletteUI.UUID_EXPORT,
                    readonly=True,
                )
            else:
                last_export.items = pal_data
            last_export.save(ignore_readonly=True)

            # Save the configs since we're writing to disk lots anyway.
            GEN_OPTS.save_check()
            config.APP.write_file(config.APP_LOC)

            if conf.launch_after_export or conf.after_export is not config.gen_opts.AfterExport.NORMAL:
                do_action = await dialog.ask_yes_no(
                    optionWindow.AFTER_EXPORT_TEXT[
                        conf.after_export, conf.launch_after_export,
                    ].format(msg=TRANS_EXPORTED),
                    title=TRANS_EXPORTED_TITLE,
                )
            else:  # No action to do, so just show an OK.
                await dialog.show_info(TRANS_EXPORTED, title=TRANS_EXPORTED_TITLE)
                do_action = False

            # Do the desired action - if quit, we don't bother to update UI.
            if do_action:
                # Launch first so quitting doesn't affect this.
                if conf.launch_after_export:
                    await info.game.launch()

                if conf.after_export is AfterExport.NORMAL:
                    pass
                elif conf.after_export is AfterExport.MINIMISE:
                    TK_ROOT.iconify()
                elif conf.after_export is AfterExport.QUIT:
                    quit_app()
                    continue
                else:
                    assert_never(conf.after_export)

            # Select the last_export palette, so reloading loads this item selection.
            # But leave it at the current palette, if it's unmodified.
            if pal_ui.selected.items != pal_data:
                pal_ui.select_palette(paletteUI.UUID_EXPORT, False)
                pal_ui.is_dirty.set()


async def init_option(
    core_nursery: trio.Nursery,
    pane: SubPane,
    tk_img: TKImages,
    export: Callable[[], object],
    export_ready: trio_util.AsyncValue[bool],
    corridor: TkSelector,
    task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Initialise the export options pane."""
    pane.win.columnconfigure(0, weight=1)
    pane.win.rowconfigure(0, weight=1)

    frame = ttk.Frame(pane.win)
    frame.grid(row=0, column=0, sticky='nsew')
    frame.columnconfigure(0, weight=1)

    export_btn = ttk.Button(frame, command=export)
    export_btn.state(('disabled',))
    export_btn.grid(row=4, sticky="EW", padx=5)

    props = ttk.Frame(frame, width="50")
    props.columnconfigure(1, weight=1)
    props.grid(row=5, sticky="EW")

    music_frame = ttk.Labelframe(props)
    wid_transtoken.set_text(music_frame, TransToken.ui('Music: '))

    await core_nursery.start(
        music_conf.make_widgets, core_nursery, music_frame, pane,
    )
    suggest_windows[packages.Music] = music_conf.WINDOWS[consts.MusicChannel.BASE]

    def suggested_style_set() -> None:
        """Set music, skybox, voices, etc to the settings defined for a style."""
        for win in suggest_windows.values():
            win.sel_suggested()

    def suggested_style_mousein(_: tk.Event[tk.Misc]) -> None:
        """When mousing over the button, show the suggested items."""
        for win in suggest_windows.values():
            win.suggested_rollover_active.value = True

    def suggested_style_mouseout(_: tk.Event[tk.Misc]) -> None:
        """Return text to the normal value on mouseout."""
        for win in suggest_windows.values():
            win.suggested_rollover_active.value = False

    sugg_btn = ttk.Button(props, command=suggested_style_set)
    # '\u2193' is the downward arrow symbol.
    wid_transtoken.set_text(sugg_btn, TransToken.ui(
        "{down_arrow} Use Suggested {down_arrow}"
    ).format(down_arrow='\u2193'))
    sugg_btn.grid(row=1, column=1, columnspan=2, sticky="EW", padx=0)
    sugg_btn.bind('<Enter>', suggested_style_mousein)
    sugg_btn.bind('<Leave>', suggested_style_mouseout)

    async def configure_voice() -> None:
        """Open the voiceEditor window to configure a Quote Pack.

        TODO: Push parsing into editor code, make not async.
        """
        try:
            chosen_voice = packages.get_loaded_packages().obj_by_id(packages.QuotePack, voice_win.chosen.value)
        except KeyError:
            return
        info, _ = await chosen_voice.parse_conf()
        voiceEditor.show(tk_img, chosen_voice, info)
    for ind, name in enumerate([
            TransToken.ui("Style: "),
            None,
            TransToken.ui("Voice: "),
            TransToken.ui("Skybox: "),
            TransToken.ui("Elev Vid: "),
            TransToken.ui("Corridor: "),
            ]):
        if name is None:
            # This is the "Suggested" button!
            continue
        wid_transtoken.set_text(ttk.Label(props), name).grid(row=ind)

    voice_frame = ttk.Frame(props)
    voice_frame.columnconfigure(1, weight=1)
    btn_conf_voice = ttk.Button(
        voice_frame,
        command=lambda: core_nursery.start_soon(configure_voice),
        width=8,
    )
    btn_conf_voice.grid(row=0, column=0, sticky='NS')
    tk_img.apply(btn_conf_voice, ICO_GEAR_DIS)
    tooltip.add_tooltip(
        btn_conf_voice,
        TransToken.ui('Enable or disable particular voice lines, to prevent them from being added.'),
    )

    if utils.WIN:
        # On Windows, the buttons get inset on the left a bit. Inset everything
        # else to adjust.
        left_pad = (1, 0)
    else:
        left_pad = (0, 0)

    # Make all the selector window textboxes.
    (await style_win.widget(props)).grid(row=0, column=1, sticky='EW', padx=left_pad)
    # row=1: Suggested.
    voice_frame.grid(row=2, column=1, sticky='EW')
    (await skybox_win.widget(props)).grid(row=3, column=1, sticky='EW', padx=left_pad)
    (await elev_win.widget(props)).grid(row=4, column=1, sticky='EW', padx=left_pad)

    corr_button = ttk.Button(props, command=corridor.show_trigger.trigger)
    wid_transtoken.set_text(corr_button, TransToken.ui('Select'))
    corr_button.grid(row=5, column=1, sticky='EW')

    music_frame.grid(row=6, column=0, sticky='EW', columnspan=2)
    (await voice_win.widget(voice_frame)).grid(row=0, column=1, sticky='EW', padx=left_pad)

    if tk_tools.USE_SIZEGRIP:
        sizegrip = ttk.Sizegrip(props, cursor=tk_tools.Cursors.STRETCH_HORIZ)
        sizegrip.grid(row=2, column=5, rowspan=2, sticky="NS")

    async def voice_conf_task() -> None:
        """Turn the configuration button off when no voice is selected."""
        async with aclosing(voice_win.chosen.eventual_values()) as agen:
            async for voice_id in agen:
                # This might be open, so force-close it to ensure it isn't corrupt...
                voiceEditor.save()
                if voice_id == utils.ID_NONE:
                    btn_conf_voice.state(['disabled'])
                    tk_img.apply(btn_conf_voice, ICO_GEAR_DIS)
                else:
                    btn_conf_voice.state(['!disabled'])
                    tk_img.apply(btn_conf_voice, ICO_GEAR)

    async def export_btn_task() -> None:
        """Update the export button as necessary."""
        async with aclosing(gameMan.EXPORT_BTN_TEXT.eventual_values()) as agen:
            async for text in agen:
                wid_transtoken.set_text(export_btn, text)

    task_status.started()
    async with trio.open_nursery() as nursery:
        nursery.start_soon(tk_tools.apply_bool_enabled_state_task, export_ready, export_btn)
        nursery.start_soon(tk_tools.apply_bool_enabled_state_task, corridor.show_trigger.ready, corr_button)
        nursery.start_soon(voice_conf_task)
        nursery.start_soon(export_btn_task)
        while True:
            await trio_util.wait_any(*[
                window.chosen.wait_transition
                for window in suggest_windows.values()
            ])
            if all(not win.can_suggest() for win in suggest_windows.values()):
                sugg_btn.state(['disabled'])
            else:
                sugg_btn.state(['!disabled'])


async def on_game_changed() -> None:
    """Callback for when the game is changed.

    This updates the title bar to match, and saves it into the config.
    """
    async with aclosing(gameMan.selected_game.eventual_values()) as agen:
        async for game in agen:
            if game is None:
                continue
            wid_transtoken.set_win_title(
                TK_ROOT,
                TRANS_MAIN_TITLE.format(version=utils.BEE_VERSION, game=game.name),
            )
            config.APP.store_conf(LastSelected(utils.obj_id(game.name)), 'game')


async def init_windows(
    core_nursery: trio.Nursery,
    tk_img: TKImages,
    export_trig: EdgeTrigger[exporting.ExportInfo],
    export_rec: trio.MemoryReceiveChannel[lifecycle.ExportResult],
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Initialise all windows and panes.

    """
    global sign_ui, context_win, item_picker

    await run_as_task(create_selectors, core_nursery)

    # This is updated at the end.
    cur_style = AsyncValue(PakRef(packages.Style, utils.obj_id(style_win.chosen.value)))

    def export() -> None:
        """Export the palette."""
        info = fetch_export_info()
        if info is not None and export_trig.ready.value:
            export_trig.trigger(info)

    menu_bar = MenuBar(TK_ROOT, export, export_trig.ready)
    core_nursery.start_soon(menu_bar.task, tk_img)
    core_nursery.start_soon(on_game_changed)
    core_nursery.start_soon(gameMan.update_export_text)
    await trio.lowlevel.checkpoint()

    ui_bg = tk.Frame(TK_ROOT, bg=ItemsBG, name='bg')
    ui_bg.grid(row=0, column=0, sticky='NSEW')
    TK_ROOT.columnconfigure(0, weight=1)
    TK_ROOT.rowconfigure(0, weight=1)
    ui_bg.rowconfigure(0, weight=1)

    style = ttk.Style()
    # Custom button style with correct background
    # Custom label style with correct background
    style.configure('BG.TButton', background=ItemsBG)
    style.configure('Preview.TLabel', background='#F4F5F5')

    await trio.lowlevel.checkpoint()
    preview_frame = tk.Frame(ui_bg, bg=ItemsBG, name='preview')
    preview_frame.grid(
        row=0, column=3,
        sticky="NW",
        padx=(2, 5), pady=5,
    )
    await tk_tools.wait_eventloop()
    TK_ROOT.minsize(
        width=preview_frame.winfo_reqwidth()+200,
        height=preview_frame.winfo_reqheight()+5,
    )  # Prevent making the window smaller than the preview pane

    await trio.lowlevel.checkpoint()
    await LOAD_UI.step('preview')

    ttk.Separator(ui_bg, orient='vertical').grid(
        row=0, column=4,
        sticky="NS",
        padx=10, pady=10,
    )

    picker_split_frame = tk.Frame(ui_bg, bg=ItemsBG, name='picker_split')
    picker_split_frame.grid(row=0, column=5, sticky="NSEW", padx=5, pady=5)
    ui_bg.columnconfigure(5, weight=1)

    picker_frame = ttk.Frame(
        picker_split_frame,
        name='picker',
        padding=5,
        borderwidth=4,
        relief="raised",
    )
    picker_frame.grid(row=1, column=0, sticky="NSEW")
    picker_split_frame.rowconfigure(1, weight=1)
    picker_split_frame.columnconfigure(0, weight=1)

    item_picker = ItemPicker(preview_frame, picker_frame, cur_style)
    core_nursery.start_soon(item_picker.task)

    await LOAD_UI.step('picker')

    # This will sit on top of the palette section, spanning from left
    # to right
    search_frame = ttk.Frame(
        picker_split_frame,
        name='searchbar',
        padding=5,
        borderwidth=0,
        relief="raised",
    )
    search_frame.grid(row=0, column=0, sticky='ew')

    await LOAD_UI.step('filter')

    item_search.init(search_frame, item_picker.cur_filter)
    core_nursery.start_soon(item_search.update_task, cur_style)

    toolbar_frame = tk.Frame(
        preview_frame,
        name='toolbar',
        bg=ItemsBG,
        width=192,
        height=26,
        borderwidth=0,
        )
    toolbar_frame.place(x=73, y=2)

    windows['pal'] = SubPane(
        TK_ROOT, tk_img, CONF_PALETTE,
        menu_bar=menu_bar.view_menu,
        tool_frame=toolbar_frame,
    )
    await trio.lowlevel.checkpoint()

    pal_frame = ttk.Frame(windows['pal'].win, name='pal_frame')
    pal_frame.grid(row=0, column=0, sticky='NSEW')
    windows['pal'].win.columnconfigure(0, weight=1)
    windows['pal'].win.rowconfigure(0, weight=1)

    await trio.lowlevel.checkpoint()
    pal_ui = paletteUI.PaletteUI(
        pal_frame, menu_bar.pal_menu, item_picker,
        palettes=await paletteLoader.load_palettes(DIALOG),
        tk_img=tk_img,
        dialog_menu=TkDialogs(TK_ROOT),
        dialog_window=TkDialogs(windows['pal'].win),
    )
    await trio.lowlevel.checkpoint()

    TK_ROOT.bind_all(tk_tools.KEY_SAVE, lambda e: pal_ui.event_save(DIALOG))
    TK_ROOT.bind_all(tk_tools.KEY_SAVE_AS, lambda e: pal_ui.event_save_as(DIALOG))
    TK_ROOT.bind_all(tk_tools.KEY_EXPORT, lambda e: export())
    core_nursery.start_soon(pal_ui.update_task)

    core_nursery.start_soon(export_complete_task, export_rec, pal_ui, DIALOG)

    await LOAD_UI.step('palette')

    packageMan.make_window()

    await LOAD_UI.step('packageman')

    windows['opt'] = SubPane(
        TK_ROOT, tk_img, CONF_EXPORT_OPTS,
        menu_bar=menu_bar.view_menu,
        tool_frame=toolbar_frame,
    )
    corridor = TkSelector(tk_img, cur_style)
    await core_nursery.start(init_option, core_nursery, windows['opt'], tk_img, export, export_trig.ready, corridor)
    core_nursery.start_soon(corridor.task)
    await LOAD_UI.step('options')

    signage_trigger: EdgeTrigger[()] = EdgeTrigger()
    sign_ui = SignageUI(TK_IMG)
    core_nursery.start_soon(sign_ui.task, signage_trigger)

    await run_as_task(
        core_nursery.start, itemconfig.make_pane,
        core_nursery, toolbar_frame, menu_bar.view_menu, tk_img, signage_trigger,
    )
    await LOAD_UI.step('itemvar')

    await run_as_task(
        core_nursery.start, CompilerPane.make_pane,
        toolbar_frame, tk_img, menu_bar.view_menu,
    )
    await LOAD_UI.step('compiler')

    btn_clear = tk_tools.make_tool_button(
        toolbar_frame, tk_img,
        img='icons/clear_pal',
        command=item_picker.clear_palette,
    )
    btn_clear.grid(row=0, column=0, padx=2)
    tooltip.add_tooltip(
        btn_clear,
        TransToken.ui('Remove all items from the palette.'),
    )

    btn_shuffle = tk_tools.make_tool_button(
        toolbar_frame, tk_img,
        img='icons/shuffle_pal',
        command=item_picker.fill_palette,
    )
    btn_shuffle.grid(
        row=0,
        column=1,
        padx=((2, 5) if utils.MAC else (2, 10)),
    )
    tooltip.add_tooltip(
        btn_shuffle,
        TransToken.ui('Fill empty spots in the palette with random items.'),
    )

    await trio.lowlevel.checkpoint()
    await core_nursery.start(backup_win.init_toplevel, tk_img)
    await LOAD_UI.step('backup')
    voiceEditor.init_widgets()
    await LOAD_UI.step('voiceline')
    context_win = ContextWin(item_picker, tk_img, cur_style)
    await core_nursery.start(context_win.init_widgets, signage_trigger)
    await LOAD_UI.step('contextwin')
    await core_nursery.start(functools.partial(
        optionWindow.init_widgets,
        unhide_palettes=pal_ui.reset_hidden_palettes,
        reset_all_win=reset_panes,
    ))
    await LOAD_UI.step('optionwindow')
    await trio.lowlevel.checkpoint()

    # When clicking on any window, hide the context window
    hide_ctx_win = context_win.hide_context
    tk_tools.bind_leftclick(TK_ROOT, hide_ctx_win)
    tk_tools.bind_leftclick(itemconfig.PANE.win, hide_ctx_win)
    tk_tools.bind_leftclick(CompilerPane.window, hide_ctx_win)
    tk_tools.bind_leftclick(corridor.win, hide_ctx_win)
    tk_tools.bind_leftclick(windows['opt'].win, hide_ctx_win)
    tk_tools.bind_leftclick(windows['pal'].win, hide_ctx_win)

    # Load to properly apply config settings, then save to ensure
    # the file has any defaults applied.
    await trio.lowlevel.checkpoint()
    optionWindow.load()
    await trio.lowlevel.checkpoint()
    optionWindow.save()

    await trio.lowlevel.checkpoint()
    TK_ROOT.deiconify()

    for pane in [
        windows['pal'], windows['opt'],
        itemconfig.PANE, CompilerPane.PANE,
    ]:
        core_nursery.start_soon(pane.task)
        await trio.lowlevel.checkpoint()
        pane.win.deiconify()  # show it once we've loaded everything

    if utils.MAC:
        TK_ROOT.lift()  # Raise to the top of the stack

    await tk_tools.wait_eventloop()

    # Position windows according to remembered settings:
    try:
        main_win_state = config.APP.get_cur_conf(WindowState, 'main_window')
    except KeyError:
        # We don't have a config, position the window ourselves
        # move the main window if needed to allow room for palette
        if TK_ROOT.winfo_rootx() < windows['pal'].win.winfo_reqwidth() + 50:
            TK_ROOT.geometry(
                f'+{windows["pal"].win.winfo_reqwidth() + 50}+{TK_ROOT.winfo_rooty()}'
            )
        else:
            TK_ROOT.geometry(f'+{TK_ROOT.winfo_rootx()}+{TK_ROOT.winfo_rooty()}')
    else:
        start_x, start_y = tk_tools.adjust_inside_screen(
            main_win_state.x, main_win_state.y,
            win=TK_ROOT,
        )
        TK_ROOT.geometry(f'+{start_x}+{start_y}')
    await tk_tools.wait_eventloop()

    # First move to default positions, then load the config.
    # If the config is valid, this will move them to user-defined
    # positions.
    reposition_panes()
    await tk_tools.wait_eventloop()
    async with trio.open_nursery() as nursery:
        for pane in [
            itemconfig.PANE, CompilerPane.PANE,
            windows['opt'], windows['pal'],
        ]:
            nursery.start_soon(pane.load_conf)

    item_picker.set_items(pal_ui.selected.items)
    pal_ui.is_dirty.set()
    task_status.started()

    async with aclosing(style_win.chosen.eventual_values()) as agen:
        async for style_id in agen:
            packset = packages.get_loaded_packages()
            try:
                selected_style = utils.obj_id(style_id, 'Style')
            except ValueError as exc:
                LOGGER.warning(str(exc))
                style_win.choose_item(style_win.item_list[0])
                continue

            ref: packages.PakRef[packages.Style]
            cur_style.value = ref = packages.PakRef(packages.Style, selected_style)

            style_obj = ref.resolve(packset)

            # Update variant selectors on the itemconfig pane
            for item_id, func in itemconfig.ITEM_VARIANT_LOAD:
                func(ref)

            # Disable this if the style doesn't have elevators
            elev_win.readonly = style_obj is not None and not style_obj.has_video

            sign_ui.style_changed(selected_style)

            if style_obj is not None:
                for sugg_cls, win in suggest_windows.items():
                    win.set_suggested(style_obj.suggested[sugg_cls])
                StyleVarPane.refresh(packset, style_obj)
