"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations
from collections import defaultdict
from typing import Dict, List
from enum import Enum
import itertools

import attrs
import srctools.logger
from srctools import Property
from srctools.dmx import Element, Attribute as DMAttr, ValueType as DMXValue

from app import img, tkMarkdown, config
import packages
import editoritems
from consts import CORRIDOR_COUNTS, CorrKind, CorrOrient, CorrDir, GameMode


LOGGER = srctools.logger.get_logger(__name__)

# For converting style corridor definitions, the item IDs of corridors.
ITEMS = [
    (GameMode.SP, CorrDir.ENTRY, 'ITEM_ENTRY_DOOR', 'sp_entry'),
    (GameMode.SP, CorrDir.EXIT, 'ITEM_EXIT_DOOR', 'sp_exit'),
    (GameMode.COOP, CorrDir.ENTRY, 'ITEM_COOP_ENTRY_DOOR', ''),
    (GameMode.COOP, CorrDir.EXIT, 'ITEM_COOP_EXIT_DOOR', 'coop'),
]
EMPTY_DESC = tkMarkdown.MarkdownData.text('')

IMG_WIDTH_SML = 144
IMG_HEIGHT_SML = 96
ICON_GENERIC_SML = img.Handle.builtin('BEE2/corr_generic', IMG_WIDTH_SML, IMG_HEIGHT_SML)

IMG_WIDTH_LRG = 256
IMG_HEIGHT_LRG = 192
ICON_GENERIC_LRG = img.Handle.builtin('BEE2/corr_generic', IMG_WIDTH_LRG, IMG_HEIGHT_LRG)


@attrs.frozen
class Corridor:
    """An individual corridor definition. """
    instance: str
    name: str
    desc: tkMarkdown.MarkdownData = attrs.field(repr=False)
    images: List[img.Handle]
    dnd_icon: img.Handle
    authors: List[str]
    # Indicates the initial corridor items if 1-7.
    orig_index: int = 0
    # If this was converted from editoritems.txt
    legacy: bool = False

class RandMode(Enum):
    """Kind of randomisation to use."""
    SINGLE = 'single'
    EDITOR = 'editor'  # 4 or 7, depending on editor instance count.
    ALL = 'all'  # Use all regardless.


@config.register('Corridor', uses_id=True)
@attrs.frozen
class Config(config.Data):
    """The current configuration for a corridor."""
    selected: List[str] = attrs.Factory(list)
    random: RandMode = RandMode.EDITOR

    @staticmethod
    def get_id(
        style: str,
        mode: GameMode,
        direction: CorrDir,
        orient: CorrOrient,
    ) -> str:
        """Given the style and kind of corridor, return the ID for config lookup."""
        return f'{style.casefold()}:{mode.value}_{direction.value}_{orient.value}'

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'Config':
        """Parse from KeyValues1 configs."""
        assert version == 1, version
        corr = [
            prop.value
            for prop in data.find_children('selected')
        ]
        try:
            rand = RandMode(data['random', 'editor'])
        except ValueError:
            rand = RandMode.EDITOR

        return Config(corr, rand)

    def export_kv1(self) -> Property:
        """Serialise to a Keyvalues1 config."""
        return Property('Corridor', [
            Property('random', self.random.value),
            Property('Selected', [
                Property('Corridor', corr)
                for corr in self.selected
            ])
        ])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'Config':
        """Parse from DMX configs."""
        assert version == 1, version
        try:
            rand = RandMode(data['random'].val_str)
        except (KeyError, TypeError, ValueError):
            rand = RandMode.EDITOR
        try:
            corr = list(data['selected'].iter_str())
        except KeyError:
            corr = []

        return cls(corr, rand)

    def export_dmx(self) -> Element:
        """Serialise to DMX configs."""
        elem = Element('Corridor', 'DMEConfig')
        elem['random'] = self.random.value
        elem['selected'] = selected = DMAttr.array('selected', DMXValue.STR)
        selected.extend(self.selected)
        return elem


def parse_specifier(specifier: str) -> CorrKind:
    """Parse a string like 'sp_entry' or 'exit_coop_dn' into the 3 enums."""
    orient: CorrOrient | None = None
    mode: GameMode | None = None
    direction: CorrDir | None = None
    for part in specifier.casefold().split('_'):
        try:
            parsed_dir = CorrDir(part)
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
            images = [
                img.Handle.parse(subprop, data.pak_id, IMG_WIDTH_LRG, IMG_HEIGHT_LRG)
                for subprop in prop.find_all('Image')
            ]
            if 'icon' in prop:
                icon = img.Handle.parse(prop.find_key('icon'), data.pak_id, IMG_WIDTH_SML, IMG_HEIGHT_SML)
            elif images:
                icon = images[0].resize(IMG_WIDTH_SML, IMG_HEIGHT_SML)
            else:
                icon = ICON_GENERIC_SML
            if not images:
                images.append(ICON_GENERIC_LRG)

            corridors[parse_specifier(prop.name)].append(Corridor(
                instance=prop['instance'],
                name=prop['Name', 'Corridor'],
                authors=packages.sep_values(prop['authors', '']),
                desc=packages.desc_parse(prop, '', data.pak_id),
                orig_index=prop.int('DefaultIndex', 0),
                images=images,
                dnd_icon=icon,
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
            count = CORRIDOR_COUNTS[mode, direction]
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

                    corr_list = corridors.corridors.setdefault(
                        (mode, direction, CorrOrient.HORIZONTAL),
                        [],
                    )
                    if not corr_list:
                        # Look for parent styles with definitions to inherit.
                        for parent_style in style.bases[1:]:
                            try:
                                parent_group = packset.obj_by_id(CorridorGroup, parent_style.id)
                                parent_corr = parent_group.corridors[mode, direction, CorrOrient.HORIZONTAL]
                            except KeyError:
                                continue
                            for corridor in parent_corr:
                                if not corridor.legacy:
                                    corr_list.append(corridor)

                    # If the item has corridors defined, transfer to this.
                    had_legacy = False
                    for ind in range(count):
                        try:
                            inst = variant.editor.instances[ind]
                        except IndexError:
                            LOGGER.warning('Corridor {}:{} does not have enough instances!', style_id, item_id)
                            break
                        if inst.inst == editoritems.FSPath():  # Blank, not used.
                            continue
                        if variant_attr:
                            style_info = style.corridors[variant_attr, ind + 1]
                            corridor = Corridor(
                                instance=str(inst.inst),
                                name=style_info.name,
                                images=[img.Handle.file(style_info.icon, IMG_WIDTH_LRG, IMG_HEIGHT_LRG)],
                                dnd_icon=img.Handle.file(style_info.icon, IMG_WIDTH_SML, IMG_HEIGHT_SML),
                                authors=style.selitem_data.auth,
                                desc=tkMarkdown.MarkdownData.text(style_info.desc),
                                orig_index=ind + 1,
                                legacy=True,
                            )
                        else:
                            corridor = Corridor(
                                instance=str(inst.inst),
                                name='Corridor',
                                images=[ICON_GENERIC_LRG],
                                dnd_icon=ICON_GENERIC_SML,
                                authors=style.selitem_data.auth,
                                desc=EMPTY_DESC,
                                orig_index=ind + 1,
                                legacy=True,
                            )
                        corr_list.append(corridor)
                        had_legacy = True
                    if had_legacy:
                        LOGGER.warning('Legacy corridor definition for {}:{}_{}!', style_id, mode.value, direction.value)

    @staticmethod
    def export(exp_data: packages.ExportData) -> None:
        """Override editoritems with the new corridor specifier."""
        pass
