"""Data structure for specifying custom corridors."""
from __future__ import annotations
from typing import Final, Literal

from collections.abc import Sequence, Mapping
from enum import Enum

from srctools import logger
import attrs

from consts import DefaultItems
from transtoken import TransToken
import utils

LOGGER = logger.get_logger(__name__)


class GameMode(Enum):
    """Possible game modes."""
    SP = 'sp'
    COOP = 'coop'


class Direction(Enum):
    """The direction of a corridor."""
    ENTRY = 'entry'
    EXIT = 'exit'


@utils.freeze_enum_props
class Attachment(Enum):
    """The surface the corridor attaches to. Horizontal is vanilla."""
    HORIZONTAL = 'horizontal'
    FLAT = HORIZ = HORIZONTAL
    FLOOR = 'floor'
    CEILING = 'ceiling'
    CEIL = CEILING


class Orient(Enum):
    """Legacy enum, refers to the direction through the corridor."""
    HORIZONTAL = 'horizontal'
    FLAT = HORIZ = HORIZONTAL
    UP = 'up'
    DOWN = DN = 'down'


ORIENT_TO_ATTACH: Mapping[tuple[Direction, Orient], Attachment] = {
    (Direction.ENTRY, Orient.FLAT): Attachment.HORIZ,
    (Direction.ENTRY, Orient.UP): Attachment.FLOOR,
    (Direction.ENTRY, Orient.DN): Attachment.CEILING,
    (Direction.EXIT, Orient.FLAT): Attachment.HORIZ,
    (Direction.EXIT, Orient.UP): Attachment.CEILING,
    (Direction.EXIT, Orient.DN): Attachment.FLOOR,
}
ATTACH_TO_ORIENT: Mapping[tuple[Direction, Attachment], Orient] = {
    (direct, attach): orient
    for (direct, orient), attach in ORIENT_TO_ATTACH.items()
}


@attrs.frozen(kw_only=True)
class Corridor:
    """An individual corridor definition. """
    instance: str
    # Fixup values which are set on the corridor instance.
    fixups: Mapping[str, str]
    # Whether this corridor should default to being enabled.
    default_enabled: bool
    # If this was converted from editoritems.txt
    legacy: bool
    # IDs of options specifically added to this corridor.
    option_ids: frozenset[utils.ObjectID]


@attrs.frozen
class OptValue:
    """A value for an option."""
    id: utils.ObjectID
    name: TransToken  # Name to use.


@attrs.frozen(kw_only=True)
class Option:
    """An option that can be swapped between various values."""
    id: utils.ObjectID
    name: TransToken
    default: utils.SpecialID  # id or <RANDOM>
    desc: TransToken
    values: Sequence[OptValue]
    fixup: str


# Maps item IDs to their corridors, and vice versa.
ID_TO_CORR: Final[Mapping[utils.ObjectID, tuple[GameMode, Direction]]] = {
    DefaultItems.door_sp_entry.id: (GameMode.SP, Direction.ENTRY),
    DefaultItems.door_sp_exit.id: (GameMode.SP, Direction.EXIT),
    DefaultItems.door_coop_entry.id: (GameMode.COOP, Direction.ENTRY),
    DefaultItems.door_coop_exit.id: (GameMode.COOP, Direction.EXIT),
}
CORR_TO_ID: Final[Mapping[tuple[GameMode, Direction], utils.ObjectID]] = {v: k for k, v in ID_TO_CORR.items()}

# A specific type of corridor.
type CorrKind = tuple[GameMode, Direction, Attachment]
# A filter on which types this applies to. None values match all possible instead.
type CorrSpec = tuple[GameMode | None, Direction | None, Attachment | None]
# Options are only differentiated based on mode/direction.
type OptionGroup = tuple[GameMode, Direction]
# Number of default instances for each kind.
CORRIDOR_COUNTS: Final[Mapping[tuple[GameMode, Direction], Literal[1, 4, 7]]] = {
    (GameMode.SP, Direction.ENTRY): 7,
    (GameMode.SP, Direction.EXIT): 4,
    (GameMode.COOP, Direction.ENTRY): 1,
    (GameMode.COOP, Direction.EXIT): 4,
}


@attrs.frozen
class ExportedConf:
    """Data written to the pickle file for the compiler to use."""
    corridors: Mapping[CorrKind, Sequence[Corridor]]
    global_opt_ids: Mapping[OptionGroup, frozenset[utils.ObjectID]]
    options: Mapping[utils.ObjectID, Option]


def parse_filename(filename: str) -> tuple[GameMode, Direction, int] | None:
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
