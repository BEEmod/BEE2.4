"""Data structure for specifying custom corridors."""
from enum import Enum
from typing import Dict, List, Tuple, Mapping
from typing_extensions import Final, TypeAlias, Literal

import attrs

import utils


class GameMode(Enum):
    """Possible game modes."""
    SP = 'sp'
    COOP = 'coop'


class Direction(Enum):
    """The direction of a corridor."""
    ENTRY = 'entry'
    EXIT = 'exit'


@utils.freeze_enum_props
class Orient(Enum):
    """The orientation of the corridor, up/down are new."""
    HORIZONTAL = 'horizontal'
    FLAT = HORIZ = HORIZONTAL
    UP = 'up'
    DOWN = DN = 'down'

    @property
    def flipped(self) -> 'Orient':
        """Return the orient flipped along Z."""
        if self is Orient.UP:
            return Orient.DN
        if self is Orient.DN:
            return Orient.UP
        return self


@attrs.frozen
class Corridor:
    """An individual corridor definition. """
    instance: str
    # Indicates the initial corridor items if 1-7.
    orig_index: int
    # If this was converted from editoritems.txt
    legacy: bool


# The order of the keys we use.
CorrKind: TypeAlias = Tuple[GameMode, Direction, Orient]
# The data in the pickle file we write for the compiler to read.
ExportedConf: TypeAlias = Dict[CorrKind, List[Corridor]]
# Number of default instances for each kind.
CORRIDOR_COUNTS: Final[Mapping[Tuple[GameMode, Direction], Literal[1, 4, 7]]] = {
    (GameMode.SP, Direction.ENTRY): 7,
    (GameMode.SP, Direction.EXIT): 4,
    (GameMode.COOP, Direction.ENTRY): 1,
    (GameMode.COOP, Direction.EXIT): 4,
}
