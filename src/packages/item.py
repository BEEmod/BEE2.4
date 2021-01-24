import operator
import re
from typing import (
    Optional, Union, Callable, Tuple, NamedTuple,
    Dict, List, Iterable, Match,
)
from srctools import FileSystem, Property, EmptyMapping
import srctools.logger

from app import tkMarkdown
from packages import (
    PakObject, ParseData, ExportData,
    sep_values, desc_parse,
    set_cond_source, get_config
)

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
        editoritems: Property,
        vbsp_config: Property,
        editor_extra: Iterable[Property],
        authors: List[str],
        tags: List[str],
        desc: tkMarkdown.MarkdownData,
        icons: Dict[str, str],
        ent_count: str='',
        url: str = None,
        all_name: str=None,
        all_icon: str=None,
        source: str='',
    ):
        self.editor = editoritems
        self.editor_extra = Property(None, list(editor_extra))
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
            self.editor.copy(),
            self.vbsp_config.copy(),
            self.editor_extra.copy(),
            self.authors.copy(),
            self.tags.copy(),
            self.desc.copy(),
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
            self.editor.copy(),
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
        variant._modify_editoritems(props, Property('', [variant.editor]), source)
        if 'Item' in variant.editor_extra and 'extra' in props:
            variant._modify_editoritems(
                props.find_key('extra'),
                variant.editor_extra,
                source,
            )

        return variant

    def _modify_editoritems(
        self,
        props: Property,
        editor: Property,
        source: str,
    ) -> None:
        """Modify either the base or extra editoritems block."""
        is_extra = editor is self.editor_extra

        subtypes = list(editor.find_all('Item', 'Editor', 'SubType'))

        # Implement overriding palette items
        for item in props.find_children('Palette'):
            pal_icon = item['icon', None]
            pal_name = item['pal_name', None]  # Name for the palette icon
            bee2_icon = item['bee2', None]

            if item.name == 'all':
                if is_extra:
                    raise Exception(
                        'Cannot specify "all" for hidden '
                        'editoritems blocks in {}!'.format(source)
                    )
                else:
                    if pal_icon:
                        self.all_icon = pal_icon
                    if pal_name:
                        self.all_name = pal_name
                    if bee2_icon:
                        self.icons['all'] = bee2_icon
                continue

            try:
                subtype = subtypes[int(item.name)]
            except (IndexError, ValueError, TypeError):
                raise Exception(
                    'Invalid index "{}" when modifying '
                    'editoritems for {}'.format(item.name, source)
                )

            # Overriding model data.
            models = []
            for prop in item:
                if prop.name in ('models', 'model'):
                    if prop.has_children():
                        models.extend([subprop.value for subprop in prop])
                    else:
                        models.append(prop.value)
            if models:
                while 'model' in subtype:
                    del subtype['model']
                for model in models:
                    subtype.append(Property('Model', [
                        Property('ModelName', model),
                    ]))

            if item['name', None]:
                subtype['name'] = item['name']  # Name for the subtype

            if bee2_icon:
                if is_extra:
                    raise Exception(
                        'Cannot specify BEE2 icons for hidden '
                        'editoritems blocks in {}!'.format(source)
                    )
                else:
                    self.icons[item.name] = bee2_icon

            if pal_name or pal_icon:
                palette = subtype.ensure_exists('Palette')
                if pal_name:
                    palette['Tooltip'] = pal_name
                if pal_icon:
                    palette['Image'] = pal_icon

        # Allow overriding the instance blocks, only for the first in extras.
        exporting = editor.find_key('Item').ensure_exists('Exporting')

        instances = exporting.ensure_exists('Instances')
        inst_children = {
            self._inst_block_key(prop): prop
            for prop in
            instances
        }
        instances.clear()

        for inst in props.find_children('Instances'):
            try:
                del inst_children[self._inst_block_key(inst)]
            except KeyError:
                pass
            if inst.has_children():
                inst_children[self._inst_block_key(inst)] = inst.copy()
            else:
                # Shortcut to just create the property
                inst_children[self._inst_block_key(inst)] = Property(
                    inst.real_name,
                    [Property('Name', inst.value)],
                )
        for key, prop in sorted(inst_children.items(), key=operator.itemgetter(0)):
            instances.append(prop)

        # Override IO commands.
        if 'IOConf' in props:
            for io_block in exporting:
                if io_block.name not in ('outputs', 'inputs'):
                    continue
                while 'bee2' in io_block:
                    del io_block['bee2']

            io_conf = props.find_key('IOConf')
            io_conf.name = 'BEE2'
            exporting.ensure_exists('Inputs').append(io_conf)

    @staticmethod
    def _inst_block_key(prop: Property):
        """Sort function for the instance blocks.

        String values come first, then all numeric ones in order.
        """
        if prop.real_name.isdecimal():
            return 0, int(prop.real_name)
        else:
            return 1, prop.real_name


class Item(PakObject):
    """An item in the editor..."""
    log_ent_count = False

    def __init__(
        self,
        item_id: str,
        versions,
        def_version,
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
        self.def_data = def_version['def_style']
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
        versions = {}
        def_version = None
        # The folders we parse for this - we don't want to parse the same
        # one twice. First they're set to None if we need to read them,
        # then parse_item_folder() replaces that with the actual values
        folders: Dict[str, Optional[ItemVariant]] = {}
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
            vals = {
                'name':    ver['name', 'Regular'],
                'id':      ver['ID', 'VER_DEFAULT'],
                'styles':  {},
                'isolate': ver.bool('isolated'),
                'def_style': None,
                }
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
                    folders[folder.folder] = None

                # The first style is considered the 'default', and is used
                # if not otherwise present.
                # We set it to the name, then lookup later in setup_style_tree()
                if vals['def_style'] is None:
                    vals['def_style'] = style.real_name
                vals['styles'][style.real_name] = folder

                if style.real_name == folder.style:
                    raise ValueError(
                        'Item "{}"\'s "{}" style '
                        'can\'t inherit from itself!'.format(
                            data.id,
                            style.real_name,
                        ))
            versions[vals['id']] = vals

            # The first version is the 'default',
            # so non-isolated versions will fallback to it.
            # But the default is isolated itself.
            if def_version is None:
                def_version = vals
                vals['isolate'] = True

        # Fill out the folders dict with the actual data
        parse_item_folder(folders, data.fsys, data.pak_id)

        # Then copy over to the styles values
        for ver in versions.values():
            if ver['def_style'] in folders:
                ver['def_style'] = folders[ver['def_style']]
            for sty, fold in ver['styles'].items():
                if isinstance(fold, str):
                    ver['styles'][sty] = folders[fold]

        if not versions:
            raise ValueError('Item "' + data.id + '" has no versions!')

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
                folders.items()
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
                our_ver = self.versions[ver_id]['styles']
                for sty_id, style in version['styles'].items():
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
        editoritems = exp_data.editoritems
        vbsp_config = exp_data.vbsp_conf
        pal_list, versions, prop_conf = exp_data.selected

        style_id = exp_data.selected_style.id

        aux_item_configs = {
            conf.id: conf
            for conf in ItemConfig.all()
        }

        for item in sorted(Item.all(), key=operator.attrgetter('id')):  # type: Item
            ver_id = versions.get(item.id, 'VER_DEFAULT')

            (
                item_block,
                editor_parts,
                config_part
            ) = item._get_export_data(
                pal_list, ver_id, style_id, prop_conf,
            )
            editoritems += apply_replacements(item_block)
            editoritems += apply_replacements(editor_parts)
            vbsp_config += apply_replacements(config_part)

            # Add auxiliary configs as well.
            try:
                aux_conf = aux_item_configs[item.id]  # type: ItemConfig
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
    ) -> Tuple[Property, Property, Property]:
        """Get the data for an exported item."""

        # Build a dictionary of this item's palette positions,
        # if any exist.
        palette_items = {
            subitem: index
            for index, (item, subitem) in
            enumerate(pal_list)
            if item == self.id
        }

        item_data = self.versions[ver_id]['styles'][style_id]  # type: ItemVariant

        new_editor = item_data.editor.copy()

        new_editor['type'] = self.id  # Set the item ID to match our item
        # This allows the folders to be reused for different items if needed.

        for index, editor_section in enumerate(
                new_editor.find_all("Editor", "Subtype")):

            # For each subtype, see if it's on the palette
            for editor_sec_index, pal_section in enumerate(
                    editor_section):
                # We need to manually loop so we get the index of the palette
                # property block in the section
                if pal_section.name != "palette":
                    # Skip non-palette blocks in "SubType"
                    # (animations, sounds, model)
                    continue

                if index in palette_items:
                    icon = pal_section['Image']

                    if len(palette_items) == 1:
                        # Switch to the 'Grouped' icon and name
                        if item_data.all_name is not None:
                            pal_section['Tooltip'] = item_data.all_name

                        if item_data.all_icon is not None:
                            icon = item_data.all_icon

                    # Bug in Portal 2 - palette icons must end with '.png',
                    # so force that to be the case for all icons.
                    if icon.casefold().endswith('.vtf'):
                        icon = icon[:-3] + 'png'
                    pal_section['Image'] = icon

                    pal_section['Position'] = "{x} {y} 0".format(
                        x=palette_items[index] % 4,
                        y=palette_items[index] // 4,
                    )
                else:
                    # This subtype isn't on the palette, delete the entire
                    # "Palette" block.
                    del editor_section[editor_sec_index]
                    break

        # Apply configured default values to this item
        prop_overrides = prop_conf.get(self.id, {})
        for prop_section in new_editor.find_all("Editor", "Properties"):
            for item_prop in prop_section:
                if item_prop.bool('BEE2_ignore'):
                    continue

                if item_prop.name.casefold() in prop_overrides:
                    item_prop['DefaultValue'] = prop_overrides[item_prop.name.casefold()]
        return (
            new_editor,
            item_data.editor_extra.copy(),
            # Add all_conf first so it's conditions run first by default
            self.all_conf + item_data.vbsp_config,
        )

    @staticmethod
    def convert_item_io(
        comm_block: Property,
        item: Property,
        conv_peti_input: Callable[[Property, str, str], None]=lambda a, b, c: None,
    ) -> Tuple[bool, bool, bool]:
        """Convert editoritems configs with the new BEE2 connections format.

        This produces (conf,  has_input, has_output, has_secondary):
        The config block for instances.cfg, and if inputs, outputs, and the
        secondary input are present.
        """
        item_id = comm_block.name
        # Look in the Inputs and Outputs blocks to find the io definitions.
        # Copy them to property names like 'Input_Activate'.
        has_input = False
        has_secondary = False
        has_output = False

        for prop in item.find_children('Exporting', 'Inputs', 'BEE2'):
            comm_block.append(prop.copy())

        for prop in item.find_children('Exporting', 'Outputs', 'BEE2'):
            comm_block.append(prop.copy())

        for block in item.find_all('Exporting', 'Inputs', CONN_NORM):
            has_input = True
            conv_peti_input(block, 'enable_cmd', 'activate')
            conv_peti_input(block, 'disable_cmd', 'deactivate')
        for block in item.find_all('Exporting', 'Outputs', CONN_NORM):
            has_output = True
            for io_prop in block:
                comm_block['out_' + io_prop.name] = io_prop.value
        # The funnel item type is special, having the additional input type.
        # Handle that specially.
        if item_id == 'item_tbeam':
            for block in item.find_all('Exporting', 'Inputs', CONN_FUNNEL):
                has_secondary = True
                conv_peti_input(block, 'sec_enable_cmd', 'activate')
                conv_peti_input(block, 'sec_disable_cmd', 'deactivate')

        # For special situations, allow forcing that we have these.
        force_io = ''
        while 'force' in comm_block:
            force_io = comm_block['force', ''].casefold()
            del comm_block['force']
        if 'in' in force_io:
            has_input = True
        if 'out' in force_io:
            has_output = True

        if 'enable_cmd' in comm_block or 'disable_cmd' in comm_block:
            has_input = True
        inp_type = comm_block['type', ''].casefold()
        if inp_type == 'dual':
            has_secondary = True
        elif inp_type == 'daisychain':
            # We specify this.
            if 'enable_cmd' in comm_block or 'disable_cmd' in comm_block:
                LOGGER.warning(
                    'DAISYCHAIN items cannot have inputs specified.'
                )
            # The item has an input, but the instance never gets it.
            has_input = True
            if not has_output:
                LOGGER.warning(
                    'DAISYCHAIN items need an output to make sense!'
                )
        elif inp_type.endswith('_logic'):
            if 'out_activate' in comm_block or 'out_deactivate' in comm_block:
                LOGGER.warning(
                    'AND_LOGIC or OR_LOGIC items cannot '
                    'have outputs specified.'
                )
            if 'enable_cmd' in comm_block or 'disable_cmd' in comm_block:
                LOGGER.warning(
                    'AND_LOGIC or OR_LOGIC items cannot '
                    'have inputs specified.'
                )
            # These logically always have both.
            has_input = has_output = True
        elif 'out_activate' in comm_block or 'out_deactivate' in comm_block:
            has_output = True
        if item_id in (
            'item_indicator_panel',
            'item_indicator_panel_timer',
            'item_indicator_toggle',
        ):
            # Force the antline instances to have inputs, so we can specify
            # the real instance doesn't. We need the fake ones to match
            # instances to items.
            has_input = True

        # Remove all the IO blocks from editoritems, and replace with
        # dummy ones.
        # Then remove the config blocks.
        for io_type in ('Inputs', 'Outputs'):
            for block in item.find_all('Exporting', io_type):
                while CONN_NORM in block:
                    del block[CONN_NORM]
                while 'BEE2' in block:
                    del block['BEE2']
        if has_input:
            item.ensure_exists('Exporting').ensure_exists('Inputs').append(
                Property(CONN_NORM, [
                    Property('Activate', 'ACTIVATE'),
                    Property('Deactivate', 'DEACTIVATE'),
                ])
            )
        # Add the secondary for funnels only.
        if item_id.casefold() == 'item_tbeam':
            if not has_secondary:
                LOGGER.warning(
                    "No dual input for TBeam, these won't function."
                )
            item.ensure_exists('Exporting').ensure_exists('Inputs').append(
                Property(CONN_FUNNEL, [
                    Property('Activate', 'ACTIVATE_SECONDARY'),
                    Property('Deactivate', 'DEACTIVATE_SECONDARY'),
                ])
            )
        # Fizzlers don't work correctly with outputs - we don't
        # want it in editoritems.
        if has_output and item['ItemClass', ''].casefold() != 'itembarrierhazard':
            item.ensure_exists('Exporting').ensure_exists('Outputs').append(
                Property(CONN_NORM, [
                    Property('Activate', 'ON_ACTIVATED'),
                    Property('Deactivate', 'ON_DEACTIVATED'),
                ])
            )
        return has_input, has_output, has_secondary



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
    folders: Dict[str, Union['ItemVariant', UnParsedItemVariant]],
    filesystem: FileSystem,
    pak_id: str,
):
    """Parse through the data in item/ folders.

    folders is a dict, with the keys set to the folder names we want.
    The values will be filled in with itemVariant values
    """
    for fold in folders:
        prop_path = 'items/' + fold + '/properties.txt'
        editor_path = 'items/' + fold + '/editoritems.txt'
        config_path = 'items/' + fold + '/vbsp_config.cfg'
        try:
            with filesystem:
                props = filesystem.read_prop(prop_path).find_key('Properties')
                editor = filesystem.read_prop(editor_path)
        except FileNotFoundError as err:
            raise IOError(
                '"' + pak_id + ':items/' + fold + '" not valid!'
                'Folder likely missing! '
            ) from err

        try:
            editoritems, *editor_extra = Property.find_all(editor, 'Item')
        except ValueError:
            raise ValueError(
                '"{}:items/{}/editoritems.txt has no '
                '"Item" block!'.format(pak_id, fold)
            )

        # editor_extra is any extra blocks (offset catchers, extent items).
        # These must not have a palette section - it'll override any the user
        # chooses.
        for item_block in editor_extra:  # type: Property
            for subtype in item_block.find_all('Editor', 'SubType'):
                while 'palette' in subtype:
                    LOGGER.warning(
                        '"{}:items/{}/editoritems.txt has palette set for extra'
                        ' item blocks. Deleting.'.format(pak_id, fold)
                    )
                    del subtype['palette']

        folders[fold] = ItemVariant(
            editoritems=editoritems,
            editor_extra=editor_extra,

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