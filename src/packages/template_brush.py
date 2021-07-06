"""Implements the parsing required for the app to identify all templates."""
from __future__ import annotations
from atomicwrites import atomic_write
import os

from srctools import VMF, Property, KeyValError
from srctools.filesys import File, RawFileSystem, ZipFileSystem, VPKFileSystem
from srctools.dmx import Element as DMXElement, ValueType as DMXValue, Attribute as DMXAttr
import srctools.logger

import packages
from app import gameMan
from utils import PackagePath

LOGGER = srctools.logger.get_logger(__name__)
TEMPLATES: dict[str, PackagePath] = {}


def parse_template(pak_id: str, file: File) -> None:
    """Parse the specified template file, extracting its ID."""
    path = f'{pak_id}:{file.path}'
    temp_id = parse_template_fast(file, path)
    if not temp_id:
        LOGGER.warning('Fast-parse failure on {}!', path)
        with file.open_str() as f:
            props = Property.parse(f)
        conf_ents = VMF.parse(props).by_class['bee2_template_conf']
        del props
        if len(conf_ents) > 1:
            raise KeyValError(f'Multiple configuration entities in template!', path, None)
        elif not conf_ents:
            raise KeyValError(f'No configration entity for template!', path, None)
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

    with atomic_write(game.abs_path('bin/bee2/templates.lst'), mode='wb', overwrite=True) as f:
        root.export_binary(f, fmt_name='bee_templates', unicode='format')
