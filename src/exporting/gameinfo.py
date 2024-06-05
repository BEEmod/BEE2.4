"""Modify gameinfo to add our game folder."""
from __future__ import annotations
from typing import Final, TYPE_CHECKING
import os

import srctools
import trio

import utils
from exporting import ExportData, STEPS


# The line we inject to add our BEE2 folder into the game search path.
# We always add ours such that it's the highest priority, other
# than '|gameinfo_path|.'
GAMEINFO_LINE: Final = 'Game\t|gameinfo_path|../bee2'
OLD_GAMEINFO_LINE: Final = 'Game\t"BEE2"'


LOGGER = srctools.logger.get_logger(__name__)
if TYPE_CHECKING:
    from app.gameMan import Game


@STEPS.add_step(prereq=(), results=())
async def step_edit_gameinfo(exp: ExportData) -> None:
    """Modify gameinfo."""
    await edit_gameinfos(exp.game, True)


async def edit_gameinfos(game: Game, add_line: bool) -> None:
    """Modify all gameinfo.txt files to add or remove our line.

    Add_line determines if we are adding or removing it.
    """
    async with trio.open_nursery() as nursery:
        for folder in game.dlc_priority():
            filename = os.path.join(game.root, folder, 'gameinfo.txt')
            nursery.start_soon(trio.to_thread.run_sync, edit_gameinfo, filename, add_line)


def edit_gameinfo(filename: str, add_line: bool) -> None:
    """Modify a single gameinfo.txt file to add or remove our line."""
    try:
        file = open(filename, encoding='utf8')
    except FileNotFoundError:
        return  # No gameinfo here.

    with file:
        data = list(file)

    for line_num, line in reversed(list(enumerate(data))):
        clean_line = srctools.clean_line(line)
        if add_line:
            if clean_line == GAMEINFO_LINE:
                break  # Already added!
            elif clean_line == OLD_GAMEINFO_LINE:
                LOGGER.debug("Updating gameinfo hook to {}", filename)
                data[line_num] = utils.get_indent(line) + GAMEINFO_LINE + '\n'
                break
            elif '|gameinfo_path|' in clean_line and GAMEINFO_LINE not in line:
                LOGGER.debug("Adding gameinfo hook to {}", filename)
                # Match the line's indentation
                data.insert(
                    line_num + 1,
                    utils.get_indent(line) + GAMEINFO_LINE + '\n',
                )
                break
        else:
            if clean_line == GAMEINFO_LINE or clean_line == OLD_GAMEINFO_LINE:
                LOGGER.debug("Removing gameinfo hook from {}", filename)
                data.pop(line_num)
                break
    else:
        if add_line:
            LOGGER.warning('Failed editing "{}" to add our special folder!', filename)
        return

    with srctools.AtomicWriter(filename, encoding='utf8') as file2:
        for line in data:
            file2.write(line)
