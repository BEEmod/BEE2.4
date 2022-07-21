"""Window for configuring BEE2's options, as well as the home of some options."""
from collections import defaultdict
from pathlib import Path

import tkinter as tk
import trio
from tkinter import ttk, messagebox
from typing import Callable, List, Optional, Tuple, Dict

import attrs
import srctools.logger

from app.tooltip import add_tooltip
from app import (
    TK_ROOT, LAUNCH_AFTER_EXPORT, PRESERVE_RESOURCES, DEV_MODE, background_run,
    contextWin, gameMan, tk_tools, sound, logWindow, img, UI,
)
from config import AfterExport
from localisation import gettext
import loadScreen
import config


LOGGER = srctools.logger.get_logger(__name__)
AFTER_EXPORT_ACTION = tk.IntVar(name='OPT_after_export_action', value=AfterExport.MINIMISE.value)

# action, launching_game -> suffix on the message box.
AFTER_EXPORT_TEXT: Dict[Tuple[AfterExport, bool], str] = {
    (AfterExport.NORMAL, False): '',
    (AfterExport.NORMAL, True): gettext('\nLaunch Game?'),

    (AfterExport.MINIMISE, False): gettext('\nMinimise BEE2?'),
    (AfterExport.MINIMISE, True): gettext('\nLaunch Game and minimise BEE2?'),

    (AfterExport.QUIT, False): gettext('\nQuit BEE2?'),
    (AfterExport.QUIT, True): gettext('\nLaunch Game and quit BEE2?'),
}

# The checkbox variables, along with the GenOptions attribute they control.
VARS: List[Tuple[str, tk.Variable]] = []


win = tk.Toplevel(TK_ROOT)
win.transient(master=TK_ROOT)
tk_tools.set_window_icon(win)
win.title(gettext('BEE2 Options'))
win.withdraw()


def show() -> None:
    """Display the option window."""
    # Re-apply, so the vars update.
    load()
    win.deiconify()
    contextWin.hide_context()  # Ensure this closes.
    tk_tools.center_win(win)


def load() -> None:
    """Load the current settings from config."""
    conf = config.get_cur_conf(config.GenOptions)
    AFTER_EXPORT_ACTION.set(conf.after_export.value)
    for name, var in VARS:
        var.set(getattr(conf, name))


def save() -> None:
    """Save settings into the config and apply them to other windows."""
    # Preserve options set elsewhere.
    res = attrs.asdict(config.get_cur_conf(config.GenOptions), recurse=False)

    res['after_export'] = AfterExport(AFTER_EXPORT_ACTION.get())
    for name, var in VARS:
        res[name] = var.get()
    config.store_conf(config.GenOptions(**res))


async def apply_config(conf: config.GenOptions) -> None:
    """Used to apply the configuration to all windows."""
    logWindow.HANDLER.set_visible(conf.show_log_win)
    loadScreen.set_force_ontop(conf.force_load_ontop)
    # We don't propagate compact splash, that isn't important after the UI loads.
    UI.refresh_palette_icons()


def clear_caches() -> None:
    """Wipe the cache times in configs.

     This will force package resources to be extracted again.
     """
    message = gettext(
        'Package cache times have been reset. '
        'These will now be extracted during the next export.'
    )

    for game in gameMan.all_games:
        game.mod_times.clear()
        game.save()

    # This needs to be disabled, since otherwise we won't actually export
    # anything...
    conf = config.get_cur_conf(config.GenOptions)
    if conf.preserve_resources:
        config.store_conf(attrs.evolve(conf, preserve_resources=False))
        message += '\n\n' + gettext('"Preserve Game Resources" has been disabled.')

    gameMan.CONFIG.save_check()
    config.write_settings()

    # Since we've saved, dismiss this window.
    win.withdraw()

    messagebox.showinfo(title=gettext('Packages Reset'), message=message)


def make_checkbox(
    frame: tk.Misc,
    name: str,
    *,
    desc: str,
    var: tk.BooleanVar = None,
    tooltip='',
    callback: Optional[Callable[[], object]] = None,
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
    assert name in config.GenOptions.__annotations__, list(config.GenOptions.__annotations__)

    VARS.append((name, var))
    widget = ttk.Checkbutton(frame, variable=var, text=desc)

    if callback is not None:
        widget['command'] = callback

    if tooltip:
        add_tooltip(widget, tooltip)

    return widget


async def init_widgets(
    *,
    reset_all_win: Callable[[], object],
) -> None:
    """Create all the widgets."""
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
    nbook.add(fr_general, text=gettext('General'))

    fr_win = ttk.Frame(nbook)
    nbook.add(fr_win, text=gettext('Windows'))

    fr_dev = ttk.Frame(nbook)
    nbook.add(fr_dev, text=gettext('Development'))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(init_gen_tab, fr_general)
        nursery.start_soon(init_win_tab, fr_win, reset_all_win)
        nursery.start_soon(init_dev_tab, fr_dev)

    ok_cancel = ttk.Frame(win)
    ok_cancel.grid(row=1, column=0, padx=5, pady=5, sticky='E')

    def ok() -> None:
        """Close and apply changes."""
        save()
        background_run(config.apply_conf, config.GenOptions)
        win.withdraw()

    def cancel() -> None:
        """Close the window, then reload from configs to rollback changes."""
        win.withdraw()
        load()

    ok_btn = ttk.Button(ok_cancel, text=gettext('OK'), command=ok)
    cancel_btn = ttk.Button(ok_cancel, text=gettext('Cancel'), command=cancel)
    ok_btn.grid(row=0, column=0)
    cancel_btn.grid(row=0, column=1)
    win.protocol("WM_DELETE_WINDOW", cancel)

    load()  # Load the existing config.
    # Then apply to other windows.
    await config.set_and_run_ui_callback(config.GenOptions, apply_config)


async def init_gen_tab(f: ttk.Frame) -> None:
    """Make widgets in the 'General' tab."""
    after_export_frame = ttk.LabelFrame(f, text=gettext('After Export:'))
    after_export_frame.grid(
        row=0,
        rowspan=2,
        column=0,
        sticky='NS',
        padx=(0, 10),
    )

    exp_nothing = ttk.Radiobutton(
        after_export_frame,
        text=gettext('Do Nothing'),
        variable=AFTER_EXPORT_ACTION,
        value=AfterExport.NORMAL.value,
    )
    exp_minimise = ttk.Radiobutton(
        after_export_frame,
        text=gettext('Minimise BEE2'),
        variable=AFTER_EXPORT_ACTION,
        value=AfterExport.MINIMISE.value,
    )
    exp_quit = ttk.Radiobutton(
        after_export_frame,
        text=gettext('Quit BEE2'),
        variable=AFTER_EXPORT_ACTION,
        value=AfterExport.QUIT.value,
    )
    exp_nothing.grid(row=0, column=0, sticky='w')
    exp_minimise.grid(row=1, column=0, sticky='w')
    exp_quit.grid(row=2, column=0, sticky='w')

    add_tooltip(exp_nothing, gettext('After exports, do nothing and keep the BEE2 in focus.'))
    add_tooltip(exp_minimise, gettext('After exports, minimise to the taskbar/dock.'))
    add_tooltip(exp_quit, gettext('After exports, quit the BEE2.'))

    make_checkbox(
        after_export_frame,
        'launch_after_export',
        var=LAUNCH_AFTER_EXPORT,
        desc=gettext('Launch Game'),
        tooltip=gettext('After exporting, launch the selected game automatically.'),
    ).grid(row=3, column=0, sticky='W', pady=(10, 0))

    if sound.has_sound():
        mute = make_checkbox(f, name='play_sounds', desc=gettext('Play Sounds'))
    else:
        mute = ttk.Checkbutton(
            f,
            text=gettext('Play Sounds'),
            state='disabled',
        )
        add_tooltip(
            mute,
            gettext('Pyglet is either not installed or broken.\nSound effects have been disabled.')
        )
    mute.grid(row=0, column=1, sticky='E')

    reset_cache = ttk.Button(
        f,
        text=gettext('Reset Package Caches'),
        command=clear_caches,
    )
    reset_cache.grid(row=1, column=1, sticky='EW')
    add_tooltip(
        reset_cache,
        gettext('Force re-extracting all package resources.'),
    )


async def init_win_tab(
    f: ttk.Frame,
    reset_all_win: Callable[[], object],
) -> None:
    """Optionsl relevant to specific windows."""

    make_checkbox(
        f, 'force_load_ontop',
        desc=gettext('Keep loading screens on top'),
        tooltip=gettext(
            "Force loading screens to be on top of other windows. "
            "Since they don't appear on the taskbar/dock, they can't be "
            "brought to the top easily again."
        ),
    ).grid(row=0, column=0, sticky='W')
    make_checkbox(
        f, 'compact_splash',
        desc=gettext('Use compact splash screen'),
        tooltip=gettext(
            "Use an alternate smaller splash screen, which takes up less screen space."
        ),
    ).grid(row=0, column=1, sticky='E')

    make_checkbox(
        f, 'keep_win_inside',
        desc=gettext('Keep windows inside screen'),
        tooltip=gettext(
            'Prevent sub-windows from moving outside the screen borders. '
            'If you have multiple monitors, disable this.'
        ),
    ).grid(row=1, column=0, sticky='W')

    ttk.Button(
        f,
        text=gettext('Reset All Window Positions'),
        # Indirect reference to allow UI to set this later
        command=reset_all_win,
    ).grid(row=1, column=1, sticky='E')


async def init_dev_tab(f: ttk.Frame) -> None:
    """Various options useful for development."""
    f.columnconfigure(0, weight=1)
    f.columnconfigure(2, weight=1)

    make_checkbox(
        f, 'log_missing_ent_count',
        desc=gettext('Log missing entity counts'),
        tooltip=gettext(
            'When loading items, log items with missing entity counts in their properties.txt file.'
        ),
    ).grid(row=0, column=0, columnspan=2, sticky='W')

    make_checkbox(
        f, 'log_missing_styles',
        desc=gettext("Log when item doesn't have a style"),
        tooltip=gettext(
            'Log items have no applicable version for a particular style. This usually means it '
            'will look very bad.'
        ),
    ).grid(row=1, column=0, columnspan=2, sticky='W')

    make_checkbox(
        f, 'log_item_fallbacks',
        desc=gettext("Log when item uses parent's style"),
        tooltip=gettext(
            'Log when an item reuses a variant from a parent style (1970s using 1950s items, '
            'for example). This is usually fine, but may need to be fixed.'
        ),
    ).grid(row=2, column=0, columnspan=2, sticky='W')

    make_checkbox(
        f, 'visualise_inheritance',
        desc=gettext("Display item inheritance"),
        tooltip=gettext(
            'Add overlays to item icons to display which inherit from parent styles or '
            'have no applicable style.'
        ),
    ).grid(row=3, column=0, columnspan=2, sticky='W')

    make_checkbox(
        f, 'dev_mode',
        var=DEV_MODE,
        desc=gettext("Development Mode"),
        tooltip=gettext(
            'Enables displaying additional UI specific for '
            'development purposes. Requires restart to have an effect.'
        ),
    ).grid(row=0, column=2, columnspan=2, sticky='W')

    make_checkbox(
        f, 'preserve_resources',
        desc=gettext('Preserve Game Directories'),
        var=PRESERVE_RESOURCES,
        tooltip=gettext(
            'When exporting, do not copy resources to \n"bee2/" and "sdk_content/maps/bee2/".\n'
            "Only enable if you're developing new content, to ensure it is not overwritten."
        ),
    ).grid(row=1, column=2, columnspan=2, sticky='W')

    make_checkbox(
        f, 'show_log_win',
        desc=gettext('Show Log Window'),
        tooltip=gettext('Show the log file in real-time.'),
    ).grid(row=2, column=2, columnspan=2, sticky='W')

    make_checkbox(
        f, 'force_all_editor_models',
        desc=gettext("Force Editor Models"),
        tooltip=gettext(
            'Make all props_map_editor models available for use. Portal 2 has a limit of 1024 '
            'models loaded in memory at once, so we need to disable unused ones to free this up.'
        ),
    ).grid(row=3, column=2, columnspan=2, sticky='W')

    ttk.Separator(orient='horizontal').grid(row=9, column=0, columnspan=3, sticky='EW')

    ttk.Button(
        f,
        text=gettext('Dump All objects'),
        command=report_all_obj,
    ).grid(row=10, column=0)

    ttk.Button(
        f,
        text=gettext('Dump Items list'),
        command=report_items,
    ).grid(row=10, column=1)
    reload_img = ttk.Button(
        f,
        text=gettext('Reload Images'),
        command=img.refresh_all,
    )
    add_tooltip(reload_img, gettext(
        'Reload all images in the app. Expect the app to freeze momentarily.'
    ))
    reload_img.grid(row=10, column=2)

# Various "reports" that can be produced.


def get_report_file(filename: str) -> Path:
    """The folder where reports are dumped to."""
    reports = Path('reports')
    reports.mkdir(parents=True, exist_ok=True)
    file = (reports / filename).resolve()
    LOGGER.info('Producing {}...', file)
    return file


def report_all_obj() -> None:
    """Print a list of every object type and ID."""
    from packages import OBJ_TYPES, LOADED
    for type_name, obj_type in OBJ_TYPES.items():
        with get_report_file(f'obj_{type_name}.txt').open('w') as f:
            f.write(f'{len(LOADED.all_obj(obj_type))} {type_name}:\n')
            for obj in LOADED.all_obj(obj_type):
                f.write(f'- {obj.id}\n')


def report_items() -> None:
    """Print out all the item IDs used, with subtypes."""
    from packages import Item, LOADED
    with get_report_file('items.txt').open('w') as f:
        for item in sorted(LOADED.all_obj(Item), key=lambda it: it.id):
            for vers_name, version in item.versions.items():
                if len(item.versions) == 1:
                    f.write(f'- `<{item.id}>`\n')
                else:
                    f.write(f'- `<{item.id}:{vers_name}>`\n')

                variant_to_id = defaultdict(list)
                for sty_id, variant in version.styles.items():
                    variant_to_id[variant].append(sty_id)

                for variant, style_ids in variant_to_id.items():
                    f.write(
                        f'\t- [ ] {", ".join(sorted(style_ids))}:\n'
                        f'\t  `{variant.source}`\n'
                    )
