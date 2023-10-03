"""Export the core files."""
import pickle
import pickletools

import trio
from srctools import AtomicWriter, Keyvalues

from . import ExportData, STEPS, StepResource
import editoritems


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

    def write_file(conf: Keyvalues, filename: str) -> None:
        """Write the file."""
        with AtomicWriter(filename, encoding='utf8') as vbsp_file:
            for line in conf.export():
                vbsp_file.write(line)

    await trio.to_thread.run_sync(
        write_file,
        exp.vbsp_conf, exp.game.abs_path('bin/bee2/vbsp_config.cfg'),
    )


@STEPS.add_step(prereq=[
    StepResource.EI_DATA,
    StepResource.STYLE,
    StepResource.BACKUP,  # Originals must be backed up first.
], results=[StepResource.EI_FILE])
async def step_write_editoritems_script(exp: ExportData) -> None:
    """Writes the completed editoritems.txt script, for the editor."""
    path = exp.game.abs_path('portal2_dlc2/scripts/editoritems.txt')

    def write_file() -> None:
        """Write to a temporary file first, to ensure editoritems can't be partially written."""
        with AtomicWriter(path, encoding='utf8') as editor_file:
            editoritems.Item.export(
                editor_file,
                exp.all_items, exp.renderables,
                id_filenames=False,
            )

    await trio.to_thread.run_sync(write_file)


@STEPS.add_step(prereq=[StepResource.EI_DATA, StepResource.STYLE], results=[StepResource.EI_FILE])
async def step_write_editoritems_db(exp: ExportData) -> None:
    """Write the editoritems database, including all our information ready for the compiler."""
    pick = await trio.to_thread.run_sync(pickle.dumps, exp.all_items, pickle.HIGHEST_PROTOCOL)
    pick = await trio.to_thread.run_sync(pickletools.optimize, pick)
    await trio.Path(exp.game.abs_path('bin/bee2/editor.bin')).write_bytes(pick)
