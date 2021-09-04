"""StyleVPK allows specifying a set of files that will be added to a DLC3 VPK.

This allows altering the in-editor wall textures, as well as a few others.
"""
import os
import shutil

import utils
from packages import (
    PakObject, ParseData, ExportData, NoVPKExport, LOGGER,
    VPK_OVERRIDE_README, VPK_FOLDER,
)
from srctools import FileSystem, VPK


class StyleVPK(PakObject):
    """A set of VPK files used for styles.

    These are copied into _dlc3, allowing changing the in-editor wall
    textures.
    """
    def __init__(self, vpk_id, filesys: FileSystem, directory: str) -> None:
        """Initialise a StyleVPK object."""
        self.id = vpk_id
        self.fsys = filesys
        self.dir = directory

    @classmethod
    def parse(cls, data: ParseData):
        """Read the VPK file from the package."""
        vpk_name = data.info['filename']

        source_folder = os.path.normpath('vpk/' + vpk_name)

        # At least one exists?
        if not any(data.fsys.walk_folder(source_folder)):
            raise Exception(
                'VPK object "{}" has no associated files!'.format(data.id)
            )

        return cls(data.id, data.fsys, source_folder)

    @staticmethod
    def export(exp_data: ExportData):
        """Generate the VPK file in the game folder."""
        sel_vpk = exp_data.selected_style.vpk_name

        if sel_vpk:
            for vpk in StyleVPK.all():
                if vpk.id.casefold() == sel_vpk:
                    sel_vpk = vpk
                    break
            else:
                sel_vpk = None
        else:
            sel_vpk = None

        try:
            dest_folder = StyleVPK.clear_vpk_files(exp_data.game)
        except PermissionError:
            raise NoVPKExport()  # We can't edit the VPK files - P2 is open..

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

            vpk_file.add_folder(override_folder)
            del vpk_file['BEE2_README.txt']  # Don't add this to the VPK though..

        LOGGER.info('Written {} files to VPK!', len(vpk_file))

    @staticmethod
    def clear_vpk_files(game) -> str:
        """Remove existing VPKs files from a game.

         We want to leave other files - otherwise users will end up
         regenerating the sound cache every time they export.

        This returns the path to the game folder.
        """
        dest_folder = game.abs_path(VPK_FOLDER.get(
            game.steamID,
            'portal2_dlc3',
        ))

        os.makedirs(dest_folder, exist_ok=True)
        try:
            for file in os.listdir(dest_folder):
                if file[:6] == 'pak01_':
                    os.remove(os.path.join(dest_folder, file))
        except PermissionError:
            # The player might have Portal 2 open. Abort changing the VPK.
            LOGGER.warning("Couldn't replace VPK files. Is Portal 2 "
                           "or Hammer open?")
            raise

        return dest_folder
