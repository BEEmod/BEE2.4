"""The package containg all UI code."""
import tkinter as tk
from types import TracebackType, new_class
from typing import Awaitable, Callable, Optional, Type, TypeVar, overload, Generic

import utils
import trio  # Import first, so it monkeypatches traceback before us.

# We must always have one Tk object, and it needs to be constructed
# before most of TKinter will function. So doing it here does it first.
TK_ROOT = tk.Tk()
TK_ROOT.withdraw()  # Hide the window until everything is loaded.

# The nursery where UI tasks etc are run in.
_APP_NURSERY: Optional[trio.Nursery] = None


if '__class_getitem__' not in vars(tk.Event):
    # Patch in it being generic, by replacing it with a copy that subclasses Generic.
    _W_co = TypeVar("_W_co", covariant=True, bound=tk.Misc)
    _W_co.__module__ = 'tkinter'
    tk.Event = new_class(
        'Event', (Generic[_W_co], ),
        exec_body=lambda ns: ns.update(vars(tk.Event)),
    )

def _run_main_loop(*args, **kwargs) -> None:
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
    exc_tb: Optional[TracebackType],
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
    exc_tb: TracebackType,
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


# TODO: Remove once mypy supports TypeVarTuple.
# BGRunArgsT = TypeVarTuple('BGRunArgsT')
T1 = TypeVar('T1')
T2 = TypeVar('T2')
T3 = TypeVar('T3')
T4 = TypeVar('T4')
T5 = TypeVar('T5')

@overload
def background_run(
    func: Callable[[], Awaitable[object]],
    /, *, name: Optional[str] = None,
) -> None: ...
@overload
def background_run(
    func: Callable[[T1], Awaitable[object]],
    arg1: T1,
    /, *, name: Optional[str] = None,
) -> None: ...
@overload
def background_run(
    func: Callable[[T1, T2], Awaitable[object]],
    arg1: T1, arg2: T2,
    /, *, name: Optional[str] = None,
) -> None: ...
@overload
def background_run(
    func: Callable[[T1, T2, T3], Awaitable[object]],
    arg1: T1, arg2: T2, arg3: T3,
    /, *, name: Optional[str] = None,
) -> None: ...
@overload
def background_run(
    func: Callable[[T1, T2, T3, T4], Awaitable[object]],
    arg1: T1, arg2: T2, arg3: T3, arg4: T4,
    /, *, name: Optional[str] = None,
) -> None: ...
@overload
def background_run(
    func: Callable[[T1, T2, T3, T4, T5], Awaitable[object]],
    arg1: T1, arg2: T2, arg3: T3, arg4: T4, arg5: T5,
    /, *, name: Optional[str] = None,
) -> None: ...

def background_run(
    # func: Callable[[Unpack[BGRunArgsT]], Awaitable[object]], /,
    # *args: Unpack[BGRunArgsT],
    func: Callable[..., Awaitable[object]],
    /, *args: object, name: Optional[str] = None,
) -> None:
    """When the UI is live, begin this specified task."""
    if _APP_NURSERY is None:
        raise ValueError('App nursery has not started.')
    _APP_NURSERY.start_soon(func, *args, name=name)


# Various configuration booleans.
LAUNCH_AFTER_EXPORT = tk.BooleanVar(value=True, name='OPT_launch_after_export')
DEV_MODE = tk.BooleanVar(value=utils.DEV_MODE, name='OPT_development_mode')
