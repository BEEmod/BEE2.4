"""Run the BEE2."""
from typing import Awaitable, Callable, Any, ClassVar, Deque, Dict, Optional, List, Tuple
import time
import collections
import logging

from outcome import Outcome, Error
from srctools import Keyvalues
import trio
from typing_extensions import override

from app import (
    CompilerPane, TK_ROOT, localisation, sound, img, gameMan, music_conf,
    UI, logWindow,
)
from config.windows import WindowState
from transtoken import TransToken
from ui_tk.dialogs import DIALOG
from ui_tk.errors import display_errors
from ui_tk import wid_transtoken
from ui_tk.img import TK_IMG
from config.gen_opts import GenOptions
from config.last_sel import LastSelected
from exporting import mod_support, ExportData
from app.errors import ErrorUI, Result as ErrorResult
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
    await loadScreen.MAIN_UI.set_length(16)
    loadScreen.set_force_ontop(conf.force_load_ontop)
    loadScreen.show_main_loader(conf.compact_splash)

    # OS X starts behind other windows, fix that.
    if utils.MAC:
        TK_ROOT.lift()

    logWindow.HANDLER.set_visible(conf.show_log_win)
    logWindow.HANDLER.setLevel(conf.log_win_level)
    app.background_run(logWindow.loglevel_bg)

    LOGGER.debug('Loading settings...')

    # This is cancelled when the quit button is pressed.
    # noinspection PyProtectedMember
    with app._APP_QUIT_SCOPE:
        await gameMan.load(DIALOG)
        try:
            last_game = config.APP.get_cur_conf(LastSelected, 'game')
        except KeyError:
            pass
        else:
            if last_game.id is not None:
                gameMan.set_game_by_name(last_game.id)

        LOGGER.info('Loading Packages...')
        packset = packages.get_loaded_packages()
        mod_support.scan_music_locs(packset, gameMan.all_games)
        async with ErrorUI(
            error_desc=TransToken.ui_plural(
                'An error occurred when loading packages:',
                'Multiple errors occurred when loading packages:',
            ),
            warn_desc=TransToken.ui('Loading packages was partially successful:'),
        ) as error_ui:
            await utils.run_as_task(
                packages.load_packages,
                packset,
                list(BEE2_config.get_package_locs()),
                error_ui,
            )
        if error_ui.result is ErrorResult.FAILED:
            return
        package_sys = packages.PACKAGE_SYS
        await loadScreen.MAIN_UI.step('pre_ui')
        app.background_run(img.init, package_sys, TK_IMG)
        app.background_run(sound.sound_task)
        app.background_run(wid_transtoken.update_task)
        app.background_run(localisation.load_aux_langs, gameMan.all_games, packset)

        # Load filesystems into various modules
        music_conf.load_filesystems(package_sys.values())
        await utils.run_as_task(UI.load_packages, packset, TK_IMG)
        await loadScreen.MAIN_UI.step('package_load')
        LOGGER.info('Done!')

        LOGGER.info('Initialising UI...')
        await utils.run_as_task(UI.init_windows, TK_IMG)
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

        confs = [
            BEE2_config.GEN_OPTS,
            CompilerPane.COMPILE_CFG,
        ]

        try:
            await trio.sleep_forever()

        finally:
            LOGGER.info('Shutting down application.')

            # Save all our configs, but skip if any exceptions occur.

            # If our window isn't actually visible, this is set to nonsense -
            # ignore those values.
            if TK_ROOT.winfo_viewable():
                config.APP.store_conf(WindowState(
                    x=TK_ROOT.winfo_rootx(),
                    y=TK_ROOT.winfo_rooty(),
                ), 'main_window')

            try:
                config.APP.write_file(config.APP_LOC)
            except Exception:
                LOGGER.exception('Saving main conf:')
            for conf_file in confs:
                try:
                    conf_file.save_check()
                except Exception:
                    LOGGER.exception('Saving {}:', conf_file.filename)
            try:
                gameMan.save()
            except Exception:
                LOGGER.exception('Saving game config')
            # Clean this out.
            try:
                sound.clean_sample_folder()
            except Exception:
                LOGGER.exception('Deleting music samples.')


class Tracer(trio.abc.Instrument):
    """Track tasks to detect slow ones."""
    slow: ClassVar[List[Tuple[float, str]]] = []

    def __init__(self) -> None:
        self.elapsed: Dict[trio.lowlevel.Task, float] = {}
        self.start_time: Dict[trio.lowlevel.Task, Optional[float]] = {}
        self.args: Dict[trio.lowlevel.Task, Dict[str, object]] = {}

    @override
    def task_spawned(self, task: trio.lowlevel.Task) -> None:
        """Setup vars when a task is spawned."""
        self.elapsed[task] = 0.0
        self.start_time[task] = None
        self.args[task] = task.coro.cr_frame.f_locals.copy()

    @override
    def before_task_step(self, task: trio.lowlevel.Task) -> None:
        """Begin timing this task."""
        self.start_time[task] = time.perf_counter()

    @override
    def after_task_step(self, task: trio.lowlevel.Task) -> None:
        """Count up the time."""
        cur_time = time.perf_counter()
        try:
            prev = self.start_time[task]
        except KeyError:
            pass
        else:
            if prev is not None:
                change = cur_time - prev
                self.elapsed[task] += change
                self.start_time[task] = None
                if change > (5/1000):
                    LOGGER.warning(
                        'Task didn\'t yield ({:.02f}ms): {!r}:{}, args={}',
                        change*1000,
                        task, task.coro.cr_frame.f_lineno,
                        self.get_args(task),
                    )

    @override
    def task_exited(self, task: trio.lowlevel.Task) -> None:
        """Log results when exited."""
        cur_time = time.perf_counter()
        elapsed = self.elapsed.pop(task, 0.0)
        start = self.start_time.pop(task, None)
        if start is not None:
            elapsed += cur_time - start

        if elapsed > 0.1:
            self.slow.append((elapsed, f'Task time={elapsed:.06}: {task!r}, args={self.get_args(task)}'))
        self.args.pop(task, None)

    def get_args(self, task: trio.lowlevel.Task) -> object:
        """Get the args for a task."""
        args = self.args.pop(task, srctools.EmptyMapping)
        return {
            name: (
                # Hide objects with really massive reprs.
                '...' if isinstance(val, (dict, Keyvalues, packages.PackagesSet, ExportData))
                else val
            )
            for name, val in args.items()
            if 'KI_PROTECTION' not in name  # Trio flag.
        }


async def app_main(init: Callable[[], Awaitable[Any]]) -> None:
    """The main loop for Trio."""
    LOGGER.debug('Opening nursery...')
    async with trio.open_nursery() as nursery:
        app._APP_NURSERY = nursery
        await nursery.start(display_errors)
        await nursery.start(loadScreen.startup)
        await gameMan.check_app_in_game(DIALOG)

        # Run main app, then cancel this nursery to quit all other tasks.
        await init()
        nursery.cancel_scope.cancel()


def done_callback(result: Outcome[None]) -> None:
    """The app finished, quit."""
    if isinstance(result, Error):
        LOGGER.error('Trio exited with exception', exc_info=result.error)
        app.tk_error(type(result.error), result.error, result.error.__traceback__)
    else:
        LOGGER.debug('Trio exited normally.')
    TK_ROOT.quit()


def start_main(init: Callable[[], Awaitable[object]] = init_app) -> None:
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
    try:
        trio.lowlevel.start_guest_run(
            app_main, init,
            run_sync_soon_threadsafe=run_sync_soon_threadsafe,
            run_sync_soon_not_threadsafe=run_sync_soon_not_threadsafe,
            done_callback=done_callback,
            instruments=[Tracer()] if utils.DEV_MODE else [],
            strict_exception_groups=True,
        )
        TK_ROOT.mainloop()
    finally:
        logging.shutdown()
