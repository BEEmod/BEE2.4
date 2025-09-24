"""Defines individual corridors to allow swapping which are used."""
from __future__ import annotations
from typing import Final, override

from collections import defaultdict
from collections.abc import Sequence, Iterator, Mapping
import itertools

from srctools import Keyvalues, logger
import attrs

import utils
from app import img, lazy_conf
from app.mdown import MarkdownData
import packages
import editoritems
from corridor import (
    Attachment, CorrKind, CorrSpec, OptValue, OptionGroup,
    Orient, Direction, GameMode,
    Option, Corridor,
    CORRIDOR_COUNTS, ID_TO_CORR,
    ORIENT_TO_ATTACH,
)
from packages import PackagesSet
from transtoken import AppError, TransToken, TransTokenSource


LOGGER = logger.get_logger(__name__)

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

TRANS_DUPLICATE_OPTION = TransToken.untranslated(
    'Duplicate corridor option ID "{option}" in corridor group for style "{group}"!'
)
TRANS_MISSING_VARIANT = TransToken.untranslated('No corridors defined for {style}:{variant}!')


@attrs.frozen(kw_only=True)
class CorridorUI(Corridor):
    """Additional data only useful for the UI. """
    name: TransToken
    config: lazy_conf.LazyConf
    desc: MarkdownData = attrs.field(repr=False)
    images: Sequence[img.Handle]
    icon: img.Handle
    authors: Sequence[TransToken]

    def strip_ui(self) -> Corridor:
        """Strip these UI attributes for the compiler export."""
        return Corridor(
            instance=self.instance,
            default_enabled=self.default_enabled,
            legacy=self.legacy,
            fixups=self.fixups,
            option_ids=self.option_ids,
        )


def parse_specifier(specifier: str) -> CorrSpec:
    """Parse a string like 'sp_entry' or 'exit_coop_dn' into the 3 enums."""
    attach: Attachment | None = None
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
                raise AppError(TransToken.untranslated(
                    f'Multiple entry/exit keywords in corridor type "{specifier}"!'
                ))
            direction = parsed_dir
            continue
        try:
            parsed_attach = Attachment[part.upper()]
        except KeyError:
            pass
        else:
            if attach is not None or orient is not None:
                raise AppError(TransToken.untranslated(
                    f'Multiple attachment keywords in corridor type "{specifier}"!'
                ))
            attach = parsed_attach
            continue
        try:
            parsed_orient = Orient[part.upper()]
        except KeyError:
            pass
        else:
            if attach is not None or orient is not None:
                raise AppError(TransToken.untranslated(
                    f'Multiple attachment keywords in corridor type "{specifier}"!'
                ))
            orient = parsed_orient
            continue
        try:
            parsed_mode = GameMode(part)
        except ValueError:
            pass
        else:
            if mode is not None:
                raise AppError(TransToken.untranslated(
                    f'Multiple sp/coop keywords in corridor type "{specifier}"!'
                ))
            mode = parsed_mode
            continue
        # Completely empty specifier will split into [''], allow `sp__exit` too.
        if part:
            raise AppError(TransToken.untranslated(
                f'Unknown keyword "{part}" in corridor type "{specifier}"!'
            ))
    if orient is not None:
        # Use exit so that 'up' -> ceiling, 'down' -> floor.
        attach = ORIENT_TO_ATTACH[direction or Direction.EXIT, orient]
    return mode, direction, attach


def parse_corr_kind(specifier: str) -> CorrKind:
    """Parse a string into a specific corridor type."""
    mode, direction, attach = parse_specifier(specifier)
    if attach is None:  # Infer horizontal if unspecified.
        attach = Attachment.HORIZONTAL
    if direction is None:
        raise AppError(TransToken.untranslated(
            f'Corridor type "{specifier}" must specify a direction!'
        ))
    if mode is None:
        raise AppError(TransToken.untranslated(
            f'Corridor type "{specifier}" must specify a game mode!'
        ))
    return mode, direction, attach


def parse_option(
    data: packages.ParseData,
    kv: Keyvalues,
) -> Option:
    """Parse a KV1 config into an option."""
    opt_id = utils.obj_id(kv.real_name, 'corridor option')
    name = TransToken.parse(data.pak_id, kv['name'])
    valid_ids: set[utils.ObjectID] = set()
    values: list[OptValue] = []
    fixup = kv['var']
    desc = TransToken.parse(data.pak_id, packages.parse_multiline_key(kv, 'description'))

    for child in kv.find_children('Values'):
        val_id = utils.obj_id(child.real_name, 'corridor option value')
        if val_id in valid_ids:
            LOGGER.warning('Duplicate value "{}"!', child.name)
        valid_ids.add(val_id)
        values.append(OptValue(
            id=val_id,
            name=TransToken.parse(data.pak_id, child.value),
        ))

    if not values:
        raise AppError(TransToken.untranslated(
            f'Corridor option "{opt_id}" for style "{data.id}" has no valid values!'
        ))

    try:
        default = utils.special_id(kv['default'], 'corridor option default')
    except LookupError:
        default = values[0].id
    else:
        if default not in valid_ids and default != utils.ID_RANDOM:
            LOGGER.warning('Default id "{}" is not valid!', default)
            default = values[0].id

    return Option(
        id=opt_id,
        name=name,
        default=default,
        values=values,
        fixup=fixup,
        desc=desc,
    )


@attrs.define(slots=False, kw_only=True)
class CorridorGroup(packages.PakObject, allow_mult=True):
    """A collection of corridors defined for the style with this ID."""
    id: str
    corridors: dict[CorrKind, list[CorridorUI]]
    inherit: Sequence[str] = ()  # Copy all the corridors defined in these groups.
    options: dict[utils.ObjectID, Option] = attrs.Factory(dict)
    global_options: dict[OptionGroup, list[Option]] = attrs.Factory(dict)

    @classmethod
    @override
    async def parse(cls, data: packages.ParseData) -> CorridorGroup:
        """Parse from the file."""
        corridors: dict[CorrKind, list[CorridorUI]] = defaultdict(list)
        inherits: list[str] = []

        options: dict[utils.ObjectID, Option] = {}
        global_options: dict[OptionGroup, list[Option]] = defaultdict(list)
        for opt_kv in data.info.find_children('Options'):
            with logger.context(opt_kv.real_name):
                option = parse_option(data, opt_kv)
            if option.id in options:
                raise AppError(TRANS_DUPLICATE_OPTION.format(option=option.id, group=data.id))
            options[option.id] = option
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

            mode, direction, attach = parse_corr_kind(kv.name)

            if is_legacy := kv.bool('legacy'):
                if attach is Attachment.HORIZONTAL:
                    LOGGER.warning(
                        '{.value}_{.value}_{.value} has legacy corridor "{}"',
                        mode, direction, attach, kv['Name', kv['instance']],
                    )
                else:
                    raise AppError(TransToken.untranslated(
                        f'Non-horizontal {mode.value}_{direction.value}_{attach.value} corridor '
                        f'"{kv["Name", kv["instance"]]}" cannot be defined as a legacy corridor!'
                    ))
            try:
                name = TransToken.parse(data.pak_id, kv['Name'])
            except LookupError:
                name = TRANS_CORRIDOR_GENERIC

            corridors[mode, direction, attach].append(CorridorUI(
                instance=kv['instance'],
                name=name,
                authors=list(map(TransToken.untranslated, packages.sep_values(kv['authors', '']))),
                desc=packages.desc_parse(kv, 'Corridor', data.pak_id),
                default_enabled=not kv.bool('disabled', False),
                config=await packages.get_config(
                    data.packset, kv,
                    'items',
                    data.pak_id,
                    source=f'Corridor {kv.name}',
                ),
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

    @override
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
    @override
    async def post_parse(cls, ctx: packages.PackErrorInfo) -> None:
        """After items are parsed, convert legacy definitions in the item into these groups."""
        packset = ctx.packset
        # Need both of these to be parsed.
        await packset.ready(packages.Item).wait()
        await packset.ready(packages.Style).wait()
        # Groups we synthesised.
        legacy_groups: set[utils.ObjectID] = set()
        for item_id, (mode, direction) in ID_TO_CORR.items():
            try:
                item = packset.obj_by_id(packages.Item, item_id, warn=False)
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
                        corridor_group = packset.obj_by_id(cls, style_id, warn=False)
                    except KeyError:
                        # Synthesise a new group to match.
                        corridor_group = cls(id=style_id, corridors={})
                        packset.add(corridor_group, item.pak_id, item.pak_name)
                        legacy_groups.add(style_id)
                        LOGGER.info('Synthesising corridor group for "{}"', style_id)

                    corr_list = corridor_group.corridors.setdefault(
                        (mode, direction, Attachment.HORIZONTAL),
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
                                desc=MarkdownData.BLANK,
                                config=lazy_conf.BLANK,
                                default_enabled=True,
                                # Replicate previous behaviour, where this var was set to the
                                # corridor index automatically.
                                fixups={'corr_index': str(ind + 1)},
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
                                desc=MarkdownData(TransToken.untranslated(style_info.desc), None),
                                config=lazy_conf.BLANK,
                                default_enabled=True,
                                fixups={'corr_index': str(ind + 1)},
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
                corridor_group._inherit_from(ctx, packset, inherit, True)

            if corridor_group.id in legacy_groups and not all(
                corridor_group.corridors[mode, direction, Attachment.HORIZONTAL]
                for mode in GameMode for direction in Direction
            ):
                # It's possible that a corridor could have nothing defined, if it referenced
                # the item for a style that itself did update. In that case, if we have a base,
                # try to inherit. This isn't fully correct, since the package could use <XX> refs
                # to have loaded the items. This is compatibility code anyway, make a best effort.
                try:
                    style = packset.obj_by_id(packages.Style, corridor_group.id)
                except KeyError:
                    continue
                if style.base_style:
                    LOGGER.warning(
                        'Attempting to copy corridors from {} to {}',
                        style.base_style, corridor_group.id,
                    )
                    corridor_group._inherit_from(ctx, packset, style.base_style, False)

        if utils.DEV_MODE:
            # Check no duplicate corridors exist.
            for corridor_group in packset.all_obj(cls):
                for (mode, direction, orient), corridors in corridor_group.corridors.items():
                    dup_check = set()
                    for corr in corridors:
                        if (folded := corr.instance.casefold()) in dup_check:
                            ctx.warn_fatal(TransToken.untranslated(
                                f'Duplicate corridor instance in '
                                f'{corridor_group.id}:{mode.value}_{direction.value}_'
                                f'{orient.value}!\n {corr.instance}'
                            ))
                        dup_check.add(folded)

        # If our conversion failed to locate corridors, this is a fatal error.
        for corridor_group in packset.all_obj(cls):
            for mode in GameMode:
                for direction in Direction:
                    if not corridor_group.corridors[mode, direction, Attachment.HORIZONTAL]:
                        ctx.errors.add(TRANS_MISSING_VARIANT.format(
                            style=corridor_group.id,
                            variant=f'{mode.value}_{direction.value}',
                        ), fatal=True)

    def _inherit_from(
        self,
        ctx: packages.PackErrorInfo, packset: PackagesSet,
        parent_id: str, merge: bool,
    ) -> None:
        """Perform inheritance."""
        try:
            parent_group = packset.obj_by_id(CorridorGroup, parent_id, warn=False)
        except KeyError:
            ctx.warn_auth(self.pak_id, TransToken.untranslated(
                'Corridor Group "{id}" is trying to inherit from nonexistent group "{inherit}"!'
            ).format(id=self.id, inherit=parent_id))
            return

        if parent_group.inherit:
            # Disable recursive inheritance for simplicity, can add later if it's actually
            # useful.
            ctx.warn_auth(self.pak_id, TransToken.untranslated(
                'Corridor Group "{id}" cannot inherit from a group that '
                'itself inherits ("{inherit}"). If you need this, ask for '
                'it to be supported.'
            ).format(id=self.id, inherit=parent_id))
            return
        for kind, corridors in parent_group.corridors.items():
            try:
                corr_list = self.corridors[kind]
            except KeyError:
                self.corridors[kind] = corridors.copy()
            else:
                if not corr_list or merge:
                    corr_list.extend(corridors)

        # Copy over options, but don't overwrite ones that already exist.
        for opt_kind, options in parent_group.global_options.items():
            try:
                existing = self.global_options[opt_kind]
            except KeyError:
                self.global_options[opt_kind] = options.copy()
            else:
                existing_ids = {opt.id for opt in existing}
                for option in options:
                    if option.id not in existing_ids:
                        existing.append(option)

        for option in parent_group.options.values():
            self.options.setdefault(option.id, option)

    @override
    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Iterate over translation tokens in the corridor."""
        for (mode, direction, orient), corridors in self.corridors.items():
            source = f'corridors/{self.id}.{mode.value}_{direction.value}_{orient.value}'
            for corr in corridors:
                yield corr.name, f'{source}.name'
                yield from corr.desc.iter_tokens(f'{source}.desc')

    def defaults(self, mode: GameMode, direction: Direction, attach: Attachment) -> list[CorridorUI]:
        """Fetch the default corridor set for this mode, direction and orientation."""
        try:
            corr_list = self.corridors[mode, direction, attach]
        except KeyError:
            if attach is Attachment.HORIZONTAL:
                LOGGER.warning(
                    'No corridors defined for {}:{}_{}',
                    self.id, mode.value, direction.value,
                )
            return []

        return [
            corr
            for corr in corr_list
            if corr.default_enabled
        ]

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
