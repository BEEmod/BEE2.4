"""Window for adjusting the default values of item properties."""
from __future__ import annotations

import attrs
from enum import Enum
import tkinter as tk
from tkinter import ttk
from typing import Callable, ClassVar, Generic, Iterator, Optional, Tuple, Dict, List, TypeVar
from typing_extensions import Final, Literal, TypeAlias

import srctools
import srctools.logger

from config.item_defaults import ItemDefault
from app import img, localisation, tk_tools, sound, TK_ROOT, tooltip
from editoritems import ItemPropKind, Item
import editoritems_props as all_props
from transtoken import TransToken
import utils
import config


__all__ = ['PropertyWindow']
LOGGER = srctools.logger.get_logger(__name__)
TRANS_TITLE = TransToken.ui('BEE2 - {item}')
TRANS_SUBTITLE = TransToken.ui('Settings for "{item}"')
TRANS_LABEL = TransToken.untranslated('{name}: ')
TRANS_TIMER_DELAY = TransToken.ui('Timer Delay:\n        ({tim:00})')
TRANS_START_ACTIVE_DISABLED = TransToken.ui(
    'When Oscillating mode is disabled, Start Active has no effect.'
)
TRANS_READONLY_SUBTYPE = TransToken.ui(
    'This option picks which sub-item is used. '
    'Put a different item on the palette to change the default instead.'
)
EnumT = TypeVar('EnumT', bound=Enum)

PIST_PROPS = [all_props.prop_pist_lower, all_props.prop_pist_upper]


class PropGroup:
    """A group of widgets for modifying one or more props."""
    LARGE: ClassVar[bool] = False
    label: ttk.Label
    def __init__(self, parent: ttk.Frame, label_text: TransToken) -> None:
        self.frame = tk.Frame(parent)
        self.label = ttk.Label(parent)
        localisation.set_text(self.label, label_text)

    def apply_conf(self, options: Dict[ItemPropKind, Tuple[str, bool]]) -> None:
        """Apply the specified options to the UI.

        For each property, this specifies the current value, and a boolean which is set if the option
        was specified to be readonly.
        """
        raise NotImplementedError

    def get_conf(self) -> Iterator[tuple[ItemPropKind, str]]:
        """Export options from the UI configuration."""
        raise NotImplementedError

    def set_tooltip(self, tok: TransToken) -> None:
        """Set a user tooltip on this group."""

# The prop kinds that require this group, then a function to create it.
PropGroupFactory: TypeAlias = Tuple[List[ItemPropKind], Callable[[ttk.Frame], PropGroup]]


class BoolPropGroup(PropGroup):
    """A property controlling a regular boolean."""
    def __init__(self, parent: ttk.Frame, prop: ItemPropKind[bool]) -> None:
        super().__init__(parent, TRANS_LABEL.format(name=prop.name))
        self.prop = prop
        if set(prop.subtype_values) != {False, True}:
            raise ValueError(f'Non-boolean property {prop}!')
        self.var = tk.BooleanVar(value=False)
        self.check = ttk.Checkbutton(self.frame, variable=self.var)
        tooltip.add_tooltip(self.check, show_when_disabled=True)
        self.check.grid(row=0, column=0)

    @classmethod
    def factory(cls, prop: ItemPropKind[bool]) -> PropGroupFactory:
        """Make the tuple used in PROP_GROUPS."""
        return ([prop], lambda frame: cls(frame, prop))

    def set_tooltip(self, tok: TransToken) -> None:
        """Set a user tooltip on this group."""
        tooltip.set_tooltip(self.check, tok)

    def apply_conf(self, options: Dict[ItemPropKind, Tuple[str, bool]]) -> None:
        """Apply the specified options to the UI."""
        try:
            value, readonly = options[self.prop]
        except KeyError:
            LOGGER.warning('Missing property {} from config: {}', self.prop, options)
            self.check.state(['disabled'])
        else:
            self.var.set(srctools.conv_bool(value, False))
            self.check.state(['disabled' if readonly else '!disabled'])

    def get_conf(self) -> Iterator[tuple[ItemPropKind, str]]:
        """Return the current UI configuration."""
        yield self.prop, srctools.bool_as_int(self.var.get())


class ComboPropGroup(PropGroup, Generic[EnumT]):
    """A prop group which uses a combobox to select specific options."""
    LARGE: ClassVar[bool] = True

    def __init__(self, parent: ttk.Frame, prop: ItemPropKind[EnumT], values: Dict[EnumT, TransToken]) -> None:
        super().__init__(parent, TRANS_LABEL.format(name=prop.name))
        self.prop = prop
        self.translated = values
        self.value_order = list(values)
        if prop.subtype_values and set(self.value_order) != set(prop.subtype_values):
            raise ValueError(f'{self.value_order!r} != {prop.subtype_values!r}')
        self.combo = ttk.Combobox(self.frame, exportselection=False)
        self.combo.state(['readonly'])  # Disallow typing text.
        localisation.add_callback(call=True)(self._update_combo)
        tooltip.add_tooltip(self.combo, show_when_disabled=True)
        self.combo.grid(row=0, column=0)

    def _update_combo(self) -> None:
        """Update the combo box when translations change."""
        self.combo['values'] = [str(self.translated[key]) for key in self.value_order]

    @classmethod
    def factory(cls, prop: ItemPropKind[EnumT], values: Dict[EnumT, TransToken]) -> PropGroupFactory:
        """Make the factory used in PROP_GROUPS."""
        return ([prop], lambda parent: cls(parent, prop, values))

    def set_tooltip(self, tok: TransToken) -> None:
        """Set a user tooltip on this group."""
        tooltip.set_tooltip(self.combo, tok)

    def apply_conf(self, options: Dict[ItemPropKind, Tuple[str, bool]]) -> None:
        """Apply the specified options to the UI."""
        try:
            val_str, readonly = options[self.prop]
        except KeyError:
            LOGGER.warning('Missing property {} from config: {}', self.prop, options)
            self.combo.state(['disabled'])
            return
        try:
            value = self.prop.parse(val_str)
        except ValueError:
            LOGGER.warning('Could not parse "{}" for property type "{}"', val_str, self.prop.id, exc_info=True)
            self.combo.state(['disabled'])
            return
        self.combo.current(self.value_order.index(value))
        self.combo.state(['disabled' if readonly else '!disabled'])

    def get_conf(self) -> Iterator[tuple[ItemPropKind, str]]:
        """Return the current UI configuration."""
        value = self.value_order[self.combo.current()]
        yield self.prop, self.prop.export(value)


class TimerPropGroup(PropGroup):
    """Special property group for timer delays."""
    def __init__(self, parent: ttk.Frame) -> None:
        super().__init__(parent, TRANS_TIMER_DELAY.format(tim=0))

        self.scale = ttk.Scale(
            self.frame,
            from_=0, to=30,
            orient="horizontal",
            command=self.widget_changed,
        )
        tooltip.add_tooltip(self.scale, show_when_disabled=True)
        self.scale.grid(row=0, column=0)
        self.old_val = 3
        self._enable_cback = True

    def apply_conf(self, options: Dict[ItemPropKind, Tuple[str, bool]]) -> None:
        """Apply the timer delay option to the UI."""
        try:
            value, readonly = options[all_props.prop_timer_delay]
        except KeyError:
            LOGGER.warning('Missing property TimerDelay from config: {}', options)
            self.scale.state(['disabled'])
            return
        self.scale.set(all_props.prop_timer_delay.parse(value))
        self.scale.state(['disabled' if readonly else '!disabled'])

    def get_conf(self) -> Iterator[tuple[ItemPropKind, str]]:
        """Get the current UI configuration."""
        cur_value = round(self.scale.get())
        yield all_props.prop_timer_delay, str(cur_value)

    def set_tooltip(self, tok: TransToken) -> None:
        """Set a user tooltip on this group."""
        tooltip.set_tooltip(self.scale, tok)

    def widget_changed(self, val: str) -> None:
        """Called when the widget changes."""
        if not self._enable_cback:
            return
        # Lock to whole numbers.
        new_val = round(float(val))

        # .set() will recuse, stop that.
        self._enable_cback = False
        self.scale.set(new_val)
        self._enable_cback = True

        localisation.set_text(self.label, TRANS_TIMER_DELAY.format(
            # Babel formats infinity with the right symbol.
            tim=float('inf') if new_val == 0 else str(new_val),
        ))

        if new_val > self.old_val:
            sound.fx_blockable('add')
        elif new_val < self.old_val:
            sound.fx_blockable('subtract')
        self.old_val = new_val


class TrackStartActivePropGroup(BoolPropGroup):
    """The start active boolean is only useable if oscillating mode is enabled."""
    def __init__(self, parent: ttk.Frame, prop: ItemPropKind[bool]) -> None:
        super().__init__(parent, prop)
        self.osc_prop: Optional[BoolPropGroup] = None
        self.has_osc = False
        self.user_tooltip = TransToken.BLANK

    def apply_conf(self, options: Dict[ItemPropKind, Tuple[str, bool]]) -> None:
        """Apply the configuration to the UI."""
        super().apply_conf(options)
        self.has_osc = all_props.prop_track_is_oscillating in options
        self._update()

    def get_conf(self) -> Iterator[Tuple[ItemPropKind, str]]:
        """Get the current configuration."""
        if self.osc_prop is not None and self.has_osc and not self.osc_prop.var.get():
            # Forced off.
            yield self.prop, '0'
        else:
            yield self.prop, srctools.bool_as_int(self.var.get())

    def set_oscillating(self, osc_prop: BoolPropGroup) -> None:
        """Attach the oscillating prop."""
        if self.osc_prop is None:
            self.osc_prop = osc_prop
            update = self._update

            def update_check() -> None:
                """Update the checkbox."""
                sound.fx_blockable('config')
                update()

            osc_prop.check['command'] = update_check
            update()

    def _update(self) -> None:
        """Update the enabled/disabled state."""
        if self.osc_prop is not None and self.has_osc and not self.osc_prop.var.get():
            self.check.state(('disabled', ))
            if self.user_tooltip:
                tooltip.set_tooltip(self.check, TransToken.untranslated('\n').join([
                    TRANS_START_ACTIVE_DISABLED,
                    self.user_tooltip,
                    # Decrease delay, the widget isn't interactive.
                ]), delay=100)
            else:
                tooltip.set_tooltip(self.check, TRANS_START_ACTIVE_DISABLED, delay=100)
            self.var.set(False)
        else:
            self.check.state(('!disabled', ))
            tooltip.set_tooltip(self.check, self.user_tooltip, delay=500)

    def set_tooltip(self, tok: TransToken) -> None:
        """Set a user tooltip on this group."""
        self.user_tooltip = tok
        self._update()


class PistonPropGroup(PropGroup):
    """Complex combo widget that handles all three piston properties."""
    LARGE: ClassVar[bool] = True
    MOVE_DIST: Final = 48  # Distance for each position
    BASE_OFF: Final = 12  # 0 starts this far from the left.

    IMG_PIST = img.Handle.builtin('BEE2/piston_top', 12, 64)
    IMG_PIST_SEL = img.Handle.builtin('BEE2/piston_top_sel', 12, 64)
    IMG_DEST = img.Handle.builtin('BEE2/piston_dest', 4, 64)
    IMG_DEST_SEL = img.Handle.builtin('BEE2/piston_dest_sel', 4, 64)

    def __init__(self, parent: ttk.Frame):
        super().__init__(parent, TransToken.ui('Position: '))
        self.platform = 0
        self.destination = 1
        self.cur_drag: Literal['plat', 'dest', None] = None
        self.readonly = False

        self.canvas = tk.Canvas(self.frame, width=250, height=66)
        self.canvas.grid(row=0, column=0)
        # Base grating visual.
        self.canv_base = self.canvas.create_image(
            0, 2, anchor='nw',
            image=img.Handle.builtin('BEE2/piston_base', 16, 64).get_tk(),
        )
        # The two movable ends.
        self.canv_plat = self.canvas.create_image(32, 2, anchor='n', image=self.IMG_PIST.get_tk())
        self.canv_dest = self.canvas.create_image(48, 2, anchor='n', image=self.IMG_DEST.get_tk())
        # Line representing the piston itself.
        self.canv_pist = self.canvas.create_line(7, 34, 28, 34, width=4, fill='#CEC9C6')
        # Line between top and selection.
        self.canv_move = self.canvas.create_line(36, 34, 40, 34, width=2, fill='#6B95BD', arrow='last')

        tk_tools.bind_leftclick(self.canvas, self.evt_mouse_down)
        self.canvas.bind('<Motion>', self.evt_mouse_hover)
        self.canvas.bind(tk_tools.EVENTS['LEFT_MOVE'], self.evt_mouse_drag)
        self.canvas.bind(tk_tools.EVENTS['LEFT_RELEASE'], self.evt_mouse_up)
        self.canvas.bind('<Leave>', self.evt_mouse_leave)

    def apply_conf(self, options: Dict[ItemPropKind, Tuple[str, bool]]) -> None:
        """Apply the specified options to the UI."""
        self.readonly = False
        try:
            start_up_str, readonly_start_up = options[all_props.prop_pist_start_up]
        except KeyError:
            LOGGER.warning('Missing property StartUp from config: {}', options)
            start_up = False
        else:
            start_up = srctools.conv_bool(start_up_str)
            if readonly_start_up:
                self.readonly = True
        pos = {
            all_props.prop_pist_lower: 0,
            all_props.prop_pist_upper: 1,
        }
        for prop in PIST_PROPS:
            try:
                val_str, readonly_val = options[prop]
            except KeyError:
                LOGGER.warning('Missing property {} from config: {}', prop.id, options)
                continue
            if readonly_val:
                self.readonly = True
            try:
                pos[prop] = prop.parse(val_str)
            except ValueError:
                LOGGER.warning(
                    'Could not parse "{}" for property type "{}"',
                    val_str, prop.id, exc_info=True,
                )
        if start_up:
            self.platform = pos[all_props.prop_pist_upper]
            self.destination = pos[all_props.prop_pist_lower]
        else:
            self.destination = pos[all_props.prop_pist_upper]
            self.platform = pos[all_props.prop_pist_lower]
        self.reposition()

    def get_conf(self) -> Iterator[Tuple[ItemPropKind, str]]:
        """Export options from the UI configuration."""
        if self.destination > self.platform:
            yield all_props.prop_pist_start_up, '0'
            yield all_props.prop_pist_lower, str(self.platform)
            yield all_props.prop_pist_upper, str(self.destination)
        else:
            yield all_props.prop_pist_start_up, '1'
            yield all_props.prop_pist_lower, str(self.destination)
            yield all_props.prop_pist_upper, str(self.platform)

    def _pos2x(self, pos: int) -> int:
        """Convert a position into an X coordinate."""
        return self.BASE_OFF + self.MOVE_DIST * pos

    def _x2pos(self, x: int) -> int:
        """Find the nearest position to this coordinate."""
        pos = round((x - self.BASE_OFF) / self.MOVE_DIST)
        return max(0, min(4, pos))

    def get_hit(self, x: int) -> Literal['plat', 'dest', None]:
        """Figure out which sprite is being clicked on."""
        pist_pos = self._pos2x(self.platform)
        dest_pos = self._pos2x(self.destination)
        if pist_pos - 8 <= x <= pist_pos + 24:
            return 'plat'
        elif dest_pos - 4 <= x <= dest_pos + 24:
            return 'dest'
        else:
            return None

    def evt_mouse_down(self, event: tk.Event) -> None:
        """Start dragging, when the canvas is clicked."""
        if not self.readonly:
            # Y is irrelevant
            self.cur_drag = self.get_hit(event.x)

    def evt_mouse_up(self, event: tk.Event) -> None:
        """Stop dragging."""
        self.cur_drag = None

    def evt_mouse_leave(self, event: tk.Event) -> None:
        """Failsafe, when the mouse fully leaves reset them all."""
        self.cur_drag = None
        self.canvas.itemconfigure(self.canv_plat, image=self.IMG_PIST.get_tk())
        self.canvas.itemconfigure(self.canv_dest, image=self.IMG_DEST.get_tk())

    def evt_mouse_hover(self, event: tk.Event) -> None:
        """Update mouseover effects depending on position."""
        if not self.readonly:
            # If currently dragging, always highlight, otherwise highlight those under the cursor.
            hover = self.cur_drag or self.get_hit(event.x)
            self.canvas.itemconfigure(
                self.canv_plat,
                image=(self.IMG_PIST_SEL if hover == 'plat' else self.IMG_PIST).get_tk()
            )
            self.canvas.itemconfigure(
                self.canv_dest,
                image=(self.IMG_DEST_SEL if hover == 'dest' else self.IMG_DEST).get_tk()
            )

    def evt_mouse_drag(self, event: tk.Event) -> None:
        """Called when mouse is held and dragged. If we are currently dragging, move items."""
        if self.cur_drag is None or self.readonly:
            return
        pos = self._x2pos(event.x)

        if self.cur_drag == 'plat':
            if pos == self.destination:
                # Swap!
                self.destination = self.platform
                sound.fx('swap')
            elif pos != self.platform:
                sound.fx('move')
            else:
                return  # No change.
            self.platform = pos
        elif self.cur_drag == 'dest':
            if pos == self.platform:
                # Swap!
                self.platform = self.destination
                sound.fx('swap')
            elif pos != self.destination:
                sound.fx('move')
            else:
                return  # No change.
            self.destination = pos
        else:
            raise AssertionError(self.cur_drag)
        # One changed, update.
        self.reposition()

    def reposition(self) -> None:
        """Update the canvas to match the specified positions."""
        self.canvas.coords(self.canv_plat, self._pos2x(self.platform) + 8, 2)
        self.canvas.coords(self.canv_pist, 7, 34, self._pos2x(self.platform) + 4, 34)
        self.canvas.coords(self.canv_dest, self._pos2x(self.destination) + 12, 2)
        if self.destination > self.platform:
            self.canvas.coords(
                self.canv_move,
                self._pos2x(self.platform) + 24, 34,
                self._pos2x(self.destination), 34,
            )
        else:
            # Offset down to not overlap.
            self.canvas.coords(
                self.canv_move,
                self._pos2x(self.platform) - 4, 48,
                self._pos2x(self.destination) + 20, 48,
            )


PROP_GROUPS: list[PropGroupFactory] = [
    BoolPropGroup.factory(all_props.prop_start_enabled),
    BoolPropGroup.factory(all_props.prop_start_reversed),
    BoolPropGroup.factory(all_props.prop_start_deployed),
    BoolPropGroup.factory(all_props.prop_start_open),
    BoolPropGroup.factory(all_props.prop_start_locked),
    BoolPropGroup.factory(all_props.prop_portalable),
    # all_props.prop_is_coop,
    BoolPropGroup.factory(all_props.prop_dropper_enabled),
    BoolPropGroup.factory(all_props.prop_auto_drop),
    BoolPropGroup.factory(all_props.prop_cube_auto_respawn),
    # all_props.prop_cube_fall_straight_down,
    TrackStartActivePropGroup.factory(all_props.prop_track_start_active),
    BoolPropGroup.factory(all_props.prop_track_is_oscillating),
    # all_props.prop_track_starting_pos,
    # all_props.prop_track_move_distance,
    # all_props.prop_track_speed,
    # all_props.prop_track_move_direction,
    ([
        all_props.prop_pist_lower,
        all_props.prop_pist_upper,
        all_props.prop_pist_start_up,
    ], PistonPropGroup),
    # all_props.prop_pist_auto_trigger,
    # all_props.prop_paint_type,
    # all_props.prop_paint_export_type,
    ComboPropGroup.factory(all_props.prop_paint_flow_type, {
        flow: TransToken.from_valve(f'PORTAL2_PuzzleEditor_ContextMenu_paint_flow_type_{flow.name.lower()}')
        for flow in all_props.PaintFlows
    }),
    BoolPropGroup.factory(all_props.prop_paint_allow_streaks),
    # all_props.prop_connection_count,
    # all_props.prop_connection_count_polarity,
    ([all_props.prop_timer_delay], TimerPropGroup),
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
    ComboPropGroup.factory(all_props.prop_cube_type, {
        typ: TransToken.from_valve(f'PORTAL2_PuzzleEditor_ContextMenu_cube_type_{name}')
        for typ, name in zip(
            all_props.CubeTypes,
            ['standard', 'companion', 'reflective', 'sphere', 'frankenturret']
        )
    }),
    ComboPropGroup.factory(all_props.prop_button_type, {
        typ: TransToken.from_valve(f'PORTAL2_PuzzleEditor_ContextMenu_button_type_{typ.name.lower()}')
        for typ in all_props.ButtonTypes
    }),
    ComboPropGroup.factory(all_props.prop_fizzler_type, {
        typ: TransToken.from_valve(f'PORTAL2_PuzzleEditor_ContextMenu_hazard_type_{typ.name.lower()}')
        for typ in all_props.FizzlerTypes
    }),
    ComboPropGroup.factory(all_props.prop_glass_type, {
        typ: TransToken.from_valve(f'PORTAL2_PuzzleEditor_ContextMenu_barrier_type_{typ.name.lower()}')
        for typ in all_props.GlassTypes
    }),
]


def matching_props(item: Item, props: List[ItemPropKind]) -> List[Tuple[all_props.ItemProp, bool]]:
    """Return the properties in this item that match a specific group of properties."""
    found: List[Tuple[all_props.ItemProp, bool]] = []
    for kind in props:
        # Subtype properties get their default overridden.
        readonly = kind is item.subtype_prop
        try:
            prop = item.properties[kind.id.casefold()]
        except KeyError:
            continue
        if not prop.allow_user_default:
            readonly = True
        found.append((prop, readonly))
    return found


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
            if matching_props(item, group):
                return True
        return False

    def evt_exit(self) -> None:
        """Exit the window."""
        if self.cur_item is None:
            raise AssertionError('No item?')
        self.win.grab_release()
        self.win.withdraw()

        old_conf = config.APP.get_cur_conf(ItemDefault, self.cur_item.id, ItemDefault())

        out: dict[ItemPropKind, str] = {}
        out.update(old_conf.defaults)  # Keep any extra values, just in case.
        for (props, factory), group in zip(PROP_GROUPS, self.groups):
            if group is None or not matching_props(self.cur_item, props):
                continue
            for prop_kind, value in group.get_conf():
                try:
                    prop = self.cur_item.properties[prop_kind.id.casefold()]
                except KeyError:
                    LOGGER.warning('No property {}={!r} in {}!', prop_kind.id, value, self.cur_item.id)
                    continue
                if prop.allow_user_default:
                    out[prop_kind] = value

        config.APP.store_conf(attrs.evolve(old_conf, defaults=out), self.cur_item.id)

        self.callback()

    async def show(self, item: Item, parent: tk.Toplevel, sub_name: TransToken) -> None:
        """Display the window."""
        self.cur_item = item

        large_groups: list[PropGroup] = []
        small_groups: list[PropGroup] = []
        group: PropGroup
        maybe_group: PropGroup | None
        # The Start Active prop needs to disable depending on this one's value.
        oscillating_prop: Optional[BoolPropGroup] = None
        start_active_prop: Optional[TrackStartActivePropGroup] = None

        conf = config.APP.get_cur_conf(ItemDefault, item.id, ItemDefault())

        # Stop our adjustment of the widgets from making sounds.
        sound.block_fx()

        # Build the options to pass into each prop group, to update it.
        group_options: dict[ItemPropKind, tuple[str, bool]] = {}
        for editor_prop in item.properties.values():
            readonly = editor_prop.kind is item.subtype_prop or not editor_prop.allow_user_default
            if readonly:
                value = editor_prop.export()  # Discard the stored option.
            else:
                try:
                    value = conf.defaults[editor_prop.kind]
                except KeyError:
                    value = editor_prop.export()
            group_options[editor_prop.kind] = value, readonly

            # Go through all our groups, constructing them if required.
        for i, (props, factory) in enumerate(PROP_GROUPS):
            maybe_group = self.groups[i]
            matching = matching_props(item, props)
            if matching:
                if maybe_group is not None:
                    group = maybe_group
                else:
                    self.groups[i] = group = factory(self.frame)
                (large_groups if group.LARGE else small_groups).append(group)
                group.apply_conf(group_options)
                # Identify these two groups.
                if isinstance(group, BoolPropGroup) and group.prop is all_props.prop_track_is_oscillating:
                    oscillating_prop = group
                elif isinstance(group, TrackStartActivePropGroup):
                    start_active_prop = group
                tooltip_bits = [prop.desc for prop, readonly in matching if prop.desc]
                if any(prop.kind is item.subtype_prop for prop, readonly in matching):
                    tooltip_bits.insert(0, TRANS_READONLY_SUBTYPE)
                if len(tooltip_bits) > 1:
                    group.set_tooltip(TransToken.untranslated('\n').join(tooltip_bits))
                elif len(tooltip_bits) == 1:
                    group.set_tooltip(tooltip_bits[0])
                else:
                    group.set_tooltip(TransToken.BLANK)
            elif maybe_group is not None:  # Constructed but now hiding.
                maybe_group.label.grid_forget()
                maybe_group.frame.grid_forget()

        # Link these up.
        if start_active_prop is not None and oscillating_prop is not None:
            start_active_prop.set_oscillating(oscillating_prop)

        large_row = 1
        for group in large_groups:
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
                columnspan=10,
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
            row=ind // 3 + 1 + large_row,
            columnspan=10,
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
