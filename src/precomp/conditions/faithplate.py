"""Modify and inspect faith plates."""
from srctools import Angle, Keyvalues, Entity, logger
from precomp import faithplate, template_brush, conditions
from precomp.lazy_value import LazyValue


COND_MOD_NAME = 'Faith Plates'
LOGGER = logger.get_logger(__name__, alias='cond.faithplate')


@conditions.make_test("FaithType")
def test_faith_type(inst: Entity, kv: Keyvalues) -> bool:
    """Determine the type of faith plate used.

    The value can be set to 'straight', 'straightup', 'angled',
    or 'any' to detect those types of plates.
    """
    plate = faithplate.PLATES.get(inst['targetname'])

    # Paint droppers are not faith plates and can be detected by
    # instance filename. So pretend we didn't find it.
    if isinstance(plate, faithplate.PaintDropper):
        plate = None

    des_type = kv.value.casefold()

    if des_type == 'any':
        return plate is not None
    elif des_type in ('straight', 'straightup'):
        return isinstance(plate, faithplate.StraightPlate)
    elif des_type == 'angled':
        return isinstance(plate, faithplate.AngledPlate)
    else:
        LOGGER.warning(
            'Unknown faith plate type "{}" '
            '(expected straight, straightup, angled, any).',
            des_type,
        )
        return plate is not None


@conditions.make_result('setFaithAttrs', 'setFaith', 'setFaithAttr')
def res_set_faith(res: Keyvalues) -> conditions.ResultCallable:
    """Modify the `trigger_catapult`s used for `ItemFaithPlate` items.

    This can also be used to modify the catapult for bomb-type Gel Droppers.

    - `template`: The template used for the catapult trigger. For the additional
      helper trigger, it will be offset upward.
    - `offset`: Allow shifting the triggers around.
    """
    temp_name = res['template', '']

    if temp_name:
        template = template_brush.get_template(temp_name)
    else:
        template = None
    offset = LazyValue.parse(res['offset', '']).as_vec()

    def apply_attrs(inst: Entity) -> None:
        """Apply the modification."""
        try:
            plate = faithplate.PLATES[inst['targetname']]
        except KeyError:
            LOGGER.warning(
                'No faithplate for item with name "{}"!',
                inst['targetname'],
            )
        else:
            if template is not None:
                plate.template = template

            if offset is not None:
                plate.trig_offset = offset(inst) @ Angle.from_str(inst['angles'])
    return apply_attrs


@conditions.make_result('faithMods')
def res_faith_mods() -> object:
    """This result is deprecated.

    The functions provided by this have been replaced by other features:
    - `FaithType` can be used to check the type of the plate.
    - `setFaithAttrs` can be used to modify the trigger.
    - Use the `comp_kv_setter` entity to add outputs or modify keyvalues
      on the trigger(s).
    """
    LOGGER.warning(
        'The "faithMods" result is deprecated. '
        'Use "FaithType" and "setFaithAttrs" instead, '
        'along with comp_kv_setter.'
    )
    return conditions.RES_EXHAUSTED
