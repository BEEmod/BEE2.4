"""Run the BEE2."""
import functools
from typing import Awaitable, Callable, Any, Optional, List, Tuple
import time
import collections

from outcome import Outcome, Error
from srctools import Property
import trio

import localisation
from BEE2_config import GEN_OPTS
from app import (
    TK_ROOT, sound, img, gameMan, music_conf,
    UI, logWindow,
)
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
APP_NURSERY: trio.Nursery


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

    gameMan.load()
    try:
        last_game = config.APP.get_cur_conf(LastSelected, 'game')
    except KeyError:
        pass
    else:
        gameMan.set_game_by_name(last_game.id)
    gameMan.scan_music_locs()

    LOGGER.info('Loading Packages...')
    async with trio.open_nursery() as nurs:
        nurs.start_soon(functools.partial(
            packages.load_packages,
            packages.LOADED,
            list(BEE2_config.get_package_locs()),
            loader=loadScreen.main_loader,
            has_mel_music=gameMan.MUSIC_MEL_VPK is not None,
            has_tag_music=gameMan.MUSIC_TAG_LOC is not None,
        ))
    package_sys = packages.PACKAGE_SYS
    loadScreen.main_loader.step('UI', 'pre_ui')
    app.background_run(img.init, package_sys)
    app.background_run(sound.sound_task)
    app.background_run(localisation.load_aux_langs, gameMan.all_games, packages.LOADED)

    # Load filesystems into various modules
    music_conf.load_filesystems(package_sys.values())
    gameMan.load_filesystems(package_sys.values())
    async with trio.open_nursery() as nurs:
        nurs.start_soon(UI.load_packages, packages.LOADED)
    loadScreen.main_loader.step('UI', 'package_load')
    LOGGER.info('Done!')

    LOGGER.info('Initialising UI...')
    async with trio.open_nursery() as nurs:
        nurs.start_soon(UI.init_windows)  # create all windows
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
        self.elapsed: dict[trio.lowlevel.Task, float] = {}
        self.start_time: dict[trio.lowlevel.Task, Optional[float]] = {}
        self.args: dict[trio.lowlevel.Task, dict[str, object]] = {}

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
        try:
            diff = time.perf_counter() - self.start_time[task]
        except KeyError:
            pass
        else:
            self.elapsed[task] += diff
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
                if not isinstance(val, (dict, Property, packages.PackagesSet)) and (
                    type(val).__repr__ is not object.__repr__ or  # Objects with no useful info.
                    type(val).__str__ is not object.__str__
                ) and 'KI_PROTECTION' not in name   # Trio flag.
            }
            self.slow.append((elapsed, f'Task time={elapsed:.06}: {task!r}, args={args}'))


async def app_main(init: Callable[[], Awaitable[Any]]) -> None:
    """The main loop for Trio."""
    global APP_NURSERY
    LOGGER.debug('Opening nursery...')
    async with trio.open_nursery() as nursery:
        app._APP_NURSERY = nursery
        await init()


def done_callback(result: Outcome):
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

    queue: collections.deque[Callable[[], Any]] = collections.deque()
    tk_func_name = TK_ROOT.register(tk_func)

    LOGGER.debug('Starting Trio loop.')
    trio.lowlevel.start_guest_run(
        app_main, init,
        run_sync_soon_threadsafe=run_sync_soon_threadsafe,
        run_sync_soon_not_threadsafe=run_sync_soon_not_threadsafe,
        done_callback=done_callback,
        instruments=[Tracer()] if utils.DEV_MODE else [],
    )
    TK_ROOT.mainloop()
