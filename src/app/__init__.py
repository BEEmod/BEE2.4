"""The package containg all UI code."""
from typing import Any, Awaitable, Callable, Tuple, Type, TypeVar, Generic, Union, overload

from typing_extensions import TypeVarTuple, Unpack
from types import TracebackType, new_class
import tkinter as tk

from trio_util import AsyncBool
import trio

import utils

# We must always have one Tk object, and it needs to be constructed
# before most of TKinter will function. So doing it here does it first.
TK_ROOT = tk.Tk()
TK_ROOT.withdraw()  # Hide the window until everything is loaded.

# The nursery where UI tasks etc are run in.
_APP_NURSERY: Union[trio.Nursery, None] = None
# This is quit to exit the sleep_forever(), beginning the shutdown process.
_APP_QUIT_SCOPE = trio.CancelScope()
T = TypeVar("T")
PosArgsT = TypeVarTuple('PosArgsT')


def quit_app() -> None:
    """Quit the application."""
    _APP_QUIT_SCOPE.cancel()

TK_ROOT.protocol("WM_DELETE_WINDOW", quit_app)

if '__class_getitem__' not in vars(tk.Event):
    # Patch in it being generic, by replacing it with a copy that subclasses Generic.
    _W_co = TypeVar("_W_co", covariant=True, bound=tk.Misc)
    _W_co.__module__ = 'tkinter'
    tk.Event = new_class(  # type: ignore
        'Event', (Generic[_W_co], ),
        exec_body=lambda ns: ns.update({
            name: getattr(tk.Event, name)
            for name in vars(tk.Event)
            # Specify the vars to assign, so we don't include things like __dict__ descriptors.
            if name in ['__doc__', '__module__', '__repr__']
        }),
    )


def _run_main_loop(*args: Any, **kwargs: Any) -> None:
    """Allow determining if this is running."""
    global _main_loop_running
    _main_loop_running = True
    _orig_mainloop(*args, **kwargs)


_main_loop_running = False
_orig_mainloop = TK_ROOT.mainloop
TK_ROOT.mainloop = _run_main_loop  # type: ignore[method-assign]
del _run_main_loop


# noinspection PyBroadException
def tk_error(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: Union[TracebackType, None],
) -> None:
    """Log TK errors."""
    # The exception is caught inside the TK code.
    # We don't care about that, so try and move the traceback up
    # one level.
    import logging
    if exc_tb is not None and exc_tb.tb_next:
        exc_tb = exc_tb.tb_next

    logger = logging.getLogger('BEE2')

    try:
        on_error(exc_type, exc_value, exc_tb)
    except Exception:
        logger.exception('Failed to display messagebox:')
        pass

    logger.error(
        msg='Uncaught Tk Exception:',
        exc_info=(exc_type, exc_value, exc_tb),
    )

    if _APP_NURSERY is not None:
        _APP_NURSERY.cancel_scope.cancel()

TK_ROOT.report_callback_exception = tk_error


# noinspection PyBroadException
def on_error(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: Union[TracebackType, None],
) -> None:
    """Run when the application crashes. Display to the user, log it, and quit."""
    # We don't want this to fail, so import everything here, and wrap in
    # except Exception.
    import traceback
    err = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))

    # Grab and release the grab so nothing else can block the error message.
    try:
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
        config.APP.write_file()
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
    await _APP_NURSERY.start(func, *args, name=name)


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
    async def wait(self: 'EdgeTrigger[()]') -> None: ...
    @overload
    async def wait(self: 'EdgeTrigger[T]') -> T: ...
    @overload  # Ignore spurious warnings about the above overloads being impossible.
    async def wait(self) -> Tuple[Unpack[PosArgsT]]: ...  # type: ignore[misc]
    async def wait(self) -> Union[T, Tuple[Unpack[PosArgsT]], None]:
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
