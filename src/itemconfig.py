"""Customizable configuration for specific items or groups of them."""
import tkinter as tk
from tkinter import ttk
from tkinter.colorchooser import askcolor

from collections import namedtuple

from srctools import Property, Vec
from packageLoader import PakObject, ExportData, ParseData, desc_parse
from BEE2_config import ConfigFile
import utils
import img

from typing import Union, Callable, List, Dict


LOGGER = utils.getLogger(__name__)

# Functions for each widget.
# The function is passed a parent frame, StringVar, and Property block.
WIDGETS = utils.FuncLookup('Widgets')

CONFIG = ConfigFile('item_cust_configs.cfg')

CONFIG_ORDER = []  # type: List[ConfigGroup]

TIMER_NUM = ['inf'] + list(map(str, range(3, 31)))


class Widget:
    """Represents a widget that can appear on a ConfigGroup."""
    def __init__(
        self,
        wid_id: str,
        name: str,
        create_func: Callable[[tk.Frame, tk.StringVar, Property], None],
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
        timer_widgets: List['Widget'],
    ):
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets
        self.timer_widgets = timer_widgets

    @classmethod
    def parse(cls, data: ParseData) -> 'PakObject':
        props = data.info  # type: Property

        group_name = props['Name']
        desc = desc_parse(props, data.id)

        widgets = []
        timer_widgets = []

        for wid in props.find_all('Widget'):
            try:
                create_func = WIDGETS[wid['type']]
            except KeyError:
                LOGGER.warning(
                    'Unknown widget type "{}" in <{}:{}>!',
                    wid['type'],
                    data.pak_id,
                    data.id,
                )
                continue

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
                values = {
                    num: tk.StringVar(
                        value=CONFIG.get_val(
                            data.id,
                            '{}_{}'.format(wid_id, num),
                            defaults[num],
                        ),
                        name='itemconf_{}_{}_{}'.format(data.id, wid_id, num)
                    )
                    for num in TIMER_NUM
                    # Exclude infinite if use_inf is False.
                    if use_inf or num != 'inf'
                }
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
                print(values.set(values.get()))

            (timer_widgets if is_timer else widgets).append(Widget(
                wid_id,
                name,
                create_func,
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
            timer_widgets,
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
            for wid in conf.timer_widgets:
                for num in TIMER_NUM:
                    if num == 'inf' and not wid.use_inf:
                        continue
                    config_section['{}_{}'.format(wid.id, num)] = wid.values[num].get()
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

    def swap_to_item():
        """Swap what's shown in the pane."""
        for frame in item_frames:
            frame.grid_forget()

        cur_dropdown = dropdown.current()
        if cur_dropdown == -1:
            # Not valid
            return
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
        postcommand=swap_to_item,
    )
    dropdown.grid(row=0, column=0, columnspan=2, sticky='ew')

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

        if config.widgets and config.timer_widgets:
            ttk.Separator(orient='horizontal').grid(
                row=1, column=0, sticky='ew',
            )

        # Skip if no timer widgets
        if not config.timer_widgets:
            continue

        for timer_ind, timer in enumerate(TIMER_NUM):
            if timer == 'inf':
                if not any(wid.use_inf for wid in config.timer_widgets):
                    continue
                timer_disp = '∞'
            else:
                timer_disp = str(timer)

            timer_frame = ttk.LabelFrame(frame, text=_('Timer: {}').format(timer_disp))
            timer_frame.grid(row=2 + timer_ind, column=0, sticky='ew')
            timer_frame.columnconfigure(1, weight=1)

            for subrow, wid in enumerate(config.timer_widgets):
                if timer == 'inf' and not wid.use_inf:
                    continue

                label = ttk.Label(timer_frame, text=wid.name)
                label.grid(row=subrow, column=0)
                widget = wid.create_func(
                    timer_frame,
                    wid.values[timer],
                    wid.config,
                )
                widget.grid(row=subrow, column=1, sticky='ew')

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

# ------------
# Widget types
# ------------


@WIDGETS('string', 'str')
def widget_string(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Simple textbox for entering text."""
    return ttk.Entry(
        parent,
        textvariable=var,
    )


@WIDGETS('boolean', 'bool', 'checkbox')
def widget_checkmark(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Allows ticking a box."""
    return ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
    )


@WIDGETS('range', 'slider')
def widget_slider(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Provides a slider for setting a number in a range."""
    return tk.Scale(
        parent,
        orient='horizontal',
        from_=conf.float('min'),
        to=conf.float('max', 100),
        resolution=conf.float('step', 1),
        variable=var,
    )


@WIDGETS('color', 'colour', 'rgb')
def widget_color(parent: tk.Frame, var: tk.StringVar, conf: Property) -> tk.Misc:
    """Provides a colour swatch for specifying colours.

    Values can be provided as #RRGGBB, but will be written as 3 0-255 values.
    """

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
        nonlocal r, g, b
        color, tk_color = askcolor(
            color=(r, g, b),
            parent=parent.winfo_toplevel(),
            title=_('Choose a Color'),
        )
        if color is not None:
            r, g, b = color
            var.set('{} {} {}'.format(int(r), int(g), int(b)))
            swatch['image'] = img.color_square(round(Vec(r, g, b)))

    # Isolates the swatch so it doesn't resize.
    frame = ttk.Frame(parent)
    swatch = ttk.Label(
        frame,
        relief='raised',
        image=img.color_square(Vec(r, g, b)),
    )
    utils.bind_leftclick(swatch, open_win)
    swatch.grid(row=0, column=0, sticky='w')

    return frame

