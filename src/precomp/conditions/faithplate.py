"""Modify and inspect faith plates."""
from srctools import Angle, Keyvalues, Entity, logger, Vec
from precomp import faithplate, template_brush, conditions
from precomp.lazy_value import LazyValue


COND_MOD_NAME = 'Faith Plates'
LOGGER = logger.get_logger(__name__, alias='cond.faithplate')


@conditions.make_test(
    "FaithType",
    valid_after=conditions.MetaCond.FaithPlate,
)
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


@conditions.make_result(
    'setFaithAttrs', 'setFaith', 'setFaithAttr',
    valid_after=conditions.MetaCond.FaithPlate,
)
def res_set_faith(res: Keyvalues) -> conditions.ResultCallable:
    """Modify the `trigger_catapult`s used for `ItemFaithPlate` items.

    This can also be used to modify the catapult for bomb-type Gel Droppers.

    - `paintBombFix`: Controls whether to make paint bomb launching
      reliable, by using an additional larger trigger. Disable to save ents if your plate
      can't come in contact with those.
    - `template`: The template used for the catapult trigger. For the additional
      helper trigger, it will be offset upward.
    - `templatePaintBomb`: If set, should be a larger template used for paint bombs.
       This should also be provided if you override the template, and have this enabled.
    - `offset`: Allow shifting the triggers around.
    """
    conf_temp_name = LazyValue.parse(res['template', ''])
    conf_paint_temp_name = LazyValue.parse(res['templatePaintBomb', ''])
    conf_paint_bomb_fix = LazyValue.parse(res['paintBombFix']).as_opt_bool()

    try:
        offset_str = res['offset']
    except LookupError:
        offset: LazyValue[Vec] | None = None
    else:
        offset = LazyValue.parse(offset_str).as_vec()

    def apply_attrs(inst: Entity) -> None:
        """Apply the modification."""
        try:
            plate = faithplate.PLATES[inst['targetname']]
        except KeyError:
            LOGGER.warning(
                'No faithplate for item with name "{}"!',
                inst['targetname'],
            )
            return

        temp_name = conf_temp_name(inst)
        paint_temp_name = conf_paint_temp_name(inst)
        paint_bomb_fix = conf_paint_bomb_fix(inst)
        if paint_bomb_fix is not None:
            plate.paint_bomb_fix = paint_bomb_fix
        if temp_name:
            plate.template = temp_name
            if paint_temp_name:
                plate.template_paint = paint_temp_name
            else:
                # We silently ignore if you also disabled the paint bomb fixing.
                if plate.paint_bomb_fix:
                    LOGGER.warning(
                        'Faithplate trigger "{}" provided for item "{}", but no paint template '
                        'was provided. Paint bomb interaction is disabled.'
                    )
                    plate.paint_bomb_fix = False
                # Set the template so you get reasonable behaviour if paint bomb fixing is turned
                # on later again.
                plate.template_paint = temp_name

        if offset is not None:
            plate.trig_offset = offset(inst) @ Angle.from_str(inst['angles'])
    return apply_attrs
