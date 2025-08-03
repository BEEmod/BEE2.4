"""Item package objects provide items for the palette customised for each style.

A system is provided so configurations can be shared and partially modified
as required.

Unparsed style IDs can be <special>, used usually for unstyled items.
Those are only relevant for default styles or explicit inheritance.
"""
from __future__ import annotations
from typing import Final, Self, override, ClassVar, assert_never

from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import Enum
from pathlib import PurePosixPath as FSPath
import copy
import re
from weakref import WeakKeyDictionary

from aioresult import ResultCapture
from srctools import VMF, FileSystem, Keyvalues, logger, conv_int
from srctools.tokenizer import Token, Tokenizer
import attrs
import trio

from app import DEV_MODE, img, lazy_conf, paletteLoader
from app.mdown import MarkdownData
from config.gen_opts import GenOptions
from config.item_defaults import DEFAULT_VERSION, ItemDefault
from connections import Config as ConnConfig
from editoritems import InstCount, Item as EditorItem
from packages import (
    ExportKey, PackagesSet, PackErrorInfo, PakObject, PakRef, ParseData, Style,
    desc_parse, get_config, sep_values,
)
from transtoken import TransToken, TransTokenSource
import async_util
import collisions
import config
import editoritems_vmf
import utils


LOGGER = logger.get_logger(__name__)

TRANS_EXTRA_PALETTES = TransToken.untranslated(
    '"{filename}" has palette set for extra item blocks. Deleting.'
)
TRANS_INCOMPLETE_GROUPING = TransToken.untranslated('"{filename}" has incomplete grouping icon definition!')


class InheritKind(Enum):
    """Defines how an item variant was specified for this item."""
    DEFINED = 'defined'    # Specified directly
    MODIFIED = 'modified'  # Modifies another definition
    INHERIT = 'inherit'    # Inherited from a base style
    UNSTYLED = 'unstyled'  # Fallback from elsewhere.
    REUSED = 'reused'      # Reuses another style.


@attrs.frozen
class UnParsedItemVariant:
    """The desired variant for an item, before we've figured out the dependencies."""
    pak_id: utils.ObjectID  # The package that defined this variant.
    filesys: FileSystem  # The original filesystem.
    folder: str | None  # If set, use the given folder from our package.
    # If non-None, either a single style ID, or version + style ID.
    style: utils.SpecialID | tuple[str, utils.ObjectID] | None
    config: Keyvalues | None  # Config for editing


@attrs.define
class UnParsedVersion:
    """The data for item versions, before dependencies have been constructed.

    If isolate is set, the default version will not be consulted for missing
    styles.
    """
    name: str
    id: str
    isolate: bool
    styles: dict[utils.SpecialID, UnParsedItemVariant | ItemVariant]
    def_style: utils.SpecialID
    inherit_kind: dict[str, InheritKind]


class ItemVariant:
    """Data required for an item in a particular style."""

    def __init__(
        self,
        pak_id: utils.ObjectID,
        editoritems: EditorItem,
        vbsp_config: lazy_conf.LazyConf,
        editor_extra: list[EditorItem],
        authors: list[str],
        tags: list[str],
        desc: MarkdownData,
        icons: dict[str, img.Handle],
        ent_count: str = '',
        url: str | None = None,
        all_name: TransToken = TransToken.BLANK,
        all_icon: FSPath | None = None,
        source: str = '',
    ) -> None:
        self.editor = editoritems
        self.editor_extra = editor_extra
        self.vbsp_config = vbsp_config
        self.pak_id = pak_id
        self.source = source  # Original location of configs

        self.authors = authors
        self.tags = tags
        self.desc = desc
        self.icons = icons
        self.ent_count = ent_count
        self.url = url

        # The name and VTF for grouped items
        self.all_name = all_name
        self.all_icon = all_icon

        # Cached Markdown data with a representation of the instances used.
        self._inst_desc: MarkdownData | None = None

    def copy(self) -> ItemVariant:
        """Make a copy of all the data."""
        return ItemVariant(
            self.pak_id,
            self.editor,
            self.vbsp_config,
            self.editor_extra.copy(),
            self.authors.copy(),
            self.tags.copy(),
            self.desc,
            self.icons.copy(),
            self.ent_count,
            self.url,
            self.all_name,
            self.all_icon,
            self.source,
        )

    def can_group(self) -> bool:
        """Does this variant have the data needed to group?"""
        return self.all_icon is not None and bool(self.all_name)

    def override_from_folder(self, other: ItemVariant) -> None:
        """Perform the override from another item folder."""
        self.authors.extend(other.authors)
        self.tags.extend(self.tags)
        self.vbsp_config = lazy_conf.concat(self.vbsp_config, other.vbsp_config)
        self.desc += other.desc

    async def modify(
        self,
        packset: PackagesSet,
        pak_id: utils.ObjectID,
        kv: Keyvalues,
        source: str,
    ) -> ItemVariant:
        """Apply a config to this item variant.

        This produces a copy with various modifications - switching
        out palette or instance values, changing the config, etc.
        """
        vbsp_config: lazy_conf.LazyConf
        if 'config' in kv:
            # Item.parse() has resolved this to the actual config.
            vbsp_config = await get_config(
                packset,
                kv,
                'items',
                pak_id,
                source=source,
            )
        else:
            vbsp_config = self.vbsp_config

        if 'replace' in kv:
            # Replace property values in the config via regex.
            vbsp_config = lazy_conf.replace(vbsp_config, [
                (re.compile(prop.real_name, re.IGNORECASE), prop.value)
                for prop in
                kv.find_children('Replace')
            ])

        vbsp_config = lazy_conf.concat(vbsp_config, await get_config(
            packset,
            kv,
            'items',
            pak_id,
            prop_name='append',
            source=source,
        ))

        if 'description' in kv:
            desc = desc_parse(kv, source, pak_id)
        else:
            desc = self.desc

        if 'appenddesc' in kv:
            desc += desc_parse(kv, source, pak_id, prop_name='appenddesc')

        if 'authors' in kv:
            authors = sep_values(kv['authors', ''])
        else:
            authors = self.authors

        if 'tags' in kv:
            tags = sep_values(kv['tags', ''])
        else:
            tags = self.tags.copy()

        variant = ItemVariant(
            pak_id,
            self.editor,
            vbsp_config,
            self.editor_extra.copy(),
            authors=authors,
            tags=tags,
            desc=desc,
            icons=self.icons.copy(),
            ent_count=kv['ent_count', self.ent_count],
            url=kv['url', self.url],
            all_name=self.all_name,
            all_icon=self.all_icon,
            source=f'{source} from {self.source}',
        )
        [variant.editor] = variant._modify_editoritems(
            kv,
            [variant.editor],
            pak_id,
            source,
            is_extra=False,
        )

        if 'extra' in kv:
            variant.editor_extra = variant._modify_editoritems(
                kv.find_key('extra'),
                variant.editor_extra,
                pak_id,
                source,
                is_extra=True
            )

        return variant

    def iter_trans_tokens(self, source: str) -> Iterator[TransTokenSource]:
        """Iterate over the tokens in this item variant."""
        yield from self.editor.iter_trans_tokens(source)
        if self.all_name:
            yield self.all_name, source + '.all_name'
        yield from self.desc.iter_tokens(source + '.desc')
        for item in self.editor_extra:
            yield from item.iter_trans_tokens(f'{source}:{item.id}')

    def instance_desc(self) -> MarkdownData:
        """Produce a description of the instances used by this item."""
        if self._inst_desc is not None:
            return self._inst_desc
        inst_desc = []
        for editor in [self.editor] + self.editor_extra:
            if editor is self.editor:
                inst_desc.append('\n\n**Instances:**\n')
            else:
                inst_desc.append(f'\n**Instances ({editor.id}):**\n')
            for ind, inst in enumerate(editor.instances):
                inst_desc += [
                    f'* {ind}: ',
                    f'"`{inst.inst}`"\n' if inst.inst != FSPath() else '""\n',
                ]
            for name, inst_path in editor.cust_instances.items():
                inst_desc += [
                    f'* "{name}": ',
                    f'"`{inst_path}`"\n' if inst_path != FSPath() else '""\n',
                ]
        LOGGER.info('Desc: {}', repr(''.join(inst_desc)))
        self._inst_desc = desc = MarkdownData(TransToken.untranslated(''.join(inst_desc)), None)
        return desc

    def _modify_editoritems(
        self,
        kv: Keyvalues,
        editor: list[EditorItem],
        pak_id: utils.ObjectID,
        source: str,
        is_extra: bool,
    ) -> list[EditorItem]:
        """Modify either the base or extra editoritems block."""
        # We can share a lot of the data, if it isn't changed and we take
        # care to copy modified parts.
        editor = [copy.copy(item) for item in editor]

        # Create a list of subtypes in the file, in order to edit.
        subtype_lookup = [
            (item, i, subtype)
            for item in editor
            for i, subtype in enumerate(item.subtypes)
        ]

        # Implement overriding palette items
        for item in kv.find_children('Palette'):
            try:
                pal_icon = FSPath(item['icon'])
            except LookupError:
                pal_icon = None

            try:  # Name for the palette icon
                pal_name = TransToken.parse(pak_id, item['pal_name'])
            except LookupError:
                pal_name = None

            try:
                bee2_icon = img.Handle.parse(
                    item.find_key('BEE2'), pak_id,
                    64, 64,
                    subfolder='items',
                )
            except LookupError:
                bee2_icon = None

            if item.name == 'all':
                if is_extra:
                    raise Exception(
                        'Cannot specify "all" for hidden '
                        f'editoritems blocks in {source}!'
                    )
                if pal_icon is not None:
                    self.all_icon = pal_icon
                    # If a previous BEE icon was present, remove so we use the VTF.
                    self.icons.pop('all', None)
                if pal_name is not None:
                    self.all_name = pal_name
                if bee2_icon is not None:
                    self.icons['all'] = bee2_icon
                continue

            try:
                subtype_ind = int(item.name)
                subtype_item, subtype_ind, subtype = subtype_lookup[subtype_ind]
            except (IndexError, ValueError, TypeError):
                raise Exception(
                    f'Invalid index "{item.name}" when modifying '
                    f'editoritems for {source}'
                ) from None
            subtype_item.subtypes = subtype_item.subtypes.copy()
            subtype_item.subtypes[subtype_ind] = subtype = copy.deepcopy(subtype)

            # Overriding model data.
            if 'models' in item or 'model' in item:
                subtype.models = []
                for prop in item:
                    if prop.name in ('models', 'model'):
                        if prop.has_children():
                            subtype.models.extend([FSPath(subprop.value) for subprop in prop])
                        else:
                            subtype.models.append(FSPath(prop.value))

            if 'name' in item:  # Name for the subtype
                subtype.name = TransToken.parse(pak_id, item['name'])

            if bee2_icon:
                if is_extra:
                    raise ValueError(
                        'Cannot specify BEE2 icons for hidden '
                        f'editoritems blocks in {source}!'
                    )
                self.icons[item.name] = bee2_icon
            elif pal_icon is not None:
                # If a previous BEE icon was present, remove it so we use the VTF.
                self.icons.pop(item.name, None)

            if pal_name is not None:
                subtype.pal_name = pal_name
            if pal_icon is not None:
                subtype.pal_icon = pal_icon

        if 'Collisions' in kv:
            # Adjust collisions.
            if len(editor) != 1:
                raise ValueError(
                    'Cannot specify instances for multiple '
                    f'editoritems blocks in {source}!'
                )
            editor[0].collisions = editor[0].collisions.copy()
            for coll_prop in kv.find_children('Collisions'):
                if coll_prop.name == 'remove':
                    if coll_prop.value == '*':
                        editor[0].collisions.clear()
                    else:
                        tags = frozenset(map(str.casefold, coll_prop.value.split()))
                        editor[0].collisions = [
                            coll for coll in editor[0].collisions
                            if not tags.issubset(coll.tags)
                        ]
                elif coll_prop.name == 'bbox':
                    editor[0].collisions.append(collisions.BBox(
                        coll_prop.vec('pos1'), coll_prop.vec('pos2'),
                        tags=frozenset(map(str.casefold, coll_prop['tags', ''].split())),
                        contents=collisions.CollideType.parse(coll_prop['type', 'SOLID']),
                    ))
                else:
                    raise ValueError(f'Unknown collision type "{coll_prop.real_name}" in {source}')

        if 'Instances' in kv:
            if len(editor) != 1:
                raise ValueError(
                    'Cannot specify instances for multiple '
                    f'editoritems blocks in {source}!'
                )
            editor[0].instances = editor[0].instances.copy()
            editor[0].cust_instances = editor[0].cust_instances.copy()

        for inst in kv.find_children('Instances'):
            if inst.has_children():
                inst_data = InstCount(
                    FSPath(inst['name']),
                    inst.int('entitycount'),
                    inst.int('brushcount'),
                    inst.int('brushsidecount'),
                )
            else:  # Allow just specifying the file.
                inst_data = InstCount(FSPath(inst.value), 0, 0, 0)

            if inst.real_name.isdecimal():  # Regular numeric
                try:
                    ind = int(inst.real_name)
                except IndexError:
                    # This would likely mean there's an extra definition or
                    # something.
                    raise ValueError(
                        f'Invalid index {inst.real_name} for '
                        f'instances in {source}'
                    ) from None
                editor[0].set_inst(ind, inst_data)
            else:  # BEE2 named instance
                inst_name = inst.name.removeprefix('bee2_')
                editor[0].cust_instances[inst_name] = inst_data.inst

        # Override IO commands.
        io_props: Keyvalues | None = None
        for name in ['IOConfig', 'IOConf', 'Inputs', 'Outputs']:
            try:
                io_props = kv.find_key(name)
                break
            except LookupError:
                pass
        if io_props is not None:
            if len(editor) != 1:
                raise ValueError(
                    'Cannot specify I/O for multiple '
                    f'editoritems blocks in {source}!'
                )
            force = io_props['force', '']
            editor[0].conn_config = ConnConfig.parse(editor[0].id, io_props)
            editor[0].force_input = 'in' in force
            editor[0].force_output = 'out' in force

        return editor


def style_with_version(style_id: str) -> utils.SpecialID | tuple[str, utils.ObjectID]:
    """Parse either a bare ID or an ID plus style."""
    if ':' in style_id:
        version, style = style_id.split(':', 1)
        # This looks up elsewhere, we can't support version IDs here yet....
        return version, utils.obj_id(style, 'Style')
    else:
        return utils.special_id(style_id, 'style')


@attrs.define(repr=False)
class Version:
    """Versions are a set of styles defined for an item."""
    name: str  # Todo: Translation token?
    id: str
    styles: dict[utils.ObjectID, ItemVariant] = attrs.field(repr=False)  # Repr would be absolutely massive.
    def_style: ItemVariant = attrs.field(repr=False)
    inherit_kind: dict[str, InheritKind]

    def get(self, style: PakRef[Style]) -> ItemVariant:
        """Fetch the variant for this style."""
        return self.styles.get(style.id, self.def_style)

# Maps an old item ID to its new one. If key is a PakRef, it applies to all subtypes.
type Migrations = dict[SubItemRef | PakRef[Item], SubItemRef]


class Item(PakObject, needs_foreground=True):
    """An item in the editor..."""
    __slots__ = [
        'id',
        '_unparsed_versions', 'versions', 'version_id_order',
        '_unparsed_def_ver', 'def_ver',
        'needs_unlock', 'all_conf', 'isolate_versions',
        'unstyled', 'folders', 'glob_desc', 'glob_desc_last',
    ]
    # These aren't initialised to start - we do that in assign_styled_items().
    versions: dict[str, Version]
    version_id_order: Sequence[str]  # IDs in the order to show in UI.
    def_ver: Version
    # Subtypes which have palette icons, and therefore should be shown in the UI.
    visual_subtypes: Sequence[int]

    _migrations: ClassVar[WeakKeyDictionary[PackagesSet, Migrations]] = WeakKeyDictionary()

    # The type required to export items.
    type ExportInfo = Mapping[str, Mapping[int, tuple[paletteLoader.HorizInd, paletteLoader.VertInd]]]
    export_info: Final[ExportKey[ExportInfo]] = ExportKey()

    def __init__(
        self,
        item_id: str,
        versions: dict[str, UnParsedVersion],
        *,
        def_version: UnParsedVersion,
        needs_unlock: bool,
        all_conf: lazy_conf.LazyConf,
        unstyled: bool,
        isolate_versions: bool,
        glob_desc: MarkdownData,
        desc_last: bool,
        folders: dict[tuple[FileSystem, str], ItemVariant],
    ) -> None:
        self.id = item_id
        self._unparsed_versions = versions
        self._unparsed_def_ver = def_version
        self.versions = {}
        self.needs_unlock = needs_unlock
        self.all_conf = all_conf
        # If set or set on a version, don't look at the first version
        # for unstyled items.
        self.isolate_versions = isolate_versions
        self.unstyled = unstyled
        self.glob_desc = glob_desc
        self.glob_desc_last = desc_last
        # Dict of folders we need to have decoded.
        self.folders = folders
        self.version_id_order = ()
        self.visual_subtypes = ()

    @classmethod
    def migrations(cls, packset: PackagesSet) -> Migrations:
        """Fetch the migrations dict for this package, creating if necessary."""
        try:
            return cls._migrations[packset]
        except KeyError:
            cls._migrations[packset] = res = {}
            return res

    @classmethod
    @override
    async def parse(cls, data: ParseData) -> Self:
        """Parse an item definition."""
        versions: dict[str, UnParsedVersion] = {}
        def_version: UnParsedVersion | None = None
        # The folders we parse for this - we don't want to parse the same
        # one twice.
        folders_to_parse: set[str] = set()
        unstyled = data.info.bool('unstyled')

        glob_desc = desc_parse(data.info, 'global:' + data.id, data.pak_id)
        desc_last = data.info.bool('AllDescLast')

        all_config = await get_config(
            data.packset, data.info,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
            source=f'<Item {data.id} all_conf>',
        )

        for ver in data.info.find_all('version'):
            ver_name = ver['name', 'Regular']
            ver_id = ver['ID', DEFAULT_VERSION]
            styles: dict[utils.SpecialID, UnParsedItemVariant | ItemVariant] = {}
            inherit_kind: dict[str, InheritKind] = {}
            ver_isolate = ver.bool('isolated')
            def_style: utils.SpecialID | None = None

            for style in ver.find_children('styles'):
                targ_style = utils.special_id(style.real_name, 'Style')
                if style.has_children():
                    if 'base' in style:
                        sty_id = style_with_version(style['Base'])
                    else:
                        sty_id = None
                    folder = UnParsedItemVariant(
                        data.pak_id,
                        data.fsys,
                        folder=style['folder', None],
                        style=sty_id,
                        config=style,
                    )
                    inherit_kind[targ_style] = InheritKind.MODIFIED

                elif style.value.startswith('<') and style.value.endswith('>'):
                    # Reusing another style unaltered using <>.
                    folder = UnParsedItemVariant(
                        data.pak_id,
                        data.fsys,
                        style=style_with_version(style.value[1:-1]),
                        folder=None,
                        config=None,
                    )
                    inherit_kind[targ_style] = InheritKind.REUSED
                else:
                    # Reference to the actual folder...
                    folder = UnParsedItemVariant(
                        data.pak_id,
                        data.fsys,
                        folder=style.value,
                        style=None,
                        config=None,
                    )
                    inherit_kind[targ_style] = InheritKind.DEFINED
                # We need to parse the folder now if set.
                if folder.folder:
                    folders_to_parse.add(folder.folder)

                # The first style is considered the 'default', and is used
                # if not otherwise present.
                # We set it to the name, then lookup later in setup_style_tree()
                if def_style is None:
                    def_style = targ_style
                # It'll only be UnParsed during our parsing.
                styles[targ_style] = folder

                if targ_style == folder.style:
                    raise ValueError(
                        f'Item "{data.id}"\'s "{style.real_name}" style '
                        "can't inherit from itself!"
                    )
            if def_style is None:
                raise ValueError(f'Item "{data.id}" has version section with no styles defined!')
            versions[ver_id] = version = UnParsedVersion(
                id=ver_id,
                name=ver_name,
                isolate=ver_isolate,
                styles=styles,
                inherit_kind=inherit_kind,
                def_style=def_style,
            )

            # The first version is the 'default',
            # so non-isolated versions will fallback to it.
            # But the default is isolated itself.
            if def_version is None:
                def_version = version
                version.isolate = True

        if def_version is None:
            raise ValueError(f'Item "{data.id}" has no versions!')

        # Parse all the folders for an item.
        async with trio.open_nursery() as nursery:
            parsed_folders: dict[str, ResultCapture[ItemVariant]] = {
                folder: ResultCapture.start_soon(
                    nursery, parse_item_folder,
                    data, folder,
                )
                for folder in folders_to_parse
            }

        # We want to ensure the number of visible subtypes doesn't change.
        subtype_counts = {
            tuple(
                i for i, subtype in enumerate(item_variant.result().editor.subtypes, 1)
                if subtype.pal_pos or subtype.pal_name
            )
            for item_variant in parsed_folders.values()
        }
        if len(subtype_counts) > 1:
            raise ValueError(
                f'Item "{data.id}" has different '
                f'visible subtypes in its styles: {", ".join(map(str, subtype_counts))}'
            )

        migrations = cls.migrations(data.packset)
        item_ref = PakRef(Item, utils.obj_id(data.id))
        for kv in data.info.find_children('migrations'):
            old_item = SubItemRef.parse(kv.real_name) if ':' in kv.name else PakRef.parse(Item, kv.real_name)
            new_item = SubItemRef(item_ref, conv_int(kv.value))
            existing = migrations.setdefault(old_item, new_item)
            if existing != new_item:
                raise ValueError(
                    f'Item migration from {old_item} is '
                    f'configured to produce both {existing} and {new_item}!'
                )

        return cls(
            data.id,
            versions=versions,
            def_version=def_version,
            needs_unlock=data.info.bool('needsUnlock'),
            isolate_versions=data.info.bool('isolate_versions'),
            all_conf=all_config,
            unstyled=unstyled,
            glob_desc=glob_desc,
            desc_last=desc_last,
            # Add filesystem to individualise this to the package.
            folders={
                (data.fsys, folder): item_variant.result()
                for folder, item_variant in
                parsed_folders.items()
            }
        )

    @override
    def add_over(self, override: Self) -> None:
        """Add the other item data to ourselves."""
        # Copy over all_conf always.
        self.all_conf = lazy_conf.concat(self.all_conf, override.all_conf)

        self.folders.update(override.folders)

        for ver_id, version in override._unparsed_versions.items():
            if ver_id not in self._unparsed_versions:
                # We don't have that version!
                self._unparsed_versions[ver_id] = version
            else:
                our_ver = self._unparsed_versions[ver_id]
                for sty_id, style in version.styles.items():
                    if sty_id not in our_ver.styles:
                        # We don't have that style!
                        our_ver.styles[sty_id] = style
                        our_ver.inherit_kind[sty_id] = version.inherit_kind[sty_id]
                    else:
                        raise ValueError(
                            'Two definitions for item folder {}.{}.{}',
                            self.id,
                            ver_id,
                            sty_id,
                        )
                        # our_style.override_from_folder(style)

    @override
    def __repr__(self) -> str:
        return f'<Item:{self.id}>'

    @override
    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield all translation tokens in this item."""
        yield from self.glob_desc.iter_tokens(f'items/{self.id}.desc')
        for version in self.versions.values():
            for style_id, variant in version.styles.items():
                yield from variant.iter_trans_tokens(f'items/{self.id}/{style_id}')

    @classmethod
    @override
    async def post_parse(cls, ctx: PackErrorInfo) -> None:
        """After styles and items are done, assign all the versions."""
        packset = ctx.packset
        # This has to be done after styles.
        await packset.ready(Style).wait()
        LOGGER.info('Allocating styled items...')
        styles = packset.all_obj(Style)
        async with trio.open_nursery() as nursery:
            for item_to_style in packset.all_obj(Item):
                nursery.start_soon(assign_styled_items, ctx, styles, item_to_style)
        # Migrations cannot be from an item that actually exists. If so, warn and remove.
        migrations = cls.migrations(packset)
        for from_item, to_item in list(migrations.items()):
            match from_item:
                case PakRef():
                    try:
                        packset.obj_by_id(cls, from_item.id, warn=False)
                    except KeyError:
                        LOGGER.info('Migration: {}:<all> -> {}', from_item, to_item)
                    else:
                        LOGGER.warning(
                            'Cannot migrate from all {} -> {}, the former item exists. Discarding.',
                            from_item, to_item
                        )
                        del migrations[from_item]
                case SubItemRef():
                    try:
                        existing = packset.obj_by_id(cls, from_item.item.id, warn=False)
                    except KeyError:
                        LOGGER.info('Migration: {} -> {}', from_item, to_item)
                        continue
                    # We allow a migration from a nonexistent subtype.
                    if 0 <= from_item.subtype < len(existing.visual_subtypes):
                        LOGGER.warning(
                            'Cannot migrate from {} -> {}, the former item+subtype exists. Discarding.',
                            from_item, to_item
                        )
                        del migrations[from_item]
                    else:
                        LOGGER.info('Migration: {} (invalid subtype) -> {}', from_item, to_item)
                case never:
                    assert_never(never)

    def selected_version(self) -> Version:
        """Fetch the selected version for this item."""
        conf = config.APP.get_cur_conf(ItemDefault, self.id)
        try:
            return self.versions[conf.version]
        except KeyError:
            LOGGER.warning('Version ID {} is not valid for item {}', conf.version, self.id)
            config.APP.store_conf(attrs.evolve(conf, version=self.def_ver.id), self.id)
            return self.def_ver

    def get_tags(self, style: PakRef[Style], subtype: int) -> Iterator[str]:
        """Return all the search keywords for this subtype and style."""
        variant = self.selected_version().get(style)
        yield self.pak_name
        yield from variant.tags
        yield from variant.authors
        try:
            name = variant.editor.subtypes[subtype].name
        except IndexError:
            LOGGER.warning(
                'No subtype number {} for {} in {} style!',
                subtype, self.id, style,
            )
        else:  # Include both the original and translated versions.
            if not name.is_game:
                yield name.token
            yield str(name)

    def get_version_names(self, cur_style: PakRef[Style]) -> tuple[list[str], list[str]]:
        """Get a list of the names and corresponding IDs for the item."""
        # item folders are reused, so we can find duplicates.
        style_obj_ids = {
            id(self.versions[ver_id].styles[cur_style.id])
            for ver_id in self.version_id_order
        }
        versions = list(self.version_id_order)
        if len(style_obj_ids) == 1:
            # All the variants are the same, so we effectively have one
            # variant. Disable the version display.
            versions = versions[:1]

        return versions, [
            self.versions[ver_id].name
            for ver_id in versions
        ]

    def _inherit_overlay(self, style: PakRef[Style], icon: img.Handle) -> img.Handle:
        """Add the inheritance overlay, if enabled."""
        if self.unstyled or not config.APP.get_cur_conf(GenOptions).visualise_inheritance:
            return icon
        inherit_kind = self.selected_version().inherit_kind.get(style.id, InheritKind.UNSTYLED)
        if inherit_kind is not InheritKind.DEFINED:
            icon = icon.overlay_text(inherit_kind.value.title(), 12)
        return icon

    def get_icon(self, style: PakRef[Style], sub_key: int) -> img.Handle:
        """Get an icon for the given subkey."""
        return self._inherit_overlay(style, self._get_icon(style, sub_key))

    def get_all_icon(self, style: PakRef[Style]) -> img.Handle | None:
        """Get the 'all' group icon for the specified style."""
        variant = self.selected_version().get(style)
        if not variant.can_group():
            return None
        try:
            icon = variant.icons['all']
        except KeyError:
            icon = img.Handle.file(utils.PackagePath(
                variant.pak_id, str(variant.all_icon)
            ), 64, 64)
        return self._inherit_overlay(style, icon)

    def _get_icon(self, style: PakRef[Style], subKey: int) -> img.Handle:
        """Get the raw icon, which may be overlaid if required."""
        variant = self.selected_version().get(style)
        try:
            return variant.icons[str(subKey)]
        except KeyError:
            # Read from editoritems.
            pass
        try:
            subtype = variant.editor.subtypes[subKey]
        except IndexError:
            LOGGER.warning(
                'No subtype number {} for {} in {} style!',
                subKey, self.id, style,
            )
            return img.Handle.error(64, 64)
        if subtype.pal_icon is None:
            LOGGER.warning(
                'No palette icon for {} subtype {} in {} style!',
                self.id, subKey, style,
            )
            return img.Handle.error(64, 64)

        return img.Handle.file(utils.PackagePath(
            variant.pak_id, str(subtype.pal_icon)
        ), 64, 64)


class ItemConfig(PakObject, allow_mult=True):
    """Allows adding additional configuration for items.

    The ID should match an item ID.
    """
    def __init__(
        self,
        it_id: str,
        all_conf: lazy_conf.LazyConf,
        version_conf: dict[str, dict[str, lazy_conf.LazyConf]],
    ) -> None:
        self.id = it_id
        self.versions = version_conf
        self.all_conf = all_conf

    @classmethod
    @override
    async def parse(cls, data: ParseData) -> ItemConfig:
        """Parse from config files."""
        vers: dict[str, dict[str, lazy_conf.LazyConf]] = {}
        styles: dict[str, lazy_conf.LazyConf]

        all_config = await get_config(
            data.packset,
            data.info,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
            source=f'<ItemConfig {data.pak_id}:{data.id} all_conf>',
        )

        for ver in data.info.find_all('Version'):
            ver_id = ver['ID', DEFAULT_VERSION]
            vers[ver_id] = styles = {}
            for sty_block in ver.find_all('Styles'):
                for style in sty_block:
                    styles[style.real_name] = await lazy_conf.from_file(
                        data.packset,
                        utils.PackagePath(data.pak_id, f'items/{style.value}.cfg'),
                        source=f'<ItemConfig {data.pak_id}:{data.id} in "{style.real_name}">',
                    )

        return ItemConfig(
            data.id,
            all_config,
            vers,
        )

    @override
    def add_over(self, override: ItemConfig) -> None:
        """Add additional style configs to the original config."""
        self.all_conf = lazy_conf.concat(self.all_conf, override.all_conf)

        for vers_id, styles in override.versions.items():
            our_styles = self.versions.setdefault(vers_id, {})
            for sty_id, style in styles.items():
                if sty_id not in our_styles:
                    our_styles[sty_id] = style
                else:
                    our_styles[sty_id] = lazy_conf.concat(our_styles[sty_id], style)


def _conv_pakref_item(value: PakRef[Item] | utils.ObjectID) -> PakRef[Item]:
    """Allow passing a PakRef, or a raw ID."""
    return value if isinstance(value, PakRef) else PakRef(Item, value)


@attrs.frozen
class SubItemRef:
    """Represents an item with a specific subtype."""
    item: PakRef[Item] = attrs.field(converter=_conv_pakref_item)
    subtype: int = 0

    @classmethod
    def parse(cls, value: str) -> SubItemRef:
        """Parse a string into a ref.

        :raises ValueError: If the value is invalid.
        """
        try:
            [raw_id, raw_sub] = value.split(':')
        except ValueError:
            raise ValueError(f'Invalid number of colons for ID:subtype "{value}"!') from None
        item = PakRef.parse(Item, raw_id)
        try:
            subtype = int(raw_sub)
            if subtype < 0:
                raise ValueError
        except (TypeError, OverflowError, ValueError):
            raise ValueError(f'Invalid subtype "{raw_sub}" for item "{raw_id}", must be a non-negative integer.')
        return cls(item, subtype)

    def __str__(self) -> str:
        """Convert this to a compact ID."""
        return f'{self.item.id}:{self.subtype}'

    def with_subtype(self, ind: int) -> SubItemRef:
        """Return the same item, but with a different subtype."""
        return SubItemRef(self.item, ind)


async def parse_item_folder(
    data: ParseData,
    fold: str,
) -> ItemVariant:
    """Parse through data in item/ folders, and return the result."""
    prop_path = f'items/{fold}/properties.txt'
    editor_path = f'items/{fold}/editoritems.txt'
    vmf_path = f'items/{fold}/editoritems.vmf'
    config_path = f'items/{fold}/vbsp_config.cfg'

    def parse_items(path: str) -> list[EditorItem]:
        """Parse the editoritems in order in a file."""
        items: list[EditorItem] = []
        try:
            f = data.fsys[path].open_str()
        except FileNotFoundError as err:
            raise OSError(f'"{data.pak_id}:items/{fold}" not valid! Folder likely missing! ') from err
        with f:
            tok = Tokenizer(f, path)
            for tok_type, tok_value in tok:
                if tok_type is Token.STRING:
                    if tok_value.casefold() != 'item':
                        raise tok.error('Unknown item option "{}"!', tok_value)
                    items.append(EditorItem.parse_one(tok, data.pak_id))
                elif tok_type is not Token.NEWLINE:
                    raise tok.error(tok_type)
        return items

    def parse_vmf(path: str) -> VMF | None:
        """Parse the VMF portion."""
        try:
            vmf_keyvalues = data.fsys.read_kv1(path)
        except FileNotFoundError:
            return None
        else:
            return VMF.parse(vmf_keyvalues)

    def parse_props(path: str) -> Keyvalues:
        """Parse the keyvalues file containing extra metadata."""
        try:
            prop = data.fsys.read_kv1(path)
        except FileNotFoundError:
            return Keyvalues('Properties', [])
        else:
            return prop.find_key('Properties', or_blank=True)

    async with trio.open_nursery() as nursery:
        props_res = async_util.sync_result(nursery, parse_props, prop_path, abandon_on_cancel=True)
        all_items = async_util.sync_result(nursery, parse_items, editor_path, abandon_on_cancel=True)
        editor_vmf_res = async_util.sync_result(nursery, parse_vmf, vmf_path, abandon_on_cancel=True)
    props = props_res.result()

    try:
        first_item, *extra_items = all_items.result()
    except ValueError:
        raise ValueError(
            f'"{data.pak_id}:items/{fold}/editoritems.txt has no '
            '"Item" block!'
        ) from None

    if first_item.id.casefold() != data.id.casefold():
        LOGGER.warning(
            'Item ID "{}" does not match "{}" in "{}:items/{}/editoritems.txt"! '
            'Info.txt ID will override, update editoritems!',
            data.id, first_item.id, data.pak_id, fold,
        )

    editor_vmf = editor_vmf_res.result()
    if editor_vmf is not None:
        editoritems_vmf.load(first_item, editor_vmf)
    # elif isinstance(filesystem, RawFileSystem):
    #     # Write out editoritems.vmf.
    #     editor_vmf = editoritems_vmf.save(first_item)
    #     with Path(filesystem.path, vmf_path).open('w') as f:
    #         LOGGER.info('Writing {}', f.name)
    #         await trio.to_thread.run_sync(editor_vmf.export, f)

    del editor_vmf, editor_vmf_res

    first_item.generate_collisions()

    # extra_items is any extra blocks (offset catchers, extent items).
    # These must not have a palette section - it'll override any the user
    # chooses.
    for extra_item in extra_items:
        extra_item.generate_collisions()
        for subtype in extra_item.subtypes:
            if subtype.pal_pos is not None:
                data.warn_auth(data.pak_id, TRANS_EXTRA_PALETTES.format(
                    filename=f'{data.pak_id}:items/{fold}/editoritems.txt'
                ))
                subtype.pal_icon = subtype.pal_pos = None
                subtype.pal_name = TransToken.BLANK

    # In files this is specified as PNG, but it's always really VTF.
    try:
        all_icon = FSPath(props['all_icon']).with_suffix('.vtf')
    except LookupError:
        all_icon = None

    try:
        all_name = TransToken.parse(data.pak_id, props['all_name'])
    except LookupError:
        all_name = TransToken.BLANK

    icons: dict[str, img.Handle] = {}
    for ico_kv in props.find_all('icon'):
        if ico_kv.has_children():
            for child in ico_kv:
                icons[child.name] = img.Handle.parse(
                    child, data.pak_id,
                    64, 64,
                    subfolder='items',
                )
        else:
            # Put it as the first/only icon.
            icons["0"] = img.Handle.parse(
                ico_kv, data.pak_id,
                64, 64,
                subfolder='items',
            )

    # Add the folder the item definition comes from,
    # so we can trace it later for debug messages.
    source = f'<{data.pak_id}>/items/{fold}'

    variant = ItemVariant(
        editoritems=first_item,
        editor_extra=extra_items,

        pak_id=data.pak_id,
        source=source,
        authors=sep_values(props['authors', '']),
        tags=sep_values(props['tags', '']),
        desc=desc_parse(props, f'{data.pak_id}:{prop_path}', data.pak_id),
        ent_count=props['ent_count', ''],
        url=props['infoURL', None],
        icons=icons,
        all_name=all_name,
        all_icon=all_icon,
        vbsp_config=await lazy_conf.from_file(
            data.packset,
            utils.PackagePath(data.pak_id, config_path),
            missing_ok=True,
            source=source,
        ),
    )

    if not variant.ent_count and config.APP.get_cur_conf(GenOptions).log_missing_ent_count:
        LOGGER.warning(
            '"{}:{}" has missing entity count!',
            data.pak_id,
            prop_path,
        )

    # If we have one of the grouping icon definitions but not both required
    # ones then notify the author.
    has_name = bool(variant.all_name)
    has_icon = variant.all_icon is not None
    if (has_name or has_icon or 'all' in variant.icons) and (not has_name or not has_icon):
        data.warn_auth(data.pak_id, TRANS_INCOMPLETE_GROUPING.format(
            filename=f'{data.pak_id}:{prop_path}'
        ))
    return variant


# noinspection PyProtectedMember
async def assign_styled_items(ctx: PackErrorInfo, all_styles: Iterable[Style], item: Item) -> None:
    """Handle inheritance across item folders.

    This will guarantee that all items have a definition for each
    combination of item and version.
    The priority is:
    - Exact Match
    - Parent style
    - Grandparent (etc) style
    - First version's style
    - First style of first version
    """
    # To do inheritance, we simply copy the data to ensure all items
    # have data defined for every used style.
    all_ver: list[UnParsedVersion] = list(item._unparsed_versions.values())

    # Move default version to the beginning, so it's read first.
    # that ensures it's got all styles set if we need to fallback.
    all_ver.remove(item._unparsed_def_ver)
    all_ver.insert(0, item._unparsed_def_ver)

    for vers in all_ver:
        # We need to repeatedly loop to handle the chains of
        # dependencies. This is a list of (style_id, UnParsed).
        to_change: list[tuple[utils.SpecialID, UnParsedItemVariant]] = []
        # The finished styles.
        styles: dict[utils.SpecialID, ItemVariant] = {}
        for sty_id, conf in vers.styles.items():
            if isinstance(conf, UnParsedItemVariant):
                to_change.append((sty_id, conf))
            else:
                styles[sty_id] = conf

        # If we have multiple versions, mention them.
        vers_desc = f' with version {vers.id}' if len(all_ver) > 1 else ''

        # Evaluate style lookups and modifications
        while to_change:
            # Needs to be done next loop.
            deferred: list[tuple[utils.SpecialID, UnParsedItemVariant]] = []
            start_data: ItemVariant
            for sty_id, conf in to_change:
                if conf.style:  # Based on another styled version.
                    if isinstance(conf.style, tuple):  # Both version and style specified.
                        try:
                            ver_id, base_style_id = conf.style
                            start_data = item.versions[ver_id].styles[base_style_id]
                            # TODO: This will fail if ver_id is after us in the all_ver list.
                            #       We need to do all the versions and styles together!
                        except KeyError:
                            raise ValueError(
                                f'Item {item.id}\'s {sty_id} style{vers_desc} '
                                f'referenced invalid style "{conf.style}"'
                            ) from None
                    else:  # Style lookup from this version.
                        try:
                            start_data = styles[conf.style]
                        except KeyError:
                            if conf.style in vers.styles:
                                # Not done yet, defer until next iteration.
                                deferred.append((sty_id, conf))
                                continue
                            raise ValueError(
                                f'Item {item.id}\'s {sty_id} style{vers_desc} '
                                f'referenced invalid style "{conf.style}"'
                            ) from None

                    # Can't have both style and folder.
                    if conf.folder:
                        raise ValueError(
                            f'Item {item.id}\'s {sty_id} style has '
                            f'both folder and style{vers_desc}!'
                        )
                elif conf.folder:
                    # Just a folder ref, we can do it immediately.
                    # We know this dict should be set.
                    try:
                        start_data = item.folders[conf.filesys, conf.folder]
                    except KeyError:
                        LOGGER.info('Folders: {}', item.folders.keys())
                        raise
                else:
                    # No source for our data!
                    raise ValueError(
                        f"Item {item.id}'s {sty_id} style has no data "
                        f"source{vers_desc}!"
                    )

                if conf.config is None:
                    styles[sty_id] = start_data.copy()
                else:
                    styles[sty_id] = await start_data.modify(
                        ctx.packset, conf.pak_id, conf.config,
                        f'<{item.id}:{vers.id}.{sty_id}>',
                    )

            # If we defer all the styles, there must be a loop somewhere.
            # We can't resolve that!
            if len(deferred) == len(to_change):
                unresolved = '\n'.join(
                    f'{conf.style} -> {sty_id}'
                    for sty_id, conf in deferred
                )
                raise ValueError(
                    f'Loop in style references for item {item.id}'
                    f'{vers_desc}!\nNot resolved:\n{unresolved}'
                )
            to_change = deferred

        default_style = styles[vers.def_style]

        if DEV_MODE.value:
            # Check each editoritem definition for some known issues.
            for sty_id, variant in styles.items():
                assert isinstance(variant, ItemVariant), f'{item.id}:{sty_id} = {variant!r}!!'
                with logger.context(f'{item.id}:{sty_id}'):
                    variant.editor.validate()
                for extra in variant.editor_extra:
                    with logger.context(f'{item.id}:{sty_id} -> {extra.id}'):
                        extra.validate()

        for style in all_styles:
            sty_id = utils.obj_id(style.id)
            if sty_id in styles:
                continue  # We already have a definition
            for base_style in style.bases:
                base_style_id = utils.obj_id(base_style.id)
                if base_style_id in styles:
                    # Copy the values for the parent to the child style
                    styles[sty_id] = styles[base_style_id]
                    vers.inherit_kind[sty_id] = InheritKind.INHERIT
                    # If requested, log this.
                    if not item.unstyled and config.APP.get_cur_conf(GenOptions).log_item_fallbacks:
                        LOGGER.warning(
                            'Item "{}" using parent "{}" for "{}"!',
                            item.id, base_style.id, style.id,
                        )
                    break
            else:
                # No parent matches!
                if not item.unstyled and config.APP.get_cur_conf(GenOptions).log_missing_styles:
                    LOGGER.warning(
                        'Item "{}"{} using inappropriate style for "{}"!',
                        item.id, vers_desc, style.id,
                    )
                # Unstyled elements allow inheriting anyway.
                vers.inherit_kind[sty_id] = InheritKind.INHERIT if item.unstyled else InheritKind.UNSTYLED
                # If 'isolate versions' is set on the item,
                # we never consult other versions for matching styles.
                # There we just use our first style (Clean usually).
                # The default version is always isolated.
                # If not isolated, we get the version from the default
                # version. Note the default one is computed first,
                # so it's guaranteed to have a value.
                styles[sty_id] = (
                    default_style if
                    item.isolate_versions or vers.isolate
                    else item.def_ver.styles[sty_id]
                )

        # Build the actual version object now we're complete.
        item.versions[vers.id] = real_version = Version(
            name=vers.name,
            id=vers.id,
            # Strip out <LOGIC> or the like, those can only end up in defaults.
            styles={
                sty_id: style
                for (sty_id, style) in styles.items()
                if utils.not_special_id(sty_id)
            },
            inherit_kind=vers.inherit_kind,
            def_style=default_style,
        )
        if item._unparsed_def_ver is vers:
            item.def_ver = real_version

    # Set these, now that everything is assigned.
    item.version_id_order = sorted(item.versions.keys())
    item.visual_subtypes = [
        ind
        for ind, sub in enumerate(item.def_ver.def_style.editor.subtypes)
        if sub.pal_name or sub.pal_icon
    ]
    assert hasattr(item, 'def_ver'), vars(item)
