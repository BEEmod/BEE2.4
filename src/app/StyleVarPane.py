"""The Style Properties tab, for configuring style-specific properties."""
from __future__ import annotations
from typing import Callable, Dict
from tkinter import *
from tkinter import ttk
import operator
import itertools

from srctools import Property, bool_as_int, conv_bool
from srctools.logger import get_logger
from srctools.dmx import Element
import attrs
import trio

from packages import Style, StyleVar, PackagesSet
from app import tooltip
from localisation import ngettext, gettext
import config


LOGGER = get_logger(__name__)

# Special StyleVars that are hardcoded into the BEE2.
# These are effectively attributes of Portal 2 itself, and always work
# in every style.
styleOptions = [
    StyleVar.unstyled(
        id='MultiverseCave',
        name=gettext('Multiverse Cave'),
        default=True,
        desc=gettext('Play the Workshop Cave Johnson lines on map start.'),
    ),

    StyleVar.unstyled(
        id='FixFizzlerBump',
        name=gettext('Prevent Portal Bump (fizzler)'),
        default=False,
        desc=gettext(
            'Add portal bumpers to make it more difficult to portal across '
            'fizzler edges. This can prevent placing portals in tight spaces '
            'near fizzlers, or fizzle portals on activation.'
        ),
    ),

    StyleVar.unstyled(
        id='NoMidVoices',
        name=gettext('Suppress Mid-Chamber Dialogue'),
        default=False,
        desc=gettext('Disable all voicelines other than entry and exit lines.'),
    ),

    StyleVar.unstyled(
        id='UnlockDefault',
        name=gettext('Unlock Default Items'),
        default=False,
        desc=gettext(
            'Allow placing and deleting the mandatory Entry/Exit Doors and '
            'Large Observation Room. Use with caution, this can have weird '
            'results!'
        ),
    ),

    StyleVar.unstyled(
        id='AllowGooMist',
        name=gettext('Allow Adding Goo Mist'),
        default=True,
        desc=gettext(
            'Add mist particles above Toxic Goo in certain styles. This can '
            'increase the entity count significantly with large, complex goo '
            'pits, so disable if needed.'
        ),
    ),

    StyleVar.unstyled(
        id='FunnelAllowSwitchedLights',
        name=gettext('Light Reversible Excursion Funnels'),
        default=True,
        desc=gettext(
            'Funnels emit a small amount of light. However, if multiple funnels '
            'are near each other and can reverse polarity, this can cause '
            'lighting issues. Disable this to prevent that by disabling '
            'lights. Non-reversible Funnels do not have this issue.'
        ),
    ),

    StyleVar.unstyled(
        id='EnableShapeSignageFrame',
        name=gettext('Enable Shape Framing'),
        default=True,
        desc=gettext(
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


def mandatory_unlocked() -> bool:
    """Return whether mandatory items are unlocked currently."""
    try:
        return tk_vars['UnlockDefault'].get() != 0
    except KeyError:  # Not loaded yet
        return False


@config.register('StyleVar', uses_id=True)
@attrs.frozen
class StyleVarState(config.Data):
    """Holds style var state stored in configs."""
    value: bool = False

    @classmethod
    def parse_legacy(cls, conf: Property) -> Dict[str, StyleVarState]:
        """Parse the old StyleVar config."""
        return {
            prop.real_name: cls(conv_bool(prop.value))
            for prop in conf.find_children('StyleVar')
        }

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> StyleVarState:
        """Parse KV1-formatted stylevar states."""
        assert version == 1, version
        return cls(conv_bool(data.value))

    def export_kv1(self) -> Property:
        """Export the stylevars in KV1 format."""
        return Property('', bool_as_int(self.value))

    def export_dmx(self) -> Element:
        """Export stylevars in DMX format."""
        elem = Element('StyleVar', 'DMElement')
        elem['value'] = self.value
        return elem


def export_data(chosen_style: Style) -> dict[str, bool]:
    """Construct a dict containing the current stylevar settings."""
    return {
        var.id: (tk_vars[var.id].get() == 1)
        for var in
        itertools.chain(VAR_LIST, styleOptions)
        if var.applies_to_style(chosen_style)
    }


def make_desc(packset: PackagesSet, var: StyleVar) -> str:
    """Generate the description text for a StyleVar.

    This adds 'Default: on/off', and which styles it's used in.
    """
    if var.desc:
        desc = [var.desc, '']
    else:
        desc = []

    # i18n: StyleVar default value.
    desc.append(gettext('Default: On') if var.default else gettext('Default: Off'))

    if var.styles is None:
        # i18n: StyleVar which is totally unstyled.
        desc.append(gettext('Styles: Unstyled'))
    else:
        app_styles = [
            style for style in packset.all_obj(Style)
            if var.applies_to_style(style)
        ]

        if len(app_styles) == len(packset.all_obj(Style)):
            # i18n: StyleVar which matches all styles.
            desc.append(gettext('Styles: All'))
        else:
            style_list = sorted(
                style.selitem_data.short_name
                for style in
                app_styles
            )
            desc.append(ngettext(
                # i18n: The styles a StyleVar is allowed for.
                'Style: {}', 'Styles: {}', len(style_list),
            ).format(', '.join(style_list)))

    return '\n'.join(desc)


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
    frame_all = ttk.Labelframe(frame, text=gettext("All:"))
    frame_all.grid(row=0, sticky='EW')

    frm_chosen = ttk.Labelframe(frame, text=gettext("Selected Style:"))
    frm_chosen.grid(row=1, sticky='EW')

    ttk.Separator(
        frame,
        orient=HORIZONTAL,
    ).grid(row=2, sticky='EW', pady=(10, 5))

    frm_other = ttk.Labelframe(frame, text=gettext("Other Styles:"))
    frm_other.grid(row=3, sticky='EW')

    UI['stylevar_chosen_none'] = ttk.Label(
        frm_chosen,
        text=gettext('No Options!'),
        font='TkMenuFont',
        justify='center',
    )
    UI['stylevar_other_none'] = ttk.Label(
        frm_other,
        text=gettext('None!'),
        font='TkMenuFont',
        justify='center',
    )
    VAR_LIST[:] = sorted(packset.all_obj(StyleVar), key=operator.attrgetter('id'))

    async def add_state_syncers(
        var_id: str,
        tk_var: IntVar,
        *checks: ttk.Checkbutton,
    ) -> None:
        """Makes functions for syncing stylevar state. """
        async def apply_state(state: StyleVarState) -> None:
            """Applies the given state."""
            tk_var.set(state.value)
        await config.set_and_run_ui_callback(StyleVarState, apply_state, var_id)

        def cmd_func() -> None:
            """When clicked, store configuration."""
            config.store_conf(StyleVarState(tk_var.get() != 0), var_id)

        for check in checks:
            check['command'] = cmd_func

    all_pos = 0
    for all_pos, var in enumerate(styleOptions):
        # Add the special stylevars which apply to all styles
        tk_vars[var.id] = int_var = IntVar(value=var.default)
        checkbox_all[var.id] = chk = ttk.Checkbutton(
            frame_all,
            variable=int_var,
            text=var.name,
        )
        chk.grid(row=all_pos, column=0, sticky="W", padx=3)
        tooltip.add_tooltip(chk, make_desc(packset, var))

        # Special case - this needs to refresh the filter when swapping,
        # so the items disappear or reappear.
        if var.id == 'UnlockDefault':
            def on_unlock_default_set() -> None:
                """Update item filters when this is changed by the user."""
                config.store_conf(StyleVarState(unlock_def_var.get() != 0), 'UnlockDefault')
                update_item_vis()

            async def apply_unlock_default(state: StyleVarState) -> None:
                """Update item filters when this is changed by config."""
                unlock_def_var.set(state.value)
                update_item_vis()

            unlock_def_var = int_var
            chk['command'] = on_unlock_default_set
            await config.set_and_run_ui_callback(StyleVarState, apply_unlock_default, var.id)
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

                checkbox_all[var.id] = chk = ttk.Checkbutton(frame_all, variable=tk_vars[var.id], text=var.name)
                chk.grid(row=all_pos, column=0, sticky="W", padx=3)
                tooltip.add_tooltip(chk, desc)
                nursery.start_soon(add_state_syncers, var.id, int_var, chk)
            else:
                # Swap between checkboxes depending on style.
                checkbox_chosen[var.id] = chk_chose = ttk.Checkbutton(frm_chosen, variable=tk_vars[var.id], text=var.name)
                checkbox_other[var.id] = chk_other = ttk.Checkbutton(frm_other, variable=tk_vars[var.id], text=var.name)

                tooltip.add_tooltip(checkbox_chosen[var.id], desc)
                tooltip.add_tooltip(checkbox_other[var.id], desc)
                nursery.start_soon(add_state_syncers, var.id, int_var, chk_chose, chk_other)
