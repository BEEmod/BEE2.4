from typing import Dict

import srctools
from srctools import Keyvalues

from exporting import STEPS, StepResource
from packages import ExportData, StyleVar


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_add_stylevars(exp_data: ExportData) -> None:
    """Export style var selections into the config.

    The .selected attribute is a dict mapping ids to the boolean value.
    """
    style_vars: Dict[str, bool] = exp_data.selected[StyleVar]
    # Add the StyleVars block, containing each style_var.
    exp_data.vbsp_conf.append(Keyvalues('StyleVars', [
        Keyvalues(key, srctools.bool_as_int(val))
        for key, val in
        style_vars.items()
    ]))
