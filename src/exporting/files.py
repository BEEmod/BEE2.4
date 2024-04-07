"""Export the core files."""
from typing import Final
from pathlib import Path
import os
import pickle
import pickletools
import shutil

from srctools import AtomicWriter, Keyvalues, logger
from srctools.dmx import Element
from srctools.filesys import File
import trio

from app import backup
from . import ExportData, STEPS, StepResource, STAGE_RESOURCES
import config
import editoritems


LOGGER = logger.get_logger(__name__)

# The location of all the instances in the game directory
INST_PATH: Final = 'sdk_content/maps/instances/BEE2'


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
        'Barriers',
        'BarrierFrames',
        'BarrierHoles',
        'DropperItems',
        'Quotes',
        'Conditions',
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


@STEPS.add_step(prereq=[StepResource.CONFIG_DATA], results=[StepResource.CONFIG_FILE])
async def step_write_configs(exp: ExportData) -> None:
    """Write config data that is managed by the config package."""

    def write(element: Element, filename: str) -> None:
        """Write to disk."""
        with AtomicWriter(filename, is_bytes=True) as file:
            element.export_kv2(
                file,
                fmt_name=config.DMX_NAME,
                fmt_ver=config.DMX_VERSION,
                unicode='format',
                cull_uuid=True,
            )

    dmx = await trio.to_thread.run_sync(config.COMPILER.build_dmx, exp.config)
    await trio.to_thread.run_sync(write,  dmx, exp.game.abs_path('bin/bee2/config.dmx'))


@STEPS.add_step(prereq=[], results=[StepResource.EI_FILE])
async def step_auto_backup(exp: ExportData) -> None:
    """Run an auto-backup, if requested to."""
    await backup.auto_backup(exp.game)


@STEPS.add_step(prereq=[StepResource.RES_SPECIAL], results=[StepResource.RES_PACKAGE])
async def step_copy_resources(exp: ExportData) -> None:
    """Copy over the resource files into this game.

    already_copied is passed from copy_mod_music(), to
    indicate which files should remain. It is the full path to the files.
    """
    if not exp.copy_resources:
        await STAGE_RESOURCES.skip()
        return

    already_copied = exp.resources

    def copy_file_thread(file: File, dest: Path) -> None:
        """Copy a single resource."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with file.open_bin() as fsrc, open(dest, 'wb') as fdest:
            shutil.copyfileobj(fsrc, fdest)

    async def copy_file(file: File, dest: Path) -> None:
        """Copy a single resource."""
        await trio.to_thread.run_sync(copy_file_thread, file, dest)
        await STAGE_RESOURCES.step(dest)

    count = 0

    async with trio.open_nursery() as nursery:
        for pack in exp.packset.packages.values():
            if not pack.enabled:
                continue
            for file in pack.fsys.walk_folder('resources'):
                try:
                    res, start_folder, pathstr = file.path.split('/', 2)
                except ValueError:
                    LOGGER.warning('File in resources root: "{}"!', file.path)
                    continue
                assert res.casefold() == 'resources', file.path

                start_folder = start_folder.casefold()

                if start_folder == 'instances':
                    dest = Path(exp.game.abs_path(INST_PATH), pathstr.casefold())
                elif start_folder in ('bee2', 'music_samp'):
                    continue  # Skip app icons and music samples.
                else:
                    # Preserve original casing.
                    dest = Path(exp.game.abs_path('bee2'), start_folder, pathstr)

                # Already copied from another package.
                if dest in already_copied:
                    continue
                already_copied.add(dest)
                nursery.start_soon(copy_file, file, dest)
                count += 1
            await STAGE_RESOURCES.set_length(count)

    LOGGER.info('Cache copied.')

    async with trio.open_nursery() as nursery:
        for folder in [INST_PATH, 'bee2']:
            abs_path = exp.game.abs_path(folder)
            for dirpath, dirnames, filenames in os.walk(abs_path):
                for filename in filenames:
                    # Keep VMX backups, disabled editor models, and the coop
                    # gun instance.
                    if filename.endswith(('.vmx', '.mdl_dis', 'tag_coop_gun.vmf')):
                        continue
                    path = Path(dirpath, filename)

                    if path not in already_copied:
                        LOGGER.info('Deleting: {}', path)
                        nursery.start_soon(trio.Path(path).unlink)
                        count += 1
        await STAGE_RESOURCES.set_length(count)

    # Save the new cache modification date.
    exp.game.mod_times.clear()
    for pack_id, pack in exp.packset.packages.items():
        exp.game.mod_times[pack_id.casefold()] = pack.get_modtime()
    exp.game.save()
