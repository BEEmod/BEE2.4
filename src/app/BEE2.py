"""Run the BEE2."""
from typing import Awaitable, Callable, Any, Deque, Dict, Optional, List, Tuple
import time
import collections

from outcome import Outcome, Error
from srctools import Keyvalues
import trio

from app import (
    TK_ROOT, localisation, sound, img, gameMan, music_conf,
    UI, logWindow,
)
from ui_tk.dialogs import DIALOG
from ui_tk.errors import display_errors
from config.gen_opts import GenOptions
from config.last_sel import LastSelected
import config
import app
import loadScreen
import packages
import utils
import BEE2_config
import srctools.logger

LOGGER = srctools.logger.get_logger('BEE2')


async def init_app() -> None:
    """Initialise the application."""
    conf = config.APP.get_cur_conf(GenOptions)

    LOGGER.debug('Starting loading screen...')
    loadScreen.main_loader.set_length('UI', 16)
    loadScreen.set_force_ontop(conf.force_load_ontop)
    loadScreen.show_main_loader(conf.compact_splash)

    # OS X starts behind other windows, fix that.
    if utils.MAC:
        TK_ROOT.lift()

    logWindow.HANDLER.set_visible(conf.show_log_win)
    logWindow.HANDLER.setLevel(conf.log_win_level)
    app.background_run(logWindow.loglevel_bg)

    LOGGER.debug('Loading settings...')

    await gameMan.load(DIALOG)
    try:
        last_game = config.APP.get_cur_conf(LastSelected, 'game')
    except KeyError:
        pass
    else:
        gameMan.set_game_by_name(last_game.id)
    gameMan.scan_music_locs()

    LOGGER.info('Loading Packages...')
    packset = packages.get_loaded_packages()
    packset.has_mel_music = gameMan.MUSIC_MEL_VPK is not None
    packset.has_tag_music = gameMan.MUSIC_TAG_LOC is not None
    async with trio.open_nursery() as nurs:
        nurs.start_soon(
            packages.load_packages,
            packset,
            list(BEE2_config.get_package_locs()),
            loadScreen.main_loader,
            DIALOG,
        )
    package_sys = packages.PACKAGE_SYS
    loadScreen.main_loader.step('UI', 'pre_ui')
    from ui_tk.img import TK_IMG
    app.background_run(img.init, package_sys, TK_IMG)
    app.background_run(sound.sound_task)
    app.background_run(localisation.load_aux_langs, gameMan.all_games, packset)

    # Load filesystems into various modules
    music_conf.load_filesystems(package_sys.values())
    gameMan.load_filesystems(package_sys.values())
    async with trio.open_nursery() as nurs:
        nurs.start_soon(UI.load_packages, packset, TK_IMG)
    loadScreen.main_loader.step('UI', 'package_load')
    LOGGER.info('Done!')

    LOGGER.info('Initialising UI...')
    async with trio.open_nursery() as nurs:
        nurs.start_soon(UI.init_windows, TK_IMG)  # create all windows
    LOGGER.info('UI initialised!')

    if Tracer.slow:
        LOGGER.info('Slow tasks\n{}', '\n'.join([
            msg for _, msg in
            sorted(Tracer.slow, key=lambda t: t[1], reverse=True)
        ]))

    loadScreen.main_loader.destroy()
    # Delay this until the loop has actually run.
    # Directly run TK_ROOT.lift() in TCL, instead
    # of building a callable.
    TK_ROOT.tk.call('after', 10, 'raise', TK_ROOT)
    await trio.sleep_forever()


class Tracer(trio.abc.Instrument):
    """Track tasks to detect slow ones."""
    slow: List[Tuple[float, str]] = []

    def __init__(self) -> None:
        self.elapsed: Dict[trio.lowlevel.Task, float] = {}
        self.start_time: Dict[trio.lowlevel.Task, Optional[float]] = {}
        self.args: Dict[trio.lowlevel.Task, Dict[str, object]] = {}

    def task_spawned(self, task: trio.lowlevel.Task) -> None:
        """Setup vars when a task is spawned."""
        self.elapsed[task] = 0.0
        self.start_time[task] = None
        self.args[task] = task.coro.cr_frame.f_locals.copy()

    def before_task_step(self, task: trio.lowlevel.Task) -> None:
        """Begin timing this task."""
        self.start_time[task] = time.perf_counter()

    def after_task_step(self, task: trio.lowlevel.Task) -> None:
        """Count up the time."""
        cur_time = time.perf_counter()
        try:
            prev = self.start_time[task]
        except KeyError:
            pass
        else:
            if prev is not None:
                self.elapsed[task] += time.perf_counter() - prev
                self.start_time[task] = None

    def task_exited(self, task: trio.lowlevel.Task) -> None:
        """Log results when exited."""
        elapsed = self.elapsed.pop(task, 0.0)
        start = self.start_time.pop(task, None)
        args = self.args.pop(task, srctools.EmptyMapping)
        if start is not None:
            elapsed += time.perf_counter() - start

        if elapsed > 0.1:
            args = {
                name: val
                for name, val in args.items()
                # Hide objects with really massive reprs.
                if not isinstance(val, (dict, Keyvalues, packages.PackagesSet))
                # Objects with no useful info.
                if (
                    type(val).__repr__ is not object.__repr__ or
                    type(val).__str__ is not object.__str__
                )
                if 'KI_PROTECTION' not in name   # Trio flag.
            }
            self.slow.append((elapsed, f'Task time={elapsed:.06}: {task!r}, args={args}'))


async def app_main(init: Callable[[], Awaitable[Any]]) -> None:
    """The main loop for Trio."""
    LOGGER.debug('Opening nursery...')
    async with trio.open_nursery() as nursery:
        app._APP_NURSERY = nursery
        await nursery.start(display_errors)

        # Run main app, then cancel this nursery to quit all other tasks.
        await init()
        nursery.cancel_scope.cancel()


def done_callback(result: Outcome) -> None:
    """The app finished, quit."""
    from app import UI
    if isinstance(result, Error):
        LOGGER.error('Trio exited with exception', exc_info=result.error)
        app.tk_error(type(result.error), result.error, result.error.__traceback__)
    else:
        LOGGER.debug('Trio exited normally.')
    UI.quit_application()
    TK_ROOT.quit()


def start_main(init: Callable[[], Awaitable[Any]]=init_app) -> None:
    """Starts the TK and Trio loops.

    See https://github.com/richardsheridan/trio-guest/.
    """
    def tk_func() -> None:
        """Called to execute the callback."""
        queue.popleft()()

    def run_sync_soon_threadsafe(func: Callable[[], Any]) -> None:
        """Run the specified func in the next loop, from other threads."""
        queue.append(func)
        TK_ROOT.call("after", "idle", tk_func_name)

    def run_sync_soon_not_threadsafe(func: Callable[[], Any]) -> None:
        """Run the specified func in the next loop."""
        queue.append(func)
        # The zero here apparently avoids blocking the event loop if an endless stream of
        # callbacks is triggered.
        TK_ROOT.call("after", "idle", "after", 0, tk_func_name)

    queue: Deque[Callable[[], Any]] = collections.deque()
    tk_func_name = TK_ROOT.register(tk_func)

    LOGGER.debug('Starting Trio loop.')
    trio.lowlevel.start_guest_run(
        app_main, init,
        run_sync_soon_threadsafe=run_sync_soon_threadsafe,
        run_sync_soon_not_threadsafe=run_sync_soon_not_threadsafe,
        done_callback=done_callback,
        instruments=[Tracer()] if utils.DEV_MODE else [],
        strict_exception_groups=True,
    )
    TK_ROOT.mainloop()
