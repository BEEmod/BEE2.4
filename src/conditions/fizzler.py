"""Results for custom fizzlers."""
import conditions
import srctools
import utils
import vbsp
import instanceLocs
import comp_consts as const
import template_brush
from conditions import (
    make_result, meta_cond,
    ITEMS_WITH_CLASS, CONNECTIONS
)
from srctools import Vec, Property, VMF, Entity, Solid, Output
from vbsp import TEX_FIZZLER

from typing import List, Dict

COND_MOD_NAME = 'Fizzlers'

LOGGER = utils.getLogger(__name__, alias='cond.fizzler')
