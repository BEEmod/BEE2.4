"""Results for customising the behaviour of certain items - antlines, faith plates,

"""
from collections.abc import Callable
from srctools import Keyvalues, Entity

from precomp import connections, antlines, conditions


COND_MOD_NAME = 'Custom Items'


@conditions.make_result('custAntline', valid_before=conditions.MetaCond.Connections)
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
    make_style = antlines.IndicatorStyle.parser(res, 'custAntline block')

    remove_signs = res.bool('remove_signs')
    toggle_var = res['toggle_var', '']

    def change_antlines(inst: Entity) -> None:
        """Change the antlines of an item."""
        item = connections.ITEMS[inst['targetname']]
        item.ind_style = make_style(item.ind_style)

        if remove_signs:
            for sign in item.ind_panels:
                sign.remove()
            item.ind_panels.clear()

        if toggle_var:
            item.ant_toggle_var = toggle_var
    return change_antlines
