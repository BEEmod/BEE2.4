"""Displays a loading menu while packages, palettes, etc are being loaded.

All the actual display is done in a subprocess, so we can allow interaction while
the main process is busy loading.

The id() of the main-process object is used to identify loadscreens.
"""
from __future__ import annotations

from typing import Collection, Iterable, Set, Tuple, List, TypeVar, cast, Any, Type
from types import TracebackType
from tkinter import commondialog
from weakref import WeakSet
import contextlib
import multiprocessing
import time

import attrs
import srctools.logger

import config.gen_opts
from app import localisation
import config
from transtoken import TransToken
import utils


# Keep a reference to all loading screens, so we can close them globally.
_ALL_SCREENS = cast(Set['LoadScreen'], WeakSet())

# For each loadscreen ID, record if the cancel button was pressed. We then raise
# Cancelled upon the next interaction with it to stop operation.
_SCREEN_CANCEL_FLAG: Set[int] = set()

# Pairs of pipe ends we use to send data to the daemon and vice versa.
# DAEMON is sent over to the other process.
_PIPE_MAIN_REC, _PIPE_DAEMON_SEND = multiprocessing.Pipe(duplex=False)
_PIPE_DAEMON_REC, _PIPE_MAIN_SEND = multiprocessing.Pipe(duplex=False)
# Another specifically for the logging window.
_PIPE_LOG_MAIN_REC, _PIPE_LOG_DAEMON_SEND = multiprocessing.Pipe(duplex=False)

T = TypeVar('T')


class Cancelled(BaseException):
    """Raised when the user cancels the loadscreen."""
    # TODO: Replace with Trio's cancellation.


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


def close_all() -> None:
    """Hide all loadscreen windows."""
    for screen in _ALL_SCREENS:
        screen.reset()


def show_main_loader(is_compact: bool) -> None:
    """Special function, which sets the splash screen compactness."""
    _PIPE_MAIN_SEND.send(('set_is_compact', id(main_loader), (is_compact, )))
    main_loader.show()


def set_force_ontop(ontop: bool) -> None:
    """Set whether screens will be forced on top."""
    _PIPE_MAIN_SEND.send(('set_force_ontop', None, ontop))


@contextlib.contextmanager
def suppress_screens() -> Any:
    """A context manager to suppress loadscreens while the body is active."""
    active = []
    for screen in _ALL_SCREENS:
        if not screen.active:
            continue
        screen.suppress()
        active.append(screen)
    try:
        yield
    finally:
        for screen in active:
            screen.unsuppress()


# Patch various tk windows to hide loading screens while they are open.
# Messageboxes, file dialogs and colorchooser all inherit from Dialog,
# so patching .show() will fix them all.
# contextlib managers can also be used as decorators.
commondialog.Dialog.show = suppress_screens()(commondialog.Dialog.show)  # type: ignore


class LoadScreen:
    """LoadScreens show a loading screen for items.

    stages should be (id, title) pairs for each screen stage.
    Each stage can be stepped independently, referenced by the given ID.
    The title can be blank.
    """

    def __init__(
        self,
        *stages: Tuple[str, TransToken],
        title_text: TransToken,
        is_splash: bool = False,
    ) -> None:
        # active determines whether the screen is on, and if False stops most
        # functions from doing anything
        self.active = False
        self._time = 0.0
        self.stage_ids: Set[str] = set()
        self.stage_labels: List[TransToken] = []
        self.title = title_text

        init: List[Tuple[str, str]] = []
        for st_id, title in stages:
            init.append((st_id, str(title)))
            self.stage_labels.append(title)
            self.stage_ids.add(st_id)

        # Order the daemon to make this screen. We pass translated text in for the splash screen.
        self._send_msg('init', is_splash, str(title_text), init)
        _ALL_SCREENS.add(self)

    def __enter__(self) -> 'LoadScreen':
        """LoadScreen can be used as a context manager.

        Inside the block, the screen will be visible. Cancelling will exit
        to the end of the with block.
        """
        self.show()
        return self

    def __exit__(
        self,
        exc_type: Type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> bool:
        """Hide the loading screen. If the Cancelled exception was raised, swallow that.
        """
        self.reset()
        return exc_type is Cancelled

    def _send_msg(self, command: str, *args: Any) -> None:
        """Send a message to the daemon."""
        _PIPE_MAIN_SEND.send((command, id(self), args))
        # Check the messages coming back as well.
        while _PIPE_MAIN_REC.poll():
            arg: Any
            command, arg = _PIPE_MAIN_REC.recv()
            if command == 'main_set_compact':
                # Save the compact state to the config.
                conf = config.APP.get_cur_conf(config.gen_opts.GenOptions)
                config.APP.store_conf(attrs.evolve(conf, compact_splash=arg))
            elif command == 'cancel':
                # Mark this loadscreen as cancelled.
                _SCREEN_CANCEL_FLAG.add(arg)
            else:
                raise ValueError('Bad command from daemon: ' + repr(command))

        # If the flag was set for us, raise an exception - the loading thing
        # will then stop.
        if id(self) in _SCREEN_CANCEL_FLAG:
            _SCREEN_CANCEL_FLAG.discard(id(self))
            LOGGER.info('User cancelled loading screen.')
            raise Cancelled

    def set_length(self, stage: str, num: int) -> None:
        """Set the maximum value for the specified stage."""
        if stage not in self.stage_ids:
            raise KeyError(f'"{stage}" not valid for {self.stage_ids}!')
        self._send_msg('set_length', stage, num)

    def step(self, stage: str, disp_name: object = '') -> None:
        """Increment the specified stage."""
        if stage not in self.stage_ids:
            raise KeyError(f'"{stage}" not valid for {self.stage_ids}!')
        cur = time.perf_counter()
        diff = cur - self._time
        if diff > 0.1:
            LOGGER.debug('{}: {!r} = {:.3}s', stage, disp_name, diff)
        self._time = cur
        self._send_msg('step', stage)

    def skip_stage(self, stage: str) -> None:
        """Skip over this stage of the loading process."""
        if stage not in self.stage_ids:
            raise KeyError(f'"{stage}" not valid for {self.stage_ids}!')
        self._time = time.perf_counter()
        self._send_msg('skip_stage', stage)

    def stage_iterate(self, stage: str, seq: Collection[T]) -> Iterable[T]:
        """Tie the progress of a stage to a sequence of some kind."""
        self.set_length(stage, len(seq))
        for item in seq:
            yield item
            self.step(stage, item)

    def show(self) -> None:
        """Display the loading screen."""
        self.active = True
        self._time = time.perf_counter()
        # Translate and send these across now.
        self._send_msg('show', str(self.title), list(map(str, self.stage_labels)))

    def reset(self) -> None:
        """Hide the loading screen and reset all the progress bars."""
        self.active = False
        self._send_msg('reset')

    def destroy(self) -> None:
        """Permanently destroy this screen and cleanup."""
        self.active = False
        self._send_msg('destroy')
        _ALL_SCREENS.remove(self)

    def suppress(self) -> None:
        """Temporarily hide the screen."""
        self.active = False
        self._send_msg('hide')

    def unsuppress(self) -> None:
        """Undo temporarily hiding the screen."""
        self.active = True
        self._send_msg('show', str(self.title), list(map(str, self.stage_labels)))


def shutdown() -> None:
    """Instruct the daemon process to shut down."""
    try:
        _PIPE_MAIN_SEND.send(('quit_daemon', None, None))
    except BrokenPipeError:  # Already quit, don't care.
        pass


@localisation.add_callback(call=False)
def _update_translations() -> None:
    """Update the translations."""
    _PIPE_MAIN_SEND.send((
        'update_translations', 0,
        {key: str(tok) for key, tok in TRANSLATIONS.items()},
    ))


_BG_PROC: multiprocessing.Process | None = None


def start_daemon() -> None:
    """Spawn the deamon process."""
    global _BG_PROC
    if _BG_PROC is not None:
        raise ValueError('Daemon already started!')

    # Initialise the daemon.
    _BG_PROC = multiprocessing.Process(
        target=utils.run_bg_daemon,
        args=(
            _PIPE_DAEMON_SEND,
            _PIPE_DAEMON_REC,
            _PIPE_LOG_DAEMON_SEND,
            # Convert and pass translation strings.
            {key: str(tok) for key, tok in TRANSLATIONS.items()},
        ),
        name='bg_daemon',
        daemon=True,
    )
    _BG_PROC.start()

main_loader = LoadScreen(
    ('PAK', TransToken.ui('Packages')),
    ('OBJ', TransToken.ui('Loading Objects')),
    ('UI', TransToken.ui('Initialising UI')),
    title_text=TransToken.ui('Better Extended Editor for Portal 2'),
    is_splash=True,
)
