"""Customizable configuration for specific items or groups of them."""
import tkinter as tk
from tkinter import ttk
from tkinter.colorchooser import askcolor

from functools import lru_cache

from srctools import Property, Vec, conv_int, conv_bool
from packageLoader import PakObject, ExportData, ParseData, desc_parse
import BEE2_config
from tooltip import add_tooltip
import tkMarkdown
import utils
import srctools.logger
import img
import sound

from typing import Union, Callable, List, Tuple, Optional


LOGGER = srctools.logger.get_logger(__name__)

# Functions for each widget.
# The function is passed a parent frame, StringVar, and Property block.
WidgetLookup = utils.FuncLookup('Widgets')
# Override for timer-type widgets to be more compact - passed a num:var dict
# of StringVars instead. The widgets should insert themselves into the parent
# frame.
WidgetLookupMulti = utils.FuncLookup('Multi-Widgets')

CONFIG = BEE2_config.ConfigFile('item_cust_configs.cfg')

CONFIG_ORDER = []  # type: List[ConfigGroup]

TIMER_NUM = ['inf'] + list(map(str, range(3, 31)))

INF = '∞'

# For itemvariant, we need to refresh on style changes.
ITEM_VARIANT_LOAD = []


@BEE2_config.option_handler('ItemVar')
def save_load_itemvar(prop: Property=None) -> Optional[Property]:
    """Save or load item variables into the palette."""
    if prop is None:
        prop = Property('', [])
        for group in CONFIG_ORDER:
            conf = Property(group.id, [])
            for widget in group.widgets:  # ItemVariant special case.
                if widget.values is not None:
                    conf.append(Property(widget.id, widget.values.get()))
            for widget in group.multi_widgets:
                conf.append(Property(widget.id, [
                    Property(str(tim_val), var.get())
                    for tim_val, var in
                    widget.values
                ]))
            prop.append(conf)
        return prop
    else:
        # Loading.
        for group in CONFIG_ORDER:
            conf = prop.find_key(group.id, [])
            for widget in group.widgets:
                if widget.values is not None:  # ItemVariants
                    try:
                        widget.values.set(conf[widget.id])
                    except LookupError:
                        pass

            for widget in group.multi_widgets:
                time_conf = conf.find_key(widget.id, [])
                for tim_val, var in widget.values:
                    try:
                        var.set(time_conf[str(tim_val)])
                    except LookupError:
                        pass
        return None


class Widget:
    """Represents a widget that can appear on a ConfigGroup."""
    def __init__(
        self,
        wid_id: str,
        name: str,
        tooltip: str,
        create_func: Callable[[tk.Frame, tk.StringVar, Property], None],
        multi_func: Callable[[tk.Frame, List[Tuple[str, tk.StringVar]], Property], None],
        config: Property,
        values: Union[tk.StringVar, List[Tuple[Union[int, str], tk.StringVar]]],
        is_timer: bool,
        use_inf: bool,
    ):
        self.id = wid_id
        self.name = name
        self.tooltip = tooltip
        self.values = values
        self.config = config
        self.create_func = create_func
        self.multi_func = multi_func
        self.is_timer = is_timer
        self.use_inf = use_inf  # For timer, is infinite valid?


class ConfigGroup(PakObject, allow_mult=True, has_img=False):
    """A group of configs for an item."""
    def __init__(
        self,
        conf_id: str,
        group_name: str,
        desc,
        widgets: List['Widget'],
        multi_widgets: List['Widget'],
    ):
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets
        self.multi_widgets = multi_widgets

    @classmethod
    def parse(cls, data: ParseData) -> 'PakObject':
        props = data.info  # type: Property

        if data.is_override:
            # Override doesn't have a name
            group_name = ''
        else:
            group_name = props['Name']

        desc = desc_parse(props, data.id)

        widgets = []  # type: List[Widget]
        multi_widgets = []  # type: List[Widget]

        for wid in props.find_all('Widget'):
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
            default = wid.find_key('Default', '')
            values = None  # type: Union[List[Tuple[str, tk.StringVar]], tk.StringVar]

            # Special case - can't be timer, and no values.
            if create_func is widget_item_variant:
                if is_timer:
                    LOGGER.warning("Item Variants can't be timers! ({}.{})", data.id, wid_id)
                    is_timer = use_inf = False
                # Values remains a dummy None value, we don't use it.
            elif is_timer:
                if default.has_children():
                    defaults = {
                        num: default[num]
                        for num in TIMER_NUM
                        # Exclude infinite if use_inf is False.
                        if use_inf or num != 'inf'
                    }
                else:
                    # All the same.
                    defaults = dict.fromkeys(TIMER_NUM, default.value)
                values = [
                    (num, tk.StringVar(
                        value=CONFIG.get_val(
                            data.id,
                            '{}_{}'.format(wid_id, num),
                            defaults[num],
                        ),
                        name='itemconf_{}_{}_{}'.format(data.id, wid_id, num)
                    ))
                    for num in TIMER_NUM
                    # Exclude infinite if use_inf is False.
                    if use_inf or num != 'inf'
                ]
            else:
                if default.has_children():
                    raise ValueError(
                        'Can only have multiple defaults for timered widgets!'
                    )
                values = tk.StringVar(
                    value=CONFIG.get_val(
                        data.id,
                        wid_id,
                        default.value,
                    ),
                    name='itemconf_{}_{}'.format(data.id, wid_id),
                )

            (multi_widgets if is_timer else widgets).append(Widget(
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

    def widget_ids(self):
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
                # Item_variant doesn't have an output value.
                # Skip it.
                if wid.create_func is not widget_item_variant:
                    config_section[wid.id] = wid.values.get()
            for wid in conf.multi_widgets:
                for num, var in wid.values:
                    config_section['{}_{}'.format(wid.id, num)] = var.get()
            if not config_section:
                del CONFIG[conf.id]
        CONFIG.save_check()


def make_pane(parent: ttk.Frame):
    """Create all the widgets we use."""
    if not CONFIG_ORDER:
        # No configs at all...
        ttk.Label(parent, text=_('No Item Configuration!')).pack(fill='both')
        return

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

    utils.add_mousewheel(canvas, canvas, parent)
    canvas_frame = ttk.Frame(canvas)
    canvas.create_window(0, 0, window=canvas_frame, anchor="nw")
    canvas_frame.rowconfigure(0, weight=1)

    for conf_row, config in enumerate(CONFIG_ORDER):
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

                label = ttk.Label(wid_frame, text=wid.name + ': ')
                label.grid(row=0, column=0)
                widget = wid.create_func(wid_frame, wid.values, wid.config)
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


# ------------
# Widget types
# ------------

@WidgetLookup('itemvariant', 'variant')
def widget_item_variant(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Special widget - chooses item variants.

    This replicates the box on the right-click menu for items.
    It's special-cased in the above code.
    """
    import UI
    import contextWin
    # We don't use the variable passed to us.

    try:
        item = UI.item_list[conf['ItemID']]  # type: UI.Item
    except KeyError:
        raise ValueError('Unknown item "{}"!'.format(conf['ItemID']))

    version_lookup = None

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


@WidgetLookup('string', 'str')
def widget_string(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Simple textbox for entering text."""
    return ttk.Entry(
        parent,
        textvariable=var,
    )


@WidgetLookup('boolean', 'bool', 'checkbox')
def widget_checkmark(parent: tk.Frame, var: tk.StringVar, conf: Property):
    """Allows ticking a box."""
    # Ensure it's a bool value.
    if conv_bool(var.get()):
        var.set('1')
    else:
        var.set('0')

    return ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
        command=widget_sfx,
    )


@WidgetLookupMulti('boolean', 'bool', 'checkbox')
def widget_checkmark_multi(
    parent: tk.Frame,
    values: List[Tuple[str, tk.StringVar]],
    conf: Property,
) -> tk.Widget:
    """For checkmarks, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values):
        checkbox = widget_checkmark(parent, var, conf)
        checkbox.grid(row=row, column=column)
        add_tooltip(checkbox, tim_text, delay=0)
    return parent


@WidgetLookup('range', 'slider')
def widget_slider(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Widget:
    """Provides a slider for setting a number in a range."""
    scale = tk.Scale(
        parent,
        orient='horizontal',
        from_=conf.float('min'),
        to=conf.float('max', 100),
        resolution=conf.float('step', 1),
        variable=var,
        command=widget_sfx,
    )
    return scale


@WidgetLookup('color', 'colour', 'rgb')
def widget_color_single(
    parent: tk.Frame,
    var: tk.StringVar,
    conf: Property,
) -> tk.Widget:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """
    # Isolates the swatch so it doesn't resize.
    frame = ttk.Frame(parent)
    swatch = make_color_swatch(frame, var)
    swatch.grid(row=0, column=0, sticky='w')
    return frame


@WidgetLookupMulti('color', 'colour', 'rgb')
def widget_color_multi(
        parent: tk.Frame, values: List[Tuple[str, tk.StringVar]], conf: Property):
    """For color swatches, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values):
        swatch = make_color_swatch(parent, var)
        swatch.grid(row=row, column=column)
        add_tooltip(swatch, tim_text, delay=0)


def make_color_swatch(parent: tk.Frame, var: tk.StringVar, size=16) -> ttk.Label:
    """Make a single swatch."""
    # Note: tkinter requires RGB as ints, not float!

    def get_color():
        """Parse out the color."""
        color = var.get()
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

    def open_win(e):
        """Display the color selection window."""
        widget_sfx()
        r, g, b = get_color()
        new_color, tk_color = askcolor(
            color=(r, g, b),
            parent=parent.winfo_toplevel(),
            title=_('Choose a Color'),
        )
        if new_color is not None:
            r, g, b = map(int, new_color)  # Returned as floats, which is wrong.
            var.set('{} {} {}'.format(int(r), int(g), int(b)))

    swatch = ttk.Label(
        parent,
        relief='raised',
    )

    def update_image(var_name: str, var_index: str, operation: str):
        r, g, b = get_color()
        swatch['image'] = img.color_square(round(Vec(r, g, b)), size)

    update_image('', '', '')

    # Register a function to be called whenever this variable is changed.
    var.trace_add('write', update_image)

    utils.bind_leftclick(swatch, open_win)

    return swatch


@lru_cache(maxsize=20)
def timer_values(min_value: int, max_value: int) -> List[str]:
    """Return 0:38-like strings up to the max value."""
    return [
        '{}:{:02}'.format(i//60, i % 60)
        for i in range(min_value, max_value + 1)
    ]


@WidgetLookupMulti('Timer', 'MinuteSeconds')
def widget_minute_seconds_multi(
        parent: tk.Frame, values: List[Tuple[str, tk.StringVar]], conf: Property):
    """For timers, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values, columns=5):
        timer = widget_minute_seconds(parent, var, conf)
        timer.grid(row=row, column=column)
        add_tooltip(timer, tim_text, delay=0)


@WidgetLookup('Timer', 'MinuteSeconds')
def widget_minute_seconds(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Widget:
    """A widget for specifying times - minutes and seconds.

    The value is saved as seconds.
    Max specifies the largest amount.
    """
    max_value = conf.int('max', 60)
    min_value = conf.int('min', 0)
    if min_value > max_value:
        raise ValueError('Bad min and max values!')

    values = timer_values(min_value, max_value)

    # Stores the 'pretty' value in the actual textbox.
    disp_var = tk.StringVar()

    existing_value = var.get()

    def update_disp(var_name: str, var_index: str, operation: str) -> None:
        """Whenever the string changes, update the displayed text."""
        seconds = conv_int(var.get(), -1)
        if min_value <= seconds <= max_value:
            disp_var.set('{}:{:02}'.format(seconds // 60, seconds % 60))
        else:
            LOGGER.warning('Bad timer value "{}" for "{}"!', var.get(), conf['id'])
            # Recurse, with a known safe value.
            var.set(values[0])

    # Whenever written to, call this.
    var.trace_add('write', update_disp)

    def set_var():
        """Set the variable to the current value."""
        try:
            minutes, seconds = disp_var.get().split(':')
            var.set(str(int(minutes) * 60 + int(seconds)))
        except (ValueError, TypeError):
            pass

    def validate(reason: str, operation_type: str, cur_value: str, new_char: str, new_value: str):
        """Validate the values for the text.

        This is called when the textbox is modified, to allow cancelling bad
        inputs.

        Reason is the reason this was fired: 'key', 'focusin', 'focusout', 'forced'.
        operation_type is '1' for insert, '0' for delete', '-1' for programmatic changes.
        cur_val is the value before the change occurs.
        new_char is the added/removed text.
        new_value is the value after the change, if accepted.
        """
        if operation_type == '0' or reason == 'forced':
            # Deleting or done by the program, allow that always.
            return True

        if operation_type == '1':  # Inserted text.
            # Disallow non number and colons
            if new_char not in '0123456789:':
                return False
            # Only one colon.
            if ':' in cur_value and new_char == ':':
                return False

            # Don't allow more values if it has more than 2 numbers after
            # the colon - if there is one, and it's not in the last 3 characters.
            if ':' in new_value and ':' not in new_value[-3:]:
                return False

        if reason == 'focusout':
            # When leaving focus, apply range limits and set the var.
            try:
                str_min, str_sec = new_value.split(':')
                seconds = int(str_min) * 60 + int(str_sec)
            except (ValueError, TypeError):
                seconds = min_value
            else:
                if seconds < min_value:
                    seconds = min_value
                if seconds > max_value:
                    seconds = max_value
            var.set(str(seconds))  # This then re-writes the textbox.
        return True

    validate_cmd = parent.register(validate)

    spinbox = tk.Spinbox(
        parent,
        exportselection=False,
        textvariable=disp_var,
        command=set_var,
        wrap=True,
        values=values,
        width=5,

        validate='all',
        # These define which of the possible values will be passed along.
        # http://tcl.tk/man/tcl8.6/TkCmd/spinbox.htm#M26
        validatecommand=(validate_cmd, '%V', '%d', '%s', '%S', '%P'),
    )
    # We need to set this after, it gets reset to the first one.
    var.set(existing_value)
    return spinbox
