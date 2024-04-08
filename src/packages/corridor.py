"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence, Iterator, Mapping
from typing_extensions import Final
import itertools

import attrs
import srctools.logger

import utils
from app import img, lazy_conf, tkMarkdown
import packages
import editoritems
from corridor import (
    CorrKind, CorrSpec, OptionGroup,
    Orient, Direction, GameMode,
    Option, Corridor,
    CORRIDOR_COUNTS, ID_TO_CORR,
)
from transtoken import AppError, TransToken, TransTokenSource


LOGGER = srctools.logger.get_logger(__name__)

# For converting style corridor definitions, this indicates the attribute the old data was stored in.
FALLBACKS: Final[Mapping[tuple[GameMode, Direction], str]] = {
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

ALL_MODES: Final[Sequence[GameMode]] = list(GameMode)
ALL_DIRS: Final[Sequence[Direction]] = list(Direction)
ALL_ORIENT: Final[Sequence[Orient]] = list(Orient)

TRANS_DUPLICATE_OPTION = TransToken.ui(
    'Duplicate corridor option ID "{option}" in corridor group for style "{group}"!'
)


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
            option_ids=self.option_ids,
        )


def parse_specifier(specifier: str) -> CorrSpec:
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
        # Completely empty specifier will split into [''], allow `sp__exit` too.
        if part:
            raise ValueError(f'Unknown keyword "{part}" in "{specifier}"!')
    return mode, direction, orient


def parse_corr_kind(specifier: str) -> CorrKind:
    """Parse a string into a specific corridor type."""
    mode, direction, orient = parse_specifier(specifier)
    if orient is None:  # Infer horizontal if unspecified.
        orient = Orient.HORIZONTAL
    if direction is None:
        raise ValueError(f'Direction must be specified in "{specifier}"!')
    if mode is None:
        raise ValueError(f'Game mode must be specified in "{specifier}"!')
    return mode, direction, orient


@attrs.define(slots=False, kw_only=True)
class CorridorGroup(packages.PakObject, allow_mult=True):
    """A collection of corridors defined for the style with this ID."""
    id: str
    corridors: dict[CorrKind, list[CorridorUI]]
    inherit: Sequence[str] = ()  # Copy all the corridors defined in these groups.
    options: dict[utils.ObjectID, Option] = attrs.Factory(dict)
    global_options: dict[OptionGroup, list[Option]] = attrs.Factory(dict)

    @classmethod
    async def parse(cls, data: packages.ParseData) -> CorridorGroup:
        """Parse from the file."""
        corridors: dict[CorrKind, list[CorridorUI]] = defaultdict(list)
        inherits: list[str] = []

        options: dict[utils.ObjectID, Option] = {}
        global_options: dict[OptionGroup, list[Option]] = defaultdict(list)
        for opt_kv in data.info.find_children('Options'):
            opt_id = utils.obj_id(opt_kv.real_name, 'corridor option')
            option = Option.parse(data.pak_id, opt_id, opt_kv)
            if opt_id in options:
                raise AppError(TRANS_DUPLICATE_OPTION.format(option=opt_id, group=data.id))
            options[opt_id] = option
            for spec_kv in opt_kv.find_all('global'):
                spec_mode, spec_dir, spec_orient = parse_specifier(spec_kv.value)
                # We don't differentiate by orientation.
                for mode, direction in itertools.product(
                    (spec_mode,) if spec_mode is not None else ALL_MODES,
                    (spec_dir,) if spec_dir is not None else ALL_DIRS,
                ):
                    global_options[mode, direction].append(option)

        for kv in data.info:
            if kv.name in ('id', 'options'):
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

            mode, direction, orient = parse_corr_kind(kv.name)

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
                option_ids=frozenset({
                    utils.obj_id(opt_kv.value, 'corridor option')
                    for opt_kv in kv.find_all('Option')
                }),
            ))
        return CorridorGroup(
            id=data.id,
            corridors=dict(corridors),
            inherit=inherits,
            options=options,
            global_options=dict(global_options),
        )

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

        for opt in override.options.values():
            if opt.id in self.options:
                raise AppError(TRANS_DUPLICATE_OPTION.format(option=opt.id, group=self.id))
            self.options[opt.id] = opt
        for kind, additional in override.global_options.items():
            self.global_options[kind] += additional

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
                        corridor_group = cls(id=style_id, corridors={})
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
                                option_ids=frozenset(),
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
                                option_ids=frozenset(),
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

    def get_options(self, mode: GameMode, direction: Direction, corr: CorridorUI) -> Iterator[Option]:
        """Determine all options that a specific corridor requires."""
        matched = set()

        for opt in self.global_options.get((mode, direction), ()):
            matched.add(opt.id)
            yield opt
        for opt_id in corr.option_ids - matched:
            try:
                yield self.options[opt_id]
            except KeyError:
                LOGGER.warning(
                    'Unknown option {} for corridor group "{}"!\ninstance:{}',
                    opt_id, self.id, corr.instance,
                )
