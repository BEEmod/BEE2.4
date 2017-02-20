"""Customizable configuration for specific items or groups of them."""
import random
import tkinter as tk
from tkinter import ttk
from tkinter.colorchooser import askcolor

from collections import namedtuple

from srctools import Property, Vec, conv_float
from packageLoader import PakObject, ExportData, ParseData, desc_parse
from BEE2_config import ConfigFile
from tooltip import add_tooltip
import utils
import img
import sound

from typing import Union, Callable, List, Dict, Optional, Tuple


LOGGER = utils.getLogger(__name__)

# Functions for each widget.
# The function is passed a parent frame, StringVar, and Property block.
WidgetLookup = utils.FuncLookup('Widgets')
# Override for timer-type widgets to be more compact - passed a num:var dict
# of StringVars instead. The widgets should insert themselves into the parent
# frame.
WidgetLookupMulti = utils.FuncLookup('Multi-Widgets')

CONFIG = ConfigFile('item_cust_configs.cfg')

CONFIG_ORDER = []  # type: List[ConfigGroup]

TIMER_NUM = ['inf'] + list(map(str, range(3, 31)))

INF = '∞'


class Widget:
    """Represents a widget that can appear on a ConfigGroup."""
    def __init__(
        self,
        wid_id: str,
        name: str,
        create_func: Callable[[tk.Frame, tk.StringVar, Property], None],
        multi_func: Callable[[tk.Frame, List[Tuple[str, tk.StringVar]], Property], None],
        config: Property,
        values: Union[tk.StringVar, Dict[Union[int, str], tk.StringVar]],
        is_timer: bool,
        use_inf: bool,
    ):
        self.id = wid_id
        self.name = name
        self.values = values
        self.config = config
        self.create_func = create_func
        self.multi_func = multi_func
        self.is_timer = is_timer
        self.use_inf = use_inf  # For timer, is infinite valid?


class ConfigGroup(PakObject, allow_mult=False, has_img=False):
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

        group_name = props['Name']
        desc = desc_parse(props, data.id)

        widgets = []
        multi_widgets = []

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
            default = wid.find_key('Default')
            if is_timer:
                if default.has_children():
                    defaults = {
                        num: default[num]
                        for num in TIMER_NUM
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

    @staticmethod
    def export(exp_data: ExportData):
        """Write all our values to the config."""
        for conf in CONFIG_ORDER:
            config_section = CONFIG[conf.id]
            for wid in conf.widgets:
                config_section[wid.id] = wid.values.get()
            for wid in conf.multi_widgets:
                for num, var in wid.values:
                    config_section['{}_{}'.format(wid.id, num)] = var.get()
        CONFIG.save_check()


def make_pane(parent: ttk.Frame):
    """Create all the widgets we use."""
    if not CONFIG_ORDER:
        # No configs at all...
        ttk.Label(parent, text=_('No Item Configuration!')).pack(fill='both')
        return

    CONFIG_ORDER.sort(key=lambda grp: grp.name)

    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(1, weight=1)

    item_frames = []  # type: List[ttk.Frame]

    def swap_to_item(e: tk.Event=None):
        """Swap what's shown in the pane."""
        for frame in item_frames:
            frame.grid_forget()

        cur_dropdown = dropdown.current()
        if cur_dropdown == -1:
            # Not valid
            return

        # Block sound for the first few millisec to stop excess sounds from
        # playing during gridding.
        sound.block_fx()

        item_frames[cur_dropdown].grid(row=1, column=0, sticky='nsew')

    dropdown = ttk.Combobox(
        parent,
        state='readonly',
        exportselection=False,
        values=[
            group.name
            for group in
            CONFIG_ORDER
        ],
    )
    dropdown.grid(row=0, column=0, columnspan=2, sticky='ew')
    dropdown.bind('<<ComboboxSelected>>', swap_to_item)

    # need to use a canvas to allow scrolling
    canvas = tk.Canvas(parent, highlightthickness=0)
    canvas.grid(row=1, column=0, sticky='NSEW')
    parent.rowconfigure(1, weight=1)

    scrollbar = ttk.Scrollbar(
        parent,
        orient='vertical',
        command=canvas.yview,
    )
    scrollbar.grid(column=1, row=1, sticky="ns")
    canvas['yscrollcommand'] = scrollbar.set

    utils.add_mousewheel(canvas, parent)
    canvas_frame = ttk.Frame(canvas)
    canvas.create_window(0, 0, window=canvas_frame, anchor="nw")
    canvas_frame.rowconfigure(0, weight=1)

    for config in CONFIG_ORDER:
        frame = ttk.Frame(canvas_frame)
        frame.columnconfigure(0, weight=1)
        item_frames.append(frame)

        # Now make the widgets.
        if config.widgets:
            non_timer_frame = ttk.LabelFrame(frame, text=_('General'))
            non_timer_frame.grid(row=0, column=0, sticky='ew')
            non_timer_frame.columnconfigure(1, weight=1)

            for row, wid in enumerate(config.widgets):
                label = ttk.Label(non_timer_frame, text=wid.name)
                label.grid(row=row, column=0)
                widget = wid.create_func(non_timer_frame, wid.values, wid.config)
                widget.grid(row=row, column=1, sticky='ew')

        if config.widgets and config.multi_widgets:
            ttk.Separator(orient='horizontal').grid(
                row=1, column=0, sticky='ew',
            )

        # Skip if no timer widgets
        if not config.multi_widgets:
            continue

        for row, wid in enumerate(config.multi_widgets):

            wid_frame = ttk.LabelFrame(frame, text=wid.name)
            wid_frame.grid(row=2 + row, column=0, sticky='ew')
            wid_frame.columnconfigure(1, weight=1)

            wid.multi_func(
                wid_frame,
                wid.values,
                wid.config,
            )

    # Select the first item, so we show something.
    dropdown.current(0)
    swap_to_item()

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


def multi_grid(values: List[Tuple[str, tk.StringVar]]):
    """Generate the row and columns needed for a nice layout of square widgets."""
    for tim, var in values:
        if tim == 'inf':
            tim_disp = INF
            index = 0
        else:
            tim_disp = str(tim)
            index = int(tim)
        row, column = divmod(index - 1, 10)
        yield row, column, tim_disp, var


def widget_sfx(*args):
    """Play sounds when interacting."""
    sound.fx_blockable('config')


# ------------
# Widget types
# ------------

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
    return ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
        command=widget_sfx,
    )


@WidgetLookupMulti('boolean', 'bool', 'checkbox')
def widget_checkmark(
        parent: tk.Frame, values: List[Tuple[str, tk.StringVar]], conf: Property):
    """For timers, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values):
        checkbox = widget_checkmark(parent, var, conf)
        checkbox.grid(row=row, column=column)
        add_tooltip(checkbox, tim_text, delay=0)


@WidgetLookup('range', 'slider')
def widget_slider(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
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
def widget_color_single(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
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
    """For timers, display in a more compact form."""
    for row, column, tim_text, var in multi_grid(values):
        swatch = make_color_swatch(parent, var)
        swatch.grid(row=row, column=column)
        add_tooltip(swatch, tim_text, delay=0)


def make_color_swatch(parent: tk.Frame, var: tk.StringVar, size=16) -> ttk.Label:
    """Make a single swatch."""
    color = var.get()
    if color.startswith('#'):
        try:
            r, g, b = int(var[0:2], base=16), int(var[2:4], base=16), int(var[4:], base=16)
        except ValueError:
            LOGGER.warning('Invalid RGB value: "{}"!', color)
            r = g = b = 128
    else:
        r, g, b = Vec.from_str(color, 128, 128, 128)

    def open_win(e):
        """Display the color selection window."""
        nonlocal r, g, b
        widget_sfx()
        new_color, tk_color = askcolor(
            color=(r, g, b),
            parent=parent.winfo_toplevel(),
            title=_('Choose a Color'),
        )
        if new_color is not None:
            r, g, b = new_color
            var.set('{} {} {}'.format(int(r), int(g), int(b)))
            swatch['image'] = img.color_square(round(Vec(r, g, b)), size)

    swatch = ttk.Label(
        parent,
        relief='raised',
        image=img.color_square(Vec(r, g, b), size),
    )
    utils.bind_leftclick(swatch, open_win)

    return swatch

