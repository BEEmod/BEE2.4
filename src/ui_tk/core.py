"""Connect Trio and TK together, then run the application."""
from __future__ import annotations
from typing import Any

from collections.abc import Awaitable, Callable
import collections

from outcome import Error, Outcome
import srctools.logger
import trio

from app import (
    UI, CompilerPane, gameMan, img, lifecycle, localisation, logWindow, sound,
)
from config.gen_opts import GenOptions
from config.last_sel import LastSelected
from config.windows import WindowState
from trio_debug import Tracer
from ui_tk import TK_ROOT, route_callback_exceptions, wid_transtoken
from ui_tk.dialogs import DIALOG
from ui_tk.errors import display_errors
from ui_tk.img import TK_IMG
import app
import async_util
import BEE2_config
import config
import exporting
import loadScreen
import packages
import utils


LOGGER = srctools.logger.get_logger('BEE2')
_TRACER = Tracer() if utils.CODE_DEV_MODE else None


async def init_app(core_nursery: trio.Nursery) -> None:
    """Initialise the application."""
    # This is cancelled when the quit button is pressed.
    # noinspection PyProtectedMember
    with app._APP_QUIT_SCOPE:
        conf = config.APP.get_cur_conf(GenOptions)

        LOGGER.debug('Starting loading screen...')
        await loadScreen.MAIN_UI.set_length(13)
        loadScreen.set_force_ontop(conf.force_load_ontop)
        loadScreen.show_main_loader(conf.compact_splash, app._APP_QUIT_SCOPE)

        # OS X starts behind other windows, fix that.
        if utils.MAC:
            TK_ROOT.lift()

        logWindow.HANDLER.set_visible(conf.show_log_win)
        logWindow.HANDLER.setLevel(conf.log_win_level)
        core_nursery.start_soon(logWindow.loglevel_bg)

        LOGGER.debug('Loading settings...')
        await gameMan.load(DIALOG)
        try:
            last_game = config.APP.get_cur_conf(LastSelected, 'game')
        except KeyError:
            pass
        else:
            gameMan.set_game_by_name(last_game.id)

        core_nursery.start_soon(sound.sound_task)

        export_trig = async_util.EdgeTrigger[exporting.ExportInfo]()
        export_send, export_rec = trio.open_memory_channel[lifecycle.ExportResult](1)

        core_nursery.start_soon(
            lifecycle.lifecycle,
            export_trig,
            export_send,
        )
        packset, _ = await packages.LOADED.wait_transition()
        await loadScreen.MAIN_UI.step('pre_ui')
        core_nursery.start_soon(img.init, TK_IMG)
        core_nursery.start_soon(localisation.load_aux_langs, gameMan.all_games, packset)

        LOGGER.info('Initialising UI...')
        await core_nursery.start(UI.init_windows, core_nursery, TK_IMG, export_trig, export_rec)
        LOGGER.info('UI initialised!')

        # If the loading screen was quit, we will cancel here, before the try: below.
        # So configs will not get saved - we might have half-loaded them.
        await trio.lowlevel.checkpoint()
        loadScreen.main_loader.destroy()

        # Delay this until the loop has actually run.
        # Directly run TK_ROOT.lift() in TCL, instead
        # of building a callable.
        TK_ROOT.tk.call('after', 10, 'raise', TK_ROOT)

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
            for conf_file in [
                BEE2_config.GEN_OPTS,
                CompilerPane.COMPILE_CFG,
            ]:
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


async def app_main(init: Callable[[trio.Nursery], Awaitable[Any]]) -> None:
    """The main loop for Trio."""
    LOGGER.debug('Opening nursery...')
    async with trio.open_nursery() as nursery:
        app._APP_NURSERY = nursery
        # Start some core tasks.
        await nursery.start(route_callback_exceptions)
        await nursery.start(display_errors)

        # Check very early before bad things happen.
        await gameMan.check_app_in_game(DIALOG)

        await nursery.start(loadScreen.startup)
        nursery.start_soon(wid_transtoken.update_task)

        # Run main app, then once completed cancel this nursery to quit all other tasks.
        # It gets given the nursery to allow spawning new tasks here.
        await init(nursery)
        nursery.cancel_scope.cancel()


def done_callback(result: Outcome[None]) -> None:
    """The app finished, quit."""
    if isinstance(result, Error):
        LOGGER.error('Trio exited with exception', exc_info=result.error)
        app.on_error(type(result.error), result.error, result.error.__traceback__)
    else:
        LOGGER.debug('Trio exited normally.')
        if _TRACER is not None:
            _TRACER.display_slow()
    TK_ROOT.quit()


def start_main(init: Callable[[trio.Nursery], Awaitable[object]] = init_app) -> None:
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
        instruments=[_TRACER] if _TRACER is not None else [],
        strict_exception_groups=True,
    )
    TK_ROOT.mainloop()
