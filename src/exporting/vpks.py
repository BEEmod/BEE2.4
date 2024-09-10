"""Generate a VPK, to override editor resources."""
from __future__ import annotations

from typing import TYPE_CHECKING

from collections.abc import Iterator
from functools import partial
from pathlib import Path
import itertools
import math
import re
import shutil
import struct

import trio
from srctools import VPK, logger

from transtoken import AppError, TransToken
from . import ExportData, STEPS, StepResource
from packages import StyleVPK
import utils


LOGGER = logger.get_logger(__name__)
MARKER_FILENAME = 'bee2_vpk_autogen_marker.txt'
MARKER_CONTENTS = b"""\
This file marks the VPK as being autogenerated. 
If you want to add files, see the vpk_override/ folder.
"""

VPK_OVERRIDE_README = """\
Files in this folder will be written to the VPK during every BEE2 export.
Use to override resources as you please.

Either add regular files, or put VPKs (any name) in the root to have them be repacked.
"""


TRANS_NO_PERMS = TransToken.ui(
    'VPK files were not exported, quit Portal 2 and Hammer to ensure '
    'editor wall previews are changed.'
)
TRANS_VPK_IO_ERROR = TransToken.ui(
    'The VPK "{filename}" could not be parsed. If this was made by BEE, delete it, otherwise check '
    'if it is corrupt.'
)
TRANS_SUB_VPK_IO = TransToken.ui(
    'The vpk_override VPK "{filename}" could not be parsed. Contents was skipped.'
)


if TYPE_CHECKING:
    from app.gameMan import Game


def iter_dlcs(root: Path) -> Iterator[Path]:
    """Yield all mounted folders in order."""
    yield root / 'portal2'
    for dlc in range(1, 100):
        yield root / f'portal2_dlc{dlc}'


async def find_folder(game: Game) -> trio.Path:
    """Figure out which folder to use for this game."""
    if game.unmarked_dlc3_vpk:
        # Special case. This game had the old BEE behaviour, where it blindly wrote to DLC3
        # and didn't mark the VPK. Just get rid of the folder, let our logic continue.
        old_folder = 'portal2' if game.steamID == utils.STEAM_IDS['APERTURE TAG'] else 'portal2_dlc3'
        # Keep the file, in case it actually was important.
        for old_vpk in Path(game.root, old_folder).glob('*.vpk'):
            if old_vpk.name.startswith('pak01'):
                LOGGER.info('Removing old unmarked VPK: {}', old_vpk)
                try:
                    old_vpk.rename(old_vpk.with_name(f'bee_backup_{old_vpk.stem}.vpk'))
                except FileNotFoundError:
                    pass  # Never exported, very good.
                except FileExistsError:
                    # Somehow the backup already exists, find a free name.
                    for i in itertools.count(1):
                        try:
                            old_vpk.rename(old_vpk.with_name(f'bee_backup_{old_vpk.stem}_{i}.vpk'))
                        except FileNotFoundError:
                            break
                        except FileExistsError:
                            pass

        game.unmarked_dlc3_vpk = False
        game.save()

    # We need to check if these are our VPK.
    potentials: list[Path] = []
    # If all are not ours, put it here.
    fallback: Path

    for game_folder in iter_dlcs(Path(game.root)):
        vpk_filename = game_folder / 'pak01_dir.vpk'
        if await trio.Path(vpk_filename).exists():
            potentials.append(vpk_filename)
        else:
            fallback = vpk_filename
            break
    else:
        LOGGER.warning('Ran out of DLC folders??')
        raise FileNotFoundError

    # What we want to do is find the lowest-priority/first VPK that is a BEE one.
    # But parsing is quite slow, and we expect the first three (p2, dlc1, dlc2) to all be fails.
    # So we run the jobs, then wait for each in turn. That way later ones if they finish first
    # will be ready.
    async def worker(filename: Path, event: trio.Event) -> None:
        """Parsing VPKs are expensive, do multiple concurrently."""
        try:
            vpk = await trio.to_thread.run_sync(VPK, filename, abandon_on_cancel=True)
        except (ValueError, struct.error) as exc:
            LOGGER.exception('Could not parse VPK {}:', filename, exc_info=exc)
            raise AppError(TRANS_VPK_IO_ERROR.format(filename=str(filename))) from exc
        results[filename] = MARKER_FILENAME in vpk
        event.set()

    results: dict[Path, bool | None] = dict.fromkeys(potentials, None)
    events = [trio.Event() for _ in potentials]

    event: trio.Event
    filename: Path
    found = fallback
    async with trio.open_nursery() as nursery:
        for filename, event in zip(potentials, events, strict=True):
            nursery.start_soon(worker, filename, event)
        await trio.lowlevel.checkpoint()
        for filename, event in zip(potentials, events, strict=True):
            await event.wait()
            if results[filename]:
                LOGGER.info('Found BEE vpk: {}', filename)
                found = filename
                break
    if found is fallback:
        LOGGER.info('No BEE vpk found, writing to: {}', fallback)
    return trio.Path(found)


async def clear_files(filename: trio.Path) -> None:
    """Remove existing VPK files from the specified game folder.

     We want to leave other files - otherwise users will end up
     regenerating the sound cache every time they export.
    """
    await filename.parent.mkdir(exist_ok=True)
    try:
        file: trio.Path
        for file in await filename.parent.iterdir():
            if file.suffix == '.vpk' and file.stem.startswith('pak01_'):
                await file.unlink()
    except PermissionError:
        # The player might have Portal 2 open. Abort changing the VPK.
        LOGGER.warning("Couldn't replace VPK files. Is Portal 2 or Hammer open?")
        raise


async def fill_vpk(exp_data: ExportData, vpk_file: VPK, style_vpk: StyleVPK | None) -> None:
    """Generate the new VPK."""
    def add_files(vpk: VPK, style_vpk: StyleVPK) -> None:
        """Add selected files to the VPK."""
        for file in style_vpk.fsys.walk_folder(style_vpk.dir):
            with file.open_bin() as open_file:
                vpk.add_file(
                    file.path,
                    open_file.read(),
                    style_vpk.dir,
                )

    # Write the marker, so we can identify this later. Always put it in the _dir.vpk.
    vpk_file.add_file(MARKER_FILENAME, MARKER_CONTENTS, arch_index=None)

    if style_vpk is not None:
        await trio.to_thread.run_sync(add_files, vpk_file, style_vpk)

    # Additionally, pack in game/vpk_override/ into the vpk - this allows
    # users to easily override resources in general.

    override_folder = exp_data.game.root_path / 'vpk_override'
    await override_folder.mkdir(exist_ok=True)

    # Also write a file to explain what it's for...
    readme = override_folder / 'BEE2_README.txt'
    await readme.write_text(
        VPK_OVERRIDE_README,
        encoding='utf8'
    )

    # Matches pak01_038.vpk, etc. These shouldn't be opened.
    numeric_vpk = re.compile(r'_[0-9]+\.vpk')

    file_path: trio.Path
    for file_path in await override_folder.rglob("*"):
        if file_path == readme or not await file_path.is_file():
            # Skip the readme and folders themselves.
            continue
        rel_path = file_path.relative_to(override_folder)
        if file_path.suffix == '.vpk':
            # If a VPK file is found in vpk_override, copy the contents into ours.
            # Skip trying to open pak01_028.vpk files, we just want to find the dir.
            if numeric_vpk.search(file_path.name) is not None:
                continue
            try:
                other_vpk = await trio.to_thread.run_sync(VPK, file_path)
            except (ValueError, struct.error):
                LOGGER.exception('Could not open sub-VPK file "{}":', file_path)
                exp_data.warn(TRANS_SUB_VPK_IO.format(filename=str(file_path)))
            else:
                for entry in other_vpk:
                    LOGGER.info('Adding "{}:{}" to the VPK', file_path, entry.filename)
                    await trio.to_thread.run_sync(
                        vpk_file.add_file,
                        # If the VPK is itself in a subfolder, put its children in there.
                        str(rel_path.parent / entry.filename),
                        await trio.to_thread.run_sync(entry.read),
                    )
        else:
            LOGGER.debug('Adding "{}" to the VPK', file_path)
            await trio.to_thread.run_sync(
                vpk_file.add_file,
                str(rel_path),
                await trio.Path(file_path).read_bytes(),
            )


@STEPS.add_step(prereq=[], results=[StepResource.VPK_WRITTEN])
async def step_gen_vpk(exp_data: ExportData) -> None:
    """Generate the VPK file in the game folder."""
    sel_vpk_name = exp_data.selected_style.vpk_name

    sel_vpk: StyleVPK | None
    if sel_vpk_name:
        try:
            sel_vpk = exp_data.packset.obj_by_id(StyleVPK, sel_vpk_name)
        except KeyError:
            sel_vpk = None
    else:
        sel_vpk = None

    vpk_filename = await find_folder(exp_data.game)
    LOGGER.info('VPK to write: {}', vpk_filename)
    try:
        await clear_files(vpk_filename)
    except PermissionError:
        # We can't edit the VPK files - P2 is open...
        exp_data.warn(AppError(TRANS_NO_PERMS))
        return

    # When we make a DLC folder, this changes priorities,
    # so the soundcache will be regenerated. Just copy the old one over.
    sound_cache = Path(vpk_filename, '..', 'maps', 'soundcache', '_master.cache').resolve()
    LOGGER.info('Sound cache: {}', sound_cache)
    if not sound_cache.exists():
        LOGGER.info('Copying over soundcache file for VPK folder..')
        sound_cache.parent.mkdir(parents=True, exist_ok=True)
        try:
            await trio.to_thread.run_sync(
                shutil.copy,
                exp_data.game.abs_path('portal2_dlc2/maps/soundcache/_master.cache'),
                sound_cache,
            )
        except FileNotFoundError:
            # It's fine, this will be regenerated automatically.
            pass

    # Generate the VPK.
    try:
        vpk_file = await trio.to_thread.run_sync(partial(VPK, str(vpk_filename), mode='w'))
    except PermissionError:
        # Failed to open?
        exp_data.warn(AppError(TRANS_NO_PERMS))
        return

    try:
        with vpk_file:
            await fill_vpk(exp_data, vpk_file, sel_vpk)
    except Exception:
        # Failed to write, remove the VPK so future exports don't error.
        # Shield against cancellation, it's fine if this takes too long.
        with trio.CancelScope(shield=True, deadline=math.inf):
            await vpk_filename.unlink()
        raise

    LOGGER.info('Written {} files to VPK!', len(vpk_file))
