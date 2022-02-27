"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Tuple, List
from enum import Enum

import attrs

from app import img, tkMarkdown
import packages


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
COUNTS = {
    (GameMode.SP, Direction.ENTRY): 7,
    (GameMode.SP, Direction.EXIT): 4,
    (GameMode.COOP, Direction.ENTRY): 1,
    (GameMode.COOP, Direction.EXIT): 4,
}
# For converting style corridor definitions, the item IDs of corridors.
ITEMS = [
    (GameMode.SP, Direction.ENTRY, 'ITEM_ENTRY_DOOR'),
    (GameMode.SP, Direction.EXIT, 'ITEM_EXIT_DOOR'),
    (GameMode.COOP, Direction.ENTRY, 'ITEM_COOP_ENTRY_DOOR'),
    (GameMode.COOP, Direction.EXIT, 'ITEM_COOP_EXIT_DOOR'),
]


@attrs.frozen
class Corridor:
    """An individual corridor definition. """
    instance: str
    name: str
    desc: tkMarkdown.MarkdownData
    images: List[img.Handle]
    authors: List[str]


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


@attrs.define
class CorridorGroup(packages.PakObject, allow_mult=True):
    """A collection of corridors defined for the style with this ID."""
    id: str
    corridors: Dict[CorrKind, List[Corridor]]

    @classmethod
    async def parse(cls, data: packages.ParseData) -> CorridorGroup:
        """Parse from the file."""
        corridors: dict[CorrKind, list[Corridor]] = defaultdict(list)
        for prop in data.info:
            if prop.name in {'id'}:
                continue
            corridors[parse_specifier(prop.name)].append(Corridor(
                instance=prop['instance'],
                name=prop['Name', 'Corridor'],
                authors=packages.sep_values(prop['authors', '']),
                desc=packages.desc_parse(prop, '', data.pak_id),
                images=[
                    img.Handle.parse(subprop, data.pak_id, 256, 192)
                    for subprop in prop.find_all('Image')
                ],
            ))

        return CorridorGroup(data.id, dict(corridors))

    def add_over(self: CorridorGroup, override: CorridorGroup) -> None:
        """Merge two corridor group definitions."""
        for key, corr_over in override.corridors.items():
            try:
                corr_base = self.corridors[key]
            except KeyError:
                self.corridors[key] = corr_over
            else:
                corr_base.extend(corr_over)

    @staticmethod
    def export(exp_data: packages.ExportData) -> None:
        """Override editoritems with the new corridor specifier."""
        pass
