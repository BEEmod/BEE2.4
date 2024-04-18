"""The package containg all UI code."""
from __future__ import annotations
from typing import Any, Awaitable, Callable, TypeVar, Generic, overload

from typing_extensions import TypeVarTuple, Unpack
from types import TracebackType
import tkinter as tk

from trio_util import AsyncBool
import trio

import utils

# The nursery where UI tasks etc are run in.
_APP_NURSERY: trio.Nursery | None = None
# This is quit to exit the sleep_forever(), beginning the shutdown process.
_APP_QUIT_SCOPE = trio.CancelScope()
T = TypeVar("T")
PosArgsT = TypeVarTuple('PosArgsT')


def quit_app() -> None:
    """Quit the application."""
    _APP_QUIT_SCOPE.cancel()


# TODO: Only required until we remove the vars from below.
import ui_tk


# noinspection PyBroadException
def on_error(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Run when the application crashes. Display to the user, log it, and quit."""
    # We don't want this to fail, so import everything here, and wrap in
    # except Exception.
    import traceback
    err = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Grab and release the grab so nothing else can block the error message.
    try:
        from ui_tk import TK_ROOT
        TK_ROOT.grab_set_global()
        TK_ROOT.grab_release()

        # Append traceback to the clipboard.
        TK_ROOT.clipboard_append(err)
    except Exception:
        pass

    if not issubclass(exc_type, Exception):
        # It's subclassing BaseException (KeyboardInterrupt, SystemExit),
        # so ignore the error.
        return

    # Put it onscreen.
    try:
        from tkinter import messagebox
        from transtoken import TransToken
        # Use directly, so we don't actually need the tk_tools dependency.
        messagebox.showerror(
            title=str(
                TransToken.ui('BEEMOD {version} Error!')
                .format(version=utils.BEE_VERSION)
            ),
            message=str(TransToken.ui(
                'An error occurred: \n{err}\n\n'
                'This has been copied to the clipboard.'
            ).format(err=err)),
        )
    except Exception:
        pass

    try:
        import config
        import attrs
        # Try to turn on the logging window for next time...
        conf = config.APP.get_cur_conf(config.gen_opts.GenOptions)
        config.APP.store_conf(attrs.evolve(
            conf,
            show_log_win=True,
            log_win_level='DEBUG',
        ))
        config.APP.write_file(config.APP_LOC)
    except Exception:
        # Ignore failures...
        pass


def background_run(
    func: Callable[[Unpack[PosArgsT]], Awaitable[object]],
    /, *args: Unpack[PosArgsT],
    name: str | None = None,
) -> None:
    """When the UI is live, run this specified task in app-global nursery."""
    if _APP_NURSERY is None:
        raise ValueError('App nursery has not started.')
    _APP_NURSERY.start_soon(func, *args, name=name)


async def background_start(
    func: Callable[..., Awaitable[object]], /,
    *args: object,
    name: str | None = None,
) -> Any:
    """When the UI is live, start this specified task and return when started() is called."""
    if _APP_NURSERY is None:
        raise ValueError('App nursery has not started.')
    return await _APP_NURSERY.start(func, *args, name=name)


# Various configuration booleans.
LAUNCH_AFTER_EXPORT = tk.BooleanVar(value=True, name='OPT_launch_after_export')
DEV_MODE = tk.BooleanVar(value=utils.DEV_MODE, name='OPT_development_mode')


class EdgeTrigger(Generic[Unpack[PosArgsT]]):
    """A variation on a Trio Event which can only be tripped while a task is waiting for it.

    When tripped, arbitrary arguments can be passed along as well.

    The ready attribute is updated to reflect whether trigger() can be called. The value should
    not be set.
    """
    def __init__(self) -> None:
        self._event: trio.Event | None = None
        self._result: tuple[Unpack[PosArgsT]] | None = None
        self.ready = AsyncBool()

    @overload
    async def wait(self: EdgeTrigger[()]) -> None: ...
    @overload
    async def wait(self: EdgeTrigger[T]) -> T: ...
    @overload  # Ignore spurious warnings about the above overloads being impossible.
    async def wait(self) -> tuple[Unpack[PosArgsT]]: ...  # type: ignore[misc]
    async def wait(self) -> T | tuple[Unpack[PosArgsT]] | None:
        """Wait for the trigger to fire, then return the parameters.

        Only one task can wait at a time.
        """
        if self._event is not None:
            raise ValueError('Only one task may wait() at a time!')
        try:
            self._event = trio.Event()
            self._result = None
            self.ready.value = True
            await self._event.wait()
            # TODO: Rewrite with match post 3.8
            assert self._result is not None
            if len(self._result) == 1:
                return self._result[0]
            elif len(self._result) == 0:
                return None
            else:
                return self._result
        finally:
            self._event = self._result = None
            self.ready.value = False

    def trigger(self, *args: Unpack[PosArgsT]) -> None:
        """Wake up a task blocked on wait(), and pass arguments along to it.

        Raises a ValueError if no task is blocked.
        If triggered multiple times, the last result wins.
        """
        if self._event is None:
            raise ValueError('No task is blocked on wait()!')
        self._result = args
        self._event.set()
