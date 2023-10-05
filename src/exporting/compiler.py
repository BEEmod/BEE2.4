"""Controls exporting the compiler files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
import io
import json
import shutil
import urllib.error
import urllib.request

import srctools.logger
import trio

import user_errors
import utils
from app.errors import AppError
from . import ExportData, STAGE_COMPILER, STEPS, StepResource, load_screen
from transtoken import TransToken


LOGGER = srctools.logger.get_logger(__name__)


FILES_TO_BACKUP = [
    ('Editoritems', 'portal2_dlc2/scripts/editoritems', '.txt'),
    ('Windows VBSP', 'bin/vbsp',       '.exe'),
    ('Windows VRAD', 'bin/vrad',       '.exe'),
    ('OSX VBSP',     'bin/vbsp_osx',   ''),
    ('OSX VRAD',     'bin/vrad_osx',   ''),
    ('Linux VBSP',   'bin/linux32/vbsp_linux', ''),
    ('Linux VRAD',   'bin/linux32/vrad_linux', ''),
]

if TYPE_CHECKING:
    from app.gameMan import Game


async def is_original_executable(file: trio.Path) -> bool:
    """Check if the given application is Valve's, or ours.

    We do this by checking for the PyInstaller archive.
    """
    # We can't import PyInstaller properly while frozen, so copy over
    # the important code.

    # from PyInstaller.archive.readers import CArchiveReader
    try:
        f = await file.open('rb')
    except FileNotFoundError:
        # We don't want to back up missing files.
        return False

    SIZE = 4096

    async with f:
        await f.seek(0, io.SEEK_END)
        if await f.tell() < SIZE:
            return False  # Too small.

        # Read out the last 4096 bytes, and look for the sig in there.
        await f.seek(-SIZE, io.SEEK_END)
        end_data = await f.read(SIZE)
        # We also look for BenVlodgi, to catch the BEE 1.06 precompiler.
        return b'BenVlodgi' not in end_data and b'MEI\014\013\012\013\016' not in end_data


async def terminate_error_server() -> bool:
    """If the error server is running, send it a message to get it to terminate.

    :returns: If we think it could be running.
    """
    try:
        json_text = await trio.to_thread.run_sync(user_errors.SERVER_INFO_FILE.read_text)
    except FileNotFoundError:
        LOGGER.info("No error server file, it's not running.")
        return False
    data: user_errors.ServerInfo = await trio.to_thread.run_sync(json.loads, json_text)
    del json_text

    with trio.move_on_after(10.0):
        port = data['port']
        LOGGER.info('Error server port: {}', port)
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/shutdown') as response:
                response.read()
        except urllib.error.URLError as exc:
            LOGGER.info("No response from error server, assuming it's dead: {}", exc.reason)
            return False
        else:
            # Wait for the file to be deleted.
            while user_errors.SERVER_INFO_FILE.exists():
                await trio.sleep(0.125)
            return False
    # noinspection PyUnreachableCode
    LOGGER.warning('Hit error server timeout, may still be running!')
    return True  # Hit our timeout.


async def restore_backup(game: Game) -> None:
    """Restore the original files from the backup."""
    for name, filename, ext in FILES_TO_BACKUP:
        item_path = game.abs_path(f"{filename}{ext}")
        backup_path = game.abs_path(f'{filename}_original{ext}')
        old_version = game.abs_path(f'{filename}_styles{ext}')
        if os.path.isfile(old_version):
            LOGGER.info('Restoring Stylechanger version of "{}"!', name)
            shutil.copy(old_version, item_path)
        elif os.path.isfile(backup_path):
            LOGGER.info('Restoring original "{}"!', name)
            shutil.move(backup_path, item_path)


@STEPS.add_step(prereq=[], results=[StepResource.ERROR_SERVER_TERMINATE])
async def step_terminate_error(exp_data: ExportData) -> None:
    """The error server must be terminated before copying the compiler."""
    exp_data.maybe_error_server_running = await terminate_error_server()


async def backup(description: str, item_path: trio.Path, backup_path: trio.Path) -> None:
    """Backup a single executable, or editoritems."""
    if not await item_path.is_file():
        # We can't back up at all.
        should_backup = False
    elif description == 'Editoritems':
        should_backup = not await backup_path.is_file()
    else:
        # Always backup the non-_original file, it'd be newer.
        # But only if it's Valves - not our own.
        async with trio.open_nursery() as nursery:
            should_backup_res = utils.Result(nursery, is_original_executable, item_path)
            backup_is_good = utils.Result(nursery, is_original_executable, backup_path)

        should_backup = should_backup_res()
        LOGGER.info(
            ': normal={}, backup={}',
            item_path.name,
            'Valve' if should_backup else 'BEE2',
            'Valve' if backup_is_good() else 'BEE2',
        )

        if not should_backup and not backup_is_good():
            # It's a BEE2 application, we have a problem.
            # Both the real and backup are bad, we need to get a
            # new one.
            try:
                await backup_path.unlink()
            except FileNotFoundError:
                pass
            try:
                await item_path.unlink()
            except FileNotFoundError:
                pass
            raise AppError(TransToken.ui(
                "Compiler file {file} missing. "
                "You will need to verify the game's cache in Steam to get these files back. "
                "You can then export again."
            ).format(file=item_path.name))
            # TODO: Trigger the messagebox for automatically validating.
            #       webbrowser.open('steam://validate/' + str(self.steamID))

    if should_backup:
        LOGGER.info('Backing up original {}!', item_path.name)
        await trio.to_thread.run_sync(shutil.copy, item_path, backup_path)


@STEPS.add_step(prereq=[], results=[StepResource.BACKUP])
async def step_do_backup(exp_data: ExportData) -> None:
    """Backup existing Valve compilers and editoritems."""
    async with trio.open_nursery() as nursery:
        for name, path, ext in FILES_TO_BACKUP:
            nursery.start_soon(
                backup, name,
                trio.Path(exp_data.game.abs_path(path + ext)),
                trio.Path(exp_data.game.abs_path(f'{path}_original{ext}')),
            )


@STEPS.add_step(prereq=[StepResource.BACKUP, StepResource.ERROR_SERVER_TERMINATE], results=[])
async def step_copy_compiler(exp_data: ExportData) -> None:
    """Copy the custom compiler tools."""
    LOGGER.info('Copying Custom Compiler!')
    compiler_src = utils.install_path('compiler')
    game = exp_data.game
    comp_dest = game.abs_path('bin/linux32' if utils.LINUX else 'bin')

    def perform_copy(src: Path, dest: Path) -> None:
        """Copy a file."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dest.exists():
                # First try and give ourselves write-permission,
                # if it's set read-only.
                utils.unset_readonly(dest)
            shutil.copy(src, dest)
        except PermissionError as exc:
            # We might not have permissions, if the compiler is currently
            # running.
            if exp_data.maybe_error_server_running:
                # Use a different error if this might be running.
                msg = TransToken.ui(
                    'Copying compiler file {file} failed. '
                    'Ensure {game} is not running. The webserver for the error display '
                    'may also be running, quit the vrad process or wait a few minutes.'
                )
            else:
                msg = TransToken.ui(
                    'Copying compiler file {file} failed. '
                    'Ensure {game} is not running.'
                )

            raise AppError(msg.format(file=dest, game=exp_data.game.name)) from exc

    async with trio.open_nursery() as nursery:
        for comp_file in load_screen.stage_iterate(STAGE_COMPILER, list(compiler_src.rglob('*'))):
            # Ignore folders.
            if comp_file.is_dir():
                continue

            dest = Path(comp_dest, comp_file.relative_to(compiler_src))
            LOGGER.info('\t* {} -> {}', comp_file, dest)
            nursery.start_soon(trio.to_thread.run_sync, perform_copy, comp_file, dest)
