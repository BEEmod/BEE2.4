"""StyleVPK allows specifying a set of files that will be added to a DLC3 VPK.

This allows altering the in-editor wall textures, as well as a few others.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Optional
from typing_extensions import Self
from pathlib import Path
import itertools
import os
import re
import shutil

from srctools import VPK, FileSystem
import srctools.logger
import trio

from packages import ExportData, NoVPKExport, PakObject, ParseData
import utils


if TYPE_CHECKING:
    from app.gameMan import Game

LOGGER = srctools.logger.get_logger(__name__, alias='packages.styleVPK')


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


def iter_dlcs(root: Path) -> Iterator[Path]:
    """Yield all mounted folders in order."""
    yield root / 'portal2'
    for dlc in range(1, 100):
        yield root / f'portal2_dlc{dlc}'


async def find_vpk(game: Game) -> Path:
    """Figure out which VPK filename to use for this game."""
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
        if vpk_filename.exists():
            potentials.append(vpk_filename)
        else:
            fallback = vpk_filename
            break
    else:
        LOGGER.warning('Ran out of DLC folders??')
        raise NoVPKExport()

    # What we want to do is find the lowest-priority/first VPK that is a BEE one.
    # But parsing is quite slow, and we expect the first three (p2, dlc1, dlc2) to all be fails.
    # So we run the jobs, then wait for each in turn. That way later ones if they finish first
    # will be ready.
    async def worker(filename: Path, event: trio.Event) -> None:
        """Parsing VPKs are expensive, do multiple concurrently."""
        vpk = await trio.to_thread.run_sync(VPK, filename, abandon_on_cancel=True)
        results[filename] = MARKER_FILENAME in vpk
        event.set()

    results: dict[Path, bool | None] = dict.fromkeys(potentials, None)
    events = [trio.Event() for _ in potentials]

    event: trio.Event
    filename: Path
    async with trio.open_nursery() as nursery:
        for filename, event in zip(potentials, events):
            nursery.start_soon(worker, filename, event)
        for filename, event in zip(potentials, events):
            await event.wait()
            if results[filename]:
                LOGGER.info('Found BEE vpk: {}', filename)
                return filename
    LOGGER.info('No BEE vpk found, writing to: {}', fallback)
    return fallback


def clear_files(folder: Path) -> None:
    """Remove existing VPK files from the specified game folder.

     We want to leave other files - otherwise users will end up
     regenerating the sound cache every time they export.
    """
    os.makedirs(folder, exist_ok=True)
    try:
        for file in folder.iterdir():
            if file.suffix == '.vpk' and file.stem.startswith('pak01_'):
                file.unlink()
    except PermissionError:
        # The player might have Portal 2 open. Abort changing the VPK.
        LOGGER.warning("Couldn't replace VPK files. Is Portal 2 or Hammer open?")
        raise


class StyleVPK(PakObject):
    """A set of VPK files used for styles.

    These are copied into _dlc3, allowing changing the in-editor wall
    textures.
    """
    def __init__(self, vpk_id: str, filesys: FileSystem[Any], directory: str) -> None:
        """Initialise a StyleVPK object."""
        self.id = vpk_id
        self.fsys = filesys
        self.dir = directory

    @classmethod
    async def parse(cls, data: ParseData) -> Self:
        """Read the VPK file from the package."""
        vpk_name = data.info['filename']

        source_folder = os.path.normpath('vpk/' + vpk_name)

        # At least one exists?
        if not any(data.fsys.walk_folder(source_folder)):
            raise Exception(
                f'VPK object "{data.id}" has no associated files!'
            )

        return cls(data.id, data.fsys, source_folder)

    @staticmethod
    async def export(exp_data: ExportData) -> None:
        """Generate the VPK file in the game folder."""
        sel_vpk_name = exp_data.selected_style.vpk_name

        sel_vpk: Optional[StyleVPK]
        if sel_vpk_name:
            try:
                sel_vpk = exp_data.packset.obj_by_id(StyleVPK, sel_vpk_name)
            except KeyError:
                sel_vpk = None
        else:
            sel_vpk = None

        vpk_filename = await find_vpk(exp_data.game)
        LOGGER.info('VPK to write: {}', vpk_filename)
        try:
            clear_files(vpk_filename.parent)
        except PermissionError as exc:
            raise NoVPKExport() from exc  # We can't edit the VPK files - P2 is open..

        # When we make a DLC folder, this changes priorities,
        # so the soundcache will be regenerated. Just copy the old one over.
        sound_cache = Path(vpk_filename, '..', 'maps', 'soundcache', '_master.cache').resolve()
        LOGGER.info('Sound cache: {}', sound_cache)
        if not sound_cache.exists():
            LOGGER.info('Copying over soundcache file for VPK folder..')
            sound_cache.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy(
                    exp_data.game.abs_path('portal2_dlc2/maps/soundcache/_master.cache'),
                    sound_cache,
                )
            except FileNotFoundError:
                # It's fine, this will be regenerated automatically.
                pass

        # Generate the VPK.
        vpk_file = VPK(vpk_filename, mode='w')
        with vpk_file:
            # Write the marker, so we can identify this later. Always put it in the _dir.vpk.
            vpk_file.add_file(MARKER_FILENAME, MARKER_CONTENTS, arch_index=None)
            if sel_vpk is not None:
                for file in sel_vpk.fsys.walk_folder(sel_vpk.dir):
                    with file.open_bin() as open_file:
                        vpk_file.add_file(
                            file.path,
                            open_file.read(),
                            sel_vpk.dir,
                        )

            # Additionally, pack in game/vpk_override/ into the vpk - this allows
            # users to easily override resources in general.

            override_folder = exp_data.game.abs_path('vpk_override')
            os.makedirs(override_folder, exist_ok=True)

            # Also write a file to explain what it's for...
            with open(os.path.join(override_folder, 'BEE2_README.txt'), 'w', encoding='utf8') as f:
                f.write(VPK_OVERRIDE_README)

            # Matches pak01_038.vpk, etc. These shouldn't be opened.
            numeric_vpk = re.compile(r'_[0-9]+\.vpk')

            for subfolder, _, filenames, in os.walk(override_folder):
                # Subfolder relative to the folder.
                # normpath removes '.' and similar values from the beginning
                vpk_path = os.path.normpath(os.path.relpath(subfolder, override_folder))
                for filename in filenames:
                    if filename == 'BEE2_README.txt':
                        continue  # Don't add this to the VPK though.
                    file_path = os.path.join(subfolder, filename)
                    if vpk_path == '.' and filename.endswith('.vpk'):
                        # If a VPK file is found in vpk_override, copy the contents into ours.
                        # Skip trying to open pak01_028.vpk files, we just want to find the dir.
                        if numeric_vpk.search(filename) is not None:
                            continue
                        try:
                            other_vpk = VPK(file_path)
                        except ValueError:
                            LOGGER.exception('Could not open VPK file "{}":', file_path)
                        else:
                            for entry in other_vpk:
                                LOGGER.info('Adding "{}:{}" to the VPK', file_path, entry.filename)
                                vpk_file.add_file(entry.filename, entry.read())
                    else:
                        LOGGER.debug('Adding "{}" to the VPK', file_path)
                        with open(file_path, 'rb') as f:
                            vpk_file.add_file((vpk_path, filename), f.read())

        LOGGER.info('Written {} files to VPK!', len(vpk_file))
