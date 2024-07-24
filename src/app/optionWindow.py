"""Window for configuring BEE2's options, as well as the home of some options."""
import tkinter as tk
from tkinter import ttk

from collections.abc import Callable
import itertools

import attrs
import srctools.logger
import trio
from srctools import EmptyMapping

import packages
import utils
from app.reports import report_all_obj, report_items, report_editor_models
from app import (
    DEV_MODE, background_run,
    gameMan, localisation, sound, logWindow, img, UI,
)
from config.filters import FilterConf
from config.gen_opts import GenOptions, AfterExport
from consts import Theme
from transtoken import TransToken, CURRENT_LANG
import loadScreen
import config
from ui_tk.wid_transtoken import set_text, set_win_title
from ui_tk.dialogs import Dialogs, DIALOG, TkDialogs
from ui_tk.tooltip import add_tooltip
from ui_tk import TK_ROOT, tk_tools


LOGGER = srctools.logger.get_logger(__name__)
AFTER_EXPORT_ACTION = tk.IntVar(name='OPT_after_export_action', value=AfterExport.MINIMISE.value)

# action, launching_game -> suffix on the message box.
AFTER_EXPORT_TEXT: dict[tuple[AfterExport, bool], TransToken] = {
    (AfterExport.NORMAL, False): TransToken.untranslated('{msg}'),
    (AfterExport.NORMAL, True): TransToken.ui('{msg}\nLaunch Game?'),

    (AfterExport.MINIMISE, False): TransToken.ui('{msg}\nMinimise BEE2?'),
    (AfterExport.MINIMISE, True): TransToken.ui('{msg}\nLaunch Game and minimise BEE2?'),

    (AfterExport.QUIT, False): TransToken.ui('{msg}\nQuit BEE2?'),
    (AfterExport.QUIT, True): TransToken.ui('{msg}\nLaunch Game and quit BEE2?'),
}

# The checkbox variables, along with the GenOptions attribute they control.
VARS: list[tuple[str, tk.BooleanVar]] = []
VAR_COMPRESS_ITEMS = tk.BooleanVar(name='opt_compress_items')

win = tk.Toplevel(TK_ROOT, name='optionsWin')
win.transient(master=TK_ROOT)
tk_tools.set_window_icon(win)
set_win_title(win, TransToken.ui('BEE2 Options'))
win.withdraw()

TRANS_TAB_GEN = TransToken.ui('General')
TRANS_TAB_WIN = TransToken.ui('Windows')
TRANS_TAB_DEV = TransToken.ui('Development')
TRANS_CACHE_RESET_TITLE = TransToken.ui('Packages Reset')
TRANS_CACHE_RESET = TransToken.ui(
    'Package cache times have been reset. '
    'These will now be extracted during the next export.'
)
TRANS_CACHE_RESET_AND_NO_PRESERVE = TransToken.ui(
    '{cache_reset}\n\n"Preserve Game Resources" has been disabled.'
).format(cache_reset=TRANS_CACHE_RESET)
TRANS_REBUILT_APP_LANG = TransToken.ui('UI translations rebuilt from sources successfully.')
TRANS_REBUILD_PACK_LANG = TransToken.ui('Package translations rebuilt successfully.')


# Callback to load languages when the window opens.
_load_langs: Callable[[], object] = lambda: None


def show() -> None:
    """Display the option window."""
    from app.UI import context_win
    # Re-apply, so the vars update.
    load()
    _load_langs()
    win.deiconify()
    context_win.hide_context()  # Ensure this closes.
    tk_tools.center_win(win)


def load() -> None:
    """Load the current settings from config."""
    conf = config.APP.get_cur_conf(GenOptions)
    AFTER_EXPORT_ACTION.set(conf.after_export.value)
    for name, var in VARS:
        var.set(getattr(conf, name))
    VAR_COMPRESS_ITEMS.set(config.APP.get_cur_conf(FilterConf).compress)


def save() -> None:
    """Save settings into the config and apply them to other windows."""
    # Preserve options set elsewhere.
    existing = config.APP.get_cur_conf(GenOptions)

    bool_options: dict[str, bool] = {name: var.get() for name, var in VARS}

    config.APP.store_conf(attrs.evolve(
        existing,
        after_export=AfterExport(AFTER_EXPORT_ACTION.get()),
        # Type checker can't know these keys are all valid.
        **bool_options,  # type: ignore[arg-type]
    ))
    config.APP.store_conf(FilterConf(compress=VAR_COMPRESS_ITEMS.get()))
    background_run(config.APP.apply_conf, FilterConf)


async def apply_config() -> None:
    """Apply the configuration to all windows whenever changed."""
    conf: GenOptions
    with config.APP.get_ui_channel(GenOptions) as channel:
        async for conf in channel:
            logWindow.HANDLER.set_visible(conf.show_log_win)
            loadScreen.set_force_ontop(conf.force_load_ontop)
            DEV_MODE.value = conf.dev_mode
            # We don't propagate compact splash, that isn't important after the UI loads.
            UI.refresh_palette_icons()


async def clear_caches(dialogs: Dialogs) -> None:
    """Wipe the cache times in configs.

     This will force package resources to be extracted again.
     """
    for game in gameMan.all_games:
        game.mod_times.value = EmptyMapping
        game.save()

    # This needs to be disabled, since otherwise we won't actually export
    # anything...
    conf = config.APP.get_cur_conf(GenOptions)
    if conf.preserve_resources:
        config.APP.store_conf(attrs.evolve(conf, preserve_resources=False))
        message = TRANS_CACHE_RESET_AND_NO_PRESERVE
    else:
        message = TRANS_CACHE_RESET

    gameMan.CONFIG.save_check()
    config.APP.write_file(config.APP_LOC)

    # Since we've saved, dismiss this window.
    win.withdraw()

    await dialogs.show_info(title=TRANS_CACHE_RESET_TITLE, message=message)


def make_checkbox(
    frame: tk.Misc,
    name: str,
    *,
    desc: TransToken,
    var: tk.BooleanVar | None = None,
    tooltip: TransToken = TransToken.BLANK,
    callback: Callable[[], object] | None = None,
) -> ttk.Checkbutton:
    """Add a checkbox to the given frame which toggles an option.

    name is the attribute in GenConf for this checkbox.
    If var is set, it'll be used instead of an auto-created variable.
    desc is the text put next to the checkbox.
    frame is the parent frame.
    """
    if var is None:
        var = tk.BooleanVar(name=f'gen_opt_{name}')
    # Ensure it's a valid attribute.
    assert name in GenOptions.__annotations__, list(GenOptions.__annotations__)

    VARS.append((name, var))
    widget = ttk.Checkbutton(frame, variable=var, name='check_' + name)
    set_text(widget, desc)

    if callback is not None:
        widget['command'] = callback

    if tooltip:
        add_tooltip(widget, tooltip)

    return widget


async def init_widgets(
    *,
    unhide_palettes: Callable[[], object],
    reset_all_win: Callable[[], object],
    task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Create all the widgets."""
    conf: GenOptions = config.APP.get_cur_conf(GenOptions)
    nbook = ttk.Notebook(win)
    nbook.grid(
        row=0,
        column=0,
        padx=5,
        pady=5,
        sticky=tk.NSEW,
    )
    win.columnconfigure(0, weight=1)
    win.rowconfigure(0, weight=1)

    fr_general = ttk.Frame(nbook)
    nbook.add(fr_general)

    fr_win = ttk.Frame(nbook)
    nbook.add(fr_win)

    fr_dev = ttk.Frame(nbook)
    nbook.add(fr_dev)

    fr_dev_options = ttk.Frame(fr_dev)
    fr_dev.grid_columnconfigure(0, weight=1)
    fr_dev.grid_rowconfigure(1, weight=1)
    # Add a warning splash to the dev screen.
    if conf.accepted_dev_warning:
        fr_dev_options.grid(row=0, column=0, rowspan=2, sticky='NSEW')
    else:
        def accept_warning() -> None:
            """Accept the warning message."""
            fr_dev_options.grid(row=0, column=0, rowspan=2, sticky='NSEW')
            config.APP.store_conf(attrs.evolve(
                config.APP.get_cur_conf(GenOptions),
                accepted_dev_warning=True,
            ))
            warning_btn.destroy()
            warning_lbl.destroy()

        warning_lbl = ttk.Label(fr_dev, justify="center")
        warning_btn = ttk.Button(fr_dev, command=accept_warning)
        set_text(warning_lbl, TransToken.ui(
            "Options on the development tab are intended for package authors\n"
            "and debugging purposes. Changing these may prevent BEEmod\n"
            "from functioning correctly until reverted to their original settings."
        ))
        set_text(warning_btn, TransToken.ui("Enable development options"))
        warning_lbl.grid(row=0, column=0)
        warning_btn.grid(row=1, column=0)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(init_gen_tab, fr_general, unhide_palettes)
        nursery.start_soon(init_win_tab, fr_win, reset_all_win)
        nursery.start_soon(init_dev_tab, fr_dev_options)

    ok_cancel = ttk.Frame(win)
    ok_cancel.grid(row=1, column=0, padx=5, pady=5, sticky='E')

    def ok() -> None:
        """Close and apply changes."""
        save()
        background_run(config.APP.apply_conf, GenOptions)
        win.withdraw()

    def cancel() -> None:
        """Close the window, then reload from configs to rollback changes."""
        win.withdraw()
        load()

    async def update_translations() -> None:
        """Update tab names whenever languages update."""
        while True:
            nbook.tab(0, text=str(TRANS_TAB_GEN))
            nbook.tab(1, text=str(TRANS_TAB_WIN))
            nbook.tab(2, text=str(TRANS_TAB_DEV))
            await CURRENT_LANG.wait_transition()

    set_text(
        ttk.Button(ok_cancel, command=ok),
        TransToken.ui('OK'),
    ).grid(row=0, column=0)
    set_text(
        ttk.Button(ok_cancel, command=cancel),
        TransToken.ui('Cancel'),
    ).grid(row=0, column=1)

    win.protocol("WM_DELETE_WINDOW", cancel)

    load()  # Load the existing config

    async with trio.open_nursery() as nursery:
        nursery.start_soon(update_translations)
        nursery.start_soon(apply_config)
        task_status.started()


async def init_gen_tab(
    f: ttk.Frame,
    unhide_palettes: Callable[[], object],
) -> None:
    """Make widgets in the 'General' tab."""
    global _load_langs
    dialogs = TkDialogs(f.winfo_toplevel())

    after_export_frame = ttk.LabelFrame(f)
    set_text(after_export_frame, TransToken.ui('After Export:'))
    after_export_frame.grid(
        row=0,
        rowspan=6,
        column=0,
        sticky='NS',
        padx=(0, 10),
    )
    f.rowconfigure(5, weight=1)  # Stretch underneath the right column, so it's all aligned to top.

    exp_nothing = ttk.Radiobutton(
        after_export_frame,
        variable=AFTER_EXPORT_ACTION,
        value=AfterExport.NORMAL.value,
    )
    exp_minimise = ttk.Radiobutton(
        after_export_frame,
        variable=AFTER_EXPORT_ACTION,
        value=AfterExport.MINIMISE.value,
    )
    exp_quit = ttk.Radiobutton(
        after_export_frame,
        variable=AFTER_EXPORT_ACTION,
        value=AfterExport.QUIT.value,
    )

    set_text(exp_nothing, TransToken.ui('Do Nothing'))
    set_text(exp_minimise, TransToken.ui('Minimise BEE2'))
    set_text(exp_quit, TransToken.ui('Quit BEE2'))

    exp_nothing.grid(row=0, column=0, sticky='w')
    exp_minimise.grid(row=1, column=0, sticky='w')
    exp_quit.grid(row=2, column=0, sticky='w')

    add_tooltip(exp_nothing, TransToken.ui('After exports, do nothing and keep the BEE2 in focus.'))
    add_tooltip(exp_minimise, TransToken.ui('After exports, minimise to the taskbar/dock.'))
    add_tooltip(exp_quit, TransToken.ui('After exports, quit the BEE2.'))

    make_checkbox(
        after_export_frame,
        'launch_after_export',
        desc=TransToken.ui('Launch Game'),
        tooltip=TransToken.ui('After exporting, launch the selected game automatically.'),
    ).grid(row=3, column=0, sticky='W', pady=(10, 0))

    lang_frm = ttk.Frame(f, name='lang_frm')
    lang_frm.grid(row=0, column=1, sticky='EW')

    set_text(ttk.Label(lang_frm), TransToken.ui('Language:')).grid(row=0, column=0)

    lang_box = ttk.Combobox(lang_frm, name='language')
    lang_box.state(['readonly'])
    lang_frm.columnconfigure(1, weight=1)
    lang_box.grid(row=0, column=1)

    lang_order: list[localisation.Language] = []
    lang_code_to_ind: dict[str, int] = {}

    def load_langs() -> None:
        """Load languages when the window opens."""
        lang_order.clear()
        disp_names = []
        conf = config.APP.get_cur_conf(GenOptions)

        lang_iter = localisation.get_languages()
        if conf.language == localisation.DUMMY.lang_code or DEV_MODE.value:
            # Add the dummy translation.
            lang_iter = itertools.chain(lang_iter, [localisation.DUMMY])

        for i, lang in enumerate(lang_iter):
            lang_order.append(lang)
            disp_names.append(localisation.get_lang_name(lang))
            lang_code_to_ind[lang.lang_code] = i

        lang_box['values'] = disp_names
        try:
            lang_box.current(lang_code_to_ind[conf.language])
        except KeyError:
            pass
        for code in localisation.expand_langcode(conf.language):
            try:
                lang_box.current(lang_code_to_ind[code])
                break
            except KeyError:
                pass
        else:
            LOGGER.warning(
                'Couldn\'t restore language: "{}" not in known languages {}',
                conf.language, list(lang_code_to_ind),
            )

    _load_langs = load_langs

    async def language_changed() -> None:
        """Set the language when the combo box is changed"""
        if lang_order:
            new_lang = lang_order[lang_box.current()]
            await localisation.load_aux_langs(gameMan.all_games, packages.get_loaded_packages(), new_lang)
            if lang_box.winfo_viewable():
                _load_langs()

    lang_box.bind('<<ComboboxSelected>>', tk_tools.make_handler(language_changed))

    mute_desc = TransToken.ui('Play Sounds')
    if sound.has_sound():
        mute = make_checkbox(f, name='play_sounds', desc=mute_desc)
    else:
        mute = ttk.Checkbutton(f, name='play_sounds', state='disabled')
        set_text(mute, mute_desc)
        add_tooltip(
            mute,
            TransToken.ui('Pyglet is either not installed or broken.\nSound effects have been disabled.')
        )
    mute.grid(row=1, column=1, sticky='W')

    compress_items = ttk.Checkbutton(f, variable=VAR_COMPRESS_ITEMS, name='check_compress_items')
    set_text(compress_items, TransToken.ui('Compress Items'))
    add_tooltip(compress_items, TransToken.ui(
        'If enabled, hide all but one item for those that can be swapped with a X Type option. '
        'This helps to shrink the item list, if you have a lot of items installed.'
    ))
    compress_items.grid(row=2, column=1, sticky='W')

    reset_palette = ttk.Button(f, command=unhide_palettes)
    set_text(reset_palette, TransToken.ui('Show Hidden Palettes'))
    reset_palette.grid(row=3, column=1, sticky='W')
    add_tooltip(
        reset_palette,
        TransToken.ui('Show all builtin palettes that you may have hidden.'),
    )

    reset_cache = ttk.Button(f, command=lambda: background_run(clear_caches,  dialogs))
    set_text(reset_cache, TransToken.ui('Reset Package Caches'))
    reset_cache.grid(row=4, column=1, sticky='W')
    add_tooltip(
        reset_cache,
        TransToken.ui('Force re-extracting all package resources.'),
    )


async def init_win_tab(
    f: ttk.Frame,
    reset_all_win: Callable[[], object],
) -> None:
    """Optionsl relevant to specific windows."""

    make_checkbox(
        f, 'force_load_ontop',
        desc=TransToken.ui('Keep loading screens on top'),
        tooltip=TransToken.ui(
            "Force loading screens to be on top of other windows. "
            "Since they don't appear on the taskbar/dock, they can't be "
            "brought to the top easily again."
        ),
    ).grid(row=0, column=0, sticky='W')
    make_checkbox(
        f, 'compact_splash',
        desc=TransToken.ui('Use compact splash screen'),
        tooltip=TransToken.ui(
            "Use an alternate smaller splash screen, which takes up less screen space."
        ),
    ).grid(row=0, column=1, sticky='E')

    make_checkbox(
        f, 'keep_win_inside',
        desc=TransToken.ui('Keep windows inside screen'),
        tooltip=TransToken.ui(
            'Prevent sub-windows from moving outside the screen borders. '
            'If you have multiple monitors, disable this.'
        ),
    ).grid(row=1, column=0, sticky='W')

    set_text(
        ttk.Button(f, command=reset_all_win),
        TransToken.ui('Reset All Window Positions'),
    ).grid(row=1, column=1, sticky='E')

    if not utils.FROZEN:  # Temporary button for testing.
        ttk.Button(
            f,
            text='Light mode',
            command=lambda: img.set_theme(Theme.LIGHT),
        ).grid(row=2, column=0, sticky='EW')
        ttk.Button(
            f,
            text='Dark mode',
            command=lambda: img.set_theme(Theme.DARK),
        ).grid(row=2, column=1, sticky='EW')


async def init_dev_tab(f: ttk.Frame) -> None:
    """Various options useful for development."""
    f.columnconfigure(0, weight=1)
    frm_check = ttk.Frame(f)
    frm_check.grid(row=0, column=0, sticky='ew')

    frm_check.columnconfigure(0, weight=1)
    frm_check.columnconfigure(1, weight=1)

    ttk.Separator(orient='horizontal').grid(row=1, column=0, sticky='ew')

    make_checkbox(
        frm_check, 'log_missing_ent_count',
        desc=TransToken.ui('Log missing entity counts'),
        tooltip=TransToken.ui(
            'When loading items, log items with missing entity counts in their properties.txt file.'
        ),
    ).grid(row=0, column=0, sticky='W')

    make_checkbox(
        frm_check, 'log_missing_styles',
        desc=TransToken.ui("Log when item doesn't have a style"),
        tooltip=TransToken.ui(
            'Log items have no applicable version for a particular style. This usually means it '
            'will look very bad.'
        ),
    ).grid(row=1, column=0, sticky='W')

    make_checkbox(
        frm_check, 'log_item_fallbacks',
        desc=TransToken.ui("Log when item uses parent's style"),
        tooltip=TransToken.ui(
            'Log when an item reuses a variant from a parent style (1970s using 1950s items, '
            'for example). This is usually fine, but may need to be fixed.'
        ),
    ).grid(row=2, column=0, sticky='W')

    make_checkbox(
        frm_check, 'visualise_inheritance',
        desc=TransToken.ui("Display item inheritance"),
        tooltip=TransToken.ui(
            'Add overlays to item icons to display which inherit from parent styles or '
            'have no applicable style.'
        ),
    ).grid(row=3, column=0, sticky='W')

    make_checkbox(
        frm_check, 'dev_mode',
        desc=TransToken.ui("Development Mode"),
        tooltip=TransToken.ui(
            'Enables displaying additional UI specific for '
            'development purposes. Requires restart to have an effect.'
        ),
    ).grid(row=0, column=1, sticky='W')

    make_checkbox(
        frm_check, 'preserve_resources',
        desc=TransToken.ui('Preserve Game Directories'),
        tooltip=TransToken.ui(
            'When exporting, do not copy resources to \n"bee2/" and "sdk_content/maps/bee2/".\n'
            "Only enable if you're developing new content, to ensure it is not overwritten."
        ),
    ).grid(row=1, column=1, sticky='W')

    make_checkbox(
        frm_check, 'preserve_fgd',
        desc=TransToken.ui('Preserve FGD'),
        tooltip=TransToken.ui(
            'When exporting, do not modify the FGD files.\n'
            "Enable this if you have a custom one, to prevent it from being overwritten."
        ),
    ).grid(row=2, column=1, sticky='W')

    make_checkbox(
        frm_check, 'show_log_win',
        desc=TransToken.ui('Show Log Window'),
        tooltip=TransToken.ui('Show the log file in real-time.'),
    ).grid(row=3, column=1, sticky='W')

    make_checkbox(
        frm_check, 'force_all_editor_models',
        desc=TransToken.ui("Force Editor Models"),
        tooltip=TransToken.ui(
            'Make all props_map_editor models available for use. Portal 2 has a limit of 1024 '
            'models loaded in memory at once, so we need to disable unused ones to free this up.'
        ),
    ).grid(row=4, column=1, sticky='W')

    frm_btn1 = ttk.Frame(f)
    frm_btn1.grid(row=2, column=0, sticky='ew')
    frm_btn1.columnconfigure(0, weight=1)
    frm_btn1.columnconfigure(2, weight=1)

    set_text(
        ttk.Button(frm_btn1,  command=report_all_obj),
        TransToken.ui('Dump All Objects'),
    ).grid(row=0, column=0)

    set_text(
        ttk.Button(frm_btn1, command=report_items),
        TransToken.ui('Dump Items List'),
    ).grid(row=0, column=1)

    set_text(
        ttk.Button(frm_btn1, command=lambda: background_run(report_editor_models)),
        TransToken.ui('Dump Editor Models'),
    ).grid(row=1, column=0)

    reload_img = ttk.Button(frm_btn1, command=img.refresh_all)
    set_text(reload_img, TransToken.ui('Reload Images'))
    add_tooltip(reload_img, TransToken.ui(
        'Reload all images in the app. Expect the app to freeze momentarily.'
    ))
    reload_img.grid(row=0, column=2)

    frm_btn2 = ttk.Frame(f)
    frm_btn2.grid(row=3, column=0, sticky='ew')
    frm_btn2.columnconfigure(0, weight=1)
    frm_btn2.columnconfigure(1, weight=1)

    async def rebuild_app_langs() -> None:
        """Rebuild application languages, then notify the user."""
        await localisation.rebuild_app_langs()
        await DIALOG.show_info(TRANS_REBUILT_APP_LANG)

    build_app_trans_btn = ttk.Button(frm_btn2, command=lambda: background_run(rebuild_app_langs))
    set_text(build_app_trans_btn, TransToken.ui('Build UI Translations'))
    add_tooltip(build_app_trans_btn, TransToken.ui(
        "Compile '.po' UI translation files into '.mo'. This requires those to have been "
        "downloaded from the source repo."
    ))
    build_app_trans_btn.grid(row=0, column=0, sticky='w')

    async def rebuild_pack_langs() -> None:
        """Rebuild package languages, then notify the user."""
        await localisation.rebuild_package_langs(packages.get_loaded_packages())
        await DIALOG.show_info(TRANS_REBUILD_PACK_LANG)

    build_pack_trans_btn = ttk.Button(frm_btn2, command=lambda: background_run(rebuild_pack_langs))
    set_text(build_pack_trans_btn, TransToken.ui('Build Package Translations'))
    add_tooltip(build_pack_trans_btn, TransToken.ui(
        "Export translation files for all unzipped packages. This will update existing "
        "localisations, creating them for packages that don't have any."
    ))
    build_pack_trans_btn.grid(row=0, column=1, sticky='e')
