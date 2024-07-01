"""The code for performing an export to the game folder."""
from __future__ import annotations

from typing import Any, TYPE_CHECKING
from enum import Enum, auto
from pathlib import Path, PurePath
from collections.abc import Callable
import os

import attrs
import srctools.logger
from srctools import Keyvalues

import loadScreen
import packages
import config as config_mod
from app import DEV_MODE
from app.errors import ErrorUI, Result as ErrorResult, WarningExc
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

    # The config file managed by the config package.
    CONFIG_DATA = auto()  # Anything added to the config.
    CONFIG_FILE = auto()  # The file itself being written.

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
STAGE_STEPS = loadScreen.ScreenStage(TransToken.ui('Overall Progress'))
STAGE_COMP_BACKUP = loadScreen.ScreenStage(TransToken.ui('Backup Original Files'))
STAGE_AUTO_BACKUP = loadScreen.ScreenStage(TransToken.ui('Backup Puzzles'))
STAGE_COMPILER = loadScreen.ScreenStage(TransToken.ui('Copy Compiler'))
STAGE_RESOURCES = loadScreen.ScreenStage(TransToken.ui('Copy Resources'))
STAGE_MUSIC = loadScreen.ScreenStage(TransToken.ui('Copy Music'))
load_screen = loadScreen.LoadScreen(
    STAGE_STEPS,
    STAGE_COMP_BACKUP,
    STAGE_AUTO_BACKUP,
    STAGE_COMPILER,
    STAGE_RESOURCES,
    STAGE_MUSIC,
    title_text=TransToken.ui('Exporting'),
)


@attrs.define(kw_only=True)
class ExportData:
    """The arguments to pak_object.export()."""
    # The entire loaded packages set. The repr is massive, just show the ID.
    packset: PackagesSet = attrs.field(repr=lambda pack: f'<PackagesSet @ {id(pack):x}>')
    game: Game  # The current game.
    # Usually str, but some items pass other things.
    selected: dict[type[PakObject], Any]
    # Some items need to know which style is selected
    selected_style: Style
    # If refreshing resources is enabled.
    copy_resources: bool
    # All the items in the map
    all_items: list[EditorItem] = attrs.field(factory=list, repr=False)
    # The error/connection icons
    renderables: dict[RenderableType, Renderable] = attrs.Factory(dict)
    config: config_mod.Config
    # vbsp_config.cfg file.
    vbsp_conf: Keyvalues = attrs.field(factory=Keyvalues.root, repr=False)
    # As steps export, they may fill this to include additional resources that
    # are written to the game folder. If updating the cache, these files won't
    # be deleted. This should be an absolute path.
    resources: set[PurePath] = attrs.Factory(set)
    # Flag set to indicate that the error server may be running.
    maybe_error_server_running: bool = True
    # Can be called to indicate a non-fatal error.
    warn: Callable[[WarningExc | TransToken], None]


STEPS = StepOrder(ExportData, StepResource)
TRANS_EXP_TITLE = TransToken.ui("BEE2 Export - {game}")
TRANS_ERROR = TransToken.ui_plural(
    "Exporting failed. The following error occurred:",
    "Exporting failed. The following errors occurred:",
)
TRANS_WARN = TransToken.ui_plural(
    "Exporting was partially successful, but the following issue occurred:",
    "Exporting was partially successful, but the following issues occurred:",
)


@attrs.frozen
class ExportInfo:
    """Parameters required for exporting."""
    game: Game
    packset: packages.PackagesSet
    style: packages.Style
    selected_objects: dict[type[packages.PakObject], Any]
    should_refresh: bool = False


async def export(info: ExportInfo) -> ErrorResult:
    """Export configuration to the specified game.

    - If no backup is present, the original editoritems is backed up.
    """
    LOGGER.info('-' * 20)
    LOGGER.info('Exporting Items and Style for "{}"!', info.game.name)

    LOGGER.info('Style = {}', info.style.id)
    for obj_type, selected in info.selected_objects.items():
        LOGGER.info('{} = {}', obj_type, selected)

    with load_screen:
        async with ErrorUI(
            title=TRANS_EXP_TITLE.format(game=info.game.name),
            error_desc=TRANS_ERROR,
            warn_desc=TRANS_WARN,
        ) as error_ui:
            LOGGER.info('Should refresh: {}', info.should_refresh)
            if info.should_refresh:
                # Check to ensure the cache needs to be copied over...
                should_refresh = info.game.cache_invalid()
                if should_refresh:
                    LOGGER.info("Cache invalid - copying..")
                else:
                    LOGGER.info("Skipped copying cache!")
            else:
                should_refresh = False

            # Make the folders we need to copy files to, if desired.
            os.makedirs(info.game.abs_path('bin/bee2/'), exist_ok=True)

            exp_data = ExportData(
                game=info.game,
                selected=info.selected_objects,
                packset=info.packset,
                selected_style=info.style,
                config=config_mod.APP.get_full_conf(config_mod.COMPILER),
                copy_resources=should_refresh,
                warn=error_ui.add,
            )

            await STEPS.run(exp_data, STAGE_STEPS)

            info.game.exported_style = info.style.id
            info.game.save()
    return error_ui.result


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
    exp.vbsp_conf.set_key(('Options', 'style_id'), style.id)


@STEPS.add_step(prereq=[], results=[StepResource.VCONF_DATA])
async def step_add_core_info(exp: ExportData) -> None:
    """Add some core options to the config."""
    exp.vbsp_conf.set_key(('Options', 'Game_ID'), exp.game.steamID)
    exp.vbsp_conf.set_key(('Options', 'dev_mode'), srctools.bool_as_int(DEV_MODE.value))


# Register everything.
from exporting import (  # noqa: E402
    compiler, corridors, cube_colourizer, editor_sound, elevator, fgd, files, fizzler,  # noqa: F401
    gameinfo, items, music, pack_list, quote_pack, signage, skybox, stylevar, template_brush,  # noqa: F401
    translations, vpks, barrier_hole,  # noqa: F401
)
