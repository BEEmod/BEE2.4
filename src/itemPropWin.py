#coding: utf-8
from tkinter import *  # ui library
from tk_tools import TK_ROOT
from tkinter import ttk  # themed ui components that match the OS
from functools import partial as func_partial
import math
import random

import sound as snd
import utils
import contextWin

# all editable properties in editoritems, Valve probably isn't going to
# release a major update so it's fine to hardcode this.
PROP_TYPES = {
    'toplevel':                 ('pistPlat', 'Start Position'),
    'bottomlevel':              ('pistPlat', 'End Position'),
    'angledpanelanimation':     ('panAngle', 'Panel Position'),
    'startenabled':             ('checkbox', 'Start Enabled'),
    'startreversed':            ('checkbox', 'Start Reversed'),
    'startdeployed':            ('checkbox', 'Start Deployed'),
    'startactive':              ('checkbox', 'Start Active'),
    'startopen':                ('checkbox', 'Start Open'),
    'startlocked':              ('checkbox', 'Start Locked'),
    'timerdelay':               ('timerDel', 'Delay \n(0=infinite)'),
    'dropperenabled':           ('checkbox', 'Dropper Enabled'),
    'autodrop':                 ('checkbox', 'Auto Drop'),
    'autorespawn':              ('checkbox', 'Auto Respawn'),
    'oscillate':                ('railLift', 'Oscillate'),
    'paintflowtype':            ('gelType',  'Flow Type'),
    'allowstreak':              ('checkbox', 'Allow Streaks'),
    }
# valid property types:
#  checkbox, timerDel, pistPlat, gelType, panAngle, railLift

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

widgets = {}  # holds the checkbox or other item used to manipulate the box
labels = {}  # holds the descriptive labels for each property

propList = []

values = {}  # selected values for this items
out_values = {}

PAINT_OPTS = [
    'Light',
    'Medium',
    'Heavy',
    'Drip',
    'Bomb'
    ]

DEFAULTS = { # default values for this item
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

play_sound = False
is_open = False
enable_tim_callback = True


def callback(name):
    """Do nothing by default!"""
    pass


def reset_sfx():
    global play_sound
    play_sound = True


def sfx(sound):
    """Play a sound effect.

    This waits for a certain amount of time between retriggering sounds
    so they don't overlap.
    """
    global play_sound
    if play_sound is True:
        snd.fx(sound)
        play_sound = False
        win.after(75, reset_sfx)


def scroll_angle(key, e):
    if e.delta > 0 and widgets[key].get() != '90':
        e.widget.invoke('buttonup')
    elif e.delta < 0 and widgets[key].get() != '0':
        e.widget.invoke('buttondown')


def save_paint(key, val):
    sfx('config')
    out_values[key] = val


def save_angle(key, new_angle):
    global last_angle
    if new_angle > last_angle:
        sfx('raise_' + random.choice('123'))
    elif new_angle < last_angle:
        sfx('lower_' + random.choice('123'))
    last_angle = new_angle
    out_values[key] = 'ramp_' + str(new_angle) + '_deg_open'


def save_tim(key, val):
    global enable_tim_callback
    if enable_tim_callback:
        new_val = math.floor(float(val) + 0.5)

        enable_tim_callback = False
        widgets[key].set(new_val)
        # Lock to whole numbers
        enable_tim_callback = True

        labels[key]['text'] = (
            'Timer Delay:\n        ({})'.format(
                '∞' if new_val == 0 else str(new_val))
        )

        if new_val > values[key]:
            sfx('add')
        elif new_val < values[key]:
            sfx('subtract')
        values[key] = new_val
        out_values[key] = str(new_val)


def save_pist(key, val):
    if widgets['toplevel'].get() == widgets['bottomlevel'].get():
        # user moved them to match, switch the other one around
        sfx('swap')
        widgets[
            'toplevel' if key == 'bottomlevel' else 'bottomlevel'
            ].set(values[key])
    else:
        sfx('move')

    start_pos = widgets['toplevel'].get()
    end_pos = widgets['bottomlevel'].get()

    values['toplevel'] = start_pos
    values['bottomlevel'] = end_pos

    values['startup'] = utils.bool_as_int(start_pos > end_pos)
    out_values['toplevel'] = str(max(start_pos, end_pos))
    out_values['bottomlevel'] = str(min(start_pos, end_pos))


def save_rail(key):
    if values[key].get() == 0:
        widgets['startactive'].state(['disabled'])
        values['startactive'].set(False)
    else:
        widgets['startactive'].state(['!disabled'])


def toggleCheck(key, var, e=None):
    if var.get():
        var.set(0)
    else:
        var.set(1)
    set_check(key)


def set_check(key):
    sfx('config')
    out_values[key] = str(values[key].get())


def paint_fx(e=None):
    sfx('config')


def exit_win(_=None):
    "Quit and return the new settings."
    global is_open
    win.grab_release()
    win.withdraw()
    is_open = False
    out = {}
    for key in propList:
        if key in PROP_TYPES:
            # Use out_values if it has a matching key,
            # or use values by default.
            out[key] = out_values.get(key, values[key])
    callback(out)

    if contextWin.is_open:
        # Restore the context window if we hid it earlier.
        contextWin.prop_window.deiconify()


def can_edit(prop_list):
    """Determine if any of these properties are changeable."""
    for prop in prop_list:
        if prop in PROP_TYPES:
            return True
    return False


def init(cback):
    global callback, labels, win, is_open
    callback = cback
    is_open = False
    win = Toplevel(TK_ROOT)
    win.title("BEE2")
    win.resizable(False, False)
    win.iconbitmap('../BEE2.ico')
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

    frame = ttk.Frame(win, padding=10)
    frame.grid(row=0, column=0, sticky='NSEW')
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)

    labels['noOptions'] = ttk.Label(frame, text='No Properties avalible!')
    widgets['saveButton'] = ttk.Button(frame, text='Close', command=exit_win)
    widgets['titleLabel'] = ttk.Label(frame, text='')
    widgets['titleLabel'].grid(columnspan=9)

    widgets['div_1'] = ttk.Separator(frame, orient="vertical")
    widgets['div_2'] = ttk.Separator(frame, orient="vertical")
    widgets['div_h'] = ttk.Separator(frame, orient="horizontal")

    for key, (prop_type, prop_name) in PROP_TYPES.items():
        labels[key] = ttk.Label(frame, text=prop_name+':')
        if prop_type == 'checkbox':
            values[key] = IntVar(value=DEFAULTS[key])
            out_values[key] = utils.bool_as_int(DEFAULTS[key])
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

        elif prop_type == 'railLift':
            values[key] = IntVar(value=DEFAULTS[key])
            out_values[key] = utils.bool_as_int(DEFAULTS[key])
            widgets[key] = ttk.Checkbutton(
                frame,
                variable=values[key],
                command=func_partial(save_rail, key),
                )

        elif prop_type == 'panAngle':
            frm = ttk.Frame(frame)
            widgets[key] = frm
            values[key] = StringVar(value=DEFAULTS[key])
            for pos, angle in enumerate(['30', '45', '60', '90']):
                ttk.Radiobutton(
                    frm,
                    variable=values[key],
                    value=angle,
                    text=angle,
                    command=func_partial(save_angle, key, angle),
                    ).grid(row=0, column=pos)
                frm.columnconfigure(pos, weight=1)

        elif prop_type == 'gelType':
            frm = ttk.Frame(frame)
            widgets[key] = frm
            values[key] = IntVar(value=DEFAULTS[key])
            for pos, text in enumerate(PAINT_OPTS):
                ttk.Radiobutton(
                    frm,
                    variable=values[key],
                    value=pos,
                    text=text,
                    command=func_partial(save_paint, key, pos),
                    ).grid(row=0, column=pos)
                frm.columnconfigure(pos, weight=1)
            out_values[key] = str(DEFAULTS[key])

        elif prop_type == 'pistPlat':
            widgets[key] = Scale(
                frame,
                from_=0,
                to=4,
                orient="horizontal",
                showvalue=False,
                command=func_partial(save_pist, key),
                )
            values[key] = DEFAULTS[key]
            out_values[key] = str(DEFAULTS[key])
            if ((key == 'toplevel' and DEFAULTS['startup']) or
                    (key == 'bottomlevel' and not DEFAULTS['startup'])):
                widgets[key].set(max(
                    DEFAULTS['toplevel'],
                    DEFAULTS['bottomlevel']
                    ))
            if ((key == 'toplevel' and not DEFAULTS['startup']) or
                    (key == 'bottomlevel' and DEFAULTS['startup'])):
                widgets[key].set(min(
                    DEFAULTS['toplevel'],
                    DEFAULTS['bottomlevel']))

        elif prop_type == 'timerDel':
            widgets[key] = ttk.Scale(
                frame,
                from_=0,
                to=30,
                orient="horizontal",
                command=func_partial(save_tim, key),
                )
            values[key] = DEFAULTS[key]

        elif prop_type == 'railPlat':
            widgets[key] = ttk.Checkbutton(frame)
    values['startup'] = DEFAULTS['startup']


def show_window(used_props, parent, item_name):
    global propList, is_open, block_sound, last_angle
    propList = [key.casefold() for key in used_props]
    is_open = True
    spec_row = 1

    start_up = utils.conv_bool(used_props.get('startup', '0'))
    values['startup'] = start_up
    for prop, value in used_props.items():
        if prop in PROP_TYPES and value is not None:
            prop_type = PROP_TYPES[prop][0]
            if prop_type == 'checkbox':
                values[prop].set(utils.conv_bool(value))
            elif prop_type == 'railLift':
                values[prop].set(utils.conv_bool(value))
                save_rail(prop)
            elif prop_type == 'gelType':
                values[prop].set(value)
            elif prop_type == 'panAngle':
                last_angle = value[5:7]
                values[prop].set(last_angle)
                out_values[prop] = value
            elif prop_type == 'pistPlat':
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
            elif prop_type == 'timerDel':
                try:
                    values[prop] = int(value)
                    widgets[prop].set(values[prop])
                except ValueError:
                    pass
            else:
                values[prop] = value

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
    block_sound = False
    win.after(50, reset_sfx)

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
        contextWin.prop_window.withdraw()


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
