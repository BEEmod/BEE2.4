"""Results for customising the behaviour of certain items - antlines, faith plates,

"""
from typing import Optional, Tuple
from srctools import Property, Entity
import srctools.logger

from precomp import connections, antlines, conditions


COND_MOD_NAME = 'Custom Items'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.custItems')


@conditions.make_result_setup('custAntline')
def res_cust_antline_setup(res: Property):
    if 'wall' in res:
        wall_type = antlines.AntType.parse(res.find_key('wall'))
    else:
        wall_type = None

    if 'floor' in res:
        floor_type = antlines.AntType.parse(res.find_key('floor'))
    else:
        floor_type = wall_type

    return (
        wall_type,
        floor_type,
        res.bool('remove_signs'),
        res['toggle_var', ''],
    )

CustAntValue = Tuple[Optional[antlines.AntType], Optional[
    antlines.AntType], bool, str]


@conditions.make_result('custAntline')
def res_cust_antline(inst: Entity, res: Property):
    """Customise the output antlines.

    Options:

    * `wall`: The configuration for antlines on walls. Same as global
        style options.
    * `floor`: The configuration for floor/ceiling antlines. If not provided,
        this is assumed to be the same as `wall`.
    * `remove_signs`: If true, remove the indicator signs.
    * `toggle_var`: If set, this item controls the toggle state fully of its
        antlines. This is a fixup var which will be set to the name of the
        overlays, for user control.
    """
    wall_style, floor_style, remove_signs, toggle_var = res.value  # type: CustAntValue

    item = connections.ITEMS[inst['targetname']]
    if wall_style is not None:
        item.ant_wall_style = wall_style
    if floor_style is not None:
        item.ant_floor_style = floor_style

    if remove_signs:
        for sign in item.ind_panels:
            sign.remove()
        item.ind_panels.clear()

    if toggle_var:
        item.ant_toggle_var = toggle_var


@conditions.make_result('changeOutputs')
def res_change_outputs():
    """Deprecated, use ChangeIOType."""
    LOGGER.warning('ChangeOutputs is deprecated. Use ChangeIOType.')
    return conditions.RES_EXHAUSTED


@conditions.make_result('changeInputs')
def res_change_inputs():
    """Deprecated, use ChangeIOType."""
    LOGGER.warning('ChangeInputs is deprecated. Use ChangeIOType.')
    return conditions.RES_EXHAUSTED
