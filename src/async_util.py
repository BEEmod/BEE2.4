"""Various utilities for async code."""
from __future__ import annotations
from typing import Protocol, overload
from typing_extensions import AsyncContextManager

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
import types

from srctools.logger import get_logger
from trio_util import AsyncBool, AsyncValue
import trio
import trio_util
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
        self._event: trio.Event | None = None
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


async def run_as_task[*Args](
    func: Callable[[*Args], Awaitable[object]],
    *args: *Args,
) -> None:
    """Run the specified function inside a nursery.

    This ensures it gets detected by Trio's instrumentation as a subtask.
    """
    async with trio.open_nursery() as nursery:  # noqa: ASYNC112
        nursery.start_soon(func, *args)


class CancelWrapper[T]:
    """Enter a cancel scope, then yield a value. Can be used either async or sync."""
    def __init__(self, value: T, scope: trio.CancelScope) -> None:
        self.value = value
        self.scope = scope

    def __enter__(self) -> T:
        self.scope.__enter__()
        return self.value

    async def __aenter__(self) -> T:
        self.scope.__enter__()
        return self.value

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool | None:
        return self.scope.__exit__(exc_type, exc_val, exc_tb)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool | None:
        return self.scope.__exit__(exc_type, exc_val, exc_tb)


class _IterValCancel[T](AsyncContextManager[AsyncIterator[CancelWrapper[T]], None]):
    def __init__(self, value: trio_util.AsyncValue[T]) -> None:
        self.value = value
        self._agen: AsyncGenerator[T, None] | None = None

    async def __aenter__(self) -> AsyncIterator[CancelWrapper[T]]:
        if self._agen is not None:
            raise RecursionError('Cannot re-enter.')
        self._agen = agen = self.value.eventual_values()
        return self._iterate(agen)

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._agen is not None:
            await self._agen.aclose()

    async def _iterate(
        self, agen: AsyncGenerator[T, None],
    ) -> AsyncIterator[CancelWrapper[T]]:
        scope = trio.CancelScope()
        yield CancelWrapper(await anext(agen), scope)
        async for value in agen:
            scope.cancel()
            scope = trio.CancelScope()
            yield CancelWrapper(value, scope)


def iterval_cancelling[T](
    value: trio_util.AsyncValue[T],
) -> AsyncContextManager[AsyncIterator[CancelWrapper[T]], None]:
    """Iterate over the values produced by an AsyncValue, cancelling the iteration if it changes again.

    Use like so:
    async with iterval_cancelling(some_value) as aiterator:
        async for scope in aiterator:
            [async] with scope as result:
                await use(result)
    """
    return _IterValCancel(value)
