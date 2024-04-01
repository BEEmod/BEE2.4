"""Data structure for specifying custom corridors."""
from enum import Enum
from typing import Dict, List, Optional, Tuple, Mapping
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
    # Fixup values which are set on the corridor instance.
    fixups: Mapping[str, str]
    # Indicates the initial corridor items if 1-7.
    orig_index: int
    # If this was converted from editoritems.txt
    legacy: bool


# Maps item IDs to their corridors, and vice versa.
ID_TO_CORR: Final[Mapping[str, Tuple[GameMode, Direction]]] = {
    'ITEM_ENTRY_DOOR': (GameMode.SP, Direction.ENTRY),
    'ITEM_EXIT_DOOR': (GameMode.SP, Direction.EXIT),
    'ITEM_COOP_ENTRY_DOOR': (GameMode.COOP, Direction.ENTRY),
    'ITEM_COOP_EXIT_DOOR': (GameMode.COOP, Direction.EXIT),
}
CORR_TO_ID: Final[Mapping[Tuple[GameMode, Direction], str]] = {v: k for k, v in ID_TO_CORR.items()}

# The order of the keys we use.
CorrKind: TypeAlias = Tuple[GameMode, Direction, Orient]
# Number of default instances for each kind.
CORRIDOR_COUNTS: Final[Mapping[Tuple[GameMode, Direction], Literal[1, 4, 7]]] = {
    (GameMode.SP, Direction.ENTRY): 7,
    (GameMode.SP, Direction.EXIT): 4,
    (GameMode.COOP, Direction.ENTRY): 1,
    (GameMode.COOP, Direction.EXIT): 4,
}


@attrs.frozen
class ExportedConf:
    """Data written to the pickle file for the compiler to use."""
    corridors: Dict[CorrKind, List[Corridor]]


def parse_filename(filename: str) -> Optional[Tuple[GameMode, Direction, int]]:
    """Parse the special format for corridor instance filenames."""
    folded = filename.casefold()
    if folded.startswith('instances/bee2_corridor/'):
        # It's a corridor, parse out which one.
        # instances/bee2_corridor/{mode}/{direction}/corr_{i}.vmf
        parts = folded.split('/')
        try:
            mode = GameMode(parts[2])
            direct = Direction(parts[3])
            index = int(parts[4][5:-4]) - 1
        except ValueError:
            raise ValueError(f'Unknown corridor filename "{filename}"!') from None
        return mode, direct, index
    return None
