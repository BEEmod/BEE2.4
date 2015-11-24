from tkinter import *
from tk_tools import TK_ROOT
from tkinter import ttk

from collections import namedtuple
import functools
import operator

import img as png

from BEE2_config import GEN_OPTS
from SubPane import SubPane
import tooltip
import utils

stylevar = namedtuple('stylevar', 'id name enabled desc')

# Special StyleVars that are hardcoded into the BEE2
# These are effectively attributes of Portal 2 itself, and always work
# in every style.
styleOptions = [
    # ID, Name, default value
    stylevar(
        id='MultiverseCave',
        name='Multiverse Cave',
        enabled=1,
        desc='Play the Workshop Cave Johnson lines on map start.'
    ),

    stylevar(
        id='FixPortalBump',
        name='Prevent Portal Bump  (glass)',
        enabled=0,
        desc='Add portal bumpers to make it more difficult to portal through '
             'glass panes.'
    ),

    stylevar(
        id='FixFizzlerBump',
        name='Prevent Portal Bump  (fizzler)',
        enabled=0,
        desc='Add portal bumpers to make it more difficult to portal across '
             'fizzler edges. This can prevent placing portals in tight spaces '
             'near fizzlers, or fizzle portals on activation.'
    ),

    stylevar(
        id='NoMidVoices',
        name='Suppress Mid-Chamber Dialogue',
        enabled=0,
        desc='Disable all voicelines other than entry and exit lines.'
    ),

    stylevar(
        id='UnlockDefault',
        name='Unlock Default Items',
        enabled=0,
        desc='Allow placing and deleting the mandatory Entry/Exit Doors and '
             'Large Observation Room. Use with caution, this can have weird '
             'results!'
    ),

    stylevar(
        id='AllowGooMist',
        name='Allow Adding Goo Mist',
        enabled=1,
        desc='Add mist particles above Toxic Goo in certain styles. This can '
             'increase the entity count significantly with large, complex '
             'goo pits, so disable if needed.'
    ),
]

checkbox_special = {}
checkbox_chosen = {}
checkbox_other = {}
tk_vars = {}

var_list = []

window = None

UI = {}


def update_filter():
    pass


def add_vars(data):
    """
    Add the given stylevars to our list.

    """
    global var_list
    var_list = sorted(data, key=operator.attrgetter('id'))

    for var in var_list:
        var.default = GEN_OPTS.get_bool('StyleVar', var.id, var.default)


def set_stylevar(var):
    """Save the value for a particular stylevar."""
    val = str(tk_vars[var].get())
    GEN_OPTS['StyleVar'][var] = val
    if var == 'UnlockDefault':
        update_filter()


def refresh(selected_style):
    """Move the stylevars to the correct position.

    This depends on which apply to the current style.
    """
    en_row = 0
    dis_row = 0
    for var in var_list:
        if var.applies_to_style(selected_style):
            checkbox_chosen[var.id].grid(
                row=en_row,
                sticky="W",
                padx=3,
            )
            checkbox_other[var.id].grid_remove()
            en_row += 1
        else:
            checkbox_chosen[var.id].grid_remove()
            checkbox_other[var.id].grid(
                row=dis_row,
                sticky="W",
                padx=3,
            )
            dis_row += 1
    if en_row == 0:
        UI['stylevar_chosen_none'].grid(sticky='EW')
    else:
        UI['stylevar_chosen_none'].grid_remove()

    if dis_row == 0:
        UI['stylevar_other_none'].grid(sticky='EW')
    else:
        UI['stylevar_other_none'].grid_remove()


def flow_stylevar(e=None):
    UI['style_can']['scrollregion'] = UI['style_can'].bbox(ALL)


def make_pane(tool_frame):
    """Create the styleVar pane.

    """
    global window
    window = SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Style Properties',
        name='style',
        resize_y=True,
        tool_frame=tool_frame,
        tool_img=png.png('icons/win_stylevar'),
        tool_col=3,
    )

    UI['style_can'] = Canvas(window, highlightthickness=0)
    # need to use a canvas to allow scrolling
    UI['style_can'].grid(sticky='NSEW')
    window.rowconfigure(0, weight=1)

    UI['style_scroll'] = ttk.Scrollbar(
        window,
        orient=VERTICAL,
        command=UI['style_can'].yview,
        )
    UI['style_scroll'].grid(column=1, row=0, rowspan=2, sticky="NS")
    UI['style_can']['yscrollcommand'] = UI['style_scroll'].set

    utils.add_mousewheel(UI['style_can'], window)

    canvas_frame = ttk.Frame(UI['style_can'])

    frame_all = ttk.Labelframe(canvas_frame, text="All:")
    frame_all.grid(row=0, sticky='EW')

    frm_chosen = ttk.Labelframe(canvas_frame, text="Selected Style:")
    frm_chosen.grid(row=1, sticky='EW')

    ttk.Separator(
        canvas_frame,
        orient=HORIZONTAL,
        ).grid(row=2, sticky='EW', pady=(10, 5))

    frm_other = ttk.Labelframe(canvas_frame, text="Other Styles:")
    frm_other.grid(row=3, sticky='EW')

    UI['stylevar_chosen_none'] = ttk.Label(
        frm_chosen,
        text='No Options!',
        font='TkMenuFont',
        justify='center',
        )
    UI['stylevar_other_none'] = ttk.Label(
        frm_other,
        text='None!',
        font='TkMenuFont',
        justify='center',
        )

    for pos, var in enumerate(styleOptions):
        # Add the special stylevars which apply to all styles
        tk_vars[var.id] = IntVar(
            value=GEN_OPTS.get_bool('StyleVar', var.id, var.enabled)
        )
        checkbox_special[var.id] = ttk.Checkbutton(
            frame_all,
            variable=tk_vars[var.id],
            text=var.name,
            command=functools.partial(set_stylevar, var.id)
            )
        checkbox_special[var.id].grid(row=pos, column=0, sticky="W", padx=3)

        if var.desc:
            tooltip.add_tooltip(
                checkbox_special[var.id],
                var.desc,
            )

    for var in var_list:
        tk_vars[var.id] = IntVar(value=var.default)
        args = {
            'variable': tk_vars[var.id],
            'text': var.name,
            'command': functools.partial(set_stylevar, var.id)
            }
        checkbox_chosen[var.id] = ttk.Checkbutton(frm_chosen, **args)
        checkbox_other[var.id] = ttk.Checkbutton(frm_other, **args)
        if var.desc:
            tooltip.add_tooltip(
                checkbox_chosen[var.id],
                var.desc,
            )
            tooltip.add_tooltip(
                checkbox_other[var.id],
                var.desc,
            )

    UI['style_can'].create_window(0, 0, window=canvas_frame, anchor="nw")
    UI['style_can'].update_idletasks()
    UI['style_can'].config(
        scrollregion=UI['style_can'].bbox(ALL),
        width=canvas_frame.winfo_reqwidth(),
    )

    if utils.USE_SIZEGRIP:
        ttk.Sizegrip(
            window,
            cursor=utils.CURSORS['stretch_vert'],
        ).grid(row=1, column=0)

    UI['style_can'].bind('<Configure>', flow_stylevar)