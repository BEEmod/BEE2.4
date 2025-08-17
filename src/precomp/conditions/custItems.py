"""Results for customising the behaviour of certain items - antlines, faith plates,

"""
from collections.abc import Callable
from srctools import Keyvalues, Entity

from precomp import connections, antlines, conditions


COND_MOD_NAME = 'Custom Items'


@conditions.make_result('custAntline', valid_before=conditions.MetaCond.Connections)
def res_cust_antline_setup(res: Keyvalues) -> Callable[[Entity], None]:
    """Customise the output antlines.

    The contents of the result block can be anything in the global
    [`Antlines` texturing](vbsp_config-texturing#Antlines) block. See those docs for details.
    If a section is not defined, the existing style definition is inherited.

    Additional options:

    * `toggle_var`: Deprecated. If set, the specified fixup name is set to the name of the antlines,
       and no outputs are defined. The instance can place its own texturetoggle and have full control
       over antlines. This is incompatible with antlasers, and doesn't allow for anything special
       with checkmarks/timers.
    * `remove_signs`: If true, delete all indicator signs (checkmarks or timers).
    """
    make_style = antlines.IndicatorStyle.parser(res, 'custAntline block')

    remove_signs = res.bool('remove_signs')

    def change_antlines(inst: Entity) -> None:
        """Change the antlines of an item."""
        item = connections.ITEMS[inst['targetname']]
        item.ind_style = make_style(item.ind_style)

        if remove_signs:
            for sign in item.ind_panels:
                sign.remove()
            item.ind_panels.clear()
    return change_antlines
