"""Various utilities for async code."""
from __future__ import annotations
from typing import Protocol, overload
from collections.abc import Awaitable, AsyncGenerator, Callable
import contextlib
import os

from srctools import Keyvalues
from srctools.filesys import File, FileSystem
from srctools.logger import get_logger
from trio_util import AsyncBool, AsyncValue
import trio.lowlevel
import aioresult


LOGGER = get_logger(__name__)


class CannotTrigger(Exception):
    """Raised when an EdgeTrigger tried to trigger but no task was available."""


class EdgeTrigger[*Args]:
    """A variation on a Trio Event which can only be tripped while a task is waiting for it.

    When tripped, arbitrary arguments can be passed along as well.

    The ready attribute is updated to reflect whether trigger() can be called. The value should
    not be set.
    """
    def __init__(self) -> None:
        self._lot = trio.lowlevel.ParkingLot()
        self._result: tuple[*Args] | None = None
        self.ready = AsyncBool()

    @overload
    async def wait(self: EdgeTrigger[()]) -> None: ...  # type: ignore[overload-overlap]
    @overload
    async def wait[T](self: EdgeTrigger[T]) -> T: ...
    @overload  # Ignore spurious warnings about the above overloads being impossible.
    async def wait(self) -> tuple[*Args]: ...  # type: ignore[overload-cannot-match]
    async def wait(self) -> object:
        """Wait for the trigger to fire, then return the parameters.

        Only one task can wait at a time.
        """
        if self._lot:
            raise ValueError('Only one task may wait() at a time!')
        try:
            self._result = None
            self.ready.value = True
            await self._lot.park()
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
            self._result = None
            self.ready.value = False

    def trigger(self, *args: *Args) -> None:
        """Wake up a task blocked on wait(), and pass arguments along to it.

        Raises a ValueError if no task is blocked.
        If triggered multiple times, the last result wins.
        """
        # Don't check the lock itself, another trigger might have already woken.
        if not self.ready.value:
            raise CannotTrigger('No task is blocked on wait()!')
        self._result = args
        self._lot.unpark()

    def maybe_trigger(self: EdgeTrigger[()]) -> None:
        """Wake up a task blocked on wait(), but do nothing if not currently blocked.

        This is only available if no arguments are specified, since then all calls are identical.
        """
        if self.ready.value:
            self._result = ()
            self._lot.unpark()
        else:
            LOGGER.debug('EdgeTrigger.maybe_trigger() ignored!')


class HasCurrentValue[T](Protocol):
    """Protocol for a class with an AsyncValue."""
    @property
    def current(self) -> AsyncValue[T]: ...


def sync_result[*Args, SyncResultT](
    nursery: trio.Nursery,
    func: Callable[[*Args], SyncResultT],
    /, *args: *Args,
    abandon_on_cancel: bool = False,
    limiter: trio.CapacityLimiter | None = None,
) -> aioresult.ResultCapture[SyncResultT]:
    """Wrap a sync task, using to_thread.run_sync()."""
    async def task() -> SyncResultT:
        """Run in a thread."""
        return await trio.to_thread.run_sync(
            func, *args,
            abandon_on_cancel=abandon_on_cancel,
            limiter=limiter,
        )

    return aioresult.ResultCapture.start_soon(nursery, task)


def acompose[**ParamsT, ResultT](
    func: Callable[ParamsT, Awaitable[ResultT]],
    on_completed: Callable[[ResultT], object],
) -> Callable[ParamsT, Awaitable[None]]:
    """Compose an awaitable function with a sync function that recieves the result."""
    async def task(*args: ParamsT.args, **kwargs: ParamsT.kwargs) -> None:
        """Run the func, then call on_completed on the result."""
        res = await func(*args, **kwargs)
        on_completed(res)
    return task


def _parse_kv1_path_worker(path: str | os.PathLike[str], encoding: str) -> Keyvalues:
    """Parse in the background."""
    with open(path, encoding=encoding) as f:
        return Keyvalues.parse(f, periodic_callback=trio.from_thread.check_cancelled)


def _parse_kv1_fsys_worker[FSys: FileSystem](
    fsys: FSys, file: str | File[FSys], encoding: str,
) -> Keyvalues:
    """Parse in the background."""
    return fsys.read_kv1(file, encoding, periodic_callback=trio.from_thread.check_cancelled)


async def parse_kv1_path(path: str | os.PathLike[str], encoding: str = 'utf8') -> Keyvalues:
    """Parse a keyvalues file from a path."""

    return await trio.to_thread.run_sync(
        _parse_kv1_path_worker, path, encoding,
        abandon_on_cancel=True,
    )


async def parse_kv1_fsys[FSys: FileSystem](
    fsys: FSys, file: str | File[FSys], *,
    encoding: str = 'utf8',
) -> Keyvalues:
    """Parse a keyvalues file from a filesystem file."""
    return await trio.to_thread.run_sync(
        _parse_kv1_fsys_worker, fsys, file, encoding,
        abandon_on_cancel=True,
    )


async def run_as_task[*Args](
    func: Callable[[*Args], Awaitable[object]],
    *args: *Args,
) -> None:
    """Run the specified function inside a nursery.

    This ensures it gets detected by Trio's instrumentation as a subtask.
    """
    async with trio.open_nursery() as nursery:  # noqa: ASYNC112
        nursery.start_soon(func, *args)


@contextlib.asynccontextmanager
async def iterval_cancelling[T](value: AsyncValue[T]) -> AsyncGenerator[T]:
    """Yield the current AsyncValue value, then cancel if the value changes.

    If the block completes, wait for the value to change or some other cancellation.
    Use like so:
    while True:
        async with iterval_cancelling(some_value) as value:
            ...
    """
    async def wait() -> None:
        """Wait for a change, then cancel."""
        await value.wait_transition()
        nursery.cancel_scope.cancel()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait)
        yield value.value
        # If we get here, the with block was completed. Wait for change or cancellation.
        await trio.sleep_forever()
