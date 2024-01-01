"""Conditions related to packing."""
from typing import Dict, Set

from srctools import VMF, Keyvalues, Vec
import srctools.logger

from precomp import conditions, options


LOGGER = srctools.logger.get_logger(__name__)
COND_MOD_NAME = 'Packing'

# Filenames we've packed, so we can avoid adding duplicate ents.
_PACKED_FILES: Set[str] = set()

PACKLISTS: Dict[str, Set[str]] = {}


def parse_packlists(kv: Keyvalues) -> None:
    """Parse the packlists.cfg file, to load our packing lists."""
    for child in kv.find_children('Packlist'):
        PACKLISTS[child.name] = set(child.as_array())


def pack_list(
    vmf: VMF,
    packlist_name: str,
    file_type: str='generic',
) -> None:
    """Pack the given packing list."""
    if not packlist_name:
        return
    try:
        packlist = PACKLISTS[packlist_name.casefold()]
    except KeyError:
        LOGGER.warning('Packlist "{}" does not exist!', packlist_name)
    else:
        pack_files(vmf, *packlist, file_type=file_type)


def pack_files(
    vmf: VMF,
    *files: str,
    file_type: str='generic',
) -> None:
    """Add the given files to the packing list."""

    packlist = set(files) - _PACKED_FILES

    if not packlist:
        return

    ent = vmf.create_ent(
        classname='comp_pack',
        origin=options.GLOBAL_ENTS_LOC(),
    )

    for i, file in enumerate(packlist, start=1):
        ent[file_type + str(i)] = file


@conditions.make_result('Pack')
def res_packlist(vmf: VMF, res: Keyvalues) -> object:
    """Pack files from a packing list."""
    pack_list(vmf, res.value)
    return conditions.RES_EXHAUSTED


@conditions.make_result('PackFile')
def pack_file_cond(vmf: VMF, res: Keyvalues) -> object:
    """Adda single file to the map."""
    pack_files(vmf, res.value)
    return conditions.RES_EXHAUSTED
