"""Window for configuring BEE2's options, as well as the home of some options."""
from collections import defaultdict
from pathlib import Path

from tkinter import *
from tkinter import ttk
from tkinter import messagebox
from typing import Callable, List, Tuple, Dict

from enum import Enum

from BEE2_config import GEN_OPTS
from app.tooltip import add_tooltip

import utils
import srctools.logger
from app import contextWin, gameMan, tk_tools, sound, logWindow, TK_ROOT
from localisation import gettext
import loadScreen


LOGGER = srctools.logger.get_logger(__name__)


class AfterExport(Enum):
    """Specifies what happens after exporting."""
    NORMAL = 0  # Stay visible
    MINIMISE = 1  # Minimise to tray
    QUIT = 2  # Quit the app.

UI = {}
PLAY_SOUND = BooleanVar(value=True, name='OPT_play_sounds')
KEEP_WIN_INSIDE = BooleanVar(value=True, name='OPT_keep_win_inside')
FORCE_LOAD_ONTOP = BooleanVar(value=True, name='OPT_force_load_ontop')
SHOW_LOG_WIN = BooleanVar(value=False, name='OPT_show_log_window')
LAUNCH_AFTER_EXPORT = BooleanVar(value=True, name='OPT_launch_after_export')
PRESERVE_RESOURCES = BooleanVar(value=False, name='OPT_preserve_bee2_resource_dir')
DEV_MODE = BooleanVar(value=False, name='OPT_development_mode')
AFTER_EXPORT_ACTION = IntVar(
    value=AfterExport.MINIMISE.value,
    name='OPT_after_export_action',
)

# action, launching_game -> suffix on the message box.
AFTER_EXPORT_TEXT: Dict[Tuple[AfterExport, bool], str] = {
    (AfterExport.NORMAL, False): '',
    (AfterExport.NORMAL, True): gettext('\nLaunch Game?'),

    (AfterExport.MINIMISE, False): gettext('\nMinimise BEE2?'),
    (AfterExport.MINIMISE, True): gettext('\nLaunch Game and minimise BEE2?'),

    (AfterExport.QUIT, False): gettext('\nQuit BEE2?'),
    (AfterExport.QUIT, True): gettext('\nLaunch Game and quit BEE2?'),
}

refresh_callbacks: List[Callable[[], None]] = []  # functions called to apply settings.

# All the auto-created checkbox variables
VARS: Dict[Tuple[str, str], BooleanVar] = {}


def reset_all_win() -> None:
    """Return all windows to their default positions.

    This is replaced by `UI.reset_panes`.
    """
    pass

win = Toplevel(TK_ROOT)
win.transient(master=TK_ROOT)
tk_tools.set_window_icon(win)
win.title(gettext('BEE2 Options'))
win.withdraw()


def show() -> None:
    """Display the option window."""
    win.deiconify()
    contextWin.hide_context()  # Ensure this closes
    utils.center_win(win)


def load() -> None:
    """Load the current settings from config."""
    for var in VARS.values():
        var.load()  # type: ignore


def save() -> None:
    """Save settings into the config and apply them to other windows."""
    for var in VARS.values():
        var.save()  # type: ignore

    sound.play_sound = PLAY_SOUND.get()
    utils.DISABLE_ADJUST = not KEEP_WIN_INSIDE.get()
    logWindow.HANDLER.set_visible(SHOW_LOG_WIN.get())
    loadScreen.set_force_ontop(FORCE_LOAD_ONTOP.get())

    for func in refresh_callbacks:
        func()


def clear_caches() -> None:
    """Wipe the cache times in configs.

     This will force package resources to be extracted again.
     """
    import packages

    message = gettext(
        'Package cache times have been reset. '
        'These will now be extracted during the next export.'
    )

    for game in gameMan.all_games:
        game.mod_times.clear()
        game.save()
    GEN_OPTS['General']['cache_time'] = '0'

    for pack_id in packages.packages:
        packages.PACK_CONFIG[pack_id]['ModTime'] = '0'

    # This needs to be disabled, since otherwise we won't actually export
    # anything...
    if PRESERVE_RESOURCES.get():
        PRESERVE_RESOURCES.set(False)
        message += '\n\n' + gettext('"Preserve Game Resources" has been disabled.')

    save()  # Save any option changes..

    gameMan.CONFIG.save_check()
    GEN_OPTS.save_check()
    packages.PACK_CONFIG.save_check()

    # Since we've saved, dismiss this window.
    win.withdraw()

    messagebox.showinfo(
        title=gettext('Packages Reset'),
        message=message,
    )


def make_checkbox(
    frame: Misc,
    section: str,
    item: str,
    desc: str,
    default: bool=False,
    var: BooleanVar=None,
    tooltip='',
) -> ttk.Checkbutton:
    """Add a checkbox to the given frame which toggles an option.

    section and item are the location in GEN_OPTS for this config.
    If var is set, it'll be used instead of an auto-created variable.
    desc is the text put next to the checkbox.
    default is the default value of the variable, if var is None.
    frame is the parent frame.
    """
    if var is None:
        var = BooleanVar(
            value=default,
            name='opt_' + section.casefold() + '_' + item,
        )
    else:
        default = var.get()

    VARS[section, item] = var

    def save_opt():
        """Save the checkbox's values."""
        GEN_OPTS[section][item] = srctools.bool_as_int(
            var.get()
        )

    def load_opt():
        """Load the checkbox's values."""
        var.set(GEN_OPTS.get_bool(
            section,
            item,
            default,
        ))
    load_opt()

    var.save = save_opt
    var.load = load_opt
    widget = ttk.Checkbutton(
        frame,
        variable=var,
        text=desc,
    )

    if tooltip:
        add_tooltip(widget, tooltip)

    UI[section, item] = widget
    return widget


def init_widgets() -> None:
    """Create all the widgets."""
    UI['nbook'] = nbook = ttk.Notebook(
        win,

    )
    UI['nbook'].grid(
        row=0,
        column=0,
        padx=5,
        pady=5,
        sticky=NSEW,
    )
    win.columnconfigure(0, weight=1)
    win.rowconfigure(0, weight=1)

    UI['fr_general'] = fr_general = ttk.Frame(
        nbook,
    )
    nbook.add(fr_general, text=gettext('General'))
    init_gen_tab(fr_general)

    UI['fr_win'] = fr_win = ttk.Frame(
        nbook,
    )
    nbook.add(fr_win, text=gettext('Windows'))
    init_win_tab(fr_win)

    UI['fr_dev'] = fr_dev = ttk.Frame(
        nbook,
    )
    nbook.add(fr_dev, text=gettext('Development'))
    init_dev_tab(fr_dev)

    ok_cancel = ttk.Frame(
        win
    )
    ok_cancel.grid(
        row=1,
        column=0,
        padx=5,
        pady=5,
        sticky=E,
    )

    def ok() -> None:
        save()
        win.withdraw()

    def cancel() -> None:
        win.withdraw()
        load()  # Rollback changes

    UI['ok_btn'] = ok_btn = ttk.Button(
        ok_cancel,
        text=gettext('OK'),
        command=ok,
    )
    UI['cancel_btn'] = cancel_btn = ttk.Button(
        ok_cancel,
        text=gettext('Cancel'),
        command=cancel,
    )
    ok_btn.grid(row=0, column=0)
    cancel_btn.grid(row=0, column=1)
    win.protocol("WM_DELETE_WINDOW", cancel)

    save()  # And ensure they are applied to other windows


def init_gen_tab(f: ttk.Frame) -> None:
    """Make widgets in the 'General' tab."""
    def load_after_export():
        """Read the 'After Export' radio set."""
        AFTER_EXPORT_ACTION.set(GEN_OPTS.get_int(
            'General',
            'after_export_action',
            AFTER_EXPORT_ACTION.get()
        ))

    def save_after_export():
        """Save the 'After Export' radio set."""
        GEN_OPTS['General']['after_export_action'] = str(AFTER_EXPORT_ACTION.get())

    after_export_frame = ttk.LabelFrame(
        f,
        text=gettext('After Export:'),
    )
    after_export_frame.grid(
        row=0,
        rowspan=2,
        column=0,
        sticky='NS',
        padx=(0, 10),
    )

    VARS['General', 'after_export_action'] = AFTER_EXPORT_ACTION
    AFTER_EXPORT_ACTION.load = load_after_export
    AFTER_EXPORT_ACTION.save = save_after_export
    load_after_export()

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

    add_tooltip(exp_nothing, gettext('After exports, do nothing and '
                               'keep the BEE2 in focus.'))
    add_tooltip(exp_minimise, gettext('After exports, minimise to the taskbar/dock.'))
    add_tooltip(exp_quit, gettext('After exports, quit the BEE2.'))

    make_checkbox(
        after_export_frame,
        section='General',
        item='launch_Game',
        var=LAUNCH_AFTER_EXPORT,
        desc=gettext('Launch Game'),
        tooltip=gettext('After exporting, launch the selected game automatically.'),
    ).grid(row=3, column=0, sticky='W', pady=(10, 0))

    if sound.has_sound():
        mute = make_checkbox(
            f,
            section='General',
            item='play_sounds',
            desc=gettext('Play Sounds'),
            var=PLAY_SOUND,
        )
    else:
        mute = ttk.Checkbutton(
            f,
            text=gettext('Play Sounds'),
            state='disabled',
        )
        add_tooltip(
            mute,
            gettext('Pyglet is either not installed or broken.\n'
              'Sound effects have been disabled.')
        )
    mute.grid(row=0, column=1, sticky='E')

    UI['reset_cache'] = reset_cache = ttk.Button(
        f,
        text=gettext('Reset Package Caches'),
        command=clear_caches,
    )
    reset_cache.grid(row=1, column=1, sticky='EW')
    add_tooltip(
        reset_cache,
        gettext('Force re-extracting all package resources.'),
    )


def init_win_tab(f: ttk.Frame) -> None:
    keep_inside = make_checkbox(
        f,
        section='General',
        item='keep_win_inside',
        desc=gettext('Keep windows inside screen'),
        tooltip=gettext('Prevent sub-windows from moving outside the screen borders. '
                  'If you have multiple monitors, disable this.'),
        var=KEEP_WIN_INSIDE,
    )
    keep_inside.grid(row=0, column=0, sticky=W)

    make_checkbox(
        f,
        section='General',
        item='splash_stay_ontop',
        desc=gettext('Keep loading screens on top'),
        var=FORCE_LOAD_ONTOP,
        tooltip=gettext(
            "Force loading screens to be on top of other windows. "
            "Since they don't appear on the taskbar/dock, they can't be "
            "brought to the top easily again."
        ),
    ).grid(row=0, column=1, sticky=E)

    ttk.Button(
        f,
        text=gettext('Reset All Window Positions'),
        # Indirect reference to allow UI to set this later
        command=lambda: reset_all_win(),
    ).grid(row=1, column=0, sticky=EW)


def init_dev_tab(f: ttk.Frame) -> None:
    f.columnconfigure(1, weight=1)
    f.columnconfigure(2, weight=1)

    make_checkbox(
        f,
        section='Debug',
        item='log_missing_ent_count',
        desc=gettext('Log missing entity counts'),
        tooltip=gettext('When loading items, log items with missing entity counts '
                  'in their properties.txt file.'),
    ).grid(row=0, column=0, sticky=W)

    make_checkbox(
        f,
        section='Debug',
        item='log_missing_styles',
        desc=gettext("Log when item doesn't have a style"),
        tooltip=gettext('Log items have no applicable version for a particular style.'
                  'This usually means it will look very bad.'),
    ).grid(row=1, column=0, sticky=W)

    make_checkbox(
        f,
        section='Debug',
        item='log_item_fallbacks',
        desc=gettext("Log when item uses parent's style"),
        tooltip=gettext('Log when an item reuses a variant from a parent style '
                  '(1970s using 1950s items, for example). This is usually '
                  'fine, but may need to be fixed.'),
    ).grid(row=2, column=0, sticky=W)

    make_checkbox(
        f,
        section='Debug',
        item='log_incorrect_packfile',
        desc=gettext("Log missing packfile resources"),
        tooltip=gettext('Log when the resources a "PackList" refers to are not '
                  'present in the zip. This may be fine (in a prerequisite zip),'
                  ' but it often indicates an error.'),
    ).grid(row=3, column=0, sticky=W)

    make_checkbox(
        f,
        section='Debug',
        item='development_mode',
        var=DEV_MODE,
        desc=gettext("Development Mode"),
        tooltip=gettext('Enables displaying additional UI specific for '
                  'development purposes. Requires restart to have an effect.'),
    ).grid(row=0, column=1, sticky=W)

    make_checkbox(
        f,
        section='General',
        item='preserve_bee2_resource_dir',
        desc=gettext('Preserve Game Directories'),
        var=PRESERVE_RESOURCES,
        tooltip=gettext('When exporting, do not copy resources to \n"bee2/" and'
                  ' "sdk_content/maps/bee2/".\n'
                  "Only enable if you're"
                  ' developing new content, to ensure it is not '
                  'overwritten.'),
    ).grid(row=1, column=1, sticky=W)

    make_checkbox(
        f,
        section='Debug',
        item='show_log_win',
        desc=gettext('Show Log Window'),
        var=SHOW_LOG_WIN,
        tooltip=gettext('Show the log file in real-time.'),
    ).grid(row=2, column=1, sticky=W)

    make_checkbox(
        f,
        section='Debug',
        item='force_all_editor_models',
        desc=gettext("Force Editor Models"),
        tooltip=gettext('Make all props_map_editor models available for use. '
                  'Portal 2 has a limit of 1024 models loaded in memory at '
                  'once, so we need to disable unused ones to free this up.'),
    ).grid(row=3, column=1, sticky='w')

    ttk.Separator(orient='horizontal').grid(
        row=9, column=0, columnspan=2, sticky='ew'
    )

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
    from packages import OBJ_TYPES
    for type_name, obj_type in OBJ_TYPES.items():
        with get_report_file(f'obj_{type_name}.txt').open('w') as f:
            f.write(f'{len(obj_type.all())} {type_name}:\n')
            for obj in obj_type.all():
                f.write(f'- {obj.id}\n')


def report_items() -> None:
    """Print out all the item IDs used, with subtypes."""
    from packages import Item
    with get_report_file('items.txt').open('w') as f:
        for item in sorted(Item.all(), key=lambda it: it.id):
            for vers_name, version in item.versions.items():
                if len(item.versions) == 1:
                    f.write(f'- <{item.id}>\n')
                else:
                    f.write(f'- <{item.id}:{vers_name}>\n')

                variant_to_id = defaultdict(list)
                for sty_id, variant in version.styles.items():
                    variant_to_id[variant].append(sty_id)

                for variant, style_ids in variant_to_id.items():
                    f.write(
                        f'\t- [ ] {", ".join(sorted(style_ids))}:\n'
                        f'\t  {variant.source}\n'
                    )
