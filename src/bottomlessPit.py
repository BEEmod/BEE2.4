"""Generates Bottomless Pits."""
from srctools import Vec, Property
import vbsp

# The base of a pit must be below this z-pos to be considered a pit.
# It must basically be one of the bottom two grid positions.
BOTTOMLESS_PIT_MIN = 192


def pits_allowed():
    """Are bottomless pits allowed in the configs?"""
    return vbsp.settings['pit'] is not None


def is_pit(bbox_min, bbox_max):
    """Check if the given location can be a bottomless pit."""
    return BOTTOMLESS_PIT_MIN >= bbox_min.z