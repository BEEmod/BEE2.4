"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations

import pickle
from collections import defaultdict
from collections.abc import Sequence, Iterator, Mapping
from typing import Dict, List, Tuple
from typing_extensions import Final
import itertools

import attrs
import srctools.logger
from srctools import Vec

import utils
from app import img, lazy_conf, tkMarkdown
import config
import packages
import editoritems
from config.corridors import Config
from corridor import (
    CorrKind, Orient, Direction, GameMode,
    CORRIDOR_COUNTS, ID_TO_CORR,
    Corridor, ExportedConf,
)
from transtoken import TransToken, TransTokenSource


LOGGER = srctools.logger.get_logger(__name__)

# For converting style corridor definitions, this indicates the attribute the old data was stored in.
FALLBACKS: Final[Mapping[Tuple[GameMode, Direction], str]] = {
    (GameMode.SP, Direction.ENTRY): 'sp_entry',
    (GameMode.SP, Direction.EXIT): 'sp_exit',
    (GameMode.COOP, Direction.EXIT): 'coop',
}
TRANS_CORRIDOR_GENERIC = TransToken.ui('Corridor')

IMG_WIDTH_SML: Final = 144
IMG_HEIGHT_SML: Final = 96
ICON_GENERIC_SML = img.Handle.builtin('BEE2/corr_generic', IMG_WIDTH_SML, IMG_HEIGHT_SML)

IMG_WIDTH_LRG: Final = 256
IMG_HEIGHT_LRG: Final = 192
ICON_GENERIC_LRG = img.Handle.builtin('BEE2/corr_generic', IMG_WIDTH_LRG, IMG_HEIGHT_LRG)


@attrs.frozen
class CorridorUI(Corridor):
    """Additional data only useful for the UI. """
    name: TransToken
    config: lazy_conf.LazyConf
    desc: tkMarkdown.MarkdownData = attrs.field(repr=False)
    images: Sequence[img.Handle]
    icon: img.Handle
    authors: Sequence[TransToken]

    def strip_ui(self) -> Corridor:
        """Strip these UI attributes for the compiler export."""
        return Corridor(
            instance=self.instance,
            orig_index=self.orig_index,
            legacy=self.legacy,
            fixups=self.fixups,
        )


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
class CorridorGroup(packages.PakObject, allow_mult=True, export_priority=10):
    """A collection of corridors defined for the style with this ID."""
    id: str
    corridors: Dict[CorrKind, List[CorridorUI]]
    inherit: Sequence[str] = ()  # Copy all the corridors defined in these groups.

    @classmethod
    async def parse(cls, data: packages.ParseData) -> CorridorGroup:
        """Parse from the file."""
        corridors: dict[CorrKind, list[CorridorUI]] = defaultdict(list)
        inherits: list[str] = []
        for kv in data.info:
            if kv.name == 'id':
                continue
            if kv.name == 'inherit':
                inherits.append(kv.value)
                continue
            images = [
                img.Handle.parse(subprop, data.pak_id, IMG_WIDTH_LRG, IMG_HEIGHT_LRG)
                for subprop in kv.find_all('Image')
            ]
            if 'icon' in kv:
                icon = img.Handle.parse(kv.find_key('icon'), data.pak_id, IMG_WIDTH_SML, IMG_HEIGHT_SML)
            elif images:
                icon = images[0].resize(IMG_WIDTH_SML, IMG_HEIGHT_SML)
            else:
                icon = ICON_GENERIC_SML
            if not images:
                images.append(ICON_GENERIC_LRG)

            mode, direction, orient = parse_specifier(kv.name)

            if is_legacy := kv.bool('legacy'):

                if orient is Orient.HORIZONTAL:
                    LOGGER.warning(
                        '{.value}_{.value}_{.value} has legacy corridor "{}"',
                        mode, direction, orient, kv['Name', kv['instance']],
                    )
                else:
                    raise ValueError(
                        f'Non-horizontal {mode.value}_{direction.value}_{orient.value} corridor '
                        f'"{kv["Name", kv["instance"]]}" cannot be defined as a legacy corridor!'
                    )
            try:
                name = TransToken.parse(data.pak_id, kv['Name'])
            except LookupError:
                name = TRANS_CORRIDOR_GENERIC

            corridors[mode, direction, orient].append(CorridorUI(
                instance=kv['instance'],
                name=name,
                authors=list(map(TransToken.untranslated, packages.sep_values(kv['authors', '']))),
                desc=packages.desc_parse(kv, 'Corridor', data.pak_id),
                orig_index=kv.int('DefaultIndex', 0),
                config=packages.get_config(kv, 'items', data.pak_id, source='Corridor ' + kv.name),
                images=images,
                icon=icon,
                legacy=is_legacy,
                fixups={
                    subprop.name: subprop.value
                    for subprop in kv.find_children('fixups')
                },
            ))
        return CorridorGroup(data.id, dict(corridors), inherits)

    def add_over(self: CorridorGroup, override: CorridorGroup) -> None:
        """Merge two corridor group definitions."""
        for key, corr_over in override.corridors.items():
            try:
                corr_base = self.corridors[key]
            except KeyError:
                self.corridors[key] = corr_over
            else:
                corr_base.extend(corr_over)
        if override.inherit:
            self.inherit = override.inherit

    @classmethod
    async def post_parse(cls, packset: packages.PackagesSet) -> None:
        """After items are parsed, convert legacy definitions in the item into these groups."""
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
                        # Synthesise a new group to match.
                        corridor_group = cls(style_id, {})
                        packset.add(corridor_group, item.pak_id, item.pak_name)

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
                                name=TRANS_CORRIDOR_GENERIC,
                                images=[ICON_GENERIC_LRG],
                                icon=ICON_GENERIC_SML,
                                authors=list(map(TransToken.untranslated, style.selitem_data.auth)),
                                desc=tkMarkdown.MarkdownData.BLANK,
                                config=lazy_conf.BLANK,
                                orig_index=ind + 1,
                                fixups={},
                                legacy=True,
                            )
                        else:
                            style_info = style.legacy_corridors[mode, direction, ind + 1]
                            corridor = CorridorUI(
                                instance=fname,
                                name=TRANS_CORRIDOR_GENERIC,
                                images=[img.Handle.file(style_info.icon, IMG_WIDTH_LRG, IMG_HEIGHT_LRG)],
                                icon=img.Handle.file(style_info.icon, IMG_WIDTH_SML, IMG_HEIGHT_SML),
                                authors=list(map(TransToken.untranslated, style.selitem_data.auth)),
                                desc=tkMarkdown.MarkdownData.text(style_info.desc),
                                config=lazy_conf.BLANK,
                                orig_index=ind + 1,
                                fixups={},
                                legacy=True,
                            )
                        corr_list.append(corridor)
                        had_legacy = True
                    if had_legacy:
                        LOGGER.warning(
                            'Legacy corridor definition for {}:{}_{}!',
                            style_id, mode.value, direction.value,
                        )

        # Apply inheritance.
        for corridor_group in packset.all_obj(cls):
            for inherit in corridor_group.inherit:
                try:
                    parent_group = packset.obj_by_id(cls, inherit)
                except KeyError:
                    LOGGER.warning(
                        'Corridor Group "{}" is trying to inherit from nonexistent group "{}"!',
                        corridor_group.id, inherit,
                    )
                    continue
                if parent_group.inherit:
                    # Disable recursive inheritance for simplicity, can add later if it's actually
                    # useful.
                    LOGGER.warning(
                        'Corridor Groups "{}" cannot inherit from a group that '
                        'itself inherits ("{}"). If you need this, ask for '
                        'it to be supported.',
                        corridor_group.id, inherit,
                    )
                    continue
                for kind, corridors in parent_group.corridors.items():
                    try:
                        corridor_group.corridors[kind].extend(corridors)
                    except KeyError:
                        corridor_group.corridors[kind] = corridors.copy()

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

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Iterate over translation tokens in the corridor."""
        for (mode, direction, orient), corridors in self.corridors.items():
            source = f'corridors/{self.id}.{mode.value}_{direction.value}_{orient.value}'
            for corr in corridors:
                yield corr.name, source + '.name'
                yield from tkMarkdown.iter_tokens(corr.desc, source + '.desc')

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
    async def export(cls, exp_data: packages.ExportData) -> None:
        """Override editoritems with the new corridor specifier."""
        style_id = exp_data.selected_style.id
        try:
            group = exp_data.packset.obj_by_id(cls, style_id)
        except KeyError:
            raise Exception(f'No corridor group for style "{style_id}"!') from None

        export: ExportedConf = {}
        blank = Config()
        for mode, direction, orient in itertools.product(GameMode, Direction, Orient):
            conf = config.APP.get_cur_conf(
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
                # None defined for this corridor. This is not an error for vertical ones.
                (LOGGER.warning if orient is Orient.HORIZONTAL else LOGGER.debug)(
                    'No corridors defined for {}:{}_{}',
                    style_id, mode.value, direction.value
                )
                export[mode, direction, orient] = []
                continue

            if conf.selected:
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
            else:
                # Use default setup, don't warn.
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
        # TODO: Need to ensure this happens after Item.export()!
        for item in exp_data.all_items:
            try:
                (mode, direction) = ID_TO_CORR[item.id]
            except KeyError:
                continue
            count = CORRIDOR_COUNTS[mode, direction]
            # For all items these are at the start.
            for i in range(count):
                item.set_inst(i, editoritems.InstCount(editoritems.FSPath(
                    f'instances/bee2_corridor/{mode.value}/{direction.value}/corr_{i + 1}.vmf'
                )))
            item.offset = Vec(64, 64, 64)
            # If vertical corridors exist, allow placement there.
            has_vert = False
            if export[mode, direction, Orient.UP]:
                item.invalid_surf.discard(
                    editoritems.Surface.FLOOR if direction is Direction.ENTRY else editoritems.Surface.CEIL
                )
                has_vert = True
            if export[mode, direction, Orient.DN]:
                item.invalid_surf.discard(
                    editoritems.Surface.CEIL if direction is Direction.ENTRY else editoritems.Surface.FLOOR
                )
                has_vert = True
            if has_vert:
                # Add a rotation handle.
                item.handle = editoritems.Handle.QUAD
            # Set desired facing to make them face upright, no matter what.
            item.facing = editoritems.DesiredFacing.UP
