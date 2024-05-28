"""Handle UI 'events' and propagate them to all interested callers.

This allows each UI segment to be less coupled to all other code which
may modify it.

Events are a combination of a specific argument type, and a context
(which may be None). When fired, all callbacks registed with the same
context, and the same type of argument will be called with the arg.

A set of observable collections are provided, which fire off events
whenever they are modified.
"""
from __future__ import annotations
from typing import Any, Generic
from typing_extensions import TypeVarTuple, Unpack

from collections.abc import Callable, Awaitable, Generator
from contextlib import contextmanager
import math

import attrs
import trio
import srctools.logger

__all__ = ['Event']
LOGGER = srctools.logger.get_logger(__name__)
ArgT = TypeVarTuple('ArgT')


@attrs.define(init=False, eq=False)
class Event(Generic[Unpack[ArgT]]):
    """Store functions to be called when an event occurs."""
    callbacks: list[Callable[[Unpack[ArgT]], Awaitable[Any]]]
    last_result: tuple[Unpack[ArgT]] | None = attrs.field(init=False)
    _override: trio.MemorySendChannel[tuple[Unpack[ArgT]]] | None = attrs.field(repr=False)
    _cur_calls: int
    name: str
    log: bool = attrs.field(repr=False)

    def __init__(self, name: str = '') -> None:
        self.name = name or f'<Unnamed {id(self):x}>'
        self.callbacks = []
        self._cur_calls = 0
        self._override = None
        self.log = False
        self.last_result = None

    def register(self, func: Callable[[Unpack[ArgT]], Awaitable[Any]]) -> Callable[[Unpack[ArgT]], Awaitable[Any]]:
        """Register the given function to be called.

        This can be used as a decorator.
        """
        self.callbacks.append(func)
        return func

    async def register_and_prime(self, func: Callable[[Unpack[ArgT]], Awaitable[Any]]) -> None:
        """Register the given function, then immediately call with the last value if present."""
        self.callbacks.append(func)
        if self.last_result is None:
            await trio.sleep(0)  # Checkpoint.
        else:
            await func(*self.last_result)

    async def __call__(self, /, *args: Unpack[ArgT]) -> None:
        """Run the specified event.

        This is re-entrant - if called whilst the same event is already being
        run, the second will be ignored.
        """
        if self.log:
            LOGGER.debug(
                '{}({}) = {}',
                self.name,
                ','.join([repr(x) for x in args]),
                self.callbacks,
            )

        if self._cur_calls and self.last_result is not None:
            last_pos = self.last_result
            if args == last_pos:
                return

        self.last_result = args
        self._cur_calls += 1
        try:
            if self._override is not None:
                await self._override.send(args)
            else:
                async with trio.open_nursery() as nursery:
                    for func in self.callbacks:
                        nursery.start_soon(func, *args)
        finally:
            self._cur_calls -= 1

    def unregister(self, func: Callable[[Unpack[ArgT]], Awaitable[Any]]) -> None:
        """Remove the given callback.

        If it is not registered, raise LookupError.
        """
        try:
            self.callbacks.remove(func)
        except ValueError:
            raise LookupError(func) from None

    @contextmanager
    def isolate(self) -> Generator[trio.MemoryReceiveChannel[tuple[Unpack[ArgT]]], None, None]:
        """Temporarily disable all listening callbacks, and redirect to the supplied channel.

        This is mainly intended for testing code, to prevent it from affecting other things.
        This cannot currently be nested within itself, but isolating different events is fine.
        """
        send: trio.MemorySendChannel[tuple[Unpack[ArgT]]]
        rec: trio.MemoryReceiveChannel[tuple[Unpack[ArgT]]]

        if self._override is not None:
            raise ValueError('Event.isolate() does not support nesting with itself!')
        # Use an infinite buffer. If the user doesn't read from the channel, or only reads after
        # the with statement has exited we want events to just be stored.
        send, rec = trio.open_memory_channel(math.inf)
        self._override = send
        try:
            yield rec
        finally:
            send.close()
            assert self._override is send, self._override
            self._override = None
