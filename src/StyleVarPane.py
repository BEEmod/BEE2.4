from tkinter import *
from tk_tools import TK_ROOT
from tkinter import ttk

from collections import namedtuple
import operator

from SubPane import SubPane
from srctools import Property
import packageLoader
import tooltip
import utils
import itemconfig
import BEE2_config
import img

from typing import Union, List, Dict


stylevar = namedtuple('stylevar', 'id name default desc')

# Special StyleVars that are hardcoded into the BEE2
# These are effectively attributes of Portal 2 itself, and always work
# in every style.
styleOptions = [
    # ID, Name, default value
    stylevar(
        id='MultiverseCave',
        name=_('Multiverse Cave'),
        default=1,
        desc=_('Play the Workshop Cave Johnson lines on map start.')
    ),

    stylevar(
        id='FixFizzlerBump',
        name=_('Prevent Portal Bump (fizzler)'),
        default=0,
        desc=_('Add portal bumpers to make it more difficult to portal across '
               'fizzler edges. This can prevent placing portals in tight '
               'spaces near fizzlers, or fizzle portals on activation.')
    ),

    stylevar(
        id='NoMidVoices',
        name=_('Suppress Mid-Chamber Dialogue'),
        default=0,
        desc=_('Disable all voicelines other than entry and exit lines.')
    ),

    stylevar(
        id='UnlockDefault',
        name=_('Unlock Default Items'),
        default=0,
        desc=_('Allow placing and deleting the mandatory Entry/Exit Doors and '
               'Large Observation Room. Use with caution, this can have weird '
               'results!')
    ),

    stylevar(
        id='AllowGooMist',
        name=_('Allow Adding Goo Mist'),
        default=1,
        desc=_('Add mist particles above Toxic Goo in certain styles. This can '
               'increase the entity count significantly with large, complex '
               'goo pits, so disable if needed.')
    ),

    stylevar(
        id='FunnelAllowSwitchedLights',
        name=_('Light Reversible Excursion Funnels'),
        default=1,
        desc=_('Funnels emit a small amount of light. However, if multiple funnels '
               'are near each other and can reverse polarity, this can cause '
               'lighting issues. Disable this to prevent that by disabling '
               'lights. Non-reversible Funnels do not have this issue.'),
    ),

    stylevar(
        id='EnableShapeSignageFrame',
        name=_('Enable Shape Framing'),
        default=1,
        desc=_('After 10 shape-type antlines are used, the signs repeat. '
               'With this enabled, colored frames will be added to '
               'distinguish them.'),
    ),
]

checkbox_all = {}
checkbox_chosen = {}
checkbox_other = {}
tk_vars = {}  # type: Dict[str, IntVar]

VAR_LIST = []  # type: List[packageLoader.StyleVar]
STYLES = {}

window = None

UI = {}


def update_filter():
    """Callback function replaced by tagsPane, to update items if needed."""


def add_vars(style_vars, styles):
    """
    Add the given stylevars to our list.

    """
    VAR_LIST.clear()
    VAR_LIST.extend(
        sorted(style_vars, key=operator.attrgetter('id'))
    )

    for var in VAR_LIST:
        var.enabled = BEE2_config.GEN_OPTS.get_bool('StyleVar', var.id, var.default)

    for style in styles:
        STYLES[style.id] = style


@BEE2_config.option_handler('StyleVar')
def save_load_stylevars(props: Property=None):
    """Save and load variables from configs."""
    if props is None:
        props = Property('', [])
        for var_id, var in sorted(tk_vars.items()):
            props[var_id] = str(int(var.get()))
        return props
    else:
        # Loading
        for prop in props:
            tk_vars[prop.real_name].set(prop.value)
        update_filter()


def make_desc(var: Union[packageLoader.StyleVar, stylevar], is_hardcoded=False):
    """Generate the description text for a StyleVar.

    This adds 'Default: on/off', and which styles it's used in.
    """
    if var.desc:
        desc = [var.desc, '']
    else:
        desc = []

    desc.append(
        _('Default: On')
        if var.default else
        _('Default: Off')
    )

    if is_hardcoded or var.styles is None:
        desc.append(_('Styles: Unstyled'))
    else:
        app_styles = [
            style
            for style in
            STYLES.values()
            if var.applies_to_style(style)
        ]

        if len(app_styles) == len(STYLES):
            desc.append(_('Styles: All'))
        else:
            style_list = sorted(
                style.selitem_data.short_name
                for style in
                app_styles
            )
            desc.append(
                ngettext('Style: {}', 'Styles: {}', len(style_list)
            ).format(', '.join(style_list)))

    return '\n'.join(desc)


def refresh(selected_style):
    """Move the stylevars to the correct position.

    This depends on which apply to the current style.
    """
    en_row = 0
    dis_row = 0
    for var in VAR_LIST:
        if var.applies_to_all():
            continue  # Always visible!
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
        options=BEE2_config.GEN_OPTS,
        title=_('Style/Item Properties'),
        name='style',
        resize_y=True,
        tool_frame=tool_frame,
        tool_img=img.png('icons/win_stylevar'),
        tool_col=3,
    )

    UI['nbook'] = nbook = ttk.Notebook(window)

    nbook.grid(row=0, column=0, sticky=NSEW)
    window.rowconfigure(0, weight=1)
    window.columnconfigure(0, weight=1)
    nbook.enable_traversal()

    stylevar_frame = ttk.Frame(nbook)
    stylevar_frame.rowconfigure(0, weight=1)
    stylevar_frame.columnconfigure(0, weight=1)
    nbook.add(stylevar_frame, text=_('Styles'))

    UI['style_can'] = Canvas(stylevar_frame, highlightthickness=0)
    # need to use a canvas to allow scrolling
    UI['style_can'].grid(sticky='NSEW')
    window.rowconfigure(0, weight=1)

    UI['style_scroll'] = ttk.Scrollbar(
        stylevar_frame,
        orient=VERTICAL,
        command=UI['style_can'].yview,
        )
    UI['style_scroll'].grid(column=1, row=0, rowspan=2, sticky="NS")
    UI['style_can']['yscrollcommand'] = UI['style_scroll'].set

    utils.add_mousewheel(UI['style_can'], stylevar_frame)

    canvas_frame = ttk.Frame(UI['style_can'])

    frame_all = ttk.Labelframe(canvas_frame, text=_("All:"))
    frame_all.grid(row=0, sticky='EW')

    frm_chosen = ttk.Labelframe(canvas_frame, text=_("Selected Style:"))
    frm_chosen.grid(row=1, sticky='EW')

    ttk.Separator(
        canvas_frame,
        orient=HORIZONTAL,
        ).grid(row=2, sticky='EW', pady=(10, 5))

    frm_other = ttk.Labelframe(canvas_frame, text=_("Other Styles:"))
    frm_other.grid(row=3, sticky='EW')

    UI['stylevar_chosen_none'] = ttk.Label(
        frm_chosen,
        text=_('No Options!'),
        font='TkMenuFont',
        justify='center',
        )
    UI['stylevar_other_none'] = ttk.Label(
        frm_other,
        text=_('None!'),
        font='TkMenuFont',
        justify='center',
        )

    all_pos = 0
    for all_pos, var in enumerate(styleOptions):
        # Add the special stylevars which apply to all styles
        tk_vars[var.id] = int_var = IntVar(value=var.default)
        checkbox_all[var.id] = ttk.Checkbutton(
            frame_all,
            variable=int_var,
            text=var.name,
        )
        checkbox_all[var.id].grid(row=all_pos, column=0, sticky="W", padx=3)

        # Special case - this needs to refresh the filter when swapping,
        # so the items disappear or reappear.
        if var.id == 'UnlockDefault':
            checkbox_all[var.id]['command'] = lambda e: update_filter()

        tooltip.add_tooltip(
            checkbox_all[var.id],
            make_desc(var, is_hardcoded=True),
        )

    for var in VAR_LIST:
        tk_vars[var.id] = IntVar(value=var.enabled)
        args = {
            'variable': tk_vars[var.id],
            'text': var.name,
            }
        desc = make_desc(var)
        if var.applies_to_all():
            # Available in all styles - put with the hardcoded variables.
            all_pos += 1

            checkbox_all[var.id] = check = ttk.Checkbutton(frame_all, **args)
            check.grid(row=all_pos, column=0, sticky="W", padx=3)
            tooltip.add_tooltip(check, desc)
        else:
            # Swap between checkboxes depending on style.
            checkbox_chosen[var.id] = ttk.Checkbutton(frm_chosen, **args)
            checkbox_other[var.id] = ttk.Checkbutton(frm_other, **args)
            tooltip.add_tooltip(
                checkbox_chosen[var.id],
                desc,
            )
            tooltip.add_tooltip(
                checkbox_other[var.id],
                desc,
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

    item_config_frame = ttk.Frame(nbook)
    nbook.add(item_config_frame, text=_('Items'))
    itemconfig.make_pane(item_config_frame)
