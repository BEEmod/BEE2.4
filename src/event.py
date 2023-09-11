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
from typing import overload, TypeVar, Any, Type, Generic, Callable, List, Awaitable

import attrs
import trio
import srctools.logger

__all__ = ['Event', 'ValueChange', 'ObsValue']
LOGGER = srctools.logger.get_logger(__name__)
ArgT = TypeVar('ArgT')
ValueT = TypeVar('ValueT')
ValueT_co = TypeVar('ValueT_co', covariant=True)
NoneType: Type[None] = type(None)


@attrs.define(init=False)
class Event(Generic[ArgT]):
    """Store functions to be called when an event occurs."""
    callbacks: List[Callable[[ArgT], Awaitable[Any]]]
    last_result: ArgT = attrs.field(init=False)
    cur_calls: int
    name: str
    log: bool = attrs.field(repr=False)

    def __init__(self, name: str='') -> None:
        self.name = name or f'<Unnamed {id(self):x}>'
        self.callbacks: List[Callable[[ArgT], Awaitable[Any]]] = []
        self.cur_calls = 0
        self.log = False
        # Leave last_result unset as a sentinel.

    def register(self, func: Callable[[ArgT], Awaitable[Any]]) -> None:
        """Register the given function to be called."""
        self.callbacks.append(func)

    async def register_and_prime(self, func: Callable[[ArgT], Awaitable[Any]]) -> None:
        """Register the given function, then immediately call with the last value if present."""
        self.callbacks.append(func)
        try:
            last_val = self.last_result
        except AttributeError:
            await trio.sleep(0)  # Checkpoint.
        else:
            await func(last_val)

    @overload
    async def __call__(self: Event[None]) -> None: ...
    @overload
    async def __call__(self, arg: ArgT) -> None: ...

    async def __call__(self, arg: ArgT=None) -> None:
        """Run the specified event.

        This is re-entrant - if called whilst the same event is already being
        run, the second will be ignored.
        """
        if self.log:
            LOGGER.debug('{}({!r}) = {}', self.name, arg, self.callbacks)

        if self.cur_calls:
            try:
                if self.last_result == arg:
                    return
            except AttributeError:
                pass

        self.last_result = arg
        self.cur_calls += 1
        try:
            async with trio.open_nursery() as nursery:
                for func in self.callbacks:
                    nursery.start_soon(func, arg)
        finally:
            self.cur_calls -= 1

    def unregister(self, func: Callable[[ArgT], Awaitable[Any]],) -> None:
        """Remove the given callback.

        If it is not registered, raise LookupError.
        """
        try:
            self.callbacks.remove(func)
        except ValueError:
            raise LookupError(func) from None


@attrs.frozen
class ValueChange(Generic[ValueT_co]):
    """Holds information about when a value changes."""
    old: ValueT_co
    new: ValueT_co


class ObsValue(Generic[ValueT]):
    """Holds a single value of any type, firing an event whenever it is altered."""
    on_changed: Event[ValueChange[ValueT]]
    _value: ValueT

    def __init__(self, initial: ValueT, name: str='') -> None:
        self.on_changed = Event(name)
        self._value = initial

    @property
    def value(self) -> ValueT:
        """Get the value."""
        return self._value

    async def set(self, new: ValueT) -> None:
        """Set the value, and fire the event."""
        # Note: fire the event AFTER we change the contents.
        old = self._value
        self._value = new
        await self.on_changed(ValueChange(old, new))

    def __repr__(self) -> str:
        return f'ObsValue({self._value!r}, on_changed={self.on_changed})'
