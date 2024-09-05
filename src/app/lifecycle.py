"""Manages the core package loading/export lifecycle."""
import srctools.logger
import trio

import exporting
from app import EdgeTrigger, gameMan, quit_app
from app.errors import ErrorUI, Result as ErrorResult
from exporting import ExportInfo, mod_support
from transtoken import TransToken
import BEE2_config
import packages
import utils

LOGGER = srctools.logger.get_logger(__name__)
TRANS_LOAD_ERROR = TransToken.ui_plural(
    'An error occurred when loading packages:',
    'Multiple errors occurred when loading packages:',
)
TRANS_LOAD_PARTIAL = TransToken.ui('Loading packages was partially successful:')
type ExportResult = tuple[ExportInfo, ErrorResult]


async def lifecycle(
    reload_trigger: EdgeTrigger[()],
    export_trigger: EdgeTrigger[ExportInfo],
    export_results: trio.MemorySendChannel[ExportResult],
) -> None:
    """Switches between loading packages, then exporting.

    :param reload_trigger: Triggered to cause a package reload.
    :param export_trigger: Triggered with the UI state to trigger exporting, if possible.
    :param export_results: After an export, the result is sent here.
    """
    export_info: ExportInfo | None = None
    should_reload = False

    async def wait_reload() -> None:
        """React to the reload trigger."""
        nonlocal should_reload
        await reload_trigger.wait()
        should_reload = True
        wait_nursery.cancel_scope.cancel()

    async def wait_export() -> None:
        """Enable the export UI, then wait for an export command."""
        nonlocal export_info
        export_info = await export_trigger.wait()
        wait_nursery.cancel_scope.cancel()

    while True:
        LOGGER.info('Loading packages...')
        packset = packages.PackagesSet()
        await mod_support.scan_music_locs(packset, gameMan.all_games)
        async with ErrorUI(error_desc=TRANS_LOAD_ERROR, warn_desc=TRANS_LOAD_PARTIAL) as error_ui:
            # noinspection PyProtectedMember
            await utils.run_as_task(
                packages._load_packages,
                packset,
                list(BEE2_config.get_package_locs()),
                error_ui,
            )
        if error_ui.result is ErrorResult.FAILED:
            quit_app()
            return

        async with trio.open_nursery() as load_nursery:
            # noinspection PyProtectedMember
            load_nursery.start_soon(packages._load_objects, packset)
            # noinspection PyProtectedMember
            load_nursery.start_soon(packages._load_templates, packset)

            # Todo: Move these ready calls elsewhere, then eliminate foreground.
            for pack_cls in packages.OBJ_TYPES.values():
                if pack_cls.needs_foreground:
                    await packset.ready(pack_cls).wait()
                    LOGGER.debug('{} ready', pack_cls)

            # Foreground objects loaded, release the packset for the UI.
            packages.LOADED.value = packset
        # Everything is loaded now, we can export.

        while True:
            await trio.lowlevel.checkpoint()
            if export_info is not None:
                # User pressed export, perform the export.
                await export_results.send((export_info, await exporting.export(export_info)))
            # Wait for either trigger to fire.
            async with trio.open_nursery() as wait_nursery:
                should_reload = False
                export_info = None
                # Starting wait_export will enable the UI buttons.
                wait_nursery.start_soon(wait_reload)
                wait_nursery.start_soon(wait_export)
            if should_reload:
                break  # Go the outer loop, which will reload again.
