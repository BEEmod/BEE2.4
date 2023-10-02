"""Export selected elevator videos."""
from typing import Optional

from exporting import STEPS, StepResource
from packages import ExportData, Elevator


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_elevator_video(exp_data: ExportData) -> None:
    """Export the chosen video into the configs."""
    elevator: Optional[Elevator]
    sel_id: Optional[str] = exp_data.selected[Elevator]
    if sel_id is None:
        elevator = None
    else:
        try:
            elevator = exp_data.packset.obj_by_id(Elevator, sel_id)
        except KeyError:
            raise Exception(f"Selected elevator ({exp_data.selected}) doesn't exist?") from None

    if exp_data.selected_style.has_video:
        if elevator is None:
            # Use a randomised video
            exp_data.vbsp_conf.set_key(('Elevator', 'type'), 'RAND')
        elif elevator.id == 'VALVE_BLUESCREEN':
            # This video gets a special script and handling
            exp_data.vbsp_conf.set_key(('Elevator', 'type'), 'BSOD')
        else:
            # Use the particular selected video
            exp_data.vbsp_conf.set_key(('Elevator', 'type'), 'FORCE')
            exp_data.vbsp_conf.set_key(('Elevator', 'horiz'), elevator.horiz_video)
            exp_data.vbsp_conf.set_key(('Elevator', 'vert'), elevator.vert_video)
    else:  # No elevator video for this style
        exp_data.vbsp_conf.set_key(('Elevator', 'type'), 'NONE')
