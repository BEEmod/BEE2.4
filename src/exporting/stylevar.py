from typing import Dict
import copy

import srctools
from srctools import Keyvalues

import editoritems
import utils
from consts import DefaultItems
from . import ExportData, STEPS, StepResource
from packages import StyleVar


UNLOCK_ITEMS = {
    DefaultItems.door_sp_entry.id,
    DefaultItems.door_coop_entry.id,
    DefaultItems.door_sp_entry.id,
    DefaultItems.door_sp_exit.id,
    DefaultItems.obs_room_large.id,
}


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


@STEPS.add_step(prereq=[StepResource.EI_ITEMS], results=[StepResource.EI_DATA])
async def step_unlock_defaults(exp_data: ExportData) -> None:
    """If the unlock defaults stylevar is set, unlock the default items."""
    if not exp_data.selected[StyleVar]['UnlockDefault']:
        return

    for i, item in enumerate(exp_data.all_items):
        # If the Unlock Default Items stylevar is enabled, we
        # want to force the corridors and obs room to be
        # deletable and copyable.
        # Also add DESIRES_UP, so they place in the correct orientation.
        # That would have already been done for vertical-enabled corridors, but that's
        # fine.
        if utils.obj_id(item.id) in UNLOCK_ITEMS:
            exp_data.all_items[i] = item = copy.copy(item)
            item.deletable = item.copiable = True
            item.facing = editoritems.DesiredFacing.UP
