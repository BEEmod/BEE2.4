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


class ConfigGroup(PakObject):
    """A group of configs for an item."""
    def __init__(self, conf_id: str, group_name: str, desc, widgets):
        self.id = conf_id
        self.name = group_name
        self.desc = desc
        self.widgets = widgets

    @classmethod
    def parse(cls, data: ParseData) -> 'PakObject':
        props = data.info  # type: Property

        group_name = props['GroupName']
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
                default = tk.StringVar(
                    value=CONFIG.get_val(
                        data.id,
                        wid_id,
                        props['default'],
                    ),
                    name=wid_id,
                )
            else:
                default = [
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
            config = props.find_key('Config', [])

            widgets.append(Widget(
                wid_id,
                create_func,
                config,
                default,
                is_timer,
            ))

        return cls(
            data.id,
            group_name,
            desc,
            widgets,
        )

    @staticmethod
    def export(exp_data: ExportData):
        """We immediately write to the config.

        Exporting isn't needed.
        """
        pass

def make_pane(parent: ttk.Frame):
    pass


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