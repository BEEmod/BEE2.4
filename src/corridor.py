"""Data structure for specifying custom corridors."""
from enum import Enum
from typing import Tuple, Mapping

import attrs
from typing_extensions import Final, TypeAlias, Literal


class GameMode(Enum):
    """Possible game modes."""
    SP = 'sp'
    COOP = 'coop'


class Direction(Enum):
    """The direction of a corridor."""
    ENTRY = 'entry'
    EXIT = 'exit'


class Orient(Enum):
    """The orientation of the corridor, up/down are new."""
    HORIZONTAL = 'horizontal'
    FLAT = HORIZ = HORIZONTAL
    UP = 'up'
    DOWN = DN = 'down'


CorrKind: TypeAlias = Tuple[GameMode, Direction, Orient]
# Number of default instances for each kind.
CORRIDOR_COUNTS: Final[Mapping[Tuple[GameMode, Direction], Literal[1, 4, 7]]] = {
    (GameMode.SP, Direction.ENTRY): 7,
    (GameMode.SP, Direction.EXIT): 4,
    (GameMode.COOP, Direction.ENTRY): 1,
    (GameMode.COOP, Direction.EXIT): 4,
}


@attrs.frozen
class Corridor:
    """An individual corridor definition. """
    instance: str
    # Indicates the initial corridor items if 1-7.
    orig_index: int
    # If this was converted from editoritems.txt
    legacy: bool
