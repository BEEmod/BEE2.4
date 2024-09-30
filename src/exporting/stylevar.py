"""Export stylevar selections."""
from srctools import Keyvalues, bool_as_int
import trio

from config.widgets import WidgetConfig
from packages import ConfigGroup, StyleVar
import config

from . import STEPS, ExportData, StepResource


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_add_stylevars(exp_data: ExportData) -> None:
    """Export style var selections into the config.

    The .selected attribute is a dict mapping ids to the boolean value.
    """
    style_vars: dict[str, bool] = exp_data.selected[StyleVar]
    # Add the StyleVars block, containing each style_var.
    block = Keyvalues('StyleVars', [
        Keyvalues(key, bool_as_int(val))
        for key, val in
        style_vars.items()
    ])
    await trio.lowlevel.checkpoint()
    # Also add all widgets that were stylevars, so previous packages still function.
    for group in exp_data.packset.all_obj(ConfigGroup):
        await trio.lowlevel.checkpoint()
        for widget in group.widgets:
            if widget.stylevar_id:
                value = config.APP.get_cur_conf(WidgetConfig, widget.conf_id()).values
                if isinstance(value, str):
                    block[widget.stylevar_id] = value

    exp_data.vbsp_conf.append(block)
