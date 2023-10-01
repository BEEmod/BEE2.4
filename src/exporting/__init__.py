"""The code for performing an export to the game folder."""
import os
import pickle
import pickletools
from enum import Enum, auto

import srctools.logger
import trio.to_thread
from srctools import AtomicWriter, Keyvalues

import editoritems
from packages import ExportData
from step_order import StepOrder


LOGGER = srctools.logger.get_logger(__name__)


class StepResource(Enum):
    """Identifies types of files/data that is generated during export."""
    # Editoritems-related resources.
    EI_ITEMS = auto()  # Item definitions.
    EI_DATA = auto()  # Anything affecting the file.
    EI_FILE = auto()  # The file itself being written.

    # vbsp_config-related resources.
    VCONF_DATA = auto()  # Anything affecting the file.
    VCONF_FILE = auto()  # The file itself being written.

    # Various things that need to be sequenced.
    STYLE = auto()  # Items must come after the style.
    ERROR_SERVER_TERMINATE = auto()  # This must be terminated before we can copy compiler files.


STEPS = StepOrder(ExportData, StepResource)


@STEPS.add_step(prereq=[StepResource.VCONF_DATA], results=[StepResource.VCONF_FILE])
async def step_write_vbsp_config(exp: ExportData) -> None:
    """Write the finished vbsp_config to disk."""
    # If there are multiple of these blocks, merge them together.
    # They will end up in this order.
    exp.vbsp_conf.merge_children(
        'Textures',
        'Fizzlers',
        'Options',
        'StyleVars',
        'DropperItems',
        'Conditions',
        'Quotes',
        'PackTriggers',
    )
    os.makedirs(exp.game.abs_path('bin/bee2/'), exist_ok=True)

    def write_file(conf: Keyvalues, filename: str) -> None:
        """Write the file."""
        with AtomicWriter(filename, encoding='utf8') as vbsp_file:
            for line in conf.export():
                vbsp_file.write(line)

    await trio.to_thread.run_sync(
        write_file,
        exp.vbsp_conf, exp.game.abs_path('bin/bee2/vbsp_config.cfg'),
    )


@STEPS.add_step(prereq=[StepResource.EI_DATA, StepResource.STYLE], results=[StepResource.EI_FILE])
async def write_editoritems_script(exp: ExportData) -> None:
    """Writes the completed editoritems.txt script, for the editor."""
    # AtomicWriter writes to a temporary file, then renames in one step.
    # This ensures editoritems won't be half-written.
    with AtomicWriter(exp.game.abs_path('portal2_dlc2/scripts/editoritems.txt'), encoding='utf8') as editor_file:
        editoritems.Item.export(editor_file, exp.all_items, exp.renderables, id_filenames=False)


@STEPS.add_step(prereq=[StepResource.EI_DATA, StepResource.STYLE], results=[StepResource.EI_FILE])
async def write_editoritems_db(exp: ExportData) -> None:
    """Write the editoritems database, including all our information ready for the compiler."""
    pick = await trio.to_thread.run_sync(pickle.dumps, exp.all_items, pickle.HIGHEST_PROTOCOL)
    pick = await trio.to_thread.run_sync(pickletools.optimize, pick)
    with open(exp.game.abs_path('bin/bee2/editor.bin'), 'wb') as inst_file:
        inst_file.write(pick)
