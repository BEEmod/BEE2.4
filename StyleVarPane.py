from tkinter import *
from tk_root import TK_ROOT
from tkinter import ttk

import functools
import operator

import tkinter_png as png

from BEE2_config import GEN_OPTS
from SubPane import SubPane

# Special StyleVars that are hardcoded into the BEE2
# These are effectively attributes of Portal 2 itself, and always work
# in every style.
styleOptions = [
    # ID, Name, default value
    ('MultiverseCave', 'Multiverse Cave', 1),
    ('FixPortalBump', 'Prevent Portal Bump  (glass)', 0),
    ('FixFizzlerBump', 'Prevent Portal Bump  (fizzler)', 0),
    ('NoMidVoices', 'Suppress Mid-Chamber Dialogue', 0),
    ('UnlockDefault', 'Unlock Default Items', 0),
    ]

checkbox_special = {}
checkbox_chosen = {}
checkbox_other = {}
tk_vars = {}

var_list = []

window = None

UI = {}


def add_vars(data):
    '''
    Add the given stylevars to our list.

    '''
    global var_list
    var_list = sorted(data, key=operator.attrgetter('id'))

    for var in var_list:
        var.default = GEN_OPTS.get_bool('StyleVar', var.id, var.default)


def set_stylevar(var):
    '''Save the value for a particular stylevar.'''
    val = str(tk_vars[var].get())
    GEN_OPTS['StyleVar'][var] = val


def refresh(selected_style):
    '''Move the stylevars to the correct position.

    This depends on which apply to the current style.
    '''
    en_row = 0
    dis_row = 0
    for var in var_list:
        if selected_style in var.styles:
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
    '''Create the styleVar pane.

    '''
    global window
    window = SubPane(
        TK_ROOT,
        options=GEN_OPTS,
        title='Style Properties',
        name='style',
        resize_y=True,
        tool_frame=tool_frame,
        tool_img=png.loadPng('icons/win_style'),
        tool_col=2,
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

    for pos, (var_id, name, default) in enumerate(styleOptions):
        # Add the special stylevars which apply to all styles
        tk_vars[var_id] = IntVar(
            value=GEN_OPTS.get_bool('StyleVar', var_id, default)
        )
        checkbox_special[var_id] = ttk.Checkbutton(
            frame_all,
            variable=tk_vars[var_id],
            text=name,
            command=functools.partial(set_stylevar, var_id)
            )
        checkbox_special[var_id].grid(row=pos, column=0, sticky="W", padx=3)

    for var in var_list:
        tk_vars[var.id] = IntVar(value=var.default)
        args = {
            'variable': tk_vars[var.id],
            'text': var.name,
            'command': functools.partial(set_stylevar, var.id)
            }
        checkbox_chosen[var.id] = ttk.Checkbutton(frm_chosen, **args)
        checkbox_other[var.id] = ttk.Checkbutton(frm_other, **args)

    UI['style_can'].create_window(0, 0, window=canvas_frame, anchor="nw")
    UI['style_can'].update_idletasks()
    UI['style_can'].config(
        scrollregion=UI['style_can'].bbox(ALL),
        width=canvas_frame.winfo_reqwidth(),
        )
    ttk.Sizegrip(
        window,
        cursor="sb_v_double_arrow",
        ).grid(row=1, column=0)

    UI['style_can'].bind('<Configure>', flow_stylevar)