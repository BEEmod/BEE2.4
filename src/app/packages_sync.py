"""Utility for syncing changes in Portal 2 and in unzipped packages.

First, set the PORTAL_2_LOC environment variable to the Portal 2 location.
Then drag and drop folders or files onto this application. If files are in a
package folder, they will be copied to Portal 2. If in Portal 2's directories,
they will be copied to any packages with those resources.

The destination will be 'Portal 2/bee2_dev/' if that exists, or 'Portal 2/bee2/'
otherwise.
"""
import abc
import os
import shutil
import sys
import logging
import math
from collections.abc import Awaitable, Callable
from contextlib import ExitStack, aclosing
from pathlib import Path, PurePath

from srctools import logger
from srctools.filesys import RawFileSystem

import trio_util
from srctools.mdl import MDL_EXTS

import app
from async_util import EdgeTrigger
from trio_util import AsyncBool
import trio

from BEE2_config import GEN_OPTS, get_package_locs
from packages import (
    PackagesSet, get_loaded_packages, find_packages, Package,
    LOGGER as packages_logger,
)
from app.errors import ErrorUI
from app import ReflowWindow
import utils

LOGGER = logger.get_logger(__name__)

FILE_MUTEX = utils.install_path('package_sync_mutex')
FILE_SERVER = utils.install_path('package_sync_server.json')


class SyncUIBase(ReflowWindow, abc.ABC):
    """Interface to the GUI portion.."""
    def __init__(self) -> None:
        """Setup async values used to store configuration."""
        super().__init__()
        # First file -> package selector.
        self.pack_sort_by_id = AsyncBool()
        self.applies_to_all = AsyncBool()
        self.applied_package: Package | None = None
        # Packages to pick from, in order.
        self.packages: list[Package] = []
        # Location of P2, for simplifying file paths.
        self.p2_loc: trio.Path | None = None
        self.selected_pack: EdgeTrigger[Package | None] = EdgeTrigger()

        self.can_confirm = AsyncBool(False)
        self.confirmed = trio.Event()

    def evt_reset_apply_all(self, _: object = None) -> None:
        """The action when the reset-applies button is pressed."""
        self.applied_package = None
        self.applies_to_all.value = False
        self.ui_set_reset_applies(False, 'No auto package')

    async def pack_btn_task(self, /) -> None:
        """Handles marking buttons dirty whenever sorting changes."""
        async with aclosing(self.pack_sort_by_id.eventual_values()) as agen:
            async for sort_id in agen:
                if sort_id:
                    self.packages.sort(key=lambda pack: pack.id)
                else:
                    self.packages.sort(key=lambda pack: str(pack.disp_name))
                self.item_pos_dirty.set()

    async def ask_package(self, src: trio.Path, dest: PurePath, /) -> Package | None:
        """Ask for the package this file should use."""
        self.ui_set_ask_pack(src, dest)
        return await self.selected_pack.wait()

    def short_path(self, path: trio.Path) -> str:
        """Simplify a path, if possible."""
        if self.p2_loc is not None:
            try:
                relative = path.relative_to(self.p2_loc)
            except ValueError:
                pass
            else:
                if relative.is_relative_to('sdk_content/maps/'):
                    return f'<portal2>:{relative.relative_to('sdk_content/maps/').as_posix()}'
                elif relative.parts[0].casefold() in ('bee2', 'bee2_dev'):
                    return f'<portal2>:{relative.relative_to(relative.parts[0]).as_posix()}'
        for pack in self.packages:
            try:
                relative = path.relative_to(pack.path / 'resources')
            except ValueError:
                pass
            else:
                return f'<{pack.id}>:{relative.as_posix()}'
        return str(path)

    @classmethod
    @abc.abstractmethod
    def run_loop(
        cls,
        func: Callable[['SyncUIBase', trio.Nursery, list[str]], Awaitable[object]],
        files: list[str],
        /,
    ) -> None:
        """Start the main loop for the GUI."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_set_ask_pack(self, src: trio.Path, des: PurePath, /) -> None:
        """Set the displayed filenames for asked packages."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_set_reset_applies(self, enabled: bool, text: str, /) -> None:
        """Set the button label for the applies-to-all reset button."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_add_confirm_file(self, src: trio.Path, dest: trio.Path, /) -> None:
        """Add a file to the big confirm list."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_reset(self, /) -> None:
        """Reset the list of confirmed items."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_get_files(self, /) -> list[tuple[trio.Path, trio.Path]]:
        """Get the list of selected files."""
        raise NotImplementedError


async def check_file_task(
    packset: PackagesSet,
    ui: SyncUIBase,
    portal2: trio.Path,
    files: trio.MemoryReceiveChannel[trio.Path],
    transfers: trio.MemorySendChannel[tuple[trio.Path, trio.Path]]
) -> None:
    """For eac file, determine the location it is in, and copy it to the other place."""
    game_folder_bee = 'bee2_dev' if await (portal2 / 'bee2_dev').exists() else 'bee2'

    # The resources/ folder & package for each loose package.
    pack_res = [
        (package, Path(package.fsys.path, 'resources'))
        for package in packset.packages.values()
        if isinstance(package.fsys, RawFileSystem)
    ]

    async with transfers, files:
        file: trio.Path
        async for file in files:
            try:
                relative = file.relative_to(portal2)
            except ValueError:
                # Not in Portal 2, check packages.
                for package, res_folder in pack_res:
                    try:
                        relative = file.relative_to(res_folder)
                    except ValueError:
                        continue
                    await transfer_pack2game(
                        transfers, portal2, game_folder_bee,
                        file, package, relative,
                    )
                    break
                else:
                    LOGGER.warning('File "{!s}" not in packages or Portal 2!', file)
            else:
                # In Portal 2, copy to packages.
                await transfer_game2pack(
                    ui, transfers, game_folder_bee,
                    file, relative,
                )


async def transfer_pack2game(
    transfers: trio.MemorySendChannel[tuple[trio.Path, trio.Path]],
    portal2: trio.Path,
    game_folder_bee: str,
    file: trio.Path,
    package: Package,
    res_path: trio.Path,
) -> None:
    """Handle transferring from a package to the game."""
    if res_path.parts[0] == 'instances':
        dest = (
            portal2 /
            'sdk_content/maps/instances/bee2' /
            res_path.relative_to('instances')
        )
    elif res_path.parts[0] == 'bee2':
        LOGGER.warning('File "{!s}" not for copying!', file)
        return
    else:
        dest = portal2 / game_folder_bee / res_path
    await transfers.send((file, dest))


async def transfer_game2pack(
    ui: SyncUIBase,
    transfers: trio.MemorySendChannel[tuple[trio.Path, trio.Path]],
    game_folder_bee: str,
    file: trio.Path,
    relative: trio.Path,
) -> None:
    """Determine how to transfer from the game to matching packages."""
    try:
        inst_rel = relative.relative_to('sdk_content/maps/instances/bee2')
        rel_loc = PurePath('resources', 'instances', inst_rel)
    except ValueError:
        rel_loc = PurePath('resources') / relative.relative_to(game_folder_bee)

    package_found = False

    for package in get_loaded_packages().packages.values():
        if not isinstance(package.fsys, RawFileSystem):
            # In a zip or the like.
            continue
        if str(rel_loc) in package.fsys:
            package_found = True
            await transfers.send((file, trio.Path(package.fsys.path, rel_loc)))
            # Need to keep looping, could be in multiple.
    if package_found:
        return  # Done!
    LOGGER.info('Need to ask user: file={}, applied={}, checkmark={}', rel_loc, ui.applied_package, ui.applies_to_all)

    # This file is totally new, need to ask the user.
    if ui.applied_package is not None:
        # User checked 'applies to all'.
        await transfers.send((file, trio.Path(ui.applied_package.fsys.path, rel_loc)))
    else:
        found = await ui.ask_package(file, rel_loc)
        if found is not None:
            await transfers.send((file, trio.Path(found.fsys.path, rel_loc)))
        if ui.applies_to_all.value:
            # Checkbox enabled, store that package.
            ui.applied_package = found
            ui.ui_set_reset_applies(True, f'Reset auto package: {found.disp_name}')


def filter_filename(file_path: trio.Path) -> trio.Path | None:
    """Filter filenames, removing compile files, normalise models."""
    suffix = file_path.suffix.casefold()
    if suffix in {'.vmx', '.log', '.bsp', '.prt', '.lin'}:
        # Ignore these file types.
        return None
    elif suffix in {'.vvd', '.phy', '.dx90.vtx', '.sw.vtx'}:
        return file_path.with_suffix('.mdl')
    else:
        return file_path


async def expand_file_task(
    file_rec: trio.MemoryReceiveChannel[Path],
    exp_send: trio.MemorySendChannel[trio.Path],
) -> None:
    """Expand folders into files, normalise model extensions."""
    file_path: trio.Path | None
    sub_file: trio.Path | None
    async with file_rec, exp_send:
        file: Path
        async for file in file_rec:
            file_path = trio.Path(file)
            if await file_path.is_dir():
                for sub_file in await file_path.glob('**/*'):
                    if await sub_file.is_file() and (sub_file := filter_filename(sub_file)) is not None:
                        await exp_send.send(sub_file)
            elif (file_path := filter_filename(file_path)) is not None:
                await exp_send.send(file_path)


async def main_gui(
    ui: SyncUIBase,
    core_nursery: trio.Nursery,
    files: trio.MemoryReceiveChannel[Path],
) -> None:
    """Run the main GUI."""
    try:
        portal2_loc = trio.Path(os.environ['PORTAL_2_LOC'])
    except KeyError:
        raise ValueError(
            'Environment Variable $PORTAL_2_LOC not set! '
            'This should be set to Portal 2\'s directory.'
        ) from None

    # Load the general options in to find out where packages are.
    GEN_OPTS.load()

    # Borrow PackageLoader to do the finding and loading for us.
    LOGGER.info('Locating packages...')

    # Disable logging of package info.
    packages_logger.setLevel(logging.ERROR)
    packset = get_loaded_packages()  # TODO use standalone packset
    async with ErrorUI() as errors, trio.open_nursery() as nursery:
        for loc in get_package_locs():
            nursery.start_soon(
                find_packages,
                errors,
                packset,
                loc,
            )
    packages_logger.setLevel(logging.INFO)

    LOGGER.info('Done!')
    ui.packages = list(packset.packages.values())
    ui.p2_loc = portal2_loc
    ui.evt_reset_apply_all()  # Set the text.
    core_nursery.start_soon(ui.pack_btn_task)

    exp_file_send, exp_file_rec = trio.open_memory_channel[trio.Path](1)
    transfer_send, transfer_rec = trio.open_memory_channel[tuple[trio.Path, trio.Path]](1)

    core_nursery.start_soon(expand_file_task, files, exp_file_send)
    core_nursery.start_soon(check_file_task, packset, ui, portal2_loc, exp_file_rec, transfer_send)

    enable_confirm = trio.Event()

    async def delay_enable() -> None:
        """Disable the confirm button briefly whenever a file arrives.

        That ensures you don't confirm at the same time as a file.
        """
        nonlocal enable_confirm
        while True:
            LOGGER.info('Waiting')
            await enable_confirm.wait()
            ui.can_confirm.value = False
            LOGGER.info('File sent.')
            enable_confirm = trio.Event()
            with trio.move_on_after(0.5) as scope:
                await enable_confirm.wait()
                LOGGER.info('Timer cancelled.')
            if scope.cancelled_caught:
                # Not triggered, re-enable.
                ui.can_confirm.value = True

    def do_copy(src: trio.Path, dest: trio.Path) -> None:
        print(f'Copy {src} -> {dest}')
        shutil.copyfile(src, dest)

    core_nursery.start_soon(delay_enable)

    while True:
        # Handle confirming files, then executing them.
        ui.ui_reset()
        ui.confirmed = trio.Event()
        async with trio_util.move_on_when(ui.confirmed.wait):
            async for src, dest in transfer_rec:
                ui.can_confirm.value = False
                enable_confirm.set()
                ui.ui_add_confirm_file(src, dest)
        # Confirmed, process them.
        for src, dest in ui.ui_get_files():
            LOGGER.info('"{}" -> "{}"', src, dest)
            await trio.Path(dest.parent).mkdir(exist_ok=True)

            if src.suffix.casefold() == '.mdl':
                for suffix in MDL_EXTS:
                    try:
                        await trio.to_thread.run_sync(
                            do_copy,
                            src.with_suffix(suffix),
                            dest.with_suffix(suffix),
                        )
                    except FileNotFoundError:
                        pass
            else:
                await trio.to_thread.run_sync(
                    do_copy,
                    src, dest,
                )


async def communicate(stack: ExitStack, files: list[str]) -> bool:
    """Determine if an existing instance is present, or spawn a new one."""
    # Eventually time out if we fail to find anything.
    with trio.fail_after(5.0):
        while True:
            # First, try to open the mutex file. If we succeed, we're definitely the server.
            try:
                # TODO: use os.O_TEMPORARY?
                stack.enter_context(open(FILE_MUTEX, 'xb'))
                return False  # We're the server.
            except FileExistsError:
                # It exists, try to delete - will fail if still alive.
                try:
                    FILE_MUTEX.unlink()
                except PermissionError:
                    # Server is alive. Read and try to connect.
                    try:
                        port = int(FILE_SERVER.read_text())
                        stream = await trio.open_tcp_stream('localhost', port)
                    except (OSError, ValueError):
                        # Might be starting up, try again
                        await trio.sleep(0.1)
                    else:
                        # Connected, send our files and quit.
                        print(f'Connected to server with port {port}')
                        async with stream:
                            for file in files:
                                await stream.send_all((file + '\n').encode('utf8'))
                        return True
                else:
                    # Might be dead, try to become it ourselves.
                    continue


def main(args: list[str]) -> int:
    """Run the program."""
    def cleanup() -> None:
        """Try and remove our files once we quit."""
        try:
            FILE_SERVER.unlink(missing_ok=True)
        except PermissionError:
            pass
        try:
            FILE_MUTEX.unlink(missing_ok=True)
        except PermissionError:
            pass

    with ExitStack() as stack:
        # Run this in a non-GUI event loop.
        if trio.run(communicate, stack, args):
            # Is a client, don't run the GUI.
            return 0
        # Otherwise we have the mutex, start the server in a GUI loop.
        print('Starting server!')
        stack.callback(cleanup)
        if utils.USE_WX or True:
            from ui_wx.packages_sync import WxUI
            WxUI.run_loop(start_server, args)
        else:
            from ui_tk.packages_sync import TkUI  # type: ignore
            TkUI.run_loop(start_server, args)
    return 0


async def start_server(ui: SyncUIBase, core_nursery: trio.Nursery, files: list[str]) -> None:
    """Start our server, then process in the GUI."""
    async def listen(nursery: trio.Nursery, listener: trio.SocketListener) -> None:
        """Listen to our open socket for messages."""
        while True:
            stream = await listener.accept()
            nursery.start_soon(pump_stream, stream)

    async def pump_stream(stream: trio.SocketStream) -> None:
        """Read the files sent by a client, and send them along."""
        buf = bytearray()
        async for msg in stream:
            buf += msg
            while b'\n' in buf:
                pos = buf.index(b'\n')
                await send_file.send(Path(buf[:pos].decode('utf8')))
                del buf[:pos+1]

    send_file: trio.MemorySendChannel[Path]
    rec_file: trio.MemoryReceiveChannel[Path]
    send_file, rec_file = trio.open_memory_channel(math.inf)
    async with send_file, trio.open_nursery() as nursery:
        listeners = await trio.open_tcp_listeners(0, host='localhost')
        assert listeners
        for listener in listeners:
            nursery.start_soon(listen, nursery, listener)
        address = listeners[0].socket.getsockname()[1]
        await trio.Path(FILE_SERVER).write_text(str(address))

        # Prime with our own file list.
        for file in files:
            await send_file.send(Path(file))
        # Now start the GUI.
        with app.QUIT_SCOPE:
            await main_gui(ui, core_nursery, rec_file)
        # Quit, shut down the server.
        nursery.cancel_scope.cancel('ui quit')


if __name__ == '__main__':
    LOGGER.info('BEE{} packages syncer, args={}', utils.BEE_VERSION, sys.argv[1:])
    main(sys.argv[1:])
