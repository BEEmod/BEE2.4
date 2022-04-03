"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Tuple, List
from enum import Enum

import attrs
import srctools.logger

from app import img, tkMarkdown
import packages


LOGGER = srctools.logger.get_logger(__name__)

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
    (GameMode.SP, Direction.ENTRY, 'ITEM_ENTRY_DOOR', 'sp_entry'),
    (GameMode.SP, Direction.EXIT, 'ITEM_EXIT_DOOR', 'sp_exit'),
    (GameMode.COOP, Direction.ENTRY, 'ITEM_COOP_ENTRY_DOOR', ''),
    (GameMode.COOP, Direction.EXIT, 'ITEM_COOP_EXIT_DOOR', 'coop'),
]
DESC = tkMarkdown.MarkdownData.text('')


@attrs.frozen
class Corridor:
    """An individual corridor definition. """
    instance: str
    name: str
    desc: tkMarkdown.MarkdownData = attrs.field(repr=False)
    images: List[img.Handle]
    authors: List[str]
    # Indicates the initial corridor items if 1-7.
    orig_index: int = 0
    # If this was converted from editoritems.txt
    legacy: bool = False


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


@attrs.define(slots=False)
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
                orig_index=prop.int('DefaultIndex', 0),
                legacy=False,
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

    @classmethod
    async def post_parse(cls, packset: packages.PackagesSet) -> None:
        """After items are parsed, convert definitions in the item into these groups."""
        # Need both of these to be parsed.
        await packset.ready(packages.Item).wait()
        await packset.ready(packages.Style).wait()
        for mode, direction, item_id, variant_attr in ITEMS:
            try:
                item = packset.obj_by_id(packages.Item, item_id)
            except KeyError:
                continue
            count = COUNTS[mode, direction]
            for vers in item.versions.values():
                for style_id, variant in vers.styles.items():
                    try:
                        style = packset.obj_by_id(packages.Style, style_id)
                    except KeyError:
                        continue
                    try:
                        corridors = packset.obj_by_id(cls, style_id)
                    except KeyError:
                        corridors = cls(style_id, {})
                        packset.add(corridors)

                    # If the item has corridors defined, transfer to this.
                    had_legacy = False
                    for ind in range(count):
                        try:
                            inst = variant.editor.instances[ind]
                        except IndexError:
                            LOGGER.warning('Corridor {}:{} does not have enough instances!', style_id, item_id)
                            break
                        if not inst.inst:
                            continue
                        if variant_attr:
                            style_info = style.corridors[variant_attr, ind + 1]
                            corridor = Corridor(
                                instance=str(inst.inst),
                                name=style_info.name,
                                images=[style_info.icon],
                                authors=style.selitem_data.auth,
                                desc=tkMarkdown.MarkdownData.text(style_info.desc),
                                orig_index=ind + 1,
                                legacy=True,
                            )
                        else:
                            corridor = Corridor(
                                instance=str(inst.inst),
                                name='Corridor',
                                images=[],
                                authors=style.selitem_data.auth,
                                desc=DESC,
                                orig_index=ind + 1,
                                legacy=True,
                            )
                        corridors.corridors.setdefault(
                            (mode, direction, CorrOrient.HORIZONTAL),
                            [],
                        ).append(corridor)
                        had_legacy = True
                    if had_legacy:
                        LOGGER.warning('Legacy corridor definition for {}:{}_{}!', style_id, mode.value, direction.value)

    @staticmethod
    def export(exp_data: packages.ExportData) -> None:
        """Override editoritems with the new corridor specifier."""
        pass
