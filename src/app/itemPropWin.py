from tkinter import *  # ui library

from tkinter import ttk  # themed ui components that match the OS
from functools import partial as func_partial
from enum import Enum
import random

import utils
import srctools
from app import contextWin, gameMan, tk_tools, sound, TK_ROOT
import srctools.logger

from typing import Dict, List, Union, Any

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

# All properties in editoritems, Valve probably isn't going to
# release a major update so it's fine to hardcode this.
PROP_TYPES = {
    'toplevel':                 (PropTypes.PISTON, _('Start Position')),
    'bottomlevel':              (PropTypes.PISTON, _('End Position')),
    'timerdelay':               (PropTypes.TIMER, _('Delay \n(0=infinite)')),
    'angledpanelanimation':     (PropTypes.PANEL, 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type'),
    'paintflowtype':            (PropTypes.GELS,  'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type'),

    'oscillate':                (PropTypes.OSCILLATE, 'PORTAL2_PuzzleEditor_ContextMenu_rail_oscillate'),
    'startenabled':             (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_start_enabled'),
    'startreversed':            (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_start_reversed'),
    'startdeployed':            (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_start_deployed'),
    'startactive':              (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_rail_start_active'),
    'startopen':                (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_start_open'),
    'startlocked':              (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_coop_exit_starts_locked'),
    'dropperenabled':           (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_dropper_enabled'),
    'autodrop':                 (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_auto_drop_cube'),
    'autorespawn':              (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_auto_respawn_cube'),
    'allowstreak':              (PropTypes.CHECKBOX,  'PORTAL2_PuzzleEditor_ContextMenu_allow_streak_paint'),

    # Properties that we don't allow modification of.
    'timersound': (PropTypes.NONE, 'Timer Sound'),
    'angledpaneltype': (PropTypes.NONE, 'Angled Panel Type'),
    'itemfallstraightdown': (PropTypes.NONE, 'Disable Cube Dropper Clips'),
    'paintexporttype': (PropTypes.NONE, 'Gel Export Type'),
    'autotrigger': (PropTypes.NONE, 'Automatically Move'),

    'connectioncount': (PropTypes.NONE, 'Connection Count'),
    'connectioncountpolarity': (PropTypes.NONE, 'Polarity Connection Count'),
    'coopdoor': (PropTypes.NONE, 'Is Coop?'),
    'portalable': (PropTypes.NONE, 'Flip Panel Portalability'),
    'speed': (PropTypes.NONE, 'Track Platform Speed'),
    'startingposition': (PropTypes.NONE, 'Initial Track Platform Position'),
    'traveldirection': (PropTypes.NONE, 'Track Platform Direction'),
    'traveldistance': (PropTypes.NONE, 'Track Platform Distance'),

    # Controlled by bottom and top position, not set separately.
    'startup': (PropTypes.NONE, 'Start Up'),

    # Faith Plate
    'verticalalignment': (PropTypes.NONE, 'Vertical Alignment'),
    'catapultspeed': (PropTypes.NONE, 'Faith Plate Speed'),
    'targetname': (PropTypes.NONE, 'Faith Target Name'),

    'cubetype': (PropTypes.SUB_TYPE, 'Cube Type'),
    'hazardtype': (PropTypes.SUB_TYPE, 'Fizzler Type'),
    'barriertype': (PropTypes.SUB_TYPE, 'Barrier Type'),
    'buttontype': (PropTypes.SUB_TYPE, 'Button Type'),
    'painttype': (PropTypes.SUB_TYPE, 'Gel Type'),
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
widgets = {}  # type: Dict[str, Any]
# holds the descriptive labels for each property
labels = {}  # type: Dict[str, ttk.Label]

# The properties we currently have displayed.
propList = []  # type: List[str]

# selected values for this items
values = {}  # type: Dict[str, Union[Variable, str, float]]
out_values = {}  # type: Dict[str, Union[Variable, str, float]]

PAINT_OPTS = [
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_light',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_medium',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_heavy',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_drip',
    'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_bomb',
    ]

PANEL_ANGLES = [
    ('30', 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_30'),
    ('45', 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_45'),
    ('60', 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_60'),
    ('90', 'PORTAL2_PuzzleEditor_ContextMenu_angled_panel_type_90'),
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

last_angle = '0'

is_open = False
# ttk.Scale works on floating point values,
# so it can be put partway. We need to suppress calling our callbacks
# whilst we fix it.
enable_tim_callback = True
enable_pist_callback = True


def callback(name):
    """Do nothing by default!"""
    pass


def scroll_angle(key, e):
    if e.delta > 0 and widgets[key].get() != '90':
        e.widget.invoke('buttonup')
    elif e.delta < 0 and widgets[key].get() != '0':
        e.widget.invoke('buttondown')


def save_paint(key, val):
    sound.fx_blockable('config')
    out_values[key] = val


def save_angle(key, new_angle):
    global last_angle
    if new_angle > last_angle:
        sound.fx_blockable('raise_' + random.choice('123'))
    elif new_angle < last_angle:
        sound.fx_blockable('lower_' + random.choice('123'))
    last_angle = new_angle
    out_values[key] = 'ramp_' + str(new_angle) + '_deg_open'


def save_tim(key, val):
    global enable_tim_callback
    if enable_tim_callback:
        new_val = round(float(val))

        # Lock to whole numbers
        enable_tim_callback = False
        widgets[key].set(new_val)
        enable_tim_callback = True

        labels[key]['text'] = (
            'Timer Delay:\n        ({})'.format(
                '∞' if new_val == 0 else str(new_val))
        )

        if new_val > values[key]:
            sound.fx_blockable('add')
        elif new_val < values[key]:
            sound.fx_blockable('subtract')
        values[key] = new_val
        out_values[key] = str(new_val)


def save_pist(key, val):
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


def toggleCheck(key, var, e=None):
    """Toggle a checkbox."""
    if var.get():
        var.set(0)
    else:
        var.set(1)
    set_check(key)


def set_check(key):
    sound.fx_blockable('config')
    out_values[key] = str(values[key].get())


def exit_win(e=None) -> None:
    """Quit and save the new settings."""
    global is_open
    win.grab_release()
    win.withdraw()
    is_open = False
    out = {}
    for key in propList:
        if key in PROP_TYPES:
            # Use out_values if it has a matching key,
            # or use values by default.
            out_val = out_values.get(key, values[key])
            if isinstance(out_val, Variable):
                out[key] = str(out_val.get())
            else:
                out[key] = out_val
    callback(out)

    if contextWin.is_open:
        # Restore the context window if we hid it earlier.
        contextWin.window.deiconify()


def can_edit(prop_list):
    """Determine if any of these properties are changeable."""
    for prop in prop_list:
        prop_type, prop_name = PROP_TYPES.get(prop, (PropTypes.NONE, ''))
        if prop_type.is_editable:
            return True
    return False


def init(cback):
    global callback, labels, win, is_open
    callback = cback
    is_open = False
    win = Toplevel(TK_ROOT)
    win.title("BEE2")
    win.resizable(False, False)
    tk_tools.set_window_icon(win)
    win.protocol("WM_DELETE_WINDOW", exit_win)
    win.transient(TK_ROOT)
    win.withdraw()

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

    labels['noOptions'] = ttk.Label(frame, text=_('No Properties available!'))
    widgets['saveButton'] = ttk.Button(frame, text=_('Close'), command=exit_win)
    widgets['titleLabel'] = ttk.Label(frame, text='')
    widgets['titleLabel'].grid(columnspan=9)

    widgets['div_1'] = ttk.Separator(frame, orient="vertical")
    widgets['div_2'] = ttk.Separator(frame, orient="vertical")
    widgets['div_h'] = ttk.Separator(frame, orient="horizontal")

    for key, (prop_type, prop_name) in PROP_TYPES.items():
        # Translate property names from Valve's files.
        if prop_name.startswith('PORTAL2_'):
            prop_name = gameMan.translate(prop_name) + ':'

        labels[key] = ttk.Label(frame, text=prop_name)
        if prop_type is PropTypes.CHECKBOX:
            values[key] = IntVar(value=DEFAULTS[key])
            out_values[key] = srctools.bool_as_int(DEFAULTS[key])
            widgets[key] = ttk.Checkbutton(
                frame,
                variable=values[key],
                command=func_partial(set_check, key),
                )
            widgets[key].bind(
                '<Return>',
                func_partial(
                    toggleCheck,
                    key,
                    values[key],
                    )
                )

        elif prop_type is PropTypes.OSCILLATE:
            values[key] = IntVar(value=DEFAULTS[key])
            out_values[key] = srctools.bool_as_int(DEFAULTS[key])
            widgets[key] = ttk.Checkbutton(
                frame,
                variable=values[key],
                command=func_partial(save_rail, key),
                )

        elif prop_type is PropTypes.PANEL:
            frm = ttk.Frame(frame)
            widgets[key] = frm
            values[key] = StringVar(value=DEFAULTS[key])
            for pos, (angle, disp_angle) in enumerate(PANEL_ANGLES):
                ttk.Radiobutton(
                    frm,
                    variable=values[key],
                    value=angle,
                    text=gameMan.translate(disp_angle),
                    command=func_partial(save_angle, key, angle),
                    ).grid(row=0, column=pos)
                frm.columnconfigure(pos, weight=1)

        elif prop_type is PropTypes.GELS:
            frm = ttk.Frame(frame)
            widgets[key] = frm
            values[key] = IntVar(value=DEFAULTS[key])
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


def show_window(used_props, parent, item_name):
    global is_open, last_angle
    propList[:] = [key.casefold() for key in used_props]
    is_open = True
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
            last_angle = value[5:7]
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
                    widgets[prop].set(
                        max(
                            top_level,
                            bot_level,
                            )
                        )
                if ((prop == 'toplevel' and not start_up) or
                        (prop == 'bottomlevel' and start_up)):
                    widgets[prop].set(
                        min(
                            top_level,
                            bot_level,
                            )
                        )
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
                sticky=E,
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
                sticky=E,
                padx=2,
                pady=5,
                )
            widgets[key].grid(
                row=(ind // 3) + spec_row,
                column=(ind % 3)*3 + 1,
                sticky="EW",
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
            sticky="NS",
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

    widgets['titleLabel'].configure(text='Settings for "' + item_name + '"')
    win.title('BEE2 - ' + item_name)
    win.deiconify()
    win.lift(parent)
    win.grab_set()
    win.attributes("-topmost", True)
    win.geometry(
        '+' + str(parent.winfo_rootx() - 30) +
        '+' + str(parent.winfo_rooty() - win.winfo_reqheight() - 30)
        )

    if contextWin.is_open:
        # Temporarily hide the context window while we're open.
        contextWin.window.withdraw()


# load the window if directly executing this file
if __name__ == '__main__':
    TK_ROOT.geometry('+250+250')

    def callback(vals):
        for key, value in sorted(vals.items()):
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
