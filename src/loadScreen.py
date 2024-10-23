"""Displays a loading menu while packages, palettes, etc are being loaded.

All the actual display is done in a subprocess, so we can allow interaction while
the main process is busy loading.

The id() of the main-process object is used to identify loadscreens.
"""
from __future__ import annotations
from typing import Self, assert_never
from collections.abc import (
    AsyncGenerator, Collection, Generator, MutableMapping,
)
from types import TracebackType
from weakref import WeakValueDictionary
import contextlib
import multiprocessing

import attrs
import srctools.logger
import trio

from config import APP
from config.gen_opts import GenOptions
from transtoken import CURRENT_LANG, TransToken
import ipc_types
import utils


# Keep a reference to all loading screens, so we can close them globally.
_ALL_SCREENS: MutableMapping[ipc_types.ScreenID, LoadScreen] = WeakValueDictionary()

# Queues we use to send data to the daemon and vice versa.
# SEND goes from app -> daemon, REPLY goes from daemon -> app.
_QUEUE_SEND_LOAD: multiprocessing.Queue[ipc_types.ARGS_SEND_LOAD] = multiprocessing.Queue()
_QUEUE_REPLY_LOAD: multiprocessing.Queue[ipc_types.ARGS_REPLY_LOAD] = multiprocessing.Queue()
_QUEUE_SEND_LOGGING: multiprocessing.Queue[ipc_types.ARGS_SEND_LOGGING] = multiprocessing.Queue()
_QUEUE_REPLY_LOGGING: multiprocessing.Queue[ipc_types.ARGS_REPLY_LOGGING] = multiprocessing.Queue()


LOGGER = srctools.logger.get_logger(__name__)
# All tokens used by the subprocess. We translate here before passing it down.
TRANSLATIONS = {
    'skip': TransToken.ui('Skipped!'),
    'version': TransToken.ui('Version: {ver}').format(ver=utils.BEE_VERSION),
    'cancel': TransToken.ui('Cancel'),
    'clear': TransToken.ui('Clear'),
    'copy': TransToken.ui('Copy'),
    'log_show': TransToken.ui('Show:'),
    'log_title': TransToken.ui('Logs - {ver}').format(ver=utils.BEE_VERSION),
    'level_debug': TransToken.ui('Debug messages'),
    'level_info': TransToken.ui('Default'),
    'level_warn': TransToken.ui('Warnings Only'),
}


def show_main_loader(is_compact: bool) -> None:
    """Special function, which sets the splash screen compactness."""
    _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_SetIsCompact(main_loader.id, is_compact))
    main_loader._show()


def set_force_ontop(ontop: bool) -> None:
    """Set whether screens will be forced on top."""
    _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_SetForceOnTop(ontop))


@contextlib.contextmanager
def suppress_screens() -> Generator[None, None, None]:
    """A context manager to suppress loadscreens while the body is active."""
    active = []
    for screen in _ALL_SCREENS.values():
        if not screen.active:
            continue
        screen.suppress()
        active.append(screen)
    try:
        yield None
    finally:
        for screen in active:
            screen.unsuppress()


class ScreenStage:
    """A single stage in a loading screen."""
    def __init__(self, title: TransToken) -> None:
        self.title = title
        self.id = ipc_types.StageID(format(id(self), '016X'))
        self._bound: set[LoadScreen] = set()
        self._current = 0
        self._max = 0
        self._skipped = False

    async def set_length(self, num: int) -> None:
        """Change the current length of this stage."""
        await trio.lowlevel.checkpoint()
        self._max = num
        for screen in list(self._bound):
            _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_SetLength(screen.id, self.id, num))

    async def step(self, info: object = None) -> None:
        """Increment one step."""
        await trio.lowlevel.checkpoint()
        self._current += 1
        self._skipped = False
        for screen in list(self._bound):
            _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Set(screen.id, self.id, self._current))

    async def skip(self) -> None:
        """Skip this stage."""
        await trio.lowlevel.checkpoint()
        self._current = 0
        self._skipped = True
        for screen in list(self._bound):
            _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Skip(screen.id, self.id))

    async def iterate[T](self, seq: Collection[T]) -> AsyncGenerator[T, None]:
        """Tie the progress of a stage to a sequence of some kind."""
        await self.set_length(len(seq))
        for item in seq:
            yield item
            await self.step()

    def warn_if_incomplete(self, owner: object) -> None:
        """Check to see if this finished loading, and warn if not."""

        if self._current < self._max and not self._skipped:
            LOGGER.warning(
                'Incomplete stage: "{}"."{}": {} < {}',
                owner, self.title,
                self._current, self._max,
            )


class LoadScreen:
    """LoadScreens show a loading screen for items.

    stages should be (id, title) pairs for each screen stage.
    Each stage can be stepped independently, referenced by the given ID.
    The title can be blank.
    """

    def __init__(
        self,
        *stages: ScreenStage,
        title_text: TransToken,
        is_splash: bool = False,
    ) -> None:
        # active determines whether the screen is on, and if False stops most
        # functions from doing anything
        self.active = False
        self.id = ipc_types.ScreenID(id(self))
        self.stages: list[ScreenStage] = list(stages)
        self.title = title_text
        self._scope: trio.CancelScope | None = None
        self.cancelled = False

        # Order the daemon to make this screen. We pass translated text in for the splash screen.
        _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Init(
            scr_id=self.id,
            is_splash=is_splash,
            title=str(title_text),
            stages=[
                (stage.id, str(stage.title))
                for stage in stages
            ],
        ))
        _ALL_SCREENS[self.id] = self

    def __enter__(self) -> Self:
        """LoadScreen can be used as a context manager.

        Inside the block, the screen will be visible. Cancelling will exit
        to the end of the with block.
        """
        if self._scope is not None:
            raise ValueError('Cannot re-enter loading screens!')
        self._scope = trio.CancelScope().__enter__()
        self.cancelled = False
        self._show()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Hide the loading screen. If the Cancelled exception was raised, swallow that.
        """
        scope = self._scope
        if scope is None:
            raise ValueError('Already exited?')
        self._scope = None
        self.cancelled = scope.cancelled_caught
        try:
            self.active = False
            _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Reset(self.id))
            for stage in self.stages:
                stage.warn_if_incomplete(self.title)
                stage._bound.discard(self)
        finally:
            # Always call scope's __exit__(), but just raise if our code errors.
            res = scope.__exit__(exc_type, exc_val, exc_tb)
        return res

    async def __aenter__(self) -> Self:
        """Allow use as an async context manager too.

         This makes using aclosing(stage.iterate()) more compact.
         """
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Same as synchronous exiting."""
        return self.__exit__(exc_type, exc_val, exc_tb)

    def _show(self) -> None:
        """Display the loading screen."""
        self.active = True
        # Translate and send across the titles now.
        # noinspection PyProtectedMember
        _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Show(
            self.id, str(self.title),
            [
                (str(stage.title), stage._max)
                for stage in self.stages
            ],
        ))
        for stage in self.stages:
            stage._bound.add(self)

    def destroy(self) -> None:
        """Permanently destroy this screen and cleanup."""
        self.active = False
        _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Destroy(self.id))
        for stage in self.stages:
            stage.warn_if_incomplete(self.title)
            stage._bound.discard(self)
        del _ALL_SCREENS[self.id]

    def suppress(self) -> None:
        """Temporarily hide the screen."""
        self.active = False
        _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Hide(self.id))

    def unsuppress(self) -> None:
        """Undo temporarily hiding the screen."""
        self.active = True
        # noinspection PyProtectedMember
        _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_Show(
            self.id, str(self.title),
            [
                (str(stage.title), stage._max)
                for stage in self.stages
            ],
        ))


async def _update_translations() -> None:
    """Update the translations whenever the language changes."""
    while True:
        await CURRENT_LANG.wait_transition()
        _QUEUE_SEND_LOAD.put(ipc_types.Load2Daemon_UpdateTranslations(
            {key: str(tok) for key, tok in TRANSLATIONS.items()},
        ))


async def _listen_to_process() -> None:
    """Listen to responses from the loading screens."""
    while True:
        op = await trio.to_thread.run_sync(_QUEUE_REPLY_LOAD.get, abandon_on_cancel=True)
        LOGGER.debug('Logger response: {}', op)
        match op:
            case ipc_types.Daemon2Load_MainSetCompact():
                # Save the compact state to the config.
                conf = APP.get_cur_conf(GenOptions)
                APP.store_conf(attrs.evolve(conf, compact_splash=op.compact))
            case ipc_types.Daemon2Load_Cancel():
                try:
                    screen = _ALL_SCREENS[op.screen]
                except KeyError:
                    pass
                else:
                    LOGGER.info('Cancelling load screen {!r}', screen.title)
                    if screen._scope is not None:
                        screen._scope.cancel()
            case _:
                assert_never(op)


_bg_started = False


async def startup(*, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED) -> None:
    """Spawn the daemon process, then listen to responses."""
    global _bg_started
    if _bg_started:
        raise ValueError('Daemon already started!')
    _bg_started = True

    # Initialise the daemon.
    process = multiprocessing.Process(
        target=utils.run_bg_daemon,
        args=(
            _QUEUE_SEND_LOAD, _QUEUE_REPLY_LOAD, _QUEUE_SEND_LOGGING, _QUEUE_REPLY_LOGGING,
            # Convert and pass translation strings.
            {key: str(tok) for key, tok in TRANSLATIONS.items()},
        ),
        name='bg_daemon',
        daemon=True,
    )
    await trio.sleep(0)
    process.start()
    try:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(_update_translations)
            nursery.start_soon(_listen_to_process)
            task_status.started()
    finally:
        _QUEUE_SEND_LOAD.close()
        _QUEUE_REPLY_LOAD.close()
        _QUEUE_SEND_LOGGING.close()
        _QUEUE_REPLY_LOGGING.close()
        process.terminate()


MAIN_PAK = ScreenStage(TransToken.ui('Packages'))
MAIN_OBJ = ScreenStage(TransToken.ui('Loading Objects'))
MAIN_UI = ScreenStage(TransToken.ui('Initialising UI'))

main_loader = LoadScreen(
    MAIN_PAK, MAIN_OBJ, MAIN_UI,
    title_text=TransToken.ui('Better Extended Editor for Portal 2'),
    is_splash=True,
)
