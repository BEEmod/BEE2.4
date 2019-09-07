"""Modify and inspect faith plates."""
from typing import Callable

import srctools.logger
import connections
import faithplate
import template_brush
from conditions import (
    make_flag, make_result, make_result_setup,
    resolve_value, local_name,
)
from srctools import Property, Entity, Output, Vec, VMF


COND_MOD_NAME = 'Faith Plates'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.faithplate')


@make_flag("FaithType")
def flag_faith_type(inst: Entity, flag: Property) -> bool:
    """Determine the type of faith plate used.

    The value can be set to 'straight', 'angled', or 'any' to detect those
    types of plates.
    """
    plate = faithplate.PLATES.get(inst['targetname'])

    des_type = flag.value.casefold()

    if des_type == 'any':
        return plate is not None
    elif des_type == 'straight':
        return isinstance(plate, faithplate.StraightPlate)
    elif des_type == 'angled':
        return isinstance(plate, faithplate.AngledPlate)
    else:
        LOGGER.warning(
            'Unknown faith plate type "{}" '
            '(expected straight, angled, any).',
            des_type,
        )
        return plate is not None


@make_result_setup('setFaithAttrs', 'setFaith')
def res_set_faith_setup(res: Property) -> tuple:
    temp_name = res['template', '']

    if temp_name:
        template = template_brush.get_template(temp_name)
    else:
        template = None

    return (
        template,
        res.vec('offset'),
    )


@make_result('setFaithAttrs', 'setFaith')
def res_set_faith(inst: Entity, res: Property) -> None:
    """Modify the `trigger_catapult`s used for `ItemFaithPlate` items.

    - `template`: The template used for the catapult trigger. For the additional
      helper trigger, it will be offset upward.
    - `offset`: Allow shifting the triggers around.
    """
    """Apply the modification."""
    try:
        plate = faithplate.PLATES[inst['targetname']]
    except KeyError:
        LOGGER.warning(
            'No faithplate for item with name "{}"!',
            inst['targetname'],
        )
        return

    (
        template,
        offset,
    ) = res.value
    if template is not None:
        plate.template = template

    if offset is not None:
        plate.trig_offset = offset.copy().rotate_by_str(inst['angles'])


@make_result('faithMods')
def res_faith_mods(vmf: VMF, inst: Entity, res: Property) -> None:
    """Modify the `trigger_catapult` that is created for `ItemFaithPlate` items.

    Values:

    - `raise_trig`: Raise or lower the `trigger_catapult`s by this amount.
    - `angled_targ`, `angled_in`: Instance entity and input for angled plates
    - `straight_targ`, `straight_in`: Instance entity and input for
      straight plates
    - `instvar`: A $replace value to set to either 'angled' or '
      'straight'.
    - `enabledVar`: A `$replace` value which will be copied to the main
      trigger's Start Disabled value (and inverted).
    - `trig_temp`: An ID for a template brush to add. This will be offset by
      the trigger's position (in the case of the `helper` trigger).
    """
    LOGGER.warning(
        'The "faithMods" result is deprecated. '
        'Use "FaithType" and "setFaithAttrs" instead, '
        'along with comp_kv_setter.'
    )
