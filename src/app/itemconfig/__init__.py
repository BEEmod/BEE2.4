"""Customizable configuration for specific items or groups of them."""
from __future__ import annotations
from typing import Mapping, Optional, Union, Callable, List, Tuple
from tkinter import ttk
import tkinter as tk

from srctools import EmptyMapping, Property, Vec, logger
import trio
import attr

from packages import PakObject, ExportData, ParseData, desc_parse
from app import UI, signage_ui, tkMarkdown, sound, tk_tools
from app.tooltip import add_tooltip
import BEE2_config
import utils


LOGGER = logger.get_logger(__name__)

SingleCreateFunc = Callable[[tk.Frame, tk.StringVar, Property], tk.Widget]
MultiCreateFunc = Callable[[tk.Frame, List[Tuple[str, tk.StringVar]], Property], None]

# Functions for each widget.
# The function is passed a parent frame, StringVar, and Property block.
WidgetLookup: utils.FuncLookup[SingleCreateFunc] = utils.FuncLookup('Widgets')
# Override for timer-type widgets to be more compact - passed a num:var dict
# of StringVars instead. The widgets should insert themselves into the parent
# frame.
WidgetLookupMulti: utils.FuncLookup[MultiCreateFunc] = utils.FuncLookup('Multi-Widgets')

CONFIG = BEE2_config.ConfigFile('item_cust_configs.cfg')
CONFIG_ORDER: List[ConfigGroup] = []

TIMER_NUM = list(map(str, range(3, 31)))
TIMER_NUM_INF = ['inf', *TIMER_NUM]

INF = '∞'

# For the item-variant widget, we need to refresh on style changes.
ITEM_VARIANT_LOAD = []


def parse_color(color: str) -> Tuple[int, int, int]:
    """Parse a string into a color."""
    if color.startswith('#'):
        try:
            r = int(color[1:3], base=16)
            g = int(color[3:5], base=16)
            b = int(color[5:], base=16)
        except ValueError:
            LOGGER.warning('Invalid RGB value: "{}"!', color)
            r = g = b = 128
    else:
        r, g, b = map(int, Vec.from_str(color, 128, 128, 128))
    return r, g, b


@BEE2_config.register('ItemVar', uses_id=True)
@attr.frozen
class WidgetConfig:
    """The configuation persisted to disk and stored in palettes."""
    # A single non-timer value, or timer name -> value.
    values: str | Mapping[str, str] = EmptyMapping

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> WidgetConfig:
        """Parse DMX config values."""
        assert version == 1
        if data.has_children():
            return WidgetConfig({
                prop.name: prop.value
                for prop in data
            })
        else:
            return WidgetConfig(data.value)

    def export_kv1(self) -> Property:
        """Generate keyvalues for saving configuration."""
        if isinstance(self.values, str):
            return Property('', self.values)
        else:
            return Property('', [
                Property(tim, value)
                for tim, value in self.values.items()
            ])


@BEE2_config.OPTION_SAVE('ItemVar')
def save_itemvar() -> Property:
    """Save item variables into the palette."""
    prop = Property('', [])
    for group in CONFIG_ORDER:
        conf = Property(group.id, [])
        for widget in group.widgets:
            if widget.has_values:
                conf.append(Property(widget.id, widget.values.get()))
        for widget in group.multi_widgets:
            conf.append(Property(widget.id, [
                Property(str(tim_val), var.get())
                for tim_val, var in
                widget.values
            ]))
        prop.append(conf)
    return prop


@BEE2_config.OPTION_LOAD('ItemVar')
def load_itemvar(prop: Property) -> None:
    """Load item variables into the palette."""
    for group in CONFIG_ORDER:
        conf = prop.find_block(group.id, or_blank=True)
        for widget in group.widgets:
            if widget.has_values:
                try:
                    widget.values.set(conf[widget.id])
                except LookupError:
                    pass

        for widget in group.multi_widgets:
            time_conf = conf.find_block(widget.id, or_blank=True)
            for tim_val, var in widget.values:
                try:
                    var.set(time_conf[str(tim_val)])
                except LookupError:
                    pass
    return None


@attr.define
class Widget:
    """Represents a widget that can appear on a ConfigGroup."""
    group_id: str
    id: str
    name: str
    tooltip: str
    create_func: SingleCreateFunc
    multi_func: MultiCreateFunc
    config: Property
    values: Union[tk.StringVar, list[tuple[Union[int, str], tk.StringVar]]]
    is_timer: bool
    use_inf: bool  # For timer, is infinite valid?

    @property
    def has_values(self) -> bool:
        """Item variant widgets don't have configuration, all others do."""
        return self.create_func is not widget_item_variant

    async def apply_conf(self, data: WidgetConfig) -> None:
        """Apply the configuration to the UI."""
        if isinstance(self.values, list):
            if isinstance(data.values, str):
                # Single in conf, apply to all.
                for tim_val, var in self.values:
                    var.set(data.values)
            else:
                for tim_val, var in self.values:
                    try:
                        val = data.values[tim_val]
                    except KeyError:
                        continue
                    var.set(val)
        elif isinstance(data.values, str):
            self.values.set(data.values)
        else:
            LOGGER.warning('{}:{}: Saved config is timer-based, but widget is singular.', self.group_id, self.id)


class ConfigGroup(PakObject, allow_mult=True):
    """A group of configs for an item."""
    def __init__(
        self,
        conf_id: str,
        group_name: str,
        desc,
        widgets: list[Widget],
        multi_widgets: list[Widget],
    ) -> None:
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets
        self.multi_widgets = multi_widgets

    @classmethod
    async def parse(cls, data: ParseData) -> 'PakObject':
        props = data.info

        if data.is_override:
            # Override doesn't have a name
            group_name = ''
        else:
            group_name = props['Name']

        desc = desc_parse(props, data.id, data.pak_id)

        widgets: list[Widget] = []
        multi_widgets: list[Widget] = []

        for wid in props.find_all('Widget'):
            await trio.sleep(0)
            try:
                create_func = WidgetLookup[wid['type']]
            except KeyError:
                LOGGER.warning(
                    'Unknown widget type "{}" in <{}:{}>!',
                    wid['type'],
                    data.pak_id,
                    data.id,
                )
                continue
            try:
                timer_func = WidgetLookupMulti[wid['type']]
            except KeyError:
                timer_func = widget_timer_generic(create_func)

            is_timer = wid.bool('UseTimer')
            use_inf = is_timer and wid.bool('HasInf')
            wid_id = wid['id'].casefold()
            name = wid['Label']
            tooltip = wid['Tooltip', '']
            default_prop = wid.find_key('Default', '')
            values: Union[List[Tuple[str, tk.StringVar]], tk.StringVar]

            conf = BEE2_config.get_cur_conf(WidgetConfig, f'{data.id}:{wid_id}')

            # Special case - can't be timer, and no values.
            if create_func is widget_item_variant:
                if is_timer:
                    LOGGER.warning("Item Variants can't be timers! ({}.{})", data.id, wid_id)
                    is_timer = use_inf = False
                # Values isn't used, set to a dummy value.
                values = []
            elif is_timer:
                if default_prop.has_children():
                    defaults = {
                        num: default_prop[num]
                        for num in (TIMER_NUM_INF if use_inf else TIMER_NUM)
                    }
                else:
                    # All the same.
                    defaults = dict.fromkeys(TIMER_NUM_INF if use_inf else TIMER_NUM, default_prop.value)

                values = []
                for num in (TIMER_NUM_INF if use_inf else TIMER_NUM):
                    if conf.values is EmptyMapping:
                        # No new conf, check the old conf.
                        cur_value = CONFIG.get_val(data.id, '{}_{}'.format(wid_id, num), defaults[num])
                    elif isinstance(conf.values, str):
                        cur_value = conf.values
                    else:
                        cur_value = conf.values[num]
                    values.append((num, tk.StringVar(
                        value=cur_value,
                        name=f'itemconf_{data.id}_{wid_id}_{num}'
                    )))
            else:
                if default_prop.has_children():
                    raise ValueError(
                        f'{data.id}:{wid_id}: Can only have multiple defaults for timer-ed widgets!'
                    )
                if conf.values is EmptyMapping:
                    # No new conf, check the old conf.
                    cur_value = CONFIG.get_val(data.id, wid_id, default_prop.value)
                elif isinstance(conf.values, str):
                    cur_value = conf.values
                else:
                    LOGGER.warning('Widget {}:{} had timer defaults, but widget is singular!', data.id, wid_id)
                    cur_value = default_prop.value

                values = tk.StringVar(
                    value=cur_value,
                    name=f'itemconf_{data.id}_{wid_id}',
                )

            (multi_widgets if is_timer else widgets).append(Widget(
                data.id,
                wid_id,
                name,
                tooltip,
                create_func,
                timer_func,
                wid,
                values,
                is_timer,
                use_inf,
            ))

        group = cls(
            data.id,
            group_name,
            desc,
            widgets,
            multi_widgets,
        )
        CONFIG_ORDER.append(group)

        # If we are new, write our defaults to config.
        CONFIG.save_check()

        return group

    def add_over(self, override: 'ConfigGroup'):
        """Override a ConfigGroup to add additional widgets."""
        # Make sure they don't double-up.
        conficts = self.widget_ids() & override.widget_ids()
        if conficts:
            raise ValueError('Duplicate IDs in "{}" override - {}', self.id, conficts)

        self.widgets.extend(override.widgets)
        self.multi_widgets.extend(override.multi_widgets)
        self.desc = tkMarkdown.join(self.desc, override.desc)

        # Don't display that as well.
        CONFIG_ORDER.remove(override)

    def widget_ids(self) -> set[str]:
        """Return the set of widget IDs used."""
        return {
            wid.id
            for wid_cat in (self.widgets, self.multi_widgets)
            for wid in wid_cat
        }

    @staticmethod
    def export(exp_data: ExportData):
        """Write all our values to the config."""
        for conf in CONFIG_ORDER:
            config_section = CONFIG[conf.id]
            for wid in conf.widgets:
                if wid.has_values:
                    config_section[wid.id] = wid.values.get()
            for wid in conf.multi_widgets:
                for num, var in wid.values:
                    config_section['{}_{}'.format(wid.id, num)] = var.get()
            if not config_section:
                del CONFIG[conf.id]
        CONFIG.save_check()


async def make_pane(parent: ttk.Frame):
    """Create all the widgets we use."""
    CONFIG_ORDER.sort(key=lambda grp: grp.name)

    parent.columnconfigure(0, weight=1)

    # Need to use a canvas to allow scrolling
    canvas = tk.Canvas(parent, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky='NSEW')
    parent.rowconfigure(0, weight=1)

    scrollbar = ttk.Scrollbar(
        parent,
        orient='vertical',
        command=canvas.yview,
    )
    scrollbar.grid(column=1, row=0, sticky="ns")
    canvas['yscrollcommand'] = scrollbar.set

    tk_tools.add_mousewheel(canvas, canvas, parent)
    canvas_frame = ttk.Frame(canvas)
    canvas.create_window(0, 0, window=canvas_frame, anchor="nw")
    canvas_frame.rowconfigure(0, weight=1)

    sign_button = await signage_ui.init_widgets(canvas_frame)
    if sign_button is not None:
        sign_button.grid(row=0, column=0, sticky='ew')

    for conf_row, config in enumerate(CONFIG_ORDER, start=1):
        frame = ttk.LabelFrame(canvas_frame, text=config.name)
        frame.columnconfigure(0, weight=1)
        frame.grid(row=conf_row, column=0, sticky='nsew')

        row = 0

        widget_count = len(config.widgets) + len(config.multi_widgets)

        # Now make the widgets.
        if config.widgets:
            for row, wid in enumerate(config.widgets):
                wid_frame = ttk.Frame(frame)
                wid_frame.grid(row=row, column=0, sticky='ew')
                wid_frame.columnconfigure(1, weight=1)

                assert isinstance(wid.values, tk.StringVar)
                try:
                    widget = wid.create_func(wid_frame, wid.values, wid.config)
                except Exception:
                    LOGGER.exception('Could not construct widget {}.{}', config.id, wid.id)
                    continue

                label = ttk.Label(wid_frame, text=wid.name + ': ')
                label.grid(row=0, column=0)
                widget.grid(row=0, column=1, sticky='e')

                if wid.tooltip:
                    add_tooltip(widget, wid.tooltip)
                    add_tooltip(label, wid.tooltip)
                    add_tooltip(wid_frame, wid.tooltip)

        if config.widgets and config.multi_widgets:
            ttk.Separator(orient='horizontal').grid(
                row=1, column=0, sticky='ew',
            )

        # Skip if no timer widgets
        if not config.multi_widgets:
            continue

        # Continue from wherever we were.
        for row, wid in enumerate(config.multi_widgets, start=row+1):
            # If we only have 1 widget, don't add a redundant title.
            if widget_count == 1:
                wid_frame = ttk.Frame(frame)
            else:
                wid_frame = ttk.LabelFrame(frame, text=wid.name)

            wid_frame.grid(row=row, column=0, sticky='ew')
            assert isinstance(wid.values, list)
            wid.multi_func(
                wid_frame,
                wid.values,
                wid.config,
            )

            if wid.tooltip:
                add_tooltip(wid_frame, wid.tooltip)

    canvas.update_idletasks()
    canvas.config(
        scrollregion=canvas.bbox('ALL'),
        width=canvas_frame.winfo_reqwidth(),
    )

    def canvas_reflow(e):
        canvas['scrollregion'] = canvas.bbox('all')

    canvas.bind('<Configure>', canvas_reflow)


def widget_timer_generic(widget_func):
    """For widgets without a multi version, do it generically."""
    def generic_func(parent: tk.Frame, values: List[Tuple[str, tk.StringVar]], conf: Property):
        """Generically make a set of labels."""
        for row, (timer, var) in enumerate(values):
            if timer == 'inf':
                timer_disp = INF
            else:
                timer_disp = timer

            parent.columnconfigure(1, weight=1)

            label = ttk.Label(parent, text=timer_disp + ':')
            label.grid(row=row, column=0)
            widget = widget_func(
                parent,
                var,
                conf,
            )
            widget.grid(row=row, column=1, sticky='ew')

    return generic_func


def multi_grid(values: List[Tuple[str, tk.StringVar]], columns=10):
    """Generate the row and columns needed for a nice layout of widgets."""
    for tim, var in values:
        if tim == 'inf':
            tim_disp = INF
            index = 0
        else:
            tim_disp = str(tim)
            index = int(tim)
        row, column = divmod(index - 1, columns)
        yield row, column, tim_disp, var


def widget_sfx(*args):
    """Play sounds when interacting."""
    sound.fx_blockable('config')


@WidgetLookup('itemvariant', 'variant')
def widget_item_variant(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Special widget - chooses item variants.

    This replicates the box on the right-click menu for items.
    It's special-cased in the above code.
    """
    from app import contextWin
    # We don't use the variable passed to us.

    try:
        item = UI.item_list[conf['ItemID']]  # type: UI.Item
    except KeyError:
        raise ValueError('Unknown item "{}"!'.format(conf['ItemID']))

    version_lookup: Optional[List[str]] = None

    def update_data():
        """Refresh the data in the list."""
        nonlocal version_lookup
        version_lookup = contextWin.set_version_combobox(combobox, item)

    update_data.item_id = item.id

    def change_callback(e: tk.Event=None):
        """Change the item version."""
        item.change_version(version_lookup[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=0,
        values=[''],
    )
    combobox.state(['readonly'])  # Prevent directly typing in values
    combobox.bind('<<ComboboxSelected>>', change_callback)

    ITEM_VARIANT_LOAD.append(update_data)
    update_data()
    return combobox


# Load all the widgets.
from . import checkmark, color, slider, string, timer
