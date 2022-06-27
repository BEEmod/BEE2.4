"""Displays a loading menu while packages, palettes, etc are being loaded.

All the actual display is done in a subprocess, so we can allow interaction while
the main process is busy loading.

The id() of the main-process object is used to identify loadscreens.
"""
from types import TracebackType
from tkinter import commondialog
from weakref import WeakSet
import contextlib
import multiprocessing
import time

import attrs
import srctools.logger

from app import logWindow
import config
from localisation import gettext
import utils

from typing import Set, Tuple, cast, Any, Type


# Keep a reference to all loading screens, so we can close them globally.
_ALL_SCREENS = cast(Set['LoadScreen'], WeakSet())

# For each loadscreen ID, record if the cancel button was pressed. We then raise
# Cancelled upon the next interaction with it to stop operation.
_SCREEN_CANCEL_FLAG: Set[int] = set()

# Pairs of pipe ends we use to send data to the daemon and vice versa.
# DAEMON is sent over to the other process.
_PIPE_MAIN_REC, _PIPE_DAEMON_SEND = multiprocessing.Pipe(duplex=False)
_PIPE_DAEMON_REC, _PIPE_MAIN_SEND = multiprocessing.Pipe(duplex=False)


class Cancelled(SystemExit):
    """Raised when the user cancels the loadscreen."""


LOGGER = srctools.logger.get_logger(__name__)


def close_all() -> None:
    """Hide all loadscreen windows."""
    for screen in _ALL_SCREENS:
        screen.reset()


def show_main_loader(is_compact: bool) -> None:
    """Special function, which sets the splash screen compactness."""
    _PIPE_MAIN_SEND.send(('set_is_compact', id(main_loader), (is_compact, )))
    main_loader.show()


def set_force_ontop(ontop: bool) -> None:
    """Set whether or not screens will be forced on top."""
    # The loadscreen ID is ignored for this, it applies to all of them.
    # But we know this one exists.
    main_loader._send_msg('set_force_ontop', ontop)


@contextlib.contextmanager
def suppress_screens() -> Any:
    """A context manager to suppress loadscreens while the body is active."""
    active = []
    for screen in _ALL_SCREENS:
        if not screen.active:
            continue
        screen.suppress()
        active.append(screen)

    yield

    for screen in active:
        screen.unsuppress()


# Patch various tk windows to hide loading screens while they're are open.
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
        *stages: Tuple[str, str],
        title_text: str,
        is_splash: bool=False,
    ):
        self.active = False
        self._time = 0.0
        self.stage_ids = {st_id for st_id, title in stages}
        # active determines whether the screen is on, and if False stops most
        # functions from doing anything

        _ALL_SCREENS.add(self)

        # Order the daemon to make this screen.
        self._send_msg('init', is_splash, title_text, stages)

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
    ) -> None:
        """Hide the loading screen, and passthrough execptions.
        """
        self.reset()

    def _send_msg(self, command: str, *args: Any) -> None:
        """Send a message to the daemon."""
        _PIPE_MAIN_SEND.send((command, id(self), args))
        # Check the messages coming back as well.
        while _PIPE_MAIN_REC.poll():
            arg: Any
            command, arg = _PIPE_MAIN_REC.recv()
            if command == 'main_set_compact':
                # Save the compact state to the config.
                conf = config.get_cur_conf(config.GenOptions)
                config.store_conf(attrs.evolve(conf, compact_splash=arg))
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

    def step(self, stage: str, disp_name: str='') -> None:
        """Increment the specified stage."""
        if stage not in self.stage_ids:
            raise KeyError(f'"{stage}" not valid for {self.stage_ids}!')
        cur = time.perf_counter()
        diff = cur - self._time
        if diff > 0.1:
            LOGGER.debug('{}: "{}" = {:.3}s', stage, disp_name, diff)
        self._time = cur
        self._send_msg('step', stage)

    def skip_stage(self, stage: str) -> None:
        """Skip over this stage of the loading process."""
        if stage not in self.stage_ids:
            raise KeyError(f'"{stage}" not valid for {self.stage_ids}!')
        self._time = time.perf_counter()
        self._send_msg('skip_stage', stage)

    def show(self) -> None:
        """Display the loading screen."""
        self.active = True
        self._time = time.perf_counter()
        self._send_msg('show')

    def reset(self) -> None:
        """Hide the loading screen and reset all the progress bars."""
        self.active = False
        self._send_msg('reset')

    def destroy(self):
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
        self._send_msg('show')


def shutdown() -> None:
    """Instruct the daemon process to shutdown."""
    try:
        _PIPE_MAIN_SEND.send(('quit_daemon', None, None))
    except BrokenPipeError:  # Already quit, don't care.
        pass

# Initialise the daemon.
# noinspection PyProtectedMember
BG_PROC = multiprocessing.Process(
    target=utils.run_bg_daemon,
    args=(
        _PIPE_DAEMON_SEND,
        _PIPE_DAEMON_REC,
        logWindow.PIPE_DAEMON_SEND,
        logWindow.PIPE_DAEMON_REC,
        # Pass translation strings.
        {
            'skip': gettext('Skipped!'),
            'version': gettext('Version: ') + utils.BEE_VERSION,
            'cancel': gettext('Cancel'),
            'clear': gettext('Clear'),
            'copy': gettext('Copy'),
            'log_show': gettext('Show:'),
            'log_title': gettext('Logs - {}').format(utils.BEE_VERSION),
            'level_text': [
                gettext('Debug messages'),
                gettext('Default'),
                gettext('Warnings Only'),
            ],
        }
    ),
    name='bg_daemon',
    daemon=True,
)
BG_PROC.start()

main_loader = LoadScreen(
    ('PAK', gettext('Packages')),
    ('OBJ', gettext('Loading Objects')),
    ('UI', gettext('Initialising UI')),
    title_text=gettext('Better Extended Editor for Portal 2'),
    is_splash=True,
)
