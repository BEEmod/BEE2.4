"""Window for adjusting the default values of item properties."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from functools import partial as func_partial
from enum import Enum
from typing import Callable, Iterator, Any
import random

import utils
import srctools
from app import contextWin, gameMan, tk_tools, sound, TK_ROOT
from localisation import TransToken
import srctools.logger


LOGGER = srctools.logger.get_logger(__name__)


@utils.freeze_enum_props
class PropTypes(Enum):
    """Type of property to display."""
    NONE = 'none'
    CHECKBOX = 'checkbox'
    SUB_TYPE = 'subtype'

    PISTON = 'pist'
    TIMER = 'timer'
    PANEL = 'panel'
    GELS = 'gelType'
    OSCILLATE = 'track'

    @property
    def is_editable(self) -> bool:
        """Check if the user can change this property type."""
        return self.value not in ('none', 'subtype')

# All properties in editoritems, Valve probably isn't going to  release a major update so it's
# fine to hardcode this.
PROP_TYPES = {
    'toplevel':    (PropTypes.PISTON, TransToken.ui('Start Position')),
    'bottomlevel': (PropTypes.PISTON, TransToken.ui('End Position')),
    'timerdelay':  (PropTypes.TIMER, TransToken.ui('Delay \n(0=infinite)')),
    'angledpanelanimation': (PropTypes.PANEL, TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type')),
    'paintflowtype':        (PropTypes.GELS,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type')),

    'oscillate':      (PropTypes.OSCILLATE, TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_rail_oscillate')),
    'startenabled':   (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_enabled')),
    'startreversed':  (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_reversed')),
    'startdeployed':  (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_deployed')),
    'startactive':    (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_rail_start_active')),
    'startopen':      (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_start_open')),
    'startlocked':    (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_coop_exit_starts_locked')),
    'dropperenabled': (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_dropper_enabled')),
    'autodrop':       (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_auto_drop_cube')),
    'autorespawn':    (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_auto_respawn_cube')),
    'allowstreak':    (PropTypes.CHECKBOX,  TransToken.from_valve('PORTAL2_PuzzleEditor_ContextMenu_allow_streak_paint')),

    # Properties that we don't allow modification of.
    'timersound': (PropTypes.NONE, TransToken.ui('Timer Sound')),
    'angledpaneltype': (PropTypes.NONE, TransToken.ui('Angled Panel Type')),
    'itemfallstraightdown': (PropTypes.NONE, TransToken.ui('Disable Cube Dropper Clips')),
    'paintexporttype': (PropTypes.NONE, TransToken.ui('Gel Export Type')),
    'autotrigger': (PropTypes.NONE, TransToken.ui('Automatically Move')),

    'connectioncount': (PropTypes.NONE, TransToken.ui('Connection Count')),
    'connectioncountpolarity': (PropTypes.NONE, TransToken.ui('Polarity Connection Count')),
    'coopdoor': (PropTypes.NONE, TransToken.ui('Is Coop?')),
    'portalable': (PropTypes.NONE, TransToken.ui('Flip Panel Portalability')),
    'speed': (PropTypes.NONE, TransToken.ui('Track Platform Speed')),
    'startingposition': (PropTypes.NONE, TransToken.ui('Initial Track Platform Position')),
    'traveldirection': (PropTypes.NONE, TransToken.ui('Track Platform Direction')),
    'traveldistance': (PropTypes.NONE, TransToken.ui('Track Platform Distance')),

    # Controlled by bottom and top position, not set separately.
    'startup': (PropTypes.NONE, TransToken.ui('Start Up')),

    # Faith Plate
    'verticalalignment': (PropTypes.NONE, TransToken.ui('Vertical Alignment')),
    'catapultspeed': (PropTypes.NONE, TransToken.ui('Faith Plate Speed')),
    'targetname': (PropTypes.NONE, TransToken.ui('Faith Target Name')),

    'cubetype': (PropTypes.SUB_TYPE, TransToken.ui('Cube Type')),
    'hazardtype': (PropTypes.SUB_TYPE, TransToken.ui('Fizzler Type')),
    'barriertype': (PropTypes.SUB_TYPE, TransToken.ui('Barrier Type')),
    'buttontype': (PropTypes.SUB_TYPE, TransToken.ui('Button Type')),
    'painttype': (PropTypes.SUB_TYPE, TransToken.ui('Gel Type')),
}
# valid property types:
#  checkbox, timerDel, pistPlat, gelType, panAngle, railLift, none, subType

# order of the different properties, 'special' are the larger controls
# like sliders or dropdown boxes
PROP_POS_SPECIAL = [
    'toplevel',
    'bottomlevel',
    'angledpanelanimation',
    'paintflowtype',
    'timerdelay',
]
PROP_POS = [
    'allowstreak',
    'startenabled',
    'startreversed',
    'startdeployed',
    'startopen',
    'startlocked',
    'startactive',
    'oscillate',
    'dropperenabled',
    'autodrop',
    'autorespawn',
]

# holds the checkbox or other item used to manipulate the box
widgets: dict[str, Any] = {}
# holds the descriptive labels for each property
labels: dict[str, ttk.Label] = {}

# The properties we currently have displayed.
propList: list[str] = []

# selected values for this items
values: dict[str, tk.Variable | str | float] = {}
out_values: dict[str, tk.Variable | str | float] = {}

PAINT_OPTS = [
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_light',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_medium',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_heavy',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_drip',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_bomb',
]

PANEL_ANGLES = [
    (30, 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_30'),
    (45, 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_45'),
    (60, 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_60'),
    (90, 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_90'),
]

DEFAULTS = {  # default values for this item
    'startup': False,
    'toplevel': 1,
    'bottomlevel': 0,
    'angledpanelanimation': '45',
    'startenabled': True,
    'startreversed': False,
    'startdeployed': True,
    'startactive': True,
    'startopen': True,
    'startlocked': False,
    'timerdelay': 3,
    'dropperenabled': True,
    'autodrop': True,
    'autorespawn': True,
    'oscillate': True,
    'paintflowtype': 1,
    'allowstreak': True
    }
# Used for us to produce the appropriate changing sound.
last_angle: int = 0

# ttk.Scale works on floating point values,
# so it can be put partway. We need to suppress calling our callbacks
# whilst we fix it.
enable_tim_callback = True
enable_pist_callback = True

win = tk.Toplevel(TK_ROOT)
win.transient(TK_ROOT)
win.wm_attributes('-topmost', True)
win.withdraw()


TRANS_TITLE = TransToken.ui('BEE2 - {item}')
TRANS_SUBTITLE = TransToken.ui('Settings for "{item}"')
TRANS_LABEL = TransToken.untranslated('{name}: ')
TRANS_TIMER_DELAY = TransToken.ui('Timer Delay:\n        ({tim})')


def callback(props: dict[str, str]) -> None:
    """Called when the window is closed, to apply properties."""
    pass


def is_visible() -> bool:
    """Check if the window is visible."""
    return win.winfo_ismapped()


def scroll_angle(key: str, e: tk.Event) -> None:
    """Change callback for panel angles."""
    if e.delta > 0 and widgets[key].get() != '90':
        e.widget.invoke('buttonup')
    elif e.delta < 0 and widgets[key].get() != '0':
        e.widget.invoke('buttondown')


def save_paint(key: str, val: str) -> None:
    """Save callback for paint options."""
    sound.fx_blockable('config')
    out_values[key] = val


def save_angle(key: str, new_angle: int) -> None:
    """Change callback for angle properties."""
    global last_angle
    if new_angle > last_angle:
        sound.fx_blockable('raise_' + random.choice('123'))
    elif new_angle < last_angle:
        sound.fx_blockable('lower_' + random.choice('123'))
    last_angle = new_angle
    out_values[key] = 'ramp_' + str(new_angle) + '_deg_open'


def save_tim(key: str, val: str) -> None:
    """Change callback for TimerDelay."""
    global enable_tim_callback
    if enable_tim_callback:
        new_val = round(float(val))

        # Lock to whole numbers
        enable_tim_callback = False
        widgets[key].set(new_val)
        enable_tim_callback = True

        TRANS_TIMER_DELAY.format(
            tim='∞' if new_val == 0 else str(new_val),
        ).apply(labels[key])

        if new_val > values[key]:
            sound.fx_blockable('add')
        elif new_val < values[key]:
            sound.fx_blockable('subtract')
        values[key] = new_val
        out_values[key] = str(new_val)


def save_pist(key: str, val: str) -> None:
    """The top and bottom positions are closely interrelated."""
    global enable_pist_callback
    if not enable_pist_callback:
        return
    try:
        top_wid: ttk.Scale = widgets['toplevel']
        btm_wid: ttk.Scale = widgets['bottomlevel']
    except KeyError:
        return  # Both don't exist yet.

    # The ttk Scale widget doesn't snap to integers, so we need to do that.
    prev_top = top_wid.get()
    new_top = round(prev_top)
    prev_btm = btm_wid.get()
    new_btm = round(prev_btm)

    enable_pist_callback = False
    top_wid.set(new_top)
    btm_wid.set(new_btm)
    enable_pist_callback = True

    if top_wid.get() == btm_wid.get():
        # user moved them to match, switch the other one around
        sound.fx_blockable('swap')
        (top_wid if key == 'bottomlevel' else btm_wid).set(values[key])
    elif prev_top != new_top or prev_btm != new_btm:
        # Only play when we've actually changed.
        sound.fx_blockable('move')

    values['toplevel'] = start_pos = int(top_wid.get())
    values['bottomlevel'] = end_pos = int(btm_wid.get())

    values['startup'] = srctools.bool_as_int(start_pos > end_pos)
    out_values['toplevel'] = str(max(start_pos, end_pos))
    out_values['bottomlevel'] = str(min(start_pos, end_pos))


def save_rail(key) -> None:
    """Rail oscillation prevents Start Active from having any effect."""
    if values[key].get() == 0:
        widgets['startactive'].state(['disabled'])
        values['startactive'].set(False)
    else:
        widgets['startactive'].state(['!disabled'])


def toggle_check(key: str, var: tk.IntVar, _: tk.Event=None) -> None:
    """Toggle a checkbox."""
    if var.get():
        var.set(0)
    else:
        var.set(1)
    set_check(key)


def set_check(key: str) -> None:
    """Generic change callback for checkboxes."""
    sound.fx_blockable('config')
    out_values[key] = str(values[key].get())


def exit_win(_: tk.Event=None) -> None:
    """Quit and save the new settings."""
    win.grab_release()
    win.withdraw()
    out = {}
    for key in propList:
        if key in PROP_TYPES:
            # Use out_values if it has a matching key,
            # or use values by default.
            out_val = out_values.get(key, values[key])
            if isinstance(out_val, tk.Variable):
                out[key] = str(out_val.get())
            else:
                out[key] = out_val
    callback(out)

    if contextWin.is_visible():
        # Restore the context window if we hid it earlier.
        contextWin.window.deiconify()


def can_edit(prop_list: Iterator[str]) -> bool:
    """Determine if any of these properties are changeable."""
    for prop in prop_list:
        prop_type, prop_name = PROP_TYPES.get(prop, (PropTypes.NONE, ''))
        if prop_type.is_editable:
            return True
    return False


def init(cback: Callable[[dict[str, str]], None]) -> None:
    """Build the properties window widgets."""
    global callback
    callback = cback

    win.title("BEE2")
    win.resizable(False, False)
    tk_tools.set_window_icon(win)
    win.protocol("WM_DELETE_WINDOW", exit_win)

    if utils.MAC:
        # Switch to use the 'modal' window style on Mac.
        TK_ROOT.call(
            '::tk::unsupported::MacWindowStyle',
            'style',
            win,
            'moveableModal',
            ''
        )
    # Stop our init from triggering UI sounds.
    sound.block_fx()

    frame = ttk.Frame(win, padding=10)
    frame.grid(row=0, column=0, sticky='NSEW')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    labels['noOptions'] = ttk.Label(frame)
    TransToken.ui('No Properties available!').apply(labels['noOptions'])
    widgets['saveButton'] = ttk.Button(frame, command=exit_win)
    TransToken.ui('Close').apply(widgets['saveButton'])
    widgets['titleLabel'] = ttk.Label(frame, text='')
    widgets['titleLabel'].grid(columnspan=9)

    widgets['div_1'] = ttk.Separator(frame, orient="vertical")
    widgets['div_2'] = ttk.Separator(frame, orient="vertical")
    widgets['div_h'] = ttk.Separator(frame, orient="horizontal")

    for key, (prop_type, prop_name) in PROP_TYPES.items():
        labels[key] = ttk.Label(frame)
        TRANS_LABEL.format(name=prop_name).apply(labels[key])
        if prop_type is PropTypes.CHECKBOX:
            values[key] = tk.IntVar(value=DEFAULTS[key])
            out_values[key] = srctools.bool_as_int(DEFAULTS[key])
            widgets[key] = ttk.Checkbutton(
                frame,
                variable=values[key],
                command=func_partial(set_check, key),
                )
            widgets[key].bind(
                '<Return>',
                func_partial(
                    toggle_check,
                    key,
                    values[key],
                    )
                )

        elif prop_type is PropTypes.OSCILLATE:
            values[key] = tk.IntVar(value=DEFAULTS[key])
            out_values[key] = srctools.bool_as_int(DEFAULTS[key])
            widgets[key] = ttk.Checkbutton(
                frame,
                variable=values[key],
                command=func_partial(save_rail, key),
            )

        elif prop_type is PropTypes.PANEL:
            frm = ttk.Frame(frame)
            widgets[key] = frm
            values[key] = tk.StringVar(value=DEFAULTS[key])
            for pos, (angle, disp_angle) in enumerate(PANEL_ANGLES):
                ttk.Radiobutton(
                    frm,
                    variable=values[key],
                    value=str(angle),
                    text=gameMan.translate(disp_angle),
                    command=func_partial(save_angle, key, angle),
                ).grid(row=0, column=pos)
                frm.columnconfigure(pos, weight=1)

        elif prop_type is PropTypes.GELS:
            frm = ttk.Frame(frame)
            widgets[key] = frm
            values[key] = tk.IntVar(value=DEFAULTS[key])
            for pos, text in enumerate(PAINT_OPTS):
                ttk.Radiobutton(
                    frm,
                    variable=values[key],
                    value=pos,
                    text=gameMan.translate(text),
                    command=func_partial(save_paint, key, pos),
                ).grid(row=0, column=pos)
                frm.columnconfigure(pos, weight=1)
            out_values[key] = str(DEFAULTS[key])

        elif prop_type is PropTypes.PISTON:
            widgets[key] = pist_scale = ttk.Scale(
                frame,
                from_=0,
                to=4,
                orient="horizontal",
                command=func_partial(save_pist, key),
            )
            values[key] = DEFAULTS[key]
            out_values[key] = str(DEFAULTS[key])
            if ((key == 'toplevel' and DEFAULTS['startup']) or
                    (key == 'bottomlevel' and not DEFAULTS['startup'])):
                pist_scale.set(max(
                    DEFAULTS['toplevel'],
                    DEFAULTS['bottomlevel']
                    ))
            if ((key == 'toplevel' and not DEFAULTS['startup']) or
                    (key == 'bottomlevel' and DEFAULTS['startup'])):
                pist_scale.set(min(
                    DEFAULTS['toplevel'],
                    DEFAULTS['bottomlevel']))

        elif prop_type is PropTypes.TIMER:
            widgets[key] = ttk.Scale(
                frame,
                from_=0,
                to=30,
                orient="horizontal",
                command=func_partial(save_tim, key),
                )
            values[key] = DEFAULTS[key]

    values['startup'] = DEFAULTS['startup']


def show_window(used_props: dict[str, str], parent: tk.Toplevel, item_name: str) -> None:
    """Show the item property changing window."""
    global last_angle
    propList[:] = [key.casefold() for key in used_props]
    spec_row = 1

    start_up = srctools.conv_bool(used_props.get('startup', '0'))
    values['startup'] = start_up
    for prop, value in used_props.items():
        if prop not in PROP_TYPES:
            LOGGER.info('Unknown property type {}', prop)
            continue
        if value is None:
            continue

        prop_type = PROP_TYPES[prop][0]
        if prop_type is PropTypes.CHECKBOX:
            values[prop].set(srctools.conv_bool(value))
        elif prop_type is PropTypes.OSCILLATE:
            values[prop].set(srctools.conv_bool(value))
            save_rail(prop)
        elif prop_type is PropTypes.GELS:
            values[prop].set(value)
        elif prop_type is PropTypes.PANEL:
            last_angle = int(value[5:7])
            values[prop].set(last_angle)
            out_values[prop] = value
        elif prop_type is PropTypes.PISTON:
            values[prop] = value
            try:
                top_level = int(used_props.get('toplevel', 4))
                bot_level = int(used_props.get('bottomlevel', 0))
            except ValueError:
                pass
            else:
                if ((prop == 'toplevel' and start_up) or
                        (prop == 'bottomlevel' and not start_up)):
                    widgets[prop].set(max(top_level, bot_level))
                if ((prop == 'toplevel' and not start_up) or
                        (prop == 'bottomlevel' and start_up)):
                    widgets[prop].set(min(top_level, bot_level))
        elif prop_type is PropTypes.TIMER:
            try:
                values[prop] = int(value)
                widgets[prop].set(values[prop])
            except ValueError:
                pass
        elif not prop_type.is_editable:
            # Internal or subtype properties, just pass through unchanged.
            values[prop] = value
        else:
            LOGGER.error('Bad prop_type ({}) for {}', prop_type, prop)

    for key in PROP_POS_SPECIAL:
        if key in propList:
            labels[key].grid(
                row=spec_row,
                column=0,
                sticky='e',
                padx=2,
                pady=5,
            )
            widgets[key].grid(
                row=spec_row,
                column=1,
                sticky="EW",
                padx=2,
                pady=5,
                columnspan=9,
                )
            spec_row += 1
        else:
            labels[key].grid_remove()
            widgets[key].grid_remove()
    # if we have a 'special' prop, add the divider between the types
    if spec_row > 1:
        widgets['div_h'].grid(
            row=spec_row + 1,
            columnspan=9,
            sticky="EW",
            )
        spec_row += 2
    else:
        widgets['div_h'].grid_remove()
    ind = 0

    for key in PROP_POS:
        # Position each widget
        if key in propList:
            labels[key].grid(
                row=(ind // 3) + spec_row,
                column=(ind % 3) * 3,
                sticky=tk.E,
                padx=2,
                pady=5,
                )
            widgets[key].grid(
                row=(ind // 3) + spec_row,
                column=(ind % 3)*3 + 1,
                sticky="ew",
                padx=2,
                pady=5,
                )
            ind += 1
        else:
            labels[key].grid_remove()
            widgets[key].grid_remove()

    if ind > 1:  # is there more than 1 checkbox? (add left divider)
        widgets['div_1'].grid(
            row=spec_row,
            column=2,
            sticky="ns",
            rowspan=(ind//3) + 1
            )
    else:
        widgets['div_1'].grid_remove()

    if ind > 2:  # are there more than 2 checkboxes? (add right divider)
        widgets['div_2'].grid(
            row=spec_row,
            column=5,
            sticky="NS",
            rowspan=(ind//3) + 1,
            )
    else:
        widgets['div_2'].grid_remove()

    if ind + spec_row == 1:
        # There aren't any items, display error message
        labels['noOptions'].grid(row=1, columnspan=9)
        ind = 1
    else:
        labels['noOptions'].grid_remove()

    widgets['saveButton'].grid(
        row=ind + spec_row,
        columnspan=9,
        sticky="EW",
        )

    # Block sound for the first few millisec to stop excess sounds from
    # playing
    sound.block_fx()

    TRANS_TITLE.format(item=item_name).apply_title(win)
    TRANS_SUBTITLE.format(item=item_name).apply(widgets['titleLabel'])
    win.deiconify()
    win.lift(parent)
    win.grab_set()
    win.attributes("-topmost", True)
    win.geometry(
        f'+{str(parent.winfo_rootx() - 30)}'
        f'+{str(parent.winfo_rooty() - win.winfo_reqheight() - 30)}'
        )

    if contextWin.is_visible():
        # Temporarily hide the context window while we're open.
        contextWin.window.withdraw()


# load the window if directly executing this file
if __name__ == '__main__':
    TK_ROOT.geometry('+250+250')

    def callback(props: dict[str, str]) -> None:
        for key, value in sorted(props.items()):
            print(key + ' = ' + repr(value))

    init(callback)
    all_vals = {
        'startup': '1',
        'toplevel': '4',
        'bottomlevel': '3',
        'angledpanelanimation': 'ramp_45_deg_open',
        'startenabled': '1',
        'startreversed': '0',
        'startdeployed': '1',
        'startactive': '1',
        'startopen': '1',
        'startlocked': '0',
        'timerdelay': '15',
        'dropperenabled': '1',
        'autodrop': '1',
        'autorespawn': '1',
        'oscillate': '0',
        'paintflowtype': '1',
        'allowstreak': '1'
        }
    show_window(all_vals, TK_ROOT, "TestItemWithEveryProp")
