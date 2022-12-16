"""Window for adjusting the default values of item properties."""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Callable, ClassVar, Iterator, Optional, Tuple, List
from typing_extensions import TypeAlias

import utils
import srctools
from app import localisation, tk_tools, sound, TK_ROOT
from editoritems import ItemPropKind, Item
import editoritems_props as all_props
from transtoken import TransToken
import srctools.logger


__all__ = ['PropertyWindow']
LOGGER = srctools.logger.get_logger(__name__)
TRANS_TITLE = TransToken.ui('BEE2 - {item}')
TRANS_SUBTITLE = TransToken.ui('Settings for "{item}"')
TRANS_LABEL = TransToken.untranslated('{name}: ')
TRANS_TIMER_DELAY = TransToken.ui('Timer Delay:\n        ({tim})')


class PropGroup:
    """A group of widgets for modifying one or more props."""
    LARGE: ClassVar[bool] = False
    label: ttk.Label
    def __init__(self, parent: ttk.Frame, label_text: TransToken) -> None:
        self.frame = tk.Frame(parent)
        self.label = ttk.Label(parent)
        localisation.set_text(self.label, TRANS_LABEL.format(name=label_text))

    def apply_conf(self, options: dict[ItemPropKind, str]) -> None:
        """Apply the specified options to the UI"""
        raise NotImplementedError

    def get_conf(self) -> Iterator[tuple[ItemPropKind, str]]:
        """Export options from the UI configuration."""
        return iter([])

# The prop kinds that require this group, then a function to create it.
PropGroupFactory: TypeAlias = Tuple[List[ItemPropKind], Callable[[ttk.Frame], PropGroup]]


class BoolPropGroup(PropGroup):
    """A property controlling a regular boolean."""

    def __init__(self, parent: ttk.Frame, prop: ItemPropKind[bool]) -> None:
        super().__init__(parent, prop.name)
        self.prop = prop
        if set(prop.subtype_values) != {False, True}:
            raise ValueError(f'Non-boolean property {prop}!')
        self.var = tk.BooleanVar(value=False)
        self.check = ttk.Checkbutton(self.frame, variable=self.var)
        self.check.grid(row=0, column=0)

    @classmethod
    def factory(cls, prop: ItemPropKind[bool]) -> PropGroupFactory:
        """Make the tuple used in PROP_GROUP_FACTORIES."""
        return ([prop], lambda frame: BoolPropGroup(frame, prop))

    def apply_conf(self, options: dict[ItemPropKind, str]) -> None:
        """Apply the specified options to the UI."""
        try:
            value = srctools.conv_bool(options[self.prop], False)
        except KeyError:
            LOGGER.warning('Missing property {} from config {}', self.prop, options)
        else:
            self.var.set(value)

    def get_conf(self) -> Iterator[tuple[ItemPropKind, str]]:
        """Return the current UI configuration."""
        yield self.prop, srctools.bool_as_int(self.var.get())


PROP_GROUPS: list[PropGroupFactory] = [
    BoolPropGroup.factory(all_props.prop_start_enabled),
    BoolPropGroup.factory(all_props.prop_start_reversed),
    BoolPropGroup.factory(all_props.prop_start_deployed),
    BoolPropGroup.factory(all_props.prop_start_open),
    BoolPropGroup.factory(all_props.prop_start_locked),
    BoolPropGroup.factory(all_props.prop_portalable),
    # BoolPropGroup.factory(all_props.prop_is_coop),
    BoolPropGroup.factory(all_props.prop_dropper_enabled),
    BoolPropGroup.factory(all_props.prop_auto_drop),
    BoolPropGroup.factory(all_props.prop_cube_auto_respawn),
    # all_props.prop_cube_fall_straight_Down,
    # all_props.prop_track_start_active,
    # all_props.prop_track_is_ocillating,
    # all_props.prop_track_starting_pos,
    # all_props.prop_track_move_distance,
    # all_props.prop_track_speed,
    # all_props.prop_track_move_direction,
    # all_props.prop_pist_lower,
    # all_props.prop_pist_upper,
    # all_props.prop_pist_start_up,
    # all_props.prop_pist_auto_trigger,
    # all_props.prop_paint_type,
    # all_props.prop_paint_export_type,
    # all_props.prop_paint_flow_type,
    # all_props.prop_paint_allow_streaks,
    # all_props.prop_connection_count,
    # all_props.prop_connection_count_polarity,
    # all_props.prop_timer_delay,
    # all_props.prop_timer_sound,
    # all_props.prop_faith_vertical_alignment,
    # all_props.prop_faith_speed,
    # all_props.prop_door_is_coop,
    # all_props.prop_antline_indicator,
    # all_props.prop_antline_is_timer,
    # all_props.prop_helper_radius,
    # all_props.prop_helper_use_angles,
    # all_props.prop_helper_force_placement,
    # all_props.prop_faith_targetname,
    # all_props.prop_angled_panel_type,
    # all_props.prop_angled_panel_anim,
    # all_props.prop_cube_type,
    # all_props.prop_button_type,
    # all_props.prop_fizzler_type,
    # all_props.prop_glass_type,
]


def has_editable(item: Item, props: List[ItemPropKind]) -> bool:
    """Check if any of these properties are present in the item and are editable."""
    for kind in props:
        try:
            prop = item.properties[kind.id.casefold()]
        except KeyError:
            continue
        if prop.allow_user_default:
            return True
    return False


class PropertyWindow:
    """The window used for configuring properties."""
    def __init__(self, close_callback: Callable[[], object]) -> None:
        """Build the window."""
        self.callback = close_callback
        self.cur_item: Optional[Item] = None
        # For each PROP_GROUP, the actually constructed group.
        self.groups: List[Optional[PropGroup]] = [None] * len(PROP_GROUPS)

        self.win = tk.Toplevel(TK_ROOT)

        self.win.withdraw()
        self.win.transient(TK_ROOT)
        self.win.wm_attributes('-topmost', True)
        localisation.set_win_title(self.win, TransToken.ui("BEE2"))
        self.win.resizable(False, False)
        tk_tools.set_window_icon(self.win)
        self.win.protocol("WM_DELETE_WINDOW", self.evt_exit)
        if utils.MAC:
            # Switch to use the 'modal' window style on Mac.
            TK_ROOT.call('::tk::unsupported::MacWindowStyle', 'style', self.win, 'moveableModal', '')

        self.frame = frame = ttk.Frame(self.win, padding=10)
        frame.grid(row=0, column=0, sticky='NSEW')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.div_left = ttk.Separator(frame, orient="vertical")
        self.div_right = ttk.Separator(frame, orient="vertical")
        self.div_horiz = ttk.Separator(frame, orient="horizontal")

        self.lbl_no_options = ttk.Label(frame)
        localisation.set_text(self.lbl_no_options, TransToken.ui('No Properties available!'))
        self.btn_save = ttk.Button(frame, command=self.evt_exit)
        localisation.set_text(self.btn_save, TransToken.ui('Close'))
        self.lbl_title = ttk.Label(frame, text='')
        self.lbl_title.grid(columnspan=9)

    @staticmethod
    def can_edit(item: Item) -> bool:
        """Check if any properties on this item could be edited."""
        LOGGER.info('Can edit: {}', item.properties)
        for group, factory in PROP_GROUPS:
            if has_editable(item, group):
                return True
        return False

    def evt_exit(self) -> None:
        """Exit the window."""
        if self.cur_item is None:
            raise AssertionError('No item?')
        self.win.grab_release()
        self.win.withdraw()

        out: dict[ItemPropKind, str] = {}
        for group in self.groups:
            if group is None:
                continue
            for prop_kind, value in group.get_conf():
                try:
                    prop = self.cur_item.properties[prop_kind.id]
                except KeyError:
                    LOGGER.warning('No property {} in {}!', prop_kind.id, self.cur_item)
                    continue
                if prop.allow_user_default:
                    out[prop_kind] = value

        self.callback()

    async def show(self, item: Item, parent: tk.Toplevel, sub_name: TransToken) -> None:
        """Display the window."""
        self.cur_item = item

        large_groups: list[PropGroup] = []
        small_groups: list[PropGroup] = []
        group: PropGroup
        maybe_group: PropGroup | None

        # Go through all our groups, constructing them if required.
        for i, (props, factory) in enumerate(PROP_GROUPS):
            maybe_group = self.groups[i]
            if has_editable(item, props):
                if maybe_group is not None:
                    group = maybe_group
                else:
                    self.groups[i] = group = factory(self.frame)
                (large_groups if group.LARGE else small_groups).append(group)
            elif maybe_group is not None:  # Constructed but now hiding.
                maybe_group.label.grid_forget()
                maybe_group.frame.grid_forget()

        large_row = 1
        for large_row, group in large_groups:
            group.label.grid(
                row=large_row,
                column=0,
                sticky='e',
                padx=2, pady=5,
            )
            group.frame.grid(
                row=large_row,
                column=1,
                sticky="ew",
                padx=2, pady=5,
                columnspan=9,
            )
            large_row += 1
        # if we have a large prop, add the divider between the types.
        if large_groups:
            self.div_horiz.grid(
                row=large_row + 1,
                columnspan=9,
                sticky="ew",
            )
            large_row += 2
        else:
            self.div_horiz.grid_remove()

        ind = 0
        for group in small_groups:
            group.label.grid(
                row=(ind // 3) + large_row,
                column=(ind % 3) * 3,
                sticky="e",
                padx=2,
                pady=5,
            )
            group.frame.grid(
                row=(ind // 3) + large_row,
                column=(ind % 3) * 3 + 1,
                sticky="ew",
                padx=2,
                pady=5,
            )
            ind += 1

        if ind > 1:  # is there more than 1 checkbox? (add left divider)
            self.div_left.grid(
                row=large_row,
                column=2,
                sticky="ns",
                rowspan=(ind // 3) + 1
            )
        else:
            self.div_left.grid_remove()

        if ind > 2:  # are there more than 2 checkboxes? (add right divider)
            self.div_right.grid(
                row=large_row,
                column=5,
                sticky="ns",
                rowspan=(ind // 3) + 1,
            )
        else:
            self.div_right.grid_remove()

        if small_groups or large_groups:
            self.lbl_no_options.grid_remove()
        else:
            # There aren't any items, display error message
            self.lbl_no_options.grid(row=1, columnspan=9)
            ind = 1

        self.btn_save.grid(
            row=ind + large_row,
            columnspan=9,
            sticky="EW",
        )

        localisation.set_win_title(self.win, TRANS_TITLE.format(item=sub_name))
        localisation.set_text(self.lbl_title, TRANS_SUBTITLE.format(item=sub_name))
        self.win.wm_deiconify()
        await tk_tools.wait_eventloop()
        self.win.lift(parent)
        self.win.grab_set()
        self.win.wm_geometry(
            f'+{parent.winfo_rootx() - 30}'
            f'+{parent.winfo_rooty() - self.win.winfo_reqheight() - 30}'
        )
