"""Implements the parsing required for the app to identify all templates."""
from __future__ import annotations
import os

from srctools import VMF, AtomicWriter, KeyValError, Keyvalues
from srctools.dmx import (
    Attribute as DMXAttr, Element as DMXElement, ValueType as DMXValue,
)
from srctools.filesys import File
import srctools.logger
import trio

from app import gameMan
from utils import PackagePath
import packages


LOGGER = srctools.logger.get_logger(__name__)
TEMPLATES: dict[str, PackagePath] = {}


async def parse_template(pak_id: str, file: File) -> None:
    """Parse the specified template file, extracting its ID."""
    path = f'{pak_id}:{file.path}'
    temp_id = await trio.to_thread.run_sync(parse_template_fast, file, path, cancellable=True)
    if not temp_id:
        LOGGER.warning('Fast-parse failure on {}!', path)
        with file.open_str() as f:
            props = await trio.to_thread.run_sync(Keyvalues.parse, f, cancellable=True)
        vmf = await trio.to_thread.run_sync(VMF.parse, props, cancellable=True)
        del props
        conf_ents = list(vmf.by_class['bee2_template_conf'])
        if len(conf_ents) > 1:
            raise KeyValError('Multiple configuration entities in template!', path, None)
        elif not conf_ents:
            raise KeyValError('No configration entity for template!', path, None)
        temp_id = conf_ents[0]['template_id']
        if not temp_id:
            raise KeyValError('No template ID for template!', path, None)
    TEMPLATES[temp_id.casefold()] = PackagePath(pak_id, file.path)


def parse_template_fast(file: File, path: str) -> str:
    """Since we only care about a single KV, fully parsing is a big waste
    of time.

    So first try naively parsing - if we don't find it, fall
    back to full parsing.
    """
    in_entity = False
    nest_counter = 0
    has_classname = False
    found_id = ''
    temp_id = ''

    with file.open_str() as f:
        iterator = enumerate(f, 1)
        for lnum, line in iterator:
            line = line.strip().casefold()
            if not in_entity:
                if line != 'entity':
                    continue
                lnum, line = next(iterator, (None, ''))
                if line.strip() != '{':
                    raise KeyValError('Expected brace in entity definition', path, lnum)
                in_entity = True
                has_classname = False
                temp_id = ''
            elif line == '{':
                nest_counter += 1
            elif line == '}':
                if nest_counter == 0:
                    in_entity = False
                    if has_classname and found_id:
                        raise KeyValError('Multiple configuration entities in template!', path, lnum)
                    elif has_classname and temp_id:
                        found_id = temp_id
                else:
                    nest_counter -= 1
            else:  # Inside ent.
                if line == '"classname" "bee2_template_conf"':
                    has_classname = True
                elif line.startswith('"template_id"'):
                    temp_id = line[15:-1]
    return found_id


def write_templates(game: gameMan.Game) -> None:
    """Write out the location of all templates for the compiler to use."""
    root = DMXElement('Templates', 'DMERoot')
    template_list = root['temp'] = DMXAttr.array('list', DMXValue.ELEMENT)

    for temp_id, path in TEMPLATES.items():
        pack_path = packages.PACKAGE_SYS[path.package].path
        temp_el = DMXElement(temp_id, 'DMETemplate')
        temp_el['package'] = os.path.abspath(pack_path).replace('\\', '/')
        temp_el['path'] = path.path
        template_list.append(temp_el)

    with AtomicWriter(game.abs_path('bin/bee2/templates.lst'), is_bytes=True) as f:
        root.export_binary(f, fmt_name='bee_templates', unicode='format')
