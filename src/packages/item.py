"""Item package objects provide items for the palette customised for each style.

A system is provided so configurations can be shared and partially modified
as required.
"""
from __future__ import annotations
import operator
import re
import copy
from enum import Enum
from typing import Iterable, Iterator, Mapping, Match
from pathlib import PurePosixPath as FSPath

import attrs
import trio
from srctools import FileSystem, Keyvalues, VMF, logger, EmptyMapping
from srctools.tokenizer import Tokenizer, Token

import config.gen_opts
from app import tkMarkdown, img, lazy_conf, DEV_MODE
import config
from transtoken import TransToken, TransTokenSource
from packages import (
    PackagesSet, PakObject, ParseData, ExportData, Style,
    sep_values, desc_parse, get_config,
)
from config.item_defaults import ItemDefault, DEFAULT_VERSION
from editoritems import Item as EditorItem, InstCount
from connections import Config as ConnConfig
import editoritems_vmf
import collisions
import utils


LOGGER = logger.get_logger(__name__)

# Finds names surrounded by %s
RE_PERCENT_VAR = re.compile(r'%(\w*)%')


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
    pak_id: str  # The package that defined this variant.
    filesys: FileSystem  # The original filesystem.
    folder: str | None  # If set, use the given folder from our package.
    style: str | None  # Inherit from a specific style (implies folder is None)
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
    styles: dict[str, UnParsedItemVariant | ItemVariant]
    def_style: str
    inherit_kind: dict[str, InheritKind]


class ItemVariant:
    """Data required for an item in a particular style."""

    def __init__(
        self,
        pak_id: str,
        editoritems: EditorItem,
        vbsp_config: lazy_conf.LazyConf,
        editor_extra: list[EditorItem],
        authors: list[str],
        tags: list[str],
        desc: tkMarkdown.MarkdownData,
        icons: dict[str, img.Handle],
        ent_count: str='',
        url: str = None,
        all_name: TransToken=None,
        all_icon: FSPath=None,
        source: str='',
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
        return (
            self.all_icon is not None and
            self.all_name is not None
        )

    def override_from_folder(self, other: ItemVariant) -> None:
        """Perform the override from another item folder."""
        self.authors.extend(other.authors)
        self.tags.extend(self.tags)
        self.vbsp_config = lazy_conf.concat(self.vbsp_config, other.vbsp_config)
        self.desc = tkMarkdown.join(self.desc, other.desc)

    async def modify(self, pak_id: str, kv: Keyvalues, source: str) -> ItemVariant:
        """Apply a config to this item variant.

        This produces a copy with various modifications - switching
        out palette or instance values, changing the config, etc.
        """
        vbsp_config: lazy_conf.LazyConf
        if 'config' in kv:
            # Item.parse() has resolved this to the actual config.
            vbsp_config = get_config(
                kv,
                'items',
                pak_id,
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

        vbsp_config = lazy_conf.concat(vbsp_config, get_config(
            kv,
            'items',
            pak_id,
            prop_name='append',
        ))

        if 'description' in kv:
            desc = desc_parse(kv, source, pak_id)
        else:
            desc = self.desc

        if 'appenddesc' in kv:
            desc = tkMarkdown.join(
                desc,
                desc_parse(kv, source, pak_id, prop_name='appenddesc'),
            )

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
        if self.all_name is not None:
            yield self.all_name, source + '.all_name'
        yield from tkMarkdown.iter_tokens(self.desc, source + '.desc')
        for item in self.editor_extra:
            yield from item.iter_trans_tokens(f'{source}:{item.id}')

    def _modify_editoritems(
        self,
        kv: Keyvalues,
        editor: list[EditorItem],
        pak_id: str,
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
                )
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
                inst_name = inst.name
                if inst_name.startswith('bee2_'):
                    inst_name = inst_name[5:]
                editor[0].cust_instances[inst_name] = inst_data.inst

        # Override IO commands.
        try:
            io_props = kv.find_key('IOConf')
        except LookupError:
            pass
        else:
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


@attrs.define(repr=False)
class Version:
    """Versions are a set of styles defined for an item."""
    name: str  # Todo: Translation token?
    id: str
    styles: dict[str, ItemVariant] = attrs.field(repr=False)  # Repr would be absolutely massive.
    def_style: ItemVariant = attrs.field(repr=False)
    inherit_kind: dict[str, InheritKind]


class Item(PakObject, needs_foreground=True):
    """An item in the editor..."""
    __slots__ = [
        'id',
        '_unparsed_versions', 'versions',
        '_unparsed_def_ver', 'def_ver',
        'needs_unlock', 'all_conf', 'isolate_versions',
        'unstyled', 'folders', 'glob_desc', 'glob_desc_last',
    ]
    # These aren't initialised to start - we do that in assign_styled_items().
    versions: dict[str, Version]
    def_ver: Version

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
        glob_desc: tkMarkdown.MarkdownData,
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

    @classmethod
    async def parse(cls, data: ParseData):
        """Parse an item definition."""
        versions: dict[str, UnParsedVersion] = {}
        def_version: UnParsedVersion | None = None
        # The folders we parse for this - we don't want to parse the same
        # one twice.
        folders_to_parse: set[str] = set()
        unstyled = data.info.bool('unstyled')

        glob_desc = desc_parse(data.info, 'global:' + data.id, data.pak_id)
        desc_last = data.info.bool('AllDescLast')

        all_config = get_config(
            data.info,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
            source=f'<Item {data.id} all_conf>',
        )

        for ver in data.info.find_all('version'):
            ver_name = ver['name', 'Regular']
            ver_id = ver['ID', DEFAULT_VERSION]
            styles: dict[str, UnParsedItemVariant | ItemVariant] = {}
            inherit_kind: dict[str, InheritKind] = {}
            ver_isolate = ver.bool('isolated')
            def_style = None

            for style in ver.find_children('styles'):
                if style.has_children():
                    folder = UnParsedItemVariant(
                        data.pak_id,
                        data.fsys,
                        folder=style['folder', None],
                        style=style['Base', ''],
                        config=style,
                    )
                    inherit_kind[style.real_name] = InheritKind.MODIFIED

                elif style.value.startswith('<') and style.value.endswith('>'):
                    # Reusing another style unaltered using <>.
                    folder = UnParsedItemVariant(
                        data.pak_id,
                        data.fsys,
                        style=style.value[1:-1],
                        folder=None,
                        config=None,
                    )
                    inherit_kind[style.real_name] = InheritKind.REUSED
                else:
                    # Reference to the actual folder...
                    folder = UnParsedItemVariant(
                        data.pak_id,
                        data.fsys,
                        folder=style.value,
                        style=None,
                        config=None,
                    )
                    inherit_kind[style.real_name] = InheritKind.DEFINED
                # We need to parse the folder now if set.
                if folder.folder:
                    folders_to_parse.add(folder.folder)

                # The first style is considered the 'default', and is used
                # if not otherwise present.
                # We set it to the name, then lookup later in setup_style_tree()
                if def_style is None:
                    def_style = style.real_name
                # It'll only be UnParsed during our parsing.
                styles[style.real_name] = folder

                if style.real_name == folder.style:
                    raise ValueError(
                        f'Item "{data.id}"\'s "{style.real_name}" style '
                        "can't inherit from itself!"
                    )
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
            parsed_folders: dict[str, utils.Result[ItemVariant]] = {
                folder: utils.Result(
                    nursery, parse_item_folder,
                    folder, data.fsys, data.id, data.pak_id,
                )
                for folder in folders_to_parse
            }

        # We want to ensure the number of visible subtypes doesn't change.
        subtype_counts = {
            tuple([
                i for i, subtype in enumerate(item_variant_result().editor.subtypes, 1)
                if subtype.pal_pos or subtype.pal_name
            ])
            for item_variant_result in parsed_folders.values()
        }
        if len(subtype_counts) > 1:
            raise ValueError(
                f'Item "{data.id}" has different '
                f'visible subtypes in its styles: {", ".join(map(str, subtype_counts))}'
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
                (data.fsys, folder): item_variant_result()
                for folder, item_variant_result in
                parsed_folders.items()
            }
        )

    def add_over(self, override: 'Item') -> None:
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

    def __repr__(self) -> str:
        return f'<Item:{self.id}>'

    def iter_trans_tokens(self) -> Iterator[TransTokenSource]:
        """Yield all translation tokens in this item."""
        yield from tkMarkdown.iter_tokens(self.glob_desc, f'items/{self.id}.desc')
        for version in self.versions.values():
            for style_id, variant in version.styles.items():
                yield from variant.iter_trans_tokens(f'items/{self.id}/{style_id}')

    @classmethod
    async def post_parse(cls, packset: PackagesSet) -> None:
        """After styles and items are done, assign all the versions."""
        # This has to be done after styles.
        await packset.ready(Style).wait()
        LOGGER.info('Allocating styled items...')
        styles = packset.all_obj(Style)
        async with trio.open_nursery() as nursery:
            for item_to_style in packset.all_obj(Item):
                nursery.start_soon(assign_styled_items, styles, item_to_style)

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """Export all items into the configs.

        For the selected attribute, this is a list of (item, subitem) tuples representing the
        palette.
        """
        vbsp_config = exp_data.vbsp_conf
        pal_list: dict[str, dict[int, tuple[int, int]]] = exp_data.selected

        style_id = exp_data.selected_style.id
        item: Item
        default_conf = ItemDefault()
        for item in sorted(exp_data.packset.all_obj(Item), key=operator.attrgetter('id')):
            prop_conf = config.APP.get_cur_conf(ItemDefault, item.id, default_conf)

            (items, config_part) = item._get_export_data(pal_list, style_id, prop_conf)

            exp_data.all_items.extend(items)
            vbsp_config.extend(apply_replacements(config_part(), item.id))

            # Add auxiliary configs as well.
            try:
                aux_conf = exp_data.packset.obj_by_id(ItemConfig, item.id)
            except KeyError:
                pass
            else:
                vbsp_config.extend(apply_replacements(aux_conf.all_conf(), item.id + ':aux_all'))
                try:
                    version_data = aux_conf.versions[prop_conf.version]
                except KeyError:
                    pass  # No override.
                else:
                    # Find the first style definition for the selected one
                    # that's defined for this config
                    for poss_style in exp_data.selected_style.bases:
                        if poss_style.id in version_data:
                            vbsp_config.extend(apply_replacements(
                                version_data[poss_style.id](),
                                item.id + ':aux'
                            ))
                            break

    def _get_export_data(
        self,
        pal_list: dict[str, dict[int, tuple[int, int]]],
        style_id: str,
        prop_conf: ItemDefault,
    ) -> tuple[list[EditorItem], lazy_conf.LazyConf]:
        """Get the data for an exported item."""

        # Build a dictionary of this item's palette positions,
        # if any exist.
        palette_items: Mapping[int, tuple[int, int]] = pal_list.get(self.id.casefold(), EmptyMapping)

        try:
            sel_version = self.versions[prop_conf.version]
        except KeyError:
            LOGGER.warning('Version ID {} is not valid for item {}', prop_conf.version, self.id)
            sel_version = self.def_ver
        item_data = sel_version.styles[style_id]

        new_item = copy.deepcopy(item_data.editor)
        new_item.id = self.id  # Set the item ID to match our item
        # This allows the folders to be reused for different items if needed.

        for index, subtype in enumerate(new_item.subtypes):
            if index in palette_items:
                if len(palette_items) == 1:
                    # Switch to the 'Grouped' icon and name
                    if item_data.all_name is not None:
                        subtype.pal_name = item_data.all_name

                    if item_data.all_icon is not None:
                        subtype.pal_icon = item_data.all_icon

                subtype.pal_pos = palette_items[index]
            else:
                # This subtype isn't on the palette.
                subtype.pal_icon = None
                subtype.pal_name = None
                subtype.pal_pos = None

        # Apply configured default values to this item
        for prop in new_item.properties.values():
            if prop.allow_user_default:
                try:
                    prop.default = prop.parse_value(prop_conf.defaults[prop.kind])
                except KeyError:
                    pass
        return (
            [new_item] + item_data.editor_extra,
            # Add all_conf first so it's conditions run first by default
            lazy_conf.concat(self.all_conf, item_data.vbsp_config),
        )


class ItemConfig(PakObject, allow_mult=True):
    """Allows adding additional configuration for items.

    The ID should match an item ID.
    """
    def __init__(
        self,
        it_id,
        all_conf: lazy_conf.LazyConf,
        version_conf: dict[str, dict[str, lazy_conf.LazyConf]],
    ) -> None:
        self.id = it_id
        self.versions = version_conf
        self.all_conf = all_conf

    @classmethod
    async def parse(cls, data: ParseData) -> ItemConfig:
        """Parse from config files."""
        vers: dict[str, dict[str, lazy_conf.LazyConf]] = {}
        styles: dict[str, lazy_conf.LazyConf]

        all_config = get_config(
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
                    styles[style.real_name] = lazy_conf.from_file(
                        utils.PackagePath(data.pak_id, f'items/{style.value}.cfg'),
                        source=f'<ItemConfig {data.pak_id}:{data.id} in "{style.real_name}">',
                    )

        return ItemConfig(
            data.id,
            all_config,
            vers,
        )

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

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """This export is done in Item.export().

        Here we don't know the version set for each item.
        """
        pass


async def parse_item_folder(
    fold: str,
    filesystem: FileSystem,
    item_id: str,
    pak_id: str,
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
            f = filesystem[path].open_str()
        except FileNotFoundError as err:
            raise IOError(f'"{pak_id}:items/{fold}" not valid! Folder likely missing! ') from err
        with f:
            tok = Tokenizer(f, path)
            for tok_type, tok_value in tok:
                if tok_type is Token.STRING:
                    if tok_value.casefold() != 'item':
                        raise tok.error('Unknown item option "{}"!', tok_value)
                    items.append(EditorItem.parse_one(tok, pak_id))
                elif tok_type is not Token.NEWLINE:
                    raise tok.error(tok_type)
        return items

    def parse_vmf(path: str) -> VMF | None:
        """Parse the VMF portion."""
        try:
            vmf_keyvalues = filesystem.read_kv1(path)
        except FileNotFoundError:
            return None
        else:
            return VMF.parse(vmf_keyvalues)

    def parse_props(path: str) -> Keyvalues:
        """Parse the keyvalues file containing extra metadata."""
        try:
            prop = filesystem.read_kv1(path)
        except FileNotFoundError:
            return Keyvalues('Properties', [])
        else:
            return prop.find_key('Properties', or_blank=True)

    async with trio.open_nursery() as nursery:
        props_res = utils.Result.sync(nursery, parse_props, prop_path, cancellable=True)
        all_items = utils.Result.sync(nursery, parse_items, editor_path, cancellable=True)
        editor_vmf = utils.Result.sync(nursery, parse_vmf, vmf_path, cancellable=True)
    props = props_res()

    try:
        first_item, *extra_items = all_items()
    except ValueError:
        raise ValueError(
            f'"{pak_id}:items/{fold}/editoritems.txt has no '
            '"Item" block!'
        ) from None

    if first_item.id.casefold() != item_id.casefold():
        LOGGER.warning(
            'Item ID "{}" does not match "{}" in "{}:items/{}/editoritems.txt"! '
            'Info.txt ID will override, update editoritems!',
            item_id, first_item.id, pak_id, fold,
        )

    if editor_vmf() is not None:
        editoritems_vmf.load(first_item, editor_vmf())
        del editor_vmf
    first_item.generate_collisions()

    # extra_items is any extra blocks (offset catchers, extent items).
    # These must not have a palette section - it'll override any the user
    # chooses.
    for extra_item in extra_items:
        extra_item.generate_collisions()
        for subtype in extra_item.subtypes:
            if subtype.pal_pos is not None:
                LOGGER.warning(
                    f'"{pak_id}:items/{fold}/editoritems.txt has '
                    f'palette set for extra item blocks. Deleting.'
                )
                subtype.pal_icon = subtype.pal_pos = subtype.pal_name = None

    # In files this is specified as PNG, but it's always really VTF.
    try:
        all_icon = FSPath(props['all_icon']).with_suffix('.vtf')
    except LookupError:
        all_icon = None

    try:
        all_name = TransToken.parse(pak_id, props['all_name'])
    except LookupError:
        all_name = None

    # Add the folder the item definition comes from,
    # so we can trace it later for debug messages.
    source = f'<{pak_id}>/items/{fold}'

    variant = ItemVariant(
        editoritems=first_item,
        editor_extra=extra_items,

        pak_id=pak_id,
        source=source,
        authors=sep_values(props['authors', '']),
        tags=sep_values(props['tags', '']),
        desc=desc_parse(props, f'{pak_id}:{prop_path}', pak_id),
        ent_count=props['ent_count', ''],
        url=props['infoURL', None],
        icons={
            prop.name: img.Handle.parse(
                prop, pak_id,
                64, 64,
                subfolder='items',
            )
            for prop in
            props.find_children('icon')
        },
        all_name=all_name,
        all_icon=all_icon,
        vbsp_config=lazy_conf.from_file(
            utils.PackagePath(pak_id, config_path),
            missing_ok=True,
            source=source,
        ),
    )

    if not variant.ent_count and config.APP.get_cur_conf(config.gen_opts.GenOptions).log_missing_ent_count:
        LOGGER.warning(
            '"{}:{}" has missing entity count!',
            pak_id,
            prop_path,
        )

    # If we have one of the grouping icon definitions but not both required
    # ones then notify the author.
    has_name = variant.all_name is not None
    has_icon = variant.all_icon is not None
    if (has_name or has_icon or 'all' in variant.icons) and (not has_name or not has_icon):
        LOGGER.warning(
            'Warning: "{}:{}" has incomplete grouping icon '
            'definition!',
            pak_id,
            prop_path,
        )
    return variant


def apply_replacements(conf: Keyvalues, item_id: str) -> Keyvalues:
    """Apply a set of replacement values to a config file, returning a new copy.

    The replacements are found in a 'Replacements' block in the property.
    These replace %values% starting and ending with percents. A double-percent
    allows literal percents. Unassigned values are an error.
    """
    replace: dict[str, str] = {}
    new_conf = Keyvalues.root() if conf.is_root() else Keyvalues(conf.real_name, [])

    # Strip the replacement blocks from the config, and save the values.
    for kv in conf:
        if kv.name == 'replacements':
            for rep_prop in kv:
                replace[rep_prop.name.strip('%')] = rep_prop.value
        else:
            new_conf.append(kv)

    def rep_func(match: Match) -> str:
        """Does the replacement."""
        var = match.group(1)
        if not var:  # %% becomes %.
            return '%'
        try:
            return replace[var.casefold()]
        except KeyError:
            raise ValueError(f'Unresolved variable in "{item_id}": {var!r}\nValid vars: {replace}')

    for kv in new_conf.iter_tree(blocks=True):
        kv.name = RE_PERCENT_VAR.sub(rep_func, kv.real_name)
        if not kv.has_children():
            kv.value = RE_PERCENT_VAR.sub(rep_func, kv.value)

    return new_conf


# noinspection PyProtectedMember
async def assign_styled_items(all_styles: Iterable[Style], item: Item) -> None:
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
        to_change: list[tuple[str, UnParsedItemVariant]] = []
        # The finished styles.
        styles: dict[str, ItemVariant | None] = {}
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
            deferred: list[tuple[str, UnParsedItemVariant]] = []
            start_data: ItemVariant
            for sty_id, conf in to_change:
                if conf.style:  # Based on another styled version.
                    if ':' in conf.style:  # Both version and style specified.
                        try:
                            ver_id, base_style_id = conf.style.split(':', 1)
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
                        conf.pak_id, conf.config,f'<{item.id}:{vers.id}.{sty_id}>'
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

        if DEV_MODE.get():
            # Check each editoritem definition for some known issues.
            for sty_id, variant in styles.items():
                assert isinstance(variant, ItemVariant), f'{item.id}:{sty_id} = {variant!r}!!'
                with logger.context(f'{item.id}:{sty_id}'):
                    variant.editor.validate()
                for extra in variant.editor_extra:
                    with logger.context(f'{item.id}:{sty_id} -> {extra.id}'):
                        extra.validate()

        for style in all_styles:
            if style.id in styles:
                continue  # We already have a definition
            for base_style in style.bases:
                if base_style.id in styles:
                    # Copy the values for the parent to the child style
                    styles[style.id] = styles[base_style.id]
                    vers.inherit_kind[style.id] = InheritKind.INHERIT
                    # If requested, log this.
                    if not item.unstyled and config.APP.get_cur_conf(config.gen_opts.GenOptions).log_item_fallbacks:
                        LOGGER.warning(
                            'Item "{}" using parent "{}" for "{}"!',
                            item.id, base_style.id, style.id,
                        )
                    break
            else:
                # No parent matches!
                if not item.unstyled and config.APP.get_cur_conf(config.gen_opts.GenOptions).log_missing_styles:
                    LOGGER.warning(
                        'Item "{}"{} using inappropriate style for "{}"!',
                        item.id, vers_desc, style.id,
                    )
                # Unstyled elements allow inheriting anyway.
                vers.inherit_kind[style.id] = InheritKind.INHERIT if item.unstyled else InheritKind.UNSTYLED
                # If 'isolate versions' is set on the item,
                # we never consult other versions for matching styles.
                # There we just use our first style (Clean usually).
                # The default version is always isolated.
                # If not isolated, we get the version from the default
                # version. Note the default one is computed first,
                # so it's guaranteed to have a value.
                styles[style.id] = (
                    default_style if
                    item.isolate_versions or vers.isolate
                    else item.def_ver.styles[style.id]
                )

        # Build the actual version object now we're complete.
        item.versions[vers.id] = real_version = Version(
            name=vers.name,
            id=vers.id,
            styles=styles,
            inherit_kind=vers.inherit_kind,
            def_style=default_style,
        )
        if item._unparsed_def_ver is vers:
            item.def_ver = real_version
    assert hasattr(item, 'def_ver'), vars(item)
