"""StyleVPK allows specifying a set of files that will be added to a DLC3 VPK.

This allows altering the in-editor wall textures, as well as a few others.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING
from typing_extensions import Self
import re
import os
import shutil

from srctools import FileSystem, VPK
import srctools.logger

import utils
from packages import PakObject, ParseData, ExportData, NoVPKExport
if TYPE_CHECKING:
    from app.gameMan import Game

LOGGER = srctools.logger.get_logger(__name__, alias='packages.styleVPK')


VPK_OVERRIDE_README = """\
Files in this folder will be written to the VPK during every BEE2 export.
Use to override resources as you please.

Either add regular files, or put VPKs (any name) in the root to have them be repacked.
"""


# The folder we want to copy our VPKs to.
VPK_FOLDER = {
    # The last DLC released by Valve - this is the one that we
    # overwrite with a VPK file.
    utils.STEAM_IDS['PORTAL2']: 'portal2_dlc3',
    utils.STEAM_IDS['DEST_AP']: 'portal2_dlc3',

    # This doesn't have VPK files, and is higher priority.
    utils.STEAM_IDS['APERTURE TAG']: 'portal2',
}


class StyleVPK(PakObject):
    """A set of VPK files used for styles.

    These are copied into _dlc3, allowing changing the in-editor wall
    textures.
    """
    def __init__(self, vpk_id: str, filesys: FileSystem, directory: str) -> None:
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
    def export(exp_data: ExportData) -> None:
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

        try:
            dest_folder = StyleVPK.clear_vpk_files(exp_data.game)
        except PermissionError as exc:
            raise NoVPKExport() from exc  # We can't edit the VPK files - P2 is open..

        if exp_data.game.steamID == utils.STEAM_IDS['PORTAL2']:
            # In Portal 2, we make a dlc3 folder - this changes priorities,
            # so the soundcache will be regenerated. Just copy the old one over.
            sound_cache = os.path.join(
                dest_folder, 'maps', 'soundcache', '_master.cache'
            )
            LOGGER.info('Sound cache: {}', sound_cache)
            if not os.path.isfile(sound_cache):
                LOGGER.info('Copying over soundcache file for DLC3..')
                os.makedirs(os.path.dirname(sound_cache), exist_ok=True)
                try:
                    shutil.copy(
                        exp_data.game.abs_path(
                            'portal2_dlc2/maps/soundcache/_master.cache',
                        ),
                        sound_cache,
                    )
                except FileNotFoundError:
                    # It's fine, this will be regenerated automatically
                    pass

        # Generate the VPK.
        vpk_file = VPK(os.path.join(dest_folder, 'pak01_dir.vpk'), mode='w')
        with vpk_file:
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

            # Also write a file to explain what it's for..
            with open(os.path.join(override_folder, 'BEE2_README.txt'), 'w') as f:
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

    @staticmethod
    def clear_vpk_files(game: Game) -> str:
        """Remove existing VPKs files from a game.

         We want to leave other files - otherwise users will end up
         regenerating the sound cache every time they export.

        This returns the path to the game folder.
        """
        dest_folder = game.abs_path(VPK_FOLDER.get(game.steamID, 'portal2_dlc3'))
        os.makedirs(dest_folder, exist_ok=True)
        try:
            for file in os.listdir(dest_folder):
                if file[:6] == 'pak01_':
                    os.remove(os.path.join(dest_folder, file))
        except PermissionError:
            # The player might have Portal 2 open. Abort changing the VPK.
            LOGGER.warning("Couldn't replace VPK files. Is Portal 2 or Hammer open?")
            raise
        return dest_folder
