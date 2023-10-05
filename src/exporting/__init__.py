"""The code for performing an export to the game folder."""
from __future__ import annotations

import os
from enum import Enum, auto
from pathlib import Path
from typing import Any, TYPE_CHECKING, Tuple, Type

import attrs
import srctools.logger
from srctools import Keyvalues

import loadScreen
import packages
from app.errors import ErrorUI
from editoritems import Item as EditorItem, Renderable, RenderableType
from packages import PackagesSet, PakObject, Style
from step_order import StepOrder
from transtoken import TransToken


LOGGER = srctools.logger.get_logger(__name__)


if TYPE_CHECKING:
    from app.gameMan import Game


class StepResource(Enum):
    """Identifies types of files/data that is generated during export."""
    # Editoritems-related resources.
    EI_ITEMS = auto()  # Item definitions.
    EI_DATA = auto()  # Anything affecting the file.
    EI_FILE = auto()  # The file itself being written.

    # vbsp_config-related resources.
    VCONF_DATA = auto()  # Anything affecting the file.
    VCONF_FILE = auto()  # The file itself being written.

    # Resources in the bee2/ folder.
    RES_SPECIAL = auto()  # Generated resources, mod music, etc.
    RES_PACKAGE = auto()  # Copying all the resources defined in packages.

    # Various things that need to be sequenced.
    STYLE = auto()  # Items must come after the style.
    BACKUP = auto()  # The original compiler executables and editoritems have been backed up.
    ERROR_SERVER_TERMINATE = auto()  # This must be terminated before we can copy compiler files.
    VPK_WRITTEN = auto()  # The VPK file has been generated for overriding editor textures.


# The progress bars used when exporting data into a game
STAGE_COMP_BACKUP = 'BACK'
STAGE_PUZZ_BACKUP = 'PUZZLE_BACKUP'
STAGE_EXPORT = 'EXP'
STAGE_COMPILER = 'COMP'
STAGE_RESOURCES = 'RES'
STAGE_MUSIC = 'MUS'
load_screen = loadScreen.LoadScreen(
    (STAGE_COMP_BACKUP, TransToken.ui('Backup Original Files')),
    (STAGE_PUZZ_BACKUP, TransToken.ui('Backup Puzzles')),
    (STAGE_EXPORT, TransToken.ui('Export Configuration')),
    (STAGE_COMPILER, TransToken.ui('Copy Compiler')),
    (STAGE_RESOURCES, TransToken.ui('Copy Resources')),
    (STAGE_MUSIC, TransToken.ui('Copy Music')),
    title_text=TransToken.ui('Exporting'),
)


@attrs.define(kw_only=True)
class ExportData:
    """The arguments to pak_object.export()."""
    packset: PackagesSet  # The entire loaded packages set.
    game: Game  # The current game.
    # Usually str, but some items pass other things.
    selected: dict[Type[PakObject], Any]
    # Some items need to know which style is selected
    selected_style: Style
    # If refreshing resources is enabled.
    copy_resources: bool
    # All the items in the map
    all_items: list[EditorItem] = attrs.Factory(list)
    # The error/connection icons
    renderables: dict[RenderableType, Renderable] = attrs.Factory(dict)
    # vbsp_config.cfg file.
    vbsp_conf: Keyvalues = attrs.Factory(Keyvalues.root)
    # As steps export, they may fill this to include additional resources that
    # are written to the game folder. If updating the cache, these files won't
    # be deleted. This should be an absolute path.
    resources: set[Path] = attrs.Factory(set)
    # Flag set to indicate that the error server may be running.
    maybe_error_server_running: bool = True


STEPS = StepOrder(ExportData, StepResource)


async def export(
    game: 'Game',
    packset: packages.PackagesSet,
    style: packages.Style,
    selected_objects: dict[Type[packages.PakObject], Any],
    should_refresh: bool = False,
) -> Tuple[bool, bool]:
    """Export configuration to the specified game.

    - If no backup is present, the original editoritems is backed up.
    """
    LOGGER.info('-' * 20)
    LOGGER.info('Exporting Items and Style for "{}"!', game.name)

    LOGGER.info('Style = {}', style.id)
    for obj_type, selected in selected_objects.items():
        LOGGER.info('{} = {}', obj_type, selected)

    async with ErrorUI(
        title=TransToken.ui("BEE2 Export - {game}").format(game=game.name),
        desc=TransToken.ui("Exporting failed. The following errors occurred:")
    ) as error_ui:
        with load_screen:
            LOGGER.info('Should refresh: {}', should_refresh)
            if should_refresh:
                # Check to ensure the cache needs to be copied over..
                should_refresh = game.cache_invalid()
                if should_refresh:
                    LOGGER.info("Cache invalid - copying..")
                else:
                    LOGGER.info("Skipped copying cache!")
                    load_screen.skip_stage(STAGE_RESOURCES)

            # Make the folders we need to copy files to, if desired.
            os.makedirs(game.abs_path('bin/bee2/'), exist_ok=True)

            exp_data = ExportData(
                game=game,
                selected=selected_objects,
                packset=packset,
                selected_style=style,
                copy_resources=should_refresh,
            )

            await STEPS.run(exp_data)
    return (not error_ui.failed, False)


@STEPS.add_step(prereq=[], results=[
    StepResource.STYLE,
    StepResource.EI_ITEMS,
    StepResource.EI_DATA,
    StepResource.VCONF_DATA,
])
async def step_style(exp: ExportData) -> None:
    """The first thing that's added is the style data."""
    style = exp.selected_style
    exp.vbsp_conf.extend(await style.config())

    exp.all_items += style.items
    exp.renderables.update(style.renderables)


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_add_core_info(exp: ExportData) -> None:
    """Add some core options to the config."""
    from app import DEV_MODE  # TODO: Pass into export(), maybe?
    exp.vbsp_conf.set_key(('Options', 'Game_ID'), exp.game.steamID)
    exp.vbsp_conf.set_key(('Options', 'dev_mode'), srctools.bool_as_int(DEV_MODE.get()))


# Register everything.
from exporting import (
    compiler, corridors, cube_colourizer, editor_sound, elevator, files, fizzler, items, music,
    pack_list, quote_pack, signage, skybox, stylevar, template_brush, translations, vpks,
    widgets,
)
