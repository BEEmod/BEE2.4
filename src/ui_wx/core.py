"""Connect Trio and WxWidgets together, then run the application."""
from __future__ import annotations
from typing import Any
from collections.abc import Awaitable, Callable
import collections

from outcome import Outcome, Error
import trio
import wx

import exporting
from app import (
    CompilerPane, localisation, sound, img, gameMan, music_conf,
    UI, logWindow, lifecycle,
)
from config.windows import WindowState
from trio_debug import Tracer
from ui_wx.dialogs import DIALOG
from ui_tk.errors import display_errors
from ui_wx import wid_transtoken
from ui_wx.img import WX_IMG
from ui_wx import APP, MAIN_WINDOW
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
_TRACER = Tracer() if utils.CODE_DEV_MODE else None


async def init_app(core_nursery: trio.Nursery) -> None:
    """Initialise the application."""
    conf = config.APP.get_cur_conf(GenOptions)

    LOGGER.debug('Starting loading screen...')
    await loadScreen.MAIN_UI.set_length(16)
    loadScreen.set_force_ontop(conf.force_load_ontop)
    loadScreen.show_main_loader(conf.compact_splash)

    logWindow.HANDLER.set_visible(conf.show_log_win)
    logWindow.HANDLER.setLevel(conf.log_win_level)
    core_nursery.start_soon(logWindow.loglevel_bg)

    LOGGER.debug('Loading settings...')

    # This is cancelled when the quit button is pressed.
    # noinspection PyProtectedMember
    with app._APP_QUIT_SCOPE:
        await gameMan.load(DIALOG)
        last_game = config.APP.get_cur_conf(LastSelected, 'game')
        if last_game.id is not None:
            gameMan.set_game_by_name(last_game.id)

        core_nursery.start_soon(sound.sound_task)

        export_trig = app.EdgeTrigger[exporting.ExportInfo]()
        export_send, export_rec = trio.open_memory_channel[lifecycle.ExportResult](1)

        core_nursery.start_soon(
            lifecycle.lifecycle,
            app.EdgeTrigger[()](),  # For now, never reload.
            export_trig,
            export_send,
        )
        packset, _ = await packages.LOADED.wait_transition()
        package_sys = packages.PACKAGE_SYS
        await loadScreen.MAIN_UI.step('pre_ui')
        core_nursery.start_soon(img.init, package_sys, WX_IMG)
        core_nursery.start_soon(localisation.load_aux_langs, gameMan.all_games, packset)

        # Load filesystems into various modules.
        music_conf.load_filesystems(package_sys.values())
        await utils.run_as_task(UI.load_packages, core_nursery, packset, WX_IMG)
        await loadScreen.MAIN_UI.step('package_load')
        LOGGER.info('Done!')

        LOGGER.info('Initialising UI...')
        await core_nursery.start(UI.init_windows, core_nursery, WX_IMG, export_trig, export_rec)
        LOGGER.info('UI initialised!')

        loadScreen.main_loader.destroy()

        confs = [
            BEE2_config.GEN_OPTS,
            CompilerPane.COMPILE_CFG,
        ]

        try:
            await trio.sleep_forever()
        finally:
            LOGGER.info('Shutting down application.')

            # Save all our configs, but skip if any exceptions occur.

            # Skip for now until everything is ready.
            return

            # If our window isn't actually visible, this is set to nonsense -
            # ignore those values.
            if MAIN_WINDOW.IsActive() and (pos := MAIN_WINDOW.GetScreenPosition()).IsFullySpecified():
                config.APP.store_conf(WindowState(x=pos.x, y=pos.y), 'main_window')

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


async def app_main(init: Callable[[trio.Nursery], Awaitable[Any]]) -> None:
    """The main loop for Trio."""
    LOGGER.debug('Opening nursery...')
    async with trio.open_nursery() as nursery:
        app._APP_NURSERY = nursery
        # Start some core tasks.
        # await nursery.start(route_callback_exceptions)
        # await nursery.start(display_errors)

        # Check very early before bad things happen.
        await gameMan.check_app_in_game(DIALOG)

        nursery.start_soon(wid_transtoken.update_task)
        # await nursery.start(loadScreen.startup)

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
    APP.ExitMainLoop()


def start_main(init: Callable[[trio.Nursery], Awaitable[object]] = init_app) -> None:
    """Starts the Wx and Trio loops."""
    def run_callback(event: wx.IdleEvent) -> None:
        """Called to execute the callback."""
        while queue:
            queue.popleft()()

    def run_sync_soon_threadsafe(func: Callable[[], Any]) -> None:
        """Run the specified func in the next loop, from other threads."""
        queue.append(func)
        wx.WakeUpIdle()

    queue: collections.deque[Callable[[], Any]] = collections.deque()

    LOGGER.debug('Starting Trio loop.')
    trio.lowlevel.start_guest_run(
        app_main, init,
        run_sync_soon_threadsafe=run_sync_soon_threadsafe,
        done_callback=done_callback,
        instruments=[_TRACER] if _TRACER is not None else [],
        strict_exception_groups=True,
    )
    APP.Bind(wx.EVT_IDLE, run_callback)
    wx.WakeUpIdle()
    MAIN_WINDOW.Show()
    APP.MainLoop()
