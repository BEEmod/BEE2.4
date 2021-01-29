import operator
import re
import copy
from idlelib import editor
from typing import (
    Optional, Union, Callable, Tuple, NamedTuple,
    Dict, List, Match, Set, cast,
)
from srctools import FileSystem, Property, EmptyMapping
from pathlib import PurePosixPath as FSPath
import srctools.logger

from app import tkMarkdown
from packages import (
    PakObject, ParseData, ExportData,
    sep_values, desc_parse,
    set_cond_source, get_config,
    Style,
)
from editoritems import Item as EditorItem, InstCount
from connections import Config as ConnConfig
from srctools.tokenizer import Tokenizer, Token


LOGGER = srctools.logger.get_logger(__name__)

# Finds names surrounded by %s
RE_PERCENT_VAR = re.compile(r'%(\w*)%')

# The name given to standard connections - regular input/outputs in editoritems.
CONN_NORM = 'CONNECTION_STANDARD'
CONN_FUNNEL = 'CONNECTION_TBEAM_POLARITY'


class UnParsedItemVariant(NamedTuple):
    """The desired variant for an item, before we've figured out the dependencies."""
    filesys: FileSystem  # The original filesystem.
    folder: Optional[str]  # If set, use the given folder from our package.
    style: Optional[str]  # Inherit from a specific style (implies folder is None)
    config: Optional[Property]  # Config for editing


class ItemVariant:
    """Data required for an item in a particular style."""

    def __init__(
        self,
        editoritems: EditorItem,
        vbsp_config: Property,
        editor_extra: List[EditorItem],
        authors: List[str],
        tags: List[str],
        desc: tkMarkdown.MarkdownData,
        icons: Dict[str, str],
        ent_count: str='',
        url: str = None,
        all_name: str=None,
        all_icon: FSPath=None,
        source: str='',
    ):
        self.editor = editoritems
        self.editor_extra = editor_extra
        self.vbsp_config = vbsp_config
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

    def copy(self) -> 'ItemVariant':
        """Make a copy of all the data."""
        return ItemVariant(
            self.editor,
            self.vbsp_config.copy(),
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

    def override_from_folder(self, other: 'ItemVariant') -> None:
        """Perform the override from another item folder."""
        self.authors.extend(other.authors)
        self.tags.extend(self.tags)
        self.vbsp_config += other.vbsp_config
        self.desc = tkMarkdown.join(self.desc, other.desc)

    def modify(self, fsys: FileSystem, props: Property, source: str) -> 'ItemVariant':
        """Apply a config to this item variant.

        This produces a copy with various modifications - switching
        out palette or instance values, changing the config, etc.
        """
        if 'config' in props:
            # Item.parse() has resolved this to the actual config.
            vbsp_config = get_config(
                props,
                fsys,
                'items',
                pak_id=fsys.path,
            )
        else:
            vbsp_config = self.vbsp_config.copy()

        if 'replace' in props:
            # Replace property values in the config via regex.
            replace_vals = [
                (re.compile(prop.real_name, re.IGNORECASE), prop.value)
                for prop in
                props.find_children('Replace')
            ]
            for prop in vbsp_config.iter_tree():
                for regex, sub in replace_vals:
                    prop.name = regex.sub(sub, prop.real_name)
                    prop.value = regex.sub(sub, prop.value)

        vbsp_config += list(get_config(
            props,
            fsys,
            'items',
            prop_name='append',
            pak_id=fsys.path,
        ))

        if 'description' in props:
            desc = desc_parse(props, source)
        else:
            desc = self.desc.copy()

        if 'appenddesc' in props:
            desc = tkMarkdown.join(
                desc,
                desc_parse(props, source, prop_name='appenddesc'),
            )

        if 'authors' in props:
            authors = sep_values(props['authors', ''])
        else:
            authors = self.authors

        if 'tags' in props:
            tags = sep_values(props['tags', ''])
        else:
            tags = self.tags.copy()

        variant = ItemVariant(
            self.editor,
            vbsp_config,
            self.editor_extra.copy(),
            authors=authors,
            tags=tags,
            desc=desc,
            icons=self.icons.copy(),
            ent_count=props['ent_count', self.ent_count],
            url=props['url', self.url],
            all_name=self.all_name,
            all_icon=self.all_icon,
            source='{} from {}'.format(source, self.source),
        )
        variant.editor = variant._modify_editoritems(props, variant.editor, source)
        if 'extra' in props:
            try:
                [extra_item] = variant.editor_extra
            except ValueError:
                LOGGER.warning(
                    'Can only modify extra editoritems block with a '
                    'single item - got {}',
                    [item.id for item in variant.editor_extra],
                )
            else:
                variant.editor_extra = [variant._modify_editoritems(
                    props.find_key('extra'),
                    extra_item,
                    source,
                )]

        return variant

    def _modify_editoritems(
        self,
        props: Property,
        editor: EditorItem,
        source: str,
    ) -> EditorItem:
        """Modify either the base or extra editoritems block."""
        is_extra = editor is not self.editor
        editor = copy.copy(editor)

        # Implement overriding palette items
        for item in props.find_children('Palette'):
            try:
                pal_icon = FSPath(item['icon'])
            except LookupError:
                pal_icon = None
            pal_name = item['pal_name', None]  # Name for the palette icon
            bee2_icon = item['bee2', None]

            if item.name == 'all':
                if is_extra:
                    raise Exception(
                        'Cannot specify "all" for hidden '
                        'editoritems blocks in {}!'.format(source)
                    )
                else:
                    if pal_icon is not None:
                        self.all_icon = pal_icon
                    if pal_name is not None:
                        self.all_name = pal_name
                    if bee2_icon is not None:
                        self.icons['all'] = bee2_icon
                continue

            try:
                subtype_ind = int(item.name)
                subtype = editor.subtypes[subtype_ind]
            except (IndexError, ValueError, TypeError):
                raise Exception(
                    'Invalid index "{}" when modifying '
                    'editoritems for {}'.format(item.name, source)
                )
            editor.subtypes[subtype_ind] = subtype = copy.deepcopy(subtype)

            # Overriding model data.
            subtype.models.clear()
            for prop in item:
                if prop.name in ('models', 'model'):
                    if prop.has_children():
                        subtype.models.extend([FSPath(subprop.value) for subprop in prop])
                    else:
                        subtype.models.append(FSPath(prop.value))

            if item['name', None]:
                subtype.name = item['name']  # Name for the subtype

            if bee2_icon:
                if is_extra:
                    raise ValueError(
                        'Cannot specify BEE2 icons for hidden '
                        'editoritems blocks in {}!'.format(source)
                    )
                else:
                    self.icons[item.name] = bee2_icon

            if pal_name is not None:
                subtype.pal_name = pal_name
            if pal_icon is not None:
                subtype.pal_icon = pal_icon

        if 'Instances' in props:
            editor.instances = editor.instances.copy()
            editor.cust_instances = editor.cust_instances.copy()

        for inst in props.find_children('Instances'):
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
                editor.set_inst(ind, inst_data)
            else:  # BEE2 named instance
                editor.cust_instances[inst.name] = inst_data.inst

        # Override IO commands.
        try:
            io_props = props.find_key('IOConf')
        except LookupError:
            pass
        else:
            force = io_props['force', '']
            editor.conn_config = ConnConfig.parse(editor.id, io_props)
            editor.force_input = 'in' in force
            editor.force_output = 'out' in force

        return editor


class Version:
    """Versions are a set of styles defined for an item.

    If isolate is set, the default version will not be consulted for missing
    styles.

    During parsing, the styles are UnParsedItemVariant and def_style is the ID.
    We convert that in setup_style_tree.
    """
    __slots__ = ['name', 'id', 'isolate', 'styles', 'def_style']
    def __init__(
        self,
        id: str,
        name: str,
        isolate: bool,
        styles: Dict[str, ItemVariant],
        def_style: Union[ItemVariant, Union[str, ItemVariant]],
    ) -> None:
        self.name = name
        self.id = id
        self.isolate = isolate
        self.styles = styles
        self.def_style = def_style

    def __repr__(self) -> str:
        return f'<Version "{self.id}">'


class Item(PakObject):
    """An item in the editor..."""
    log_ent_count = False

    def __init__(
        self,
        item_id: str,
        versions: Dict[str, Version],
        def_version: Version,
        needs_unlock: bool=False,
        all_conf: Optional[Property]=None,
        unstyled: bool=False,
        isolate_versions: bool=False,
        glob_desc: tkMarkdown.MarkdownData=(),
        desc_last: bool=False,
        folders: Dict[Tuple[FileSystem, str], ItemVariant]=EmptyMapping,
    ) -> None:
        self.id = item_id
        self.versions = versions
        self.def_ver = def_version
        self.needs_unlock = needs_unlock
        self.all_conf = all_conf or Property(None, [])
        # If set or set on a version, don't look at the first version
        # for unstyled items.
        self.isolate_versions = isolate_versions
        self.unstyled = unstyled
        self.glob_desc = glob_desc
        self.glob_desc_last = desc_last
        # Dict of folders we need to have decoded.
        self.folders = folders

    @classmethod
    def parse(cls, data: ParseData):
        """Parse an item definition."""
        versions: Dict[str, Version] = {}
        def_version: Optional[Version] = None
        # The folders we parse for this - we don't want to parse the same
        # one twice.
        folders_to_parse: Set[str] = set()
        unstyled = data.info.bool('unstyled')

        glob_desc = desc_parse(data.info, 'global:' + data.id)
        desc_last = data.info.bool('AllDescLast')

        all_config = get_config(
            data.info,
            data.fsys,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )
        set_cond_source(all_config, '<Item {} all_conf>'.format(
            data.id,
        ))

        for ver in data.info.find_all('version'):
            ver_name = ver['name', 'Regular']
            ver_id = ver['ID', 'VER_DEFAULT']
            styles: Dict[str, ItemVariant] = {}
            ver_isolate = ver.bool('isolated')
            def_style = None

            for style in ver.find_children('styles'):
                if style.has_children():
                    folder = UnParsedItemVariant(
                        data.fsys,
                        folder=style['folder', None],
                        style=style['Base', ''],
                        config=style,
                    )

                elif style.value.startswith('<') and style.value.endswith('>'):
                    # Reusing another style unaltered using <>.
                    folder = UnParsedItemVariant(
                        data.fsys,
                        style=style.value[1:-1],
                        folder=None,
                        config=None,
                    )
                else:
                    # Reference to the actual folder...
                    folder = UnParsedItemVariant(
                        data.fsys,
                        folder=style.value,
                        style=None,
                        config=None,
                    )
                # We need to parse the folder now if set.
                if folder.folder:
                    folders_to_parse.add(folder.folder)

                # The first style is considered the 'default', and is used
                # if not otherwise present.
                # We set it to the name, then lookup later in setup_style_tree()
                if def_style is None:
                    def_style = style.real_name
                # It'll only be UnParsed during our parsing.
                styles[style.real_name] = cast(ItemVariant, folder)

                if style.real_name == folder.style:
                    raise ValueError(
                        'Item "{}"\'s "{}" style '
                        'can\'t inherit from itself!'.format(
                            data.id,
                            style.real_name,
                        ))
            versions[ver_id] = version = Version(
                ver_id, ver_name, ver_isolate, styles, def_style,
            )

            # The first version is the 'default',
            # so non-isolated versions will fallback to it.
            # But the default is isolated itself.
            if def_version is None:
                def_version = version
                version.isolate = True

        # Fill out the folders dict with the actual data
        parsed_folders = parse_item_folder(folders_to_parse, data.fsys, data.pak_id)

        # Then copy over to the styles values
        for ver in versions.values():
            if isinstance(ver.def_style, str):
                try:
                    ver.def_style = parsed_folders[ver.def_style]
                except KeyError:
                    pass
            for sty, fold in ver.styles.items():
                if isinstance(fold, str):
                    ver.styles[sty] = parsed_folders[fold]

        if not versions:
            raise ValueError(f'Item "{data.id}" has no versions!')

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
                (data.fsys, folder): item_variant
                for folder, item_variant in
                parsed_folders.items()
            }
        )

    def add_over(self, override: 'Item') -> None:
        """Add the other item data to ourselves."""
        # Copy over all_conf always.
        self.all_conf += override.all_conf

        self.folders.update(override.folders)

        for ver_id, version in override.versions.items():
            if ver_id not in self.versions:
                # We don't have that version!
                self.versions[ver_id] = version
            else:
                our_ver = self.versions[ver_id].styles
                for sty_id, style in version.styles.items():
                    if sty_id not in our_ver:
                        # We don't have that style!
                        our_ver[sty_id] = style
                    else:
                        raise ValueError(
                            'Two definitions for item folder {}.{}.{}',
                            self.id,
                            ver_id,
                            sty_id,
                        )
                        # our_style.override_from_folder(style)

    def __repr__(self) -> str:
        return '<Item:{}>'.format(self.id)

    @staticmethod
    def export(exp_data: ExportData):
        """Export all items into the configs.

        For the selected attribute, this takes a tuple of values:
        (pal_list, versions, prop_conf)
        Pal_list is a list of (item, subitem) tuples representing the palette.
        Versions is a {item:version_id} dictionary.
        prop_conf is a {item_id: {prop_name: value}} nested dictionary for
         overridden property names. Empty dicts can be passed instead.
        """
        vbsp_config = exp_data.vbsp_conf
        pal_list, versions, prop_conf = exp_data.selected

        style_id = exp_data.selected_style.id

        aux_item_configs: Dict[str, ItemConfig] = {
            conf.id: conf
            for conf in ItemConfig.all()
        }

        item: Item
        for item in sorted(Item.all(), key=operator.attrgetter('id')):
            ver_id = versions.get(item.id, 'VER_DEFAULT')

            (
                items,
                config_part
            ) = item._get_export_data(
                pal_list, ver_id, style_id, prop_conf,
            )

            exp_data.all_items.extend(items)
            vbsp_config += apply_replacements(config_part)

            # Add auxiliary configs as well.
            try:
                aux_conf = aux_item_configs[item.id]
            except KeyError:
                pass
            else:
                vbsp_config += apply_replacements(aux_conf.all_conf)
                try:
                    version_data = aux_conf.versions[ver_id]
                except KeyError:
                    pass  # No override.
                else:
                    # Find the first style definition for the selected one
                    # that's defined for this config
                    for poss_style in exp_data.selected_style.bases:
                        if poss_style.id in version_data:
                            vbsp_config += apply_replacements(
                                version_data[poss_style.id]
                            )
                            break

    def _get_export_data(
        self,
        pal_list,
        ver_id,
        style_id,
        prop_conf: Dict[str, Dict[str, str]],
    ) -> Tuple[List[EditorItem], Property]:
        """Get the data for an exported item."""

        # Build a dictionary of this item's palette positions,
        # if any exist.
        palette_items = {
            subitem: index
            for index, (item, subitem) in
            enumerate(pal_list)
            if item == self.id
        }

        item_data = self.versions[ver_id].styles[style_id]

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

                subtype.pal_pos = (
                    palette_items[index] % 4,
                    palette_items[index] // 4,
                )
            else:
                # This subtype isn't on the palette.
                subtype.pal_icon = None
                subtype.pal_name = None
                subtype.pal_pos = None

        # Apply configured default values to this item
        prop_overrides = prop_conf.get(self.id, {})
        for prop_name, prop in new_item.properties.items():
            if prop.allow_user_default:
                try:
                    prop.default = prop.parse_value(prop_overrides[prop_name.casefold()])
                except KeyError:
                    pass
        return (
            [new_item] + item_data.editor_extra,
            # Add all_conf first so it's conditions run first by default
            self.all_conf + item_data.vbsp_config,
        )


class ItemConfig(PakObject, allow_mult=True, has_img=False):
    """Allows adding additional configuration for items.

    The ID should match an item ID.
    """
    def __init__(
        self,
        it_id,
        all_conf: Property,
        version_conf: Dict[str, Dict[str, Property]],
    ) -> None:
        self.id = it_id
        self.versions = version_conf
        self.all_conf = all_conf

    @classmethod
    def parse(cls, data: ParseData):
        """Parse from config files."""
        filesystem = data.fsys  # type: FileSystem
        vers = {}

        all_config = get_config(
            data.info,
            data.fsys,
            'items',
            pak_id=data.pak_id,
            prop_name='all_conf',
        )
        set_cond_source(all_config, '<ItemConfig {}:{} all_conf>'.format(
            data.pak_id, data.id,
        ))

        with filesystem:
            for ver in data.info.find_all('Version'):  # type: Property
                ver_id = ver['ID', 'VER_DEFAULT']
                vers[ver_id] = styles = {}
                for sty_block in ver.find_all('Styles'):
                    for style in sty_block:
                        styles[style.real_name] = conf = filesystem.read_prop(
                            'items/' + style.value + '.cfg'
                        )

                        set_cond_source(conf, "<ItemConfig {}:{} in '{}'>".format(
                            data.pak_id, data.id, style.real_name,
                        ))

        return cls(
            data.id,
            all_config,
            vers,
        )

    def add_over(self, override: 'ItemConfig') -> None:
        """Add additional style configs to the original config."""
        self.all_conf += override.all_conf.copy()

        for vers_id, styles in override.versions.items():
            our_styles = self.versions.setdefault(vers_id, {})
            for sty_id, style in styles.items():
                if sty_id not in our_styles:
                    our_styles[sty_id] = style.copy()
                else:
                    our_styles[sty_id] += style.copy()

    @staticmethod
    def export(exp_data: ExportData) -> None:
        """This export is done in Item.export().

        Here we don't know the version set for each item.
        """
        pass


def parse_item_folder(
    folders_to_parse: Set[str],
    filesystem: FileSystem,
    pak_id: str,
) -> Dict[str, ItemVariant]:
    """Parse through the data in item/ folders.

    folders is a dict, with the keys set to the folder names we want.
    The values will be filled in with itemVariant values
    """
    folders: Dict[str, ItemVariant] = {}
    for fold in folders_to_parse:
        prop_path = 'items/' + fold + '/properties.txt'
        editor_path = 'items/' + fold + '/editoritems.txt'
        config_path = 'items/' + fold + '/vbsp_config.cfg'

        first_item: Optional[Item] = None
        extra_items: List[EditorItem] = []
        with filesystem:
            try:
                props = filesystem.read_prop(prop_path).find_key('Properties')
                f = filesystem[editor_path].open_str()
            except FileNotFoundError as err:
                raise IOError(
                    '"' + pak_id + ':items/' + fold + '" not valid!'
                    'Folder likely missing! '
                ) from err
            with f:
                tok = Tokenizer(f, editor_path)
                for tok_type, tok_value in tok:
                    if tok_type is Token.STRING:
                        if tok_value.casefold() != 'item':
                            raise tok.error('Unknown item option "{}"!', tok_value)
                        if first_item is None:
                            first_item = EditorItem.parse_one(tok)
                        else:
                            extra_items.append(EditorItem.parse_one(tok))
                    elif tok_type is not Token.NEWLINE:
                        raise tok.error(tok_type)

        if first_item is None:
            raise ValueError(
                '"{}:items/{}/editoritems.txt has no '
                '"Item" block!'.format(pak_id, fold)
            )

        # extra_items is any extra blocks (offset catchers, extent items).
        # These must not have a palette section - it'll override any the user
        # chooses.
        for extra_item in extra_items:
            for subtype in extra_item.subtypes:
                if subtype.pal_pos is not None:
                    LOGGER.warning(
                        '"{}:items/{}/editoritems.txt has palette set for extra'
                        ' item blocks. Deleting.'.format(pak_id, fold)
                    )
                    subtype.pal_icon = subtype.pal_pos = subtype.pal_name = None

        folders[fold] = ItemVariant(
            editoritems=first_item,
            editor_extra=extra_items,

            # Add the folder the item definition comes from,
            # so we can trace it later for debug messages.
            source='<{}>/items/{}'.format(pak_id, fold),
            vbsp_config=Property(None, []),

            authors=sep_values(props['authors', '']),
            tags=sep_values(props['tags', '']),
            desc=desc_parse(props, pak_id + ':' + prop_path),
            ent_count=props['ent_count', ''],
            url=props['infoURL', None],
            icons={
                p.name: p.value
                for p in
                props['icon', []]
            },
            all_name=props['all_name', None],
            all_icon=props['all_icon', None],
        )

        if Item.log_ent_count and not folders[fold].ent_count:
            LOGGER.warning(
                '"{id}:{path}" has missing entity count!',
                id=pak_id,
                path=prop_path,
            )

        # If we have at least 1, but not all of the grouping icon
        # definitions then notify the author.
        num_group_parts = (
            (folders[fold].all_name is not None)
            + (folders[fold].all_icon is not None)
            + ('all' in folders[fold].icons)
        )
        if 0 < num_group_parts < 3:
            LOGGER.warning(
                'Warning: "{id}:{path}" has incomplete grouping icon '
                'definition!',
                id=pak_id,
                path=prop_path,
            )
        try:
            with filesystem:
                folders[fold].vbsp_config = conf = filesystem.read_prop(
                    config_path,
                )
        except FileNotFoundError:
            folders[fold].vbsp_config = conf = Property(None, [])

        set_cond_source(conf, folders[fold].source)
    return folders


def apply_replacements(conf: Property) -> Property:
    """Apply a set of replacement values to a config file, returning a new copy.

    The replacements are found in a 'Replacements' block in the property.
    These replace %values% starting and ending with percents. A double-percent
    allows literal percents. Unassigned values are an error.
    """
    replace = {}
    new_conf = Property(conf.real_name, [])

    # Strip the replacement blocks from the config, and save the values.
    for prop in conf:
        if prop.name == 'replacements':
            for rep_prop in prop:
                replace[rep_prop.name.strip('%')] = rep_prop.value
        else:
            new_conf.append(prop)

    def rep_func(match: Match):
        """Does the replacement."""
        var = match.group(1)
        if not var:  # %% becomes %.
            return '%'
        try:
            return replace[var.casefold()]
        except KeyError:
            raise ValueError('Unresolved variable: {!r}\n{}'.format(var, replace))

    for prop in new_conf.iter_tree(blocks=True):
        prop.name = RE_PERCENT_VAR.sub(rep_func, prop.real_name)
        if not prop.has_children():
            prop.value = RE_PERCENT_VAR.sub(rep_func, prop.value)

    return new_conf


def assign_styled_items(
    log_fallbacks: bool,
    log_missing_styles: bool,
) -> None:
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
    for item in Item.all():
        all_ver = list(item.versions.values())

        # Move default version to the beginning, so it's read first.
        # that ensures it's got all styles set if we need to fallback.
        all_ver.remove(item.def_ver)
        all_ver.insert(0, item.def_ver)

        for vers in all_ver:
            # We need to repeatedly loop to handle the chains of
            # dependencies. This is a list of (style_id, UnParsed).
            to_change: List[Tuple[str, UnParsedItemVariant]] = []
            styles: Dict[str, Union[UnParsedItemVariant, ItemVariant, None]] = vers.styles
            for sty_id, conf in styles.items():
                to_change.append((sty_id, conf))
                # Not done yet
                styles[sty_id] = None

            # Evaluate style lookups and modifications
            while to_change:
                # Needs to be done next loop.
                deferred = []
                # UnParsedItemVariant options:
                # filesys: FileSystem  # The original filesystem.
                # folder: str  # If set, use the given folder from our package.
                # style: str  # Inherit from a specific style (implies folder is None)
                # config: Property  # Config for editing
                for sty_id, conf in to_change:
                    if conf.style:
                        try:
                            if ':' in conf.style:
                                ver_id, base_style_id = conf.style.split(':', 1)
                                start_data = item.versions[ver_id].styles[base_style_id]
                            else:
                                start_data = styles[conf.style]
                        except KeyError:
                            raise ValueError(
                                'Item {}\'s {} style referenced '
                                'invalid style "{}"'.format(
                                    item.id,
                                    sty_id,
                                    conf.style,
                                ))
                        if start_data is None:
                            # Not done yet!
                            deferred.append((sty_id, conf))
                            continue
                        # Can't have both!
                        if conf.folder:
                            raise ValueError(
                                'Item {}\'s {} style has both folder and'
                                ' style!'.format(
                                    item.id,
                                    sty_id,
                                ))
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
                            'Item {}\'s {} style has no data source!'.format(
                                item.id,
                                sty_id,
                            ))

                    if conf.config is None:
                        styles[sty_id] = start_data.copy()
                    else:
                        styles[sty_id] = start_data.modify(
                            conf.filesys,
                            conf.config,
                            '<{}:{}.{}>'.format(item.id, vers.id, sty_id),
                        )

                # If we defer all the styles, there must be a loop somewhere.
                # We can't resolve that!
                if len(deferred) == len(to_change):
                    raise ValueError(
                        'Loop in style references!\nNot resolved:\n' + '\n'.join(
                            '{} -> {}'.format(conf.style, sty_id)
                            for sty_id, conf in deferred
                        )
                    )
                to_change = deferred

            # Fix this reference to point to the actual value.
            vers.def_style = styles[vers.def_style]

            for style in Style.all():
                if style.id in styles:
                    continue  # We already have a definition
                for base_style in style.bases:
                    if base_style.id in styles:
                        # Copy the values for the parent to the child style
                        styles[style.id] = styles[base_style.id]
                        if log_fallbacks and not item.unstyled:
                            LOGGER.warning(
                                'Item "{item}" using parent '
                                '"{rep}" for "{style}"!',
                                item=item.id,
                                rep=base_style.id,
                                style=style.id,
                            )
                        break
                else:
                    # No parent matches!
                    if log_missing_styles and not item.unstyled:
                        LOGGER.warning(
                            'Item "{item}" using '
                            'inappropriate style for "{style}"!',
                            item=item.id,
                            style=style.id,
                        )

                    # If 'isolate versions' is set on the item,
                    # we never consult other versions for matching styles.
                    # There we just use our first style (Clean usually).
                    # The default version is always isolated.
                    # If not isolated, we get the version from the default
                    # version. Note the default one is computed first,
                    # so it's guaranteed to have a value.
                    styles[style.id] = (
                        vers.def_style if
                        item.isolate_versions or vers.isolate
                        else item.def_ver.styles[style.id]
                    )

