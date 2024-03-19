"""Implements the parsing required for the app to identify all templates."""
from __future__ import annotations

from srctools import VMF, KeyValError, Keyvalues
from srctools.filesys import File
import srctools.logger
import trio

from packages import PackagesSet
from utils import ObjectID, PackagePath


LOGGER = srctools.logger.get_logger(__name__)


async def parse_template(packset: PackagesSet, pak_id: ObjectID, file: File) -> None:
    """Parse the specified template file, extracting its ID."""
    path = f'{pak_id}:{file.path}'
    temp_id = await trio.to_thread.run_sync(parse_template_fast, file, path, abandon_on_cancel=True)
    if not temp_id:
        LOGGER.warning('Fast-parse failure on {}!', path)
        with file.open_str() as f:
            props = await trio.to_thread.run_sync(Keyvalues.parse, f, abandon_on_cancel=True)
        vmf = await trio.to_thread.run_sync(VMF.parse, props, abandon_on_cancel=True)
        del props
        conf_ents = list(vmf.by_class['bee2_template_conf'])
        if len(conf_ents) > 1:
            raise KeyValError('Multiple configuration entities in template!', path, None)
        elif not conf_ents:
            raise KeyValError('No configration entity for template!', path, None)
        temp_id = conf_ents[0]['template_id']
        if not temp_id:
            raise KeyValError('No template ID for template!', path, None)
    packset.templates[temp_id.casefold()] = PackagePath(pak_id, file.path)


def parse_template_fast(file: File, path: str) -> str:
    """Since we only care about a single KV, fully parsing is a big waste
    of time.

    So first try naively parsing - if we don't find it, fall
    back to full parsing.
    """
    lnum: int | None
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
