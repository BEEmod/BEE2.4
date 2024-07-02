"""Export the selected skybox/fog configuration."""
from __future__ import annotations
from srctools import bool_as_int

from . import ExportData, STEPS, StepResource
from packages import Skybox
import utils


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_skybox(exp_data: ExportData) -> None:
    """Export the selected skybox."""
    sel_id: utils.SpecialID = exp_data.selected[Skybox]
    if sel_id == utils.ID_NONE:
        return  # No skybox..

    try:
        skybox = exp_data.packset.obj_by_id(Skybox, sel_id)
    except KeyError:
        raise Exception(f"Selected skybox ({exp_data.selected}) doesn't exist?") from None

    exp_data.vbsp_conf.set_key(('Options', 'skybox'), skybox.material)
    exp_data.vbsp_conf.set_key(('Options', 'sky_draw_first'), bool_as_int(skybox.draw_first))

    exp_data.vbsp_conf.extend(await skybox.config())

    # Styles or other items shouldn't be able to set fog settings..
    if 'fog' in exp_data.vbsp_conf:
        del exp_data.vbsp_conf['fog']

    fog_opts = skybox.fog_opts.copy()
    fog_opts.name = 'Fog'

    exp_data.vbsp_conf.append(fog_opts)
