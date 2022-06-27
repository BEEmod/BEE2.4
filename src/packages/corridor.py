"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations

import pickle
from collections import defaultdict
from typing import Dict, List, Tuple, Mapping
from typing_extensions import Final
import itertools

import attrs
import srctools.logger
from srctools import Property, Vec
from srctools.dmx import Element, Attribute as DMAttr, ValueType as DMXValue

import utils
from app import img, lazy_conf, tkMarkdown
import config
import packages
import editoritems
from corridor import (
    CorrKind, Orient, Direction, GameMode,
    CORRIDOR_COUNTS, ID_TO_CORR,
    Corridor, ExportedConf,
)


LOGGER = srctools.logger.get_logger(__name__)

# For converting style corridor definitions, this indicates the attribute the old data was stored in.
FALLBACKS: Final[Mapping[Tuple[GameMode, Direction], str]] = {
    (GameMode.SP, Direction.ENTRY): 'sp_entry',
    (GameMode.SP, Direction.EXIT): 'sp_exit',
    (GameMode.COOP, Direction.EXIT): 'coop',
}
EMPTY_DESC: Final = tkMarkdown.MarkdownData.text('')

IMG_WIDTH_SML: Final = 144
IMG_HEIGHT_SML: Final = 96
ICON_GENERIC_SML = img.Handle.builtin('BEE2/corr_generic', IMG_WIDTH_SML, IMG_HEIGHT_SML)

IMG_WIDTH_LRG: Final = 256
IMG_HEIGHT_LRG: Final = 192
ICON_GENERIC_LRG = img.Handle.builtin('BEE2/corr_generic', IMG_WIDTH_LRG, IMG_HEIGHT_LRG)


@attrs.frozen
class CorridorUI(Corridor):
    """Additional data only useful for the UI. """
    name: str
    config: lazy_conf.LazyConf
    desc: tkMarkdown.MarkdownData = attrs.field(repr=False)
    images: List[img.Handle]
    dnd_icon: img.Handle
    authors: List[str]

    def strip_ui(self) -> Corridor:
        """Strip these UI attributes for the compiler export."""
        return Corridor(
            instance=self.instance,
            orig_index=self.orig_index,
            legacy=self.legacy,
            fixups=self.fixups,
        )


@config.register('Corridor', uses_id=True, version=1)
@attrs.frozen
class Config(config.Data):
    """The current configuration for a corridor."""
    selected: List[str] = attrs.field(factory=list, kw_only=True)
    unselected: List[str] = attrs.field(factory=list, kw_only=True)

    @staticmethod
    def get_id(
        style: str,
        mode: GameMode,
        direction: Direction,
        orient: Orient,
    ) -> str:
        """Given the style and kind of corridor, return the ID for config lookup."""
        return f'{style.casefold()}:{mode.value}_{direction.value}_{orient.value}'

    @classmethod
    def parse_kv1(cls, data: Property, version: int) -> 'Config':
        """Parse from KeyValues1 configs."""
        assert version == 1, version
        selected = []
        unselected = []
        for child in data.find_children('Corridors'):
            if child.name == 'selected' and not child.has_children():
                selected.append(child.value)
            elif child.name == 'unselected' and not child.has_children():
                unselected.append(child.value)

        return Config(selected=selected, unselected=unselected)

    def export_kv1(self) -> Property:
        """Serialise to a Keyvalues1 config."""
        prop = Property('Corridors', [])
        for corr in self.selected:
            prop.append(Property('selected', corr))
        for corr in self.unselected:
            prop.append(Property('unselected', corr))

        return Property('Corridor', [prop])

    @classmethod
    def parse_dmx(cls, data: Element, version: int) -> 'Config':
        """Parse from DMX configs."""
        assert version == 1, version
        try:
            selected = list(data['selected'].iter_str())
        except KeyError:
            selected = []
        try:
            unselected = list(data['unselected'].iter_str())
        except KeyError:
            unselected = []

        return Config(selected=selected, unselected=unselected)

    def export_dmx(self) -> Element:
        """Serialise to DMX configs."""
        elem = Element('Corridor', 'DMEConfig')
        elem['selected'] = selected = DMAttr.array('selected', DMXValue.STR)
        selected.extend(self.slots)
        elem['unselected'] = unselected = DMAttr.array('unselected', DMXValue.STR)
        unselected.extend(self.slots)

        return elem


def parse_specifier(specifier: str) -> CorrKind:
    """Parse a string like 'sp_entry' or 'exit_coop_dn' into the 3 enums."""
    orient: Orient | None = None
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
            parsed_orient = Orient[part.upper()]
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
        orient = Orient.HORIZONTAL
    if direction is None:
        raise ValueError(f'Direction must be specified in "{specifier}"!')
    if mode is None:
        raise ValueError(f'Game mode must be specified in "{specifier}"!')
    return mode, direction, orient


@attrs.define(slots=False)
class CorridorGroup(packages.PakObject, allow_mult=True):
    """A collection of corridors defined for the style with this ID."""
    id: str
    corridors: Dict[CorrKind, List[CorridorUI]]

    @classmethod
    async def parse(cls, data: packages.ParseData) -> CorridorGroup:
        """Parse from the file."""
        corridors: dict[CorrKind, list[CorridorUI]] = defaultdict(list)
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

            corridors[parse_specifier(prop.name)].append(CorridorUI(
                instance=prop['instance'],
                name=prop['Name', 'Corridor'],
                authors=packages.sep_values(prop['authors', '']),
                desc=packages.desc_parse(prop, '', data.pak_id),
                orig_index=prop.int('DefaultIndex', 0),
                config=packages.get_config(prop, 'items', data.pak_id, source='Corridor ' + prop.name),
                images=images,
                dnd_icon=icon,
                legacy=prop.bool('legacy'),
                fixups={
                    subprop.name: subprop.value
                    for subprop in prop.find_children('fixups')
                },
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
        for item_id, (mode, direction) in ID_TO_CORR.items():
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
                        corridor_group = packset.obj_by_id(cls, style_id)
                    except KeyError:
                        corridor_group = cls(style_id, {})
                        packset.add(corridor_group)

                    corr_list = corridor_group.corridors.setdefault(
                        (mode, direction, Orient.HORIZONTAL),
                        [],
                    )
                    # If the item has corridors defined, transfer to this.
                    had_legacy = False
                    dup_check = {corr.instance.casefold() for corr in corr_list}
                    for ind in range(count):
                        try:
                            inst = variant.editor.instances[ind]
                        except IndexError:
                            LOGGER.warning('Corridor {}:{} does not have enough instances!', style_id, item_id)
                            break
                        if inst.inst == editoritems.FSPath():  # Blank, not used.
                            continue
                        fname = str(inst.inst)
                        if (folded := fname.casefold()) in dup_check:
                            # Duplicate? Skip.
                            continue
                        dup_check.add(folded)

                        # Find the old definition to glean some info.
                        # Coop entries don't have one.
                        if mode is GameMode.COOP and direction is Direction.ENTRY:
                            corridor = CorridorUI(
                                instance=fname,
                                name='Corridor',
                                images=[ICON_GENERIC_LRG],
                                dnd_icon=ICON_GENERIC_SML,
                                authors=style.selitem_data.auth,
                                desc=EMPTY_DESC,
                                config=lazy_conf.BLANK,
                                orig_index=ind + 1,
                                fixups={},
                                legacy=True,
                            )
                        else:
                            style_info = style.legacy_corridors[mode, direction, ind + 1]
                            corridor = CorridorUI(
                                instance=fname,
                                name=style_info.name,
                                images=[img.Handle.file(style_info.icon, IMG_WIDTH_LRG, IMG_HEIGHT_LRG)],
                                dnd_icon=img.Handle.file(style_info.icon, IMG_WIDTH_SML, IMG_HEIGHT_SML),
                                authors=style.selitem_data.auth,
                                desc=tkMarkdown.MarkdownData.text(style_info.desc),
                                config=lazy_conf.BLANK,
                                orig_index=ind + 1,
                                fixups={},
                                legacy=True,
                            )
                        corr_list.append(corridor)
                        had_legacy = True
                    if had_legacy:
                        LOGGER.warning('Legacy corridor definition for {}:{}_{}!', style_id, mode.value, direction.value)

                    if not corr_list:
                        # Look for parent styles with definitions to inherit.
                        for parent_style in style.bases[1:]:
                            try:
                                parent_group = packset.obj_by_id(CorridorGroup, parent_style.id)
                                parent_corr = parent_group.corridors[mode, direction, Orient.HORIZONTAL]
                            except KeyError:
                                continue
                            if not parent_corr:
                                continue
                            for corridor in parent_corr:
                                if not corridor.legacy:
                                    corr_list.append(corridor)
                            break # Only do first parent.

        if utils.DEV_MODE:
            # Check no duplicate corridors exist.
            for corridor_group in packset.all_obj(cls):
                for (mode, direction, orient), corridors in corridor_group.corridors.items():
                    dup_check = set()
                    for corr in corridors:
                        if (folded := corr.instance.casefold()) in dup_check:
                            raise ValueError(
                                f'Duplicate corridor instance in '
                                f'{corridor_group.id}:{mode.value}_{direction.value}_'
                                f'{orient.value}!\n {corr.instance}'
                            )
                        dup_check.add(folded)

    def defaults(self, mode: GameMode, direction: Direction, orient: Orient) -> list[CorridorUI]:
        """Fetch the default corridor set for this mode, direction and orientation."""
        try:
            corr_list = self.corridors[mode, direction, orient]
        except KeyError:
            if orient is Orient.HORIZONTAL:
                LOGGER.warning(
                    'No corridors defined for {}:{}_{}',
                    self.id, mode.value, direction.value,
                )
            return []
        
        output = [
            corr 
            for corr in corr_list
            if corr.orig_index > 0
        ]
        # Sort so missing indexes are skipped.
        output.sort(key=lambda corr: corr.orig_index)
        # Ignore extras beyond the actual size.
        return output[:CORRIDOR_COUNTS[mode, direction]]

    @classmethod
    def export(cls, exp_data: packages.ExportData) -> None:
        """Override editoritems with the new corridor specifier."""
        style_id = exp_data.selected_style.id
        try:
            group = exp_data.packset.obj_by_id(cls, style_id)
        except KeyError:
            raise AssertionError(f'No corridor group for style "{style_id}"!')

        export: ExportedConf = {}
        blank = Config()
        for mode, direction, orient in itertools.product(GameMode, Direction, Orient):
            conf = config.get_cur_conf(
                Config,
                Config.get_id(style_id, mode, direction, orient),
                blank,
            )
            try:
                inst_to_corr = {
                    corr.instance.casefold(): corr
                    for corr in group.corridors[mode, direction, orient]
                }
            except KeyError:
                # None defined?
                if orient is Orient.HORIZONTAL:
                    LOGGER.warning(
                        'No corridors defined for {}:{}_{}', 
                        style_id, mode.value, direction.value
                    )
                export[mode, direction, orient] = []
                continue

            if not conf.selected:  # Use default setup.
                export[mode, direction, orient] = [
                    corr.strip_ui() for corr in
                    group.defaults(mode, direction, orient)
                ]
                continue

            chosen = [
                corr
                for corr_id in conf.selected
                if (corr := inst_to_corr.get(corr_id.casefold())) is not None
            ]

            if not chosen:
                LOGGER.warning(
                    'No corridors selected for {}:{}_{}_{}', 
                    style_id, 
                    mode.value, direction.value, orient.value,
                )
                chosen = group.defaults(mode, direction, orient)

            for corr in chosen:
                exp_data.vbsp_conf.extend(corr.config())
            export[mode, direction, orient] = list(map(CorridorUI.strip_ui, chosen))

        # Now write out.
        LOGGER.info('Writing corridor configuration...')
        with open(exp_data.game.abs_path('bin/bee2/corridors.bin'), 'wb') as file:
            pickle.dump(export, file, protocol=pickle.HIGHEST_PROTOCOL)

        # Change out all the instances in items to names following a pattern.
        # This allows the compiler to easily recognise. Also force 64-64-64 offset.
        for item in exp_data.all_items:
            try:
                (mode, direction) = ID_TO_CORR[item.id]
            except KeyError:
                continue
            count = CORRIDOR_COUNTS[mode, direction]
            # For all items these are at the start.
            for i in range(count):
                item.set_inst(i, editoritems.InstCount(
                    f'instances/bee2_corridor/{mode.value}/{direction.value}/corr_{i + 1}.vmf'
                ))
            item.offset = Vec(64, 64, 64)
            # If vertical corridors exist, allow placement there.
            if export[mode, direction, Orient.UP]:
                item.invalid_surf.discard(
                    editoritems.Surface.FLOOR if direction is Direction.ENTRY else editoritems.Surface.CEIL
                )
            if export[mode, direction, Orient.DN]:
                item.invalid_surf.discard(
                    editoritems.Surface.CEIL if direction is Direction.ENTRY else editoritems.Surface.FLOOR
                )
