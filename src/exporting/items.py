"""Export item definitions."""
from __future__ import annotations
import copy
import operator
import re
from typing import Mapping
from pathlib import PurePosixPath as FSPath

from srctools import EmptyMapping, Keyvalues
import srctools.logger
import trio

import config
from app import lazy_conf
from config.gen_opts import GenOptions
from config.item_defaults import ItemDefault
from editoritems import Item as EditorItem, InstCount
from connections import INDICATOR_CHECK_ID
from exporting import STEPS, StepResource
from packages import ExportData
from packages.item import Item, ItemConfig


# Finds names surrounded by %s
RE_PERCENT_VAR = re.compile(r'%(\w*)%')
LOGGER = srctools.logger.get_logger(__name__)


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

    def rep_func(match: re.Match[str]) -> str:
        """Does the replacement."""
        var = match.group(1)
        if not var:  # %% becomes %.
            return '%'
        try:
            return replace[var.casefold()]
        except KeyError:
            raise ValueError(
                f'Unresolved variable in "{item_id}": {var!r}\nValid vars: {replace}'
            ) from None

    for kv in new_conf.iter_tree(blocks=True):
        kv.name = RE_PERCENT_VAR.sub(rep_func, kv.real_name)
        if not kv.has_children():
            kv.value = RE_PERCENT_VAR.sub(rep_func, kv.value)

    return new_conf


def get_export_data(
    item: Item,
    pal_list: dict[str, dict[int, tuple[int, int]]],
    style_id: str,
    prop_conf: ItemDefault,
) -> tuple[list[EditorItem], lazy_conf.LazyConf]:
    """Get the data for an exported item."""

    # Build a dictionary of this item's palette positions,
    # if any exist.
    palette_items: Mapping[int, tuple[int, int]] = pal_list.get(item.id.casefold(), EmptyMapping)

    try:
        sel_version = item.versions[prop_conf.version]
    except KeyError:
        LOGGER.warning('Version ID {} is not valid for item {}', prop_conf.version, item.id)
        sel_version = item.def_ver
    item_data = sel_version.styles[style_id]

    new_item = copy.deepcopy(item_data.editor)
    new_item.id = item.id  # Set the item ID to match our item
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
        lazy_conf.concat(item.all_conf, item_data.vbsp_config),
    )


@STEPS.add_step(
    prereq=[StepResource.STYLE],
    results=[StepResource.EI_ITEMS, StepResource.EI_DATA, StepResource.VCONF_DATA],
)
async def step_write_items(exp_data: ExportData) -> None:
    """Export all items into the configs.

    For the selected attribute, this is a list of (item, subitem) tuples representing the
    palette.
    """
    vbsp_config = exp_data.vbsp_conf
    pal_list: dict[str, dict[int, tuple[int, int]]] = exp_data.selected[Item]

    style_id = exp_data.selected_style.id
    item: Item
    default_conf = ItemDefault()
    for item in sorted(exp_data.packset.all_obj(Item), key=operator.attrgetter('id')):
        prop_conf = config.APP.get_cur_conf(ItemDefault, item.id, default_conf)

        (items, config_part) = get_export_data(item, pal_list, style_id, prop_conf)

        exp_data.all_items.extend(items)
        vbsp_config.extend(apply_replacements(await config_part(), item.id))

        # Add auxiliary configs as well.
        try:
            aux_conf = exp_data.packset.obj_by_id(ItemConfig, item.id)
        except KeyError:
            pass
        else:
            vbsp_config.extend(apply_replacements(await aux_conf.all_conf(), item.id + ':aux_all'))
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
                            await version_data[poss_style.id](),
                            item.id + ':aux'
                        ))
                        break

        # Special case - if this is the indicator panel item, extract and apply the configured
        # instances.
        if item.id == INDICATOR_CHECK_ID:
            [check_item, timer_item] = items
            for ant_conf in vbsp_config.find_all('Textures', 'Antlines'):
                if 'check' in ant_conf:
                    try:
                        check_item.instances = [
                            InstCount(FSPath(ant_conf.find_block('check')['inst']))
                        ]
                    except LookupError:
                        raise ValueError(
                            'No "inst" defined for checkmarks in antline configuration!') from None
                if 'timer' in ant_conf:
                    try:
                        timer_item.instances = [
                            InstCount(FSPath(ant_conf.find_block('timer')['inst']))
                        ]
                    except LookupError:
                        raise ValueError(
                            'No "inst" defined for timers in antline configuration!') from None


@STEPS.add_step(prereq=[StepResource.EI_FILE, StepResource.RES_SPECIAL, StepResource.RES_PACKAGE], results=[])
async def step_clean_editor_models(exp_data: ExportData) -> None:
    """The game is limited to having 1024 models loaded at once.

    Editor models are always being loaded, so we need to keep the number
    small. Go through editoritems, and disable (by renaming to .mdl_dis)
    unused ones.
    """
    # If set, force them all to be present.
    force_on = config.APP.get_cur_conf(GenOptions).force_all_editor_models

    used_models = {
        str(mdl.with_suffix('')).casefold()
        for item in exp_data.all_items
        for subtype in item.subtypes
        for mdl in subtype.models
    }

    mdl_count = 0

    async def check_folder(folder: str) -> None:
        """Check a folder."""
        nonlocal mdl_count
        mdl_folder = trio.Path(exp_data.game.abs_path(f'{folder}/models/props_map_editor/'),)

        if not await mdl_folder.exists():
            return
        for file in await mdl_folder.iterdir():
            ext = ''.join(file.suffixes)
            if ext not in ('.mdl', '.mdl_dis'):
                continue

            mdl_count += 1

            if force_on or file.stem in used_models:
                new_ext = '.mdl'
            else:
                new_ext = '.mdl_dis'

            if new_ext != ext:
                await file.replace(file.with_suffix(new_ext))

    async with trio.open_nursery() as nursery:
        nursery.start_soon(check_folder, 'bee2')
        nursery.start_soon(check_folder, 'bee2_dev')

    if mdl_count != 0:
        LOGGER.info(
            '{}/{} ({:.0%}) editor models used.',
            len(used_models),
            mdl_count,
            len(used_models) / mdl_count,
        )
    else:
        LOGGER.warning('No custom editor models!')
