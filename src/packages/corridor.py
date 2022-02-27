"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations
from typing import Dict, Tuple, List
from enum import Enum


class GameMode(Enum):
    """The game mode this uses."""
    SP = 'sp'
    COOP = 'coop'


class Direction(Enum):
    """The direction of the corridor."""
    ENTRY = 'entry'
    EXIT = 'exit'


class CorrOrient(Enum):
    """The orientation of the corridor, up/down are new."""
    HORIZONTAL = 'horizontal'
    FLAT = HORIZ = HORIZONTAL
    UP = 'up'
    DOWN = DN = 'down'

CorrKind = Tuple[GameMode, Direction, CorrOrient]

def parse_specifier(specifier: str) -> CorrKind:
    """Parse a string like 'sp_entry' or 'exit_coop_dn' into the 3 enums."""
    orient: CorrOrient | None = None
    mode: GameMode | None = None
    direction: Direction | None = None
    for part in specifier.casefold().split('_'):
        try:
            parsed_dir = Direction(part)
        except ValueError:
            pass
        else:
            if direction is not None:
                raise ValueError(f'Multiple entry/exit keywords in "{specifier}"!')
            direction = parsed_dir
            continue
        try:
            parsed_orient = CorrOrient[part.upper()]
        except KeyError:
            pass
        else:
            if orient is not None:
                raise ValueError(f'Multiple orientation keywords in "{specifier}"!')
            orient = parsed_orient
            continue
        try:
            parsed_mode = GameMode(part)
        except ValueError:
            pass
        else:
            if mode is not None:
                raise ValueError(f'Multiple sp/coop keywords in "{specifier}"!')
            mode = parsed_mode
            continue
        raise ValueError(f'Unknown keyword "{part}" in "{specifier}"!')

    if orient is None:  # Allow omitting this additional variant.
        orient = CorrOrient.HORIZONTAL
    if direction is None:
        raise ValueError(f'Direction must be specified in "{specifier}"!')
    if mode is None:
        raise ValueError(f'Game mode must be specified in "{specifier}"!')
    return mode, direction, orient
