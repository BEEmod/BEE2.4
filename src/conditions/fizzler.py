"""Results for custom fizzlers."""
import utils
from conditions import (
    make_result, meta_cond,
    ITEMS_WITH_CLASS, CONNECTIONS
)
from srctools import Property, Entity
import fizzler

COND_MOD_NAME = 'Fizzlers'

LOGGER = utils.getLogger(__name__, alias='cond.fizzler')


@make_result('ChangeFizzlerType')
def res_change_fizzler_type(inst: Entity, res: Property):
    """Change the type of a fizzler. Only valid when run on the base instance."""
    fizz_name = inst['targetname']
    try:
        fizz = fizzler.FIZZLERS[fizz_name]
    except KeyError:
        LOGGER.warning('ChangeFizzlerType not run on a fizzler ("{}")!', fizz_name)
        return

    try:
        fizz.fizz_type = fizzler.FIZZ_TYPES[res.value]
    except KeyError:
        raise ValueError('Invalid fizzler type "{}"!', res.value)
