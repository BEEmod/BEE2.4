"""The package containg all UI code."""
from __future__ import annotations
from typing import Any, Protocol, overload
from typing_extensions import deprecated

from abc import abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from contextlib import aclosing
from enum import Enum
from types import TracebackType

from transtoken import TransToken
from trio_util import AsyncBool, AsyncValue
from srctools.logger import get_logger
import trio

import utils


LOGGER = get_logger(__name__)
# The nursery where UI tasks etc are run in.
_APP_NURSERY: trio.Nursery | None = None
# This is quit to exit the sleep_forever(), beginning the shutdown process.
_APP_QUIT_SCOPE = trio.CancelScope()

# We use this to activate various features only useful to package/app devs.
DEV_MODE = AsyncBool(value=utils.DEV_MODE)

# The application icon.
ICO_PATH = utils.bins_path('BEE2.ico')


if utils.WIN:
    import ctypes
    # Use Windows APIs to tell the taskbar to group us as our own program,
    # not with python.exe. Then our icon will apply, and also won't group
    # with other scripts.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'BEEMOD.application',
        )
    except (AttributeError, OSError, ValueError):
        pass  # It's not too bad if it fails.


def quit_app() -> None:
    """Quit the application."""
    _APP_QUIT_SCOPE.cancel()


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
    # TODO: Move this out of here?
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


@deprecated('Pass the core nursery down instead.')
def background_run[*Args](
    func: Callable[[*Args], Awaitable[object]],
    /, *args: *Args,
    name: str | None = None,
) -> None:
    """When the UI is live, run this specified task in app-global nursery."""
    if _APP_NURSERY is None:
        raise ValueError('App nursery has not started.')
    _APP_NURSERY.start_soon(func, *args, name=name)


@deprecated('Pass the core nursery down instead.')
async def background_start(
    func: Callable[..., Awaitable[object]], /,
    *args: object,
    name: str | None = None,
) -> Any:
    """When the UI is live, start this specified task and return when started() is called."""
    if _APP_NURSERY is None:
        raise ValueError('App nursery has not started.')
    return await _APP_NURSERY.start(func, *args, name=name)


class CannotTrigger(Exception):
    """Raised when an EdgeTrigger tried to trigger but no task was available."""


class EdgeTrigger[*Args]:
    """A variation on a Trio Event which can only be tripped while a task is waiting for it.

    When tripped, arbitrary arguments can be passed along as well.

    The ready attribute is updated to reflect whether trigger() can be called. The value should
    not be set.
    """
    def __init__(self) -> None:
        self._event: trio.Event | None = None
        self._result: tuple[*Args] | None = None
        self.ready = AsyncBool()

    @overload
    async def wait(self: EdgeTrigger[()]) -> None: ...  # type: ignore[overload-overlap]
    @overload
    async def wait[T](self: EdgeTrigger[T]) -> T: ...
    @overload  # Ignore spurious warnings about the above overloads being impossible.
    async def wait(self) -> tuple[*Args]: ...  # type: ignore[misc]
    async def wait(self) -> object:
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
            match self._result:
                case None:
                    raise AssertionError(f'{self!r} was not set!')
                case []:
                    return None
                case [value]:
                    return value
                case multiple:
                    return multiple
        finally:
            self._event = self._result = None
            self.ready.value = False

    def trigger(self, *args: *Args) -> None:
        """Wake up a task blocked on wait(), and pass arguments along to it.

        Raises a ValueError if no task is blocked.
        If triggered multiple times, the last result wins.
        """
        if self._event is None:
            raise CannotTrigger('No task is blocked on wait()!')
        self._result = args
        self._event.set()

    def maybe_trigger(self: EdgeTrigger[()]) -> None:
        """Wake up a task blocked on wait(), but do nothing if not currently blocked.

        This is only available if no arguments are specified, since then all calls are identical.
        """
        if self._event is not None:
            self._result = ()
            self._event.set()
        else:
            LOGGER.debug('EdgeTrigger.maybe_trigger() ignored!')


class HasCurrentValue[T](Protocol):
    """Protocol for a class with an AsyncValue."""
    @property
    def current(self) -> AsyncValue[T]: ...


class WidgetCache[Widget]:
    """Stores unused widgets so they can be recyled later."""
    def __init__(
        self,
        create_func: Callable[[int], Widget],
        hide_func: Callable[[Widget], object],
    ) -> None:
        self.create_func = create_func
        self.hide_func = hide_func
        self._next_id = 1  # Allows unique widget IDs.
        # Widgets currently in use.
        self._placed: list[Widget] = []
        # Widgets that were previously placed.
        self._was_visible: list[Widget] = []
        # Widgets that were placed and are now hidden.
        self._hidden: list[Widget] = []

    @property
    def placed(self) -> Sequence[Widget]:
        """The widgets currently placed."""
        return self._placed

    def reset(self) -> None:
        """Start a new batch of widgets."""
        self._was_visible += self._placed
        self._placed.clear()

    def fetch(self) -> Widget:
        """Fetch an existing widget or create one if necessary."""
        try:
            # Prefer reusing already visible ones, since they have
            # to be changed anyway.
            widget = self._was_visible.pop()
        except IndexError:
            try:
                widget = self._hidden.pop()
            except IndexError:
                widget = self.create_func(self._next_id)
                self._next_id += 1

        self._placed.append(widget)
        return widget

    def hide_unused(self) -> None:
        """Hide all widgets that aren't used in this batch."""
        for wid in self._was_visible:
            self.hide_func(wid)
        self._hidden += self._was_visible
        self._was_visible.clear()

    def hide_all(self) -> None:
        """Hide all widgets completely, resetting the batch."""
        self.reset()
        self.hide_unused()


class ReflowWindow:
    """Base class which handles the logic for a window that reflows contents to fit."""
    # Event set whenever the items need to be redrawn/re-flowed.
    items_dirty: trio.Event
    # The current number of columns per row, always >= 1.
    column_count: int

    def __init__(self) -> None:
        super().__init__()
        self.items_dirty = trio.Event()
        self.column_count = 1

    async def refresh_items_task(self) -> None:
        """Calls refresh_items whenever they're marked dirty."""
        while True:
            await self.items_dirty.wait()
            self.items_dirty = trio.Event()
            await utils.run_as_task(self._ui_reposition_items)

    def evt_window_resized(self, event: object) -> None:
        """Handle updating items, if the window width has changed."""
        columns = self._ui_calc_columns()
        if columns < 1:
            columns = 1  # We got way too small, prevent division by zero
        if columns != self.column_count:
            self.column_count = columns
            self.items_dirty.set()

    @abstractmethod
    def _ui_calc_columns(self) -> int:
        """Calculate the number of items that can be displayed per row."""

    @abstractmethod
    async def _ui_reposition_items(self) -> None:
        """Reposition all the items to fit in the current geometry.

        Called whenever items change or the window is resized.
        """
        raise NotImplementedError


class BaseEnumButton[Button, EnumT: Enum]:
    """Provides a set of buttons for toggling between enum values.

    This is bound to the provided AsyncValue, updating it when changed.
    """
    _buttons: dict[EnumT, Button]
    current: AsyncValue[EnumT]

    class EventFunc(Protocol):
        """Event functions ignore the event."""
        def __call__(self, event: object = ..., /) -> None:
            pass

    def __init__(
        self,
        current: AsyncValue[EnumT],
        values: Sequence[tuple[EnumT, TransToken]],
    ) -> None:
        self.current = current
        self._buttons = {}

        for ind, (val, label) in enumerate(values):
            btn = self._ui_create(ind, label, self._pressed_func(val))
            self._buttons[val] = btn

        if current.value not in self._buttons:
            raise ValueError(f'Default value {current.value!r} not present in {values!r}!')

        if len(self._buttons) != len(values):
            raise ValueError(f'No duplicates allowed, got: {values!r}')

    def _pressed_func(self, value: EnumT) -> BaseEnumButton.EventFunc:
        """Create the function for a button."""
        def handler(evt: object = None) -> None:
            """Handle changes."""
            self.current.value = value
            # Re-press the button, to ensure it doesn't toggler itself if pressed twice.
            self._ui_set(self._buttons[value], True)
        return handler

    async def task(self) -> None:
        """Task which must be run to update the button state."""
        async with aclosing(self.current.eventual_values()) as agen:
            async for chosen in agen:
                for val, button in self._buttons.items():
                    self._ui_set(button, val is chosen)

    @abstractmethod
    def _ui_create(self, ind: int, label: TransToken, func: BaseEnumButton.EventFunc) -> Button:
        """Create a button."""
        raise NotImplementedError

    @abstractmethod
    def _ui_set(self, button: Button, pressed: bool, /) -> None:
        """Set the current state for a button."""
        raise NotImplementedError
