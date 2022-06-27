"""Customizable configuration for specific items or groups of them."""
from typing import (
    Optional, Union, Callable,
    List, Tuple, Dict, Set,
    Iterator, AsyncIterator, Awaitable, Mapping,
)
from typing_extensions import TypeAlias
from tkinter import ttk
import tkinter as tk

from srctools import EmptyMapping, Property, Vec, logger
from srctools.dmx import Element
import trio
import attrs

from app import UI, background_run, signage_ui, tkMarkdown, sound, tk_tools
from app.tooltip import add_tooltip
import BEE2_config
import config
import utils
import packages


LOGGER = logger.get_logger(__name__)

# Called when the var is changed, to update UI if required.
UpdateFunc: TypeAlias = Callable[[str], Awaitable[None]]

# Functions for each widget.
# The function is passed a parent frame, StringVar, and Property block.
# The widget to be installed should be returned, and a callback to refresh the UI.
SingleCreateFunc: TypeAlias = Callable[
    [ttk.Frame, tk.StringVar, Property],
    Awaitable[Tuple[tk.Widget, UpdateFunc]]
]
WidgetLookup: utils.FuncLookup[SingleCreateFunc] = utils.FuncLookup('Widgets')

# Override for timer-type widgets to be more compact - passed a num:var dict of StringVars
# instead. The widgets should insert themselves into the parent frame.
# It then yields timer_val, update-func pairs.
MultiCreateFunc: TypeAlias = Callable[
    [ttk.Frame, List[Tuple[str, tk.StringVar]], Property],
    AsyncIterator[Tuple[str, UpdateFunc]]
]
WidgetLookupMulti: utils.FuncLookup[MultiCreateFunc] = utils.FuncLookup('Multi-Widgets')

CONFIG = BEE2_config.ConfigFile('item_cust_configs.cfg')

TIMER_NUM = list(map(str, range(3, 31)))
TIMER_NUM_INF = ['inf', *TIMER_NUM]

INF = '∞'

# For the item-variant widget, we need to refresh on style changes.
ITEM_VARIANT_LOAD: List[Tuple[str, Callable[[], object]]] = []


async def nop_update(__value: str) -> None:
    """Placeholder callback which does nothing."""


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


@config.register('ItemVar', uses_id=True)
@attrs.frozen
class WidgetConfig(config.Data):
    """The configuation persisted to disk and stored in palettes."""
    # A single non-timer value, or timer name -> value.
    values: Union[str, Mapping[str, str]] = EmptyMapping

    @classmethod
    def parse_legacy(cls, props: Property) -> Dict[str, 'WidgetConfig']:
        """Parse from the old legacy config."""
        data = {}
        for group in props.find_children('ItemVar'):
            if not group.has_children():
                LOGGER.warning('Illegal leaf property "{}" in ItemVar conf', group.name)
            for widget in group:
                data[f'{group.real_name}:{widget.real_name}'] = WidgetConfig.parse_kv1(widget, 1)
        return data

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'WidgetConfig':
        """Parse Keyvalues config values."""
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

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'WidgetConfig':
        """Parse DMX format configuration."""
        assert version == 1
        if 'value' in data:
            return WidgetConfig(data['value'].val_string)
        else:
            return WidgetConfig({
                attr.name[4:]: attr.val_string
                for attr in data.values()
                if attr.name.startswith('tim_')
            })

    def export_dmx(self) -> Element:
        """Generate DMX format configuration."""
        elem = Element('ItemVar', 'DMElement')
        if isinstance(self.values, str):
            elem['value'] = self.values
        else:
            for tim, value in self.values.items():
                elem[f'tim_{tim}'] = value
        return elem


@attrs.define
class Widget:
    """Common logic for both kinds of widget that can appear on a ConfigGroup."""
    group_id: str
    id: str
    name: str
    tooltip: str
    config: Property
    create_func: SingleCreateFunc

    @property
    def has_values(self) -> bool:
        """Item variant widgets don't have configuration, all others do."""
        return self.create_func is not widget_item_variant


@attrs.define
class SingleWidget(Widget):
    """Represents a single widget with no timer value."""
    value: tk.StringVar
    ui_cback: Optional[UpdateFunc] = None

    async def apply_conf(self, data: WidgetConfig) -> None:
        """Apply the configuration to the UI."""
        if isinstance(data.values, str):
            self.value.set(data.values)
        else:
            LOGGER.warning('{}:{}: Saved config is timer-based, but widget is singular.', self.group_id, self.id)

    def __attrs_post_init__(self) -> None:
        """Add functions to recompute state/UI when changed."""
        save_id = f'{self.group_id}:{self.id}'

        def on_changed(*_) -> None:
            """Recompute state and UI when changed."""
            val = self.value.get()
            config.store_conf(WidgetConfig(val), save_id)
            if self.ui_cback is not None:
                background_run(self.ui_cback, val)

        self.value.trace_add('write', on_changed)


@attrs.define
class MultiWidget(Widget):
    """Represents a group of multiple widgets for all the timer values."""
    multi_func: MultiCreateFunc  # Function to create and arrange the block of widgets.
    use_inf: bool  # For timer, is infinite valid?
    values: List[Tuple[str, tk.StringVar]]
    ui_cbacks: Dict[str, UpdateFunc] = attrs.Factory(dict)

    async def apply_conf(self, data: WidgetConfig) -> None:
        """Apply the configuration to the UI."""
        if isinstance(data.values, str):
            # Single in conf, apply to all.
            for _, var in self.values:
                var.set(data.values)
        else:
            for tim_val, var in self.values:
                try:
                    val = data.values[tim_val]
                except KeyError:
                    continue
                var.set(val)

    def __attrs_post_init__(self) -> None:
        """Add functions to recompute state/UI when changed."""
        for tim_val, var in self.values:
            var.trace_add('write', self._get_on_changed(tim_val, var))

    def _get_on_changed(self, tim_val: str, var: tk.StringVar) -> Callable[[str, str, str], None]:
        """Get a function to recompute state and UI when changed."""
        save_id = f'{self.group_id}:{self.id}'

        def on_changed(*_) -> None:
            """Recompute state and UI when changed."""
            try:
                cback = self.ui_cbacks[tim_val]
            except KeyError:
                pass
            else:
                background_run(cback, var.get())
            config.store_conf(WidgetConfig({
                num: sub_var.get()
                for num, sub_var in self.values
            }), save_id)
        return on_changed


class ConfigGroup(packages.PakObject, allow_mult=True, needs_foreground=True):
    """A group of configs for an item."""
    def __init__(
        self,
        conf_id: str,
        group_name: str,
        desc,
        widgets: List[SingleWidget],
        multi_widgets: List[MultiWidget],
    ) -> None:
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets
        self.multi_widgets = multi_widgets

    @classmethod
    async def parse(cls, data: packages.ParseData) -> 'ConfigGroup':
        """Parse the config group from info.txt."""
        props = data.info

        if data.is_override:
            # Override doesn't have a name
            group_name = ''
        else:
            group_name = props['Name']

        desc = packages.desc_parse(props, data.id, data.pak_id)

        widgets: list[SingleWidget] = []
        multi_widgets: list[MultiWidget] = []

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
            name = wid['Label', wid_id]
            tooltip = wid['Tooltip', '']
            default_prop = wid.find_key('Default', '')
            values: list[tuple[str, tk.StringVar]]

            conf = config.get_cur_conf(WidgetConfig, f'{data.id}:{wid_id}', default=WidgetConfig())

            # Special case - can't be timer, and no values.
            if create_func is widget_item_variant:
                if is_timer:
                    LOGGER.warning("Item Variants can't be timers! ({}.{})", data.id, wid_id)
                    is_timer = use_inf = False

            if is_timer:
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
                        cur_value = CONFIG.get_val(data.id, f'{wid_id}_{num}', defaults[num])
                    elif isinstance(conf.values, str):
                        cur_value = conf.values
                    else:
                        cur_value = conf.values[num]
                    values.append((num, tk.StringVar(
                        value=cur_value,
                        name=f'itemconf_{data.id}_{wid_id}_{num}'
                    )))

                multi_widgets.append(MultiWidget(
                    group_id=data.id,
                    id=wid_id,
                    name=name,
                    tooltip=tooltip,
                    config=wid,
                    create_func=create_func,
                    multi_func=timer_func,
                    values=values,
                    use_inf=use_inf,
                ))
            else:
                # Singular Widget.
                if default_prop.has_children():
                    raise ValueError(
                        f'{data.id}:{wid_id}: Can only have multiple defaults for timer-ed widgets!'
                    )

                if create_func is widget_item_variant:
                    cur_value = ''  # Not used.
                elif conf.values is EmptyMapping:
                    # No new conf, check the old conf.
                    cur_value = CONFIG.get_val(data.id, wid_id, default_prop.value)
                elif isinstance(conf.values, str):
                    cur_value = conf.values
                else:
                    LOGGER.warning('Widget {}:{} had timer defaults, but widget is singular!', data.id, wid_id)
                    cur_value = default_prop.value

                widgets.append(SingleWidget(
                    group_id=data.id,
                    id=wid_id,
                    name=name,
                    tooltip=tooltip,
                    config=wid,
                    create_func=create_func,
                    value=tk.StringVar(
                        value=cur_value,
                        name=f'itemconf_{data.id}_{wid_id}',
                    ),
                ))
        # If we are new, write our defaults to config.
        CONFIG.save_check()

        return cls(
            data.id,
            group_name,
            desc,
            widgets,
            multi_widgets,
        )

    def add_over(self, override: 'ConfigGroup') -> None:
        """Override a ConfigGroup to add additional widgets."""
        # Make sure they don't double-up.
        conficts = self.widget_ids() & override.widget_ids()
        if conficts:
            raise ValueError('Duplicate IDs in "{}" override - {}', self.id, conficts)

        self.widgets.extend(override.widgets)
        self.multi_widgets.extend(override.multi_widgets)
        self.desc = tkMarkdown.join(self.desc, override.desc)

    def widget_ids(self) -> Set[str]:
        """Return the set of widget IDs used."""
        return {
            wid.id
            for wid_list in [self.widgets, self.multi_widgets]
            for wid in wid_list
        }

    @staticmethod
    def export(exp_data: packages.ExportData) -> None:
        """Write all our values to the config."""
        for conf in exp_data.packset.all_obj(ConfigGroup):
            config_section = CONFIG[conf.id]
            for s_wid in conf.widgets:
                if s_wid.has_values:
                    config_section[s_wid.id] = s_wid.value.get()
            for m_wid in conf.multi_widgets:
                for num, var in m_wid.values:
                    config_section[f'{m_wid.id}_{num}'] = var.get()
            if not config_section:
                del CONFIG[conf.id]
        CONFIG.save_check()

    async def create_widgets(self, master: ttk.Frame) -> ttk.LabelFrame:
        """Create the widgets for this config."""
        frame = ttk.LabelFrame(master, text=self.name)
        frame.columnconfigure(0, weight=1)
        row = 0

        widget_count = len(self.widgets) + len(self.multi_widgets)

        # Now make the widgets.
        if self.widgets:
            for row, s_wid in enumerate(self.widgets):
                wid_frame = ttk.Frame(frame)
                wid_frame.grid(row=row, column=0, sticky='ew')
                wid_frame.columnconfigure(1, weight=1)
                await trio.sleep(0)
                try:
                    widget, s_wid.ui_cback = await s_wid.create_func(wid_frame, s_wid.value, s_wid.config)
                except Exception:
                    LOGGER.exception('Could not construct widget {}.{}', self.id, s_wid.id)
                    continue

                if s_wid.name:
                    label = ttk.Label(wid_frame, text=s_wid.name + ': ')
                    label.grid(row=0, column=0)
                    widget.grid(row=0, column=1, sticky='e')
                else:
                    label = None
                    widget.grid(row=0, column=0, columnspan=2, sticky='ew')
                if s_wid.has_values:
                    await config.set_and_run_ui_callback(
                        WidgetConfig, s_wid.apply_conf, f'{s_wid.group_id}:{s_wid.id}',
                    )
                if s_wid.tooltip:
                    add_tooltip(widget, s_wid.tooltip)
                    if label is not None:
                        add_tooltip(label, s_wid.tooltip)
                    add_tooltip(wid_frame, s_wid.tooltip)

        if self.widgets and self.multi_widgets:
            ttk.Separator(orient='horizontal').grid(row=1, column=0, sticky='ew')

        # Continue from wherever we were.
        for row, m_wid in enumerate(self.multi_widgets, start=row + 1):
            # If we only have 1 widget, don't add a redundant title.
            if widget_count == 1 or not m_wid.name:
                wid_frame = ttk.Frame(frame)
            else:
                wid_frame = ttk.LabelFrame(frame, text=m_wid.name)

            wid_frame.grid(row=row, column=0, sticky='ew')
            assert isinstance(m_wid.values, list)
            try:
                async for tim_val, value in m_wid.multi_func(
                    wid_frame,
                    m_wid.values,
                    m_wid.config,
                ):
                    m_wid.ui_cbacks[tim_val] = value
            except Exception:
                LOGGER.exception('Could not construct widget {}.{}', self.id, m_wid.id)
                continue
            await config.set_and_run_ui_callback(
                WidgetConfig, m_wid.apply_conf, f'{m_wid.group_id}:{m_wid.id}',
            )

            if m_wid.tooltip:
                add_tooltip(wid_frame, m_wid.tooltip)

        return frame


async def make_pane(parent: ttk.Frame) -> None:
    """Create all the widgets we use."""
    ordered_conf = sorted(packages.LOADED.all_obj(ConfigGroup), key=lambda grp: grp.name)

    parent.columnconfigure(0, weight=1)

    # Need to use a canvas to allow scrolling.
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

    for conf_row, conf in enumerate(ordered_conf, start=1):
        frame = await conf.create_widgets(canvas_frame)
        frame.grid(column=0, row=conf_row, sticky='ew')

    canvas.update_idletasks()
    canvas.config(
        scrollregion=canvas.bbox('ALL'),
        width=canvas_frame.winfo_reqwidth(),
    )

    def canvas_reflow(_) -> None:
        """Update canvas when the window resizes."""
        canvas['scrollregion'] = canvas.bbox('all')

    canvas.bind('<Configure>', canvas_reflow)


def widget_timer_generic(widget_func: SingleCreateFunc) -> MultiCreateFunc:
    """For widgets without a multi version, do it generically."""
    async def generic_func(
        parent: ttk.Frame,
        values: List[Tuple[str, tk.StringVar]],
        conf: Property,
    ) -> AsyncIterator[Tuple[str, UpdateFunc]]:
        """Generically make a set of labels."""
        for row, (tim_val, var) in enumerate(values):
            if tim_val == 'inf':
                timer_disp = INF
            else:
                timer_disp = tim_val

            parent.columnconfigure(1, weight=1)

            label = ttk.Label(parent, text=timer_disp + ':')
            label.grid(row=row, column=0)
            widget, update = await widget_func(
                parent,
                var,
                conf,
            )
            yield tim_val, update
            widget.grid(row=row, column=1, sticky='ew')

    return generic_func


def multi_grid(
    values: List[Tuple[str, tk.StringVar]],
    columns: int = 10,
) -> Iterator[Tuple[int, int, str, str, tk.StringVar]]:
    """Generate the row and columns needed for a nice layout of widgets."""
    for tim, var in values:
        if tim == 'inf':
            tim_disp = INF
            index = 0
        else:
            tim_disp = str(tim)
            index = int(tim)
        row, column = divmod(index - 1, columns)
        yield row, column, tim, tim_disp, var


def widget_sfx(*args) -> None:
    """Play sounds when interacting."""
    sound.fx_blockable('config')


@WidgetLookup('itemvariant', 'variant')
async def widget_item_variant(parent: ttk.Frame, var: tk.StringVar, conf: Property) -> Tuple[tk.Widget, UpdateFunc]:
    """Special widget - chooses item variants.

    This replicates the box on the right-click menu for items.
    It's special-cased in the above code.
    """
    from app import contextWin
    # We don't use the variable passed to us.

    try:
        item = UI.item_list[conf['ItemID']]
    except KeyError:
        raise ValueError('Unknown item "{}"!'.format(conf['ItemID']))

    version_lookup: Optional[List[str]] = None

    def update_data() -> None:
        """Refresh the data in the list."""
        nonlocal version_lookup
        version_lookup = contextWin.set_version_combobox(combobox, item)

    def change_callback(e: tk.Event=None):
        """Change the item version."""
        item.change_version(version_lookup[combobox.current()])

    combobox = ttk.Combobox(
        parent,
        exportselection=False,
        values=[''],
    )
    combobox.state(['readonly'])  # Prevent directly typing in values
    combobox.bind('<<ComboboxSelected>>', change_callback)

    ITEM_VARIANT_LOAD.append((item.id, update_data))
    update_data()
    return combobox, nop_update


# Load all the widgets.
from . import checkmark, color, dropdown, slider, string, timer
