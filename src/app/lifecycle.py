"""Manages the core package loading/export lifecycle."""
from typing import overload

from srctools import KeyValError, Keyvalues
from srctools.filesys import File
import srctools.logger
import trio

from app import DEV_MODE, gameMan, quit_app
from app.errors import ErrorUI, Result as ErrorResult
from async_util import EdgeTrigger, run_as_task
from exporting import ExportInfo, mod_support
from transtoken import TransToken
from utils import PackagePath
import BEE2_config
import exporting
import packages


LOGGER = srctools.logger.get_logger(__name__)
TRANS_LOAD_ERROR = TransToken.ui_plural(
    'An error occurred when loading packages:',
    'Multiple errors occurred when loading packages:',
)
TRANS_LOAD_PARTIAL = TransToken.ui('Loading packages was partially successful:')
type ExportResult = tuple[ExportInfo, ErrorResult]


@overload
async def lifecycle() -> None: ...
@overload
async def lifecycle(
    export_trigger: EdgeTrigger[ExportInfo],
    export_results: trio.MemorySendChannel[ExportResult],
) -> None: ...
@overload
async def lifecycle(
    export_trigger: EdgeTrigger[ExportInfo],
    export_results: trio.MemorySendChannel[ExportResult],
    reload_trigger: EdgeTrigger[()],
) -> None: ...
async def lifecycle(
    export_trigger: EdgeTrigger[ExportInfo] | None = None,
    export_results: trio.MemorySendChannel[ExportResult] | None = None,
    reload_trigger: EdgeTrigger[()] | None = None,
) -> None:
    """Switches between loading packages, then exporting.

    For testing code, params can be omitted to disable that feature.

    :param export_trigger: Triggered with the UI state to trigger exporting, if possible.
    :param export_results: After an export, the result is sent here.
    :param reload_trigger: Triggered to cause a package reload.
    """
    export_info: ExportInfo | None = None
    should_reload = False

    async def wait_reload() -> None:
        """React to the reload trigger."""
        nonlocal should_reload
        if reload_trigger is None:
            return  # Nothing to do.
        LOGGER.debug('Waiting for reload...')
        await reload_trigger.wait()
        LOGGER.info('Triggered reload!')
        should_reload = True
        wait_nursery.cancel_scope.cancel()

    async def wait_export() -> None:
        """Enable the export UI, then wait for an export command."""
        nonlocal export_info
        if export_trigger is None:
            return  # Can never export.
        LOGGER.debug('Waiting for export...')
        export_info = await export_trigger.wait()
        LOGGER.info('Triggered export!')
        wait_nursery.cancel_scope.cancel()

    while True:
        LOGGER.info('Loading packages...')
        packset = packages.PackagesSet()
        await mod_support.scan_music_locs(packset, gameMan.all_games)
        async with ErrorUI(error_desc=TRANS_LOAD_ERROR, warn_desc=TRANS_LOAD_PARTIAL) as error_ui:
            # noinspection PyProtectedMember
            await run_as_task(
                packages._load_packages,
                packset,
                list(BEE2_config.get_package_locs()),
                error_ui,
            )
        if error_ui.result is ErrorResult.FAILED:
            quit_app()
            return

        dev_filecheck_send, dev_filecheck_rec = trio.open_memory_channel[tuple[PackagePath, File]](256)

        async with trio.open_nursery() as load_nursery, dev_filecheck_send:
            if DEV_MODE.value:
                load_nursery.start_soon(filecheck_task, dev_filecheck_rec)
                packset.devmode_filecheck_chan = dev_filecheck_send
            # else: The channels will just be left unused.

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
            if export_info is not None and export_results is not None:
                # User pressed export, perform the export.
                # If export_results is None, we just ignore export requests.
                await export_results.send((export_info, await exporting.export(export_info)))
            # Wait for either trigger to fire.
            async with trio.open_nursery() as wait_nursery:
                should_reload = False
                export_info = None
                # Starting wait_export will enable the UI buttons.
                wait_nursery.start_soon(wait_reload)
                wait_nursery.start_soon(wait_export)
                await trio.sleep_forever()
            if should_reload:
                break  # Go the outer loop, which will reload again.


async def filecheck_task(rec_channel: trio.MemoryReceiveChannel[tuple[PackagePath, File]]) -> None:
    """Check all the provided files for syntax errors."""
    def worker(file: File) -> None:
        """Parse immediately, to check the syntax."""
        with file.open_str() as f:
            Keyvalues.parse(f)

    async for path, file in rec_channel:
        try:
            await trio.to_thread.run_sync(worker, file, abandon_on_cancel=True)
        except (KeyValError, FileNotFoundError, UnicodeDecodeError):
            LOGGER.exception('Unable to read "{}"', path)
