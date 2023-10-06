"""Modify the game's FGD to allow instance collapsing to work."""
from typing import IO, TYPE_CHECKING
import re
import shutil

from srctools import AtomicWriter
import srctools.logger
import trio

import config
import utils
from config.gen_opts import GenOptions
from exporting import ExportData, STEPS


LOGGER = srctools.logger.get_logger(__name__)
if TYPE_CHECKING:
    from app.gameMan import Game


@STEPS.add_step(prereq=[], results=[])
async def step_edit_fgd(exp: ExportData) -> None:
    """Modify the FGD."""
    if not config.APP.get_cur_conf(GenOptions).preserve_fgd:
        await trio.to_thread.run_sync(edit_fgd, exp.game, True)


def edit_fgd(game: Game, add_lines: bool) -> None:
    """Add our FGD files to the game folder.

    This is necessary so that VBSP offsets the entities properly,
    if they're in instances.
    Add_line determines if we are adding or removing it.
    """
    file: IO[bytes]
    # We do this in binary to ensure non-ASCII characters pass though
    # untouched.

    fgd_path = game.abs_path('bin/portal2.fgd')
    try:
        with open(fgd_path, 'rb') as file:
            data = file.readlines()
    except FileNotFoundError:
        LOGGER.warning('No FGD file? ("{}")', fgd_path)
        return

    for i, line in enumerate(data):
        match = re.match(
            br'// BEE\W*2 EDIT FLAG\W*=\W*([01])',
            line,
            re.IGNORECASE,
        )
        if match:
            if match.group(1) == b'0':
                LOGGER.info('FGD editing disabled by file.')
                return  # User specifically disabled us.
            # Delete all data after this line.
            del data[i:]
            break

    with AtomicWriter(fgd_path, is_bytes=True) as file:
        for line in data:
            file.write(line)
        if add_lines:
            file.write(
                b'// BEE 2 EDIT FLAG = 1 \n'
                b'// Added automatically by BEE2. Set above to "0" to '
                b'allow editing below text without being overwritten.\n'
                b'// You\'ll want to do that if installing Hammer Addons.'
                b'\n\n'
            )
            with utils.install_path('BEE2.fgd').open('rb') as bee2_fgd:
                shutil.copyfileobj(bee2_fgd, file)
            file.write(b'\n')
            try:
                with utils.install_path('hammeraddons.fgd').open('rb') as ha_fgd:
                    shutil.copyfileobj(ha_fgd, file)
            except FileNotFoundError:
                if utils.FROZEN:
                    raise  # Should be here!
                else:
                    LOGGER.warning('Missing hammeraddons.fgd, build the app at least once!')
