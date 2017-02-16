"""Customizable configuration for specific items or groups of them."""
import tkinter as tk
from tkinter import ttk
from tk_tools import TK_ROOT

from collections import namedtuple

from srctools import Property, Vec
from packageLoader import PakObject, ExportData, ParseData, get_config, desc_parse
from BEE2_config import ConfigFile
import utils
import srctools

from typing import List, Callable

LOGGER = utils.getLogger(__name__)

# Functions for each widget.
# The function is passed a parent frame, StringVar, and Property block.
WIDGETS = utils.FuncLookup('Widgets')

CONFIG = ConfigFile('item_cust_configs.cfg')

CONFIG_ORDER = []  # type: List[ConfigGroup]


class ConfigGroup(PakObject, allow_mult=False, has_img=False):
    """A group of configs for an item."""
    def __init__(self, conf_id: str, group_name: str, desc, widgets):
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets

    @classmethod
    def parse(cls, data: ParseData) -> 'PakObject':
        props = data.info  # type: Property

        group_name = props['Name']
        desc = desc_parse(props, data.id)

        widgets = []

        for wid in props.find_all('Widget'):
            try:
                create_func = WIDGETS[wid['type']]
            except KeyError:
                LOGGER.warning('Unknown widget type "{}" in <{}:{}>!')
                continue

            is_timer = props.bool('UseTimer')
            wid_id = wid['id'].casefold()
            if is_timer:
                values = tk.StringVar(
                    value=CONFIG.get_val(
                        data.id,
                        wid_id,
                        props['default'],
                    ),
                    name=wid_id,
                )
            else:
                values = [
                    tk.StringVar(
                        value=CONFIG.get_val(
                            data.id,
                            '{}_{}'.format(wid_id, i),
                            props['default'],
                        ),
                        name='{}_{}'.format(wid_id, i)
                    )
                    for i in range(3, 31)
                ]

            widgets.append(Widget(
                wid_id,
                create_func,
                props,
                values,
                is_timer,
            ))

        group = cls(
            data.id,
            group_name,
            desc,
            widgets,
        )
        CONFIG_ORDER.append(group)
        return group

    @staticmethod
    def export(exp_data: ExportData):
        """We immediately write to the config.

        Exporting isn't needed.
        """
        pass


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
    dropdown.grid(row=0, column=0, sticky='ew')

    for config in CONFIG_ORDER:
        frame = ttk.Labelframe(text=config.name)
        item_frames.append(frame)
        
    swap_to_item()



class Widget:
    def __init__(
        self,
        wid_id: str,
        create_func: Callable[[tk.Frame, tk.StringVar], None],
        config: Property,
        values: List[tk.StringVar],
        is_timer: bool,
    ):
        self.id = wid_id
        self.values = values
        self.config = config
        self.create_func = create_func
        self.is_timer = is_timer


# ------------
# Widget types
# ------------


@WIDGETS('string', 'str')
def widget_string(parent: tk.Frame, var: tk.StringVar, conf: Property):
    """Simple textbox for entering text."""
    wid = ttk.Entry(
        parent,
        textvariable=var,
    )
    wid.pack(fill='both')


@WIDGETS('boolean', 'bool', 'checkbox')
def widget_checkmark(parent: tk.Frame, var: tk.StringVar, conf: Property):
    """Allows ticking a box."""

    wid = ttk.Checkbutton(
        parent,
        text='',
        variable=var,
        onvalue='1',
        offvalue='0',
    )
    wid.pack(fill='both')


@WIDGETS('range', 'slider')
def widget_slider(parent: tk.Frame, var: tk.StringVar, conf: Property):
    """Provides a slider for setting a number in a range."""

    min_value = conf.float('min')

    var.trace_variable(
        'w',
        lambda: wid.set(srctools.conv_float(var.get(), min_value))
    )

    wid = tk.Scale(
        parent,
        from_=min_value,
        to=conf.float('max', 100),
        resolution=conf.float('step', 1),
        command=lambda: var.set(wid.get()),
        value=srctools.conv_float(var.get(), min_value),
    )
    wid.pack(fill='both')