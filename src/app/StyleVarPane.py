"""The Style Properties tab, for configuring style-specific properties."""
from __future__ import annotations
from typing import Callable
from tkinter import IntVar
from tkinter import ttk
import operator
import itertools

from srctools.logger import get_logger
import trio

from packages import Style, StyleVar, PackagesSet
from app import localisation, tooltip
from transtoken import TransToken
from config.stylevar import State
import config


LOGGER = get_logger(__name__)

# Special StyleVars that are hardcoded into the BEE2.
# These are effectively attributes of Portal 2 itself, and always work
# in every style.
styleOptions = [
    StyleVar.unstyled(
        id='MultiverseCave',
        name=TransToken.ui('Multiverse Cave'),
        default=True,
        desc=TransToken.ui('Play the Workshop Cave Johnson lines on map start.'),
    ),

    StyleVar.unstyled(
        id='FixFizzlerBump',
        name=TransToken.ui('Prevent Portal Bump (fizzler)'),
        default=False,
        desc=TransToken.ui(
            'Add portal bumpers to make it more difficult to portal across '
            'fizzler edges. This can prevent placing portals in tight spaces '
            'near fizzlers, or fizzle portals on activation.'
        ),
    ),

    StyleVar.unstyled(
        id='NoMidVoices',
        name=TransToken.ui('Suppress Mid-Chamber Dialogue'),
        default=False,
        desc=TransToken.ui('Disable all voicelines other than entry and exit lines.'),
    ),

    StyleVar.unstyled(
        id='UnlockDefault',
        name=TransToken.ui('Unlock Default Items'),
        default=False,
        desc=TransToken.ui(
            'Allow placing and deleting the mandatory Entry/Exit Doors and '
            'Large Observation Room. Use with caution, this can have weird '
            'results!'
        ),
    ),

    StyleVar.unstyled(
        id='AllowGooMist',
        name=TransToken.ui('Allow Adding Goo Mist'),
        default=True,
        desc=TransToken.ui(
            'Add mist particles above Toxic Goo in certain styles. This can '
            'increase the entity count significantly with large, complex goo '
            'pits, so disable if needed.'
        ),
    ),

    StyleVar.unstyled(
        id='FunnelAllowSwitchedLights',
        name=TransToken.ui('Light Reversible Excursion Funnels'),
        default=True,
        desc=TransToken.ui(
            'Funnels emit a small amount of light. However, if multiple funnels '
            'are near each other and can reverse polarity, this can cause '
            'lighting issues. Disable this to prevent that by disabling '
            'lights. Non-reversible Funnels do not have this issue.'
        ),
    ),

    StyleVar.unstyled(
        id='EnableShapeSignageFrame',
        name=TransToken.ui('Enable Shape Framing'),
        default=True,
        desc=TransToken.ui(
            'After 10 shape-type antlines are used, the signs repeat. With this'
            ' enabled, colored frames will be added to distinguish them.'
        ),
    ),
]

checkbox_all: dict[str, ttk.Checkbutton] = {}
checkbox_chosen: dict[str, ttk.Checkbutton] = {}
checkbox_other: dict[str, ttk.Checkbutton] = {}
tk_vars: dict[str, IntVar] = {}

VAR_LIST: list[StyleVar] = []
UI: dict[str, ttk.Label] = {}

TRANS_DEFAULT = {
    # i18n: StyleVar default value.
    False: TransToken.ui('Default: Off'),
    True: TransToken.ui('Default: On'),
}
# i18n: Tooltip when specific styles are used
TRANS_STYLES = TransToken.ui_plural('Style: {styles}', 'Styles: {styles}')
# i18n: StyleVar which is totally unstyled.
TRANS_UNSTYLED = TransToken.ui('Styles: Unstyled')
# i18n: StyleVar which matches all styles.
TRANS_ALL_STYLES = TransToken.ui('Styles: All')
# i18n: Order of lines in the tooltip.
TRANS_TOOLTIP = TransToken.ui('{desc}\n{defaults}\n{styles}')
TRANS_COMMA = TransToken.ui(', ')


def mandatory_unlocked() -> bool:
    """Return whether mandatory items are unlocked currently."""
    try:
        return tk_vars['UnlockDefault'].get() != 0
    except KeyError:  # Not loaded yet
        return False


def export_data(chosen_style: Style) -> dict[str, bool]:
    """Construct a dict containing the current stylevar settings."""
    return {
        var.id: (tk_vars[var.id].get() == 1)
        for var in
        itertools.chain(VAR_LIST, styleOptions)
        if var.applies_to_style(chosen_style)
    }


def make_desc(packset: PackagesSet, var: StyleVar) -> TransToken:
    """Generate the description text for a StyleVar.

    This adds 'Default: on/off', and which styles it's used in.
    """
    if var.styles is None:
        style_desc = TRANS_UNSTYLED
    else:
        app_styles = [
            style for style in packset.all_obj(Style)
            if var.applies_to_style(style)
        ]

        if len(app_styles) == len(packset.all_obj(Style)):
            style_desc = TRANS_ALL_STYLES
        else:
            style_list = [
                style.selitem_data.short_name
                for style in app_styles
            ]
            style_desc = TRANS_STYLES.format(
                styles=TRANS_COMMA.join(style_list, sort=True),
                n=len(style_list),
            )

    res = TRANS_TOOLTIP.format(
        desc=var.desc,
        defaults=TRANS_DEFAULT[var.default],
        styles=style_desc,
    )
    return res


def refresh(selected_style: Style) -> None:
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


async def make_stylevar_pane(
    frame: ttk.Frame,
    packset: PackagesSet,
    update_item_vis: Callable[[], None],
) -> None:
    """Construct the stylevar pane."""
    frame_all = ttk.Labelframe(frame)
    localisation.set_text(frame_all, TransToken.ui("All:"))
    frame_all.grid(row=0, sticky='EW')

    frm_chosen = ttk.Labelframe(frame)
    localisation.set_text(frm_chosen, TransToken.ui("Selected Style:"))
    frm_chosen.grid(row=1, sticky='EW')

    ttk.Separator(frame, orient='horizontal').grid(row=2, sticky='EW', pady=(10, 5))

    frm_other = ttk.Labelframe(frame)
    localisation.set_text(frm_other, TransToken.ui("Other Styles:"))
    frm_other.grid(row=3, sticky='EW')

    UI['stylevar_chosen_none'] = localisation.set_text(ttk.Label(
        frm_chosen,
        font='TkMenuFont',
        justify='center',
    ), TransToken.ui('No Options!'))

    UI['stylevar_other_none'] = localisation.set_text(ttk.Label(
        frm_other,
        font='TkMenuFont',
        justify='center',
    ), TransToken.ui('None!'))
    VAR_LIST[:] = sorted(packset.all_obj(StyleVar), key=operator.attrgetter('id'))

    async def add_state_syncers(
        var_id: str,
        tk_var: IntVar,
        *checks: ttk.Checkbutton,
    ) -> None:
        """Makes functions for syncing stylevar state. """
        async def apply_state(state: State) -> None:
            """Applies the given state."""
            tk_var.set(state.value)
        await config.APP.set_and_run_ui_callback(State, apply_state, var_id)

        def cmd_func() -> None:
            """When clicked, store configuration."""
            config.APP.store_conf(State(tk_var.get() != 0), var_id)

        for check in checks:
            check['command'] = cmd_func

    all_pos = 0
    for all_pos, var in enumerate(styleOptions):
        # Add the special stylevars which apply to all styles
        tk_vars[var.id] = int_var = IntVar(value=var.default)
        checkbox_all[var.id] = chk = ttk.Checkbutton(frame_all, variable=int_var)
        localisation.set_text(chk, var.name)
        chk.grid(row=all_pos, column=0, sticky="W", padx=3)
        tooltip.add_tooltip(chk, make_desc(packset, var))

        # Special case - this needs to refresh the filter when swapping,
        # so the items disappear or reappear.
        if var.id == 'UnlockDefault':
            def on_unlock_default_set() -> None:
                """Update item filters when this is changed by the user."""
                config.APP.store_conf(State(unlock_def_var.get() != 0), 'UnlockDefault')
                update_item_vis()

            async def apply_unlock_default(state: State) -> None:
                """Update item filters when this is changed by config."""
                unlock_def_var.set(state.value)
                update_item_vis()

            unlock_def_var = int_var
            chk['command'] = on_unlock_default_set
            await config.APP.set_and_run_ui_callback(State, apply_unlock_default, var.id)
        else:
            await add_state_syncers(var.id, int_var, chk)

    # The nursery is mainly used so constructing all the checkboxes can be done immediately,
    # then the UI callbacks are done after.
    async with trio.open_nursery() as nursery:
        for var in VAR_LIST:
            tk_vars[var.id] = int_var = IntVar(value=var.enabled)
            desc = make_desc(packset, var)
            if var.applies_to_all():
                # Available in all styles - put with the hardcoded variables.
                all_pos += 1
                checkbox_all[var.id] = chk = ttk.Checkbutton(frame_all, variable=tk_vars[var.id])
                localisation.set_text(chk, var.name)
                chk.grid(row=all_pos, column=0, sticky="W", padx=3)
                tooltip.add_tooltip(chk, desc)
                nursery.start_soon(add_state_syncers, var.id, int_var, chk)
            else:
                # Swap between checkboxes depending on style.
                checkbox_chosen[var.id] = chk_chose = ttk.Checkbutton(frm_chosen, variable=tk_vars[var.id])
                checkbox_other[var.id] = chk_other = ttk.Checkbutton(frm_other, variable=tk_vars[var.id])

                localisation.set_text(chk_chose, var.name)
                localisation.set_text(chk_other, var.name)
                tooltip.add_tooltip(checkbox_chosen[var.id], desc)
                tooltip.add_tooltip(checkbox_other[var.id], desc)
                nursery.start_soon(add_state_syncers, var.id, int_var, chk_chose, chk_other)
