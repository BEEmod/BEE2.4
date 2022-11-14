"""Results for customising the behaviour of certain items - antlines, faith plates,

"""
from __future__ import annotations
from typing import Callable
from srctools import Keyvalues, Entity
import srctools.logger

from precomp import connections, antlines, conditions


COND_MOD_NAME = 'Custom Items'

LOGGER = srctools.logger.get_logger(__name__, alias='cond.custItems')


@conditions.make_result('custAntline')
def res_cust_antline_setup(res: Keyvalues) -> Callable[[Entity], None]:
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
    wall_style: antlines.AntType | None
    floor_type: antlines.AntType | None
    if 'wall' in res:
        wall_style = antlines.AntType.parse(res.find_key('wall'))
    else:
        wall_style = None

    if 'floor' in res:
        floor_style = antlines.AntType.parse(res.find_key('floor'))
    else:
        floor_style = wall_style

    remove_signs = res.bool('remove_signs')
    toggle_var = res['toggle_var', '']

    def change_antlines(inst: Entity) -> None:
        """Change the antlines of an item."""
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
    return change_antlines


@conditions.make_result('changeOutputs')
def res_change_outputs() -> object:
    """Deprecated, use ChangeIOType."""
    LOGGER.warning('ChangeOutputs is deprecated. Use ChangeIOType.')
    return conditions.RES_EXHAUSTED


@conditions.make_result('changeInputs')
def res_change_inputs() -> object:
    """Deprecated, use ChangeIOType."""
    LOGGER.warning('ChangeInputs is deprecated. Use ChangeIOType.')
    return conditions.RES_EXHAUSTED
