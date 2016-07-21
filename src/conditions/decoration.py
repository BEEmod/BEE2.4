"""Randomly decorates unused blocks with props and missing tiles.

"""
from brushLoc import Block, POS

from typing import Union, Tuple, Callable

# Strings to combinations of blocks. Either a Block, tuple, or callable.
OCCUPY_TYPES = {
    'VOID': Block.VOID,
    # Pits are also empty...
    'AIR': (Block.AIR, Block.PIT_TOP, Block.PIT_MID),
    'SOLID': Block.SOLID,
    'EMBED': Block.EMBED,

    'GOO_FLOOR': (Block.GOO_BOTTOM, Block.GOO_SINGLE),
    'GOO_SURFACE': (Block.GOO_TOP, Block.GOO_SINGLE),

    'PIT_BOTTOM': (Block.PIT_BOTTOM, Block.PIT_SINGLE),
    'PIT_TOP': (Block.PIT_TOP, Block.PIT_SINGLE),

    'GOO': Block.is_goo,
    'BLOCK': Block.is_solid,
    'PIT': Block.is_pit,
}


def valid_pos(
    pos: Block,
    occu_type: Union[Block, Tuple[Block], Callable[[Block], bool]]
) -> bool:
    """Checks if a OCCUPY_TYPE is valid for a position."""
    if occu_type is pos:
        return True
    elif isinstance(occu_type, tuple):
        return pos in occu_type
    else:
        return occu_type(pos)

class Decoration:
    """Represents one decoration type."""
    def __init__(
        self,
        orient,
        rotation_interval=0,
        side_off=0,
        norm_off=-64,
        props=(),
        instances=(),
    ):
        pass
