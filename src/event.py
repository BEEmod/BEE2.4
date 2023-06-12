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
from typing import (
    overload, get_origin, TypeVar, Any, Type,
    Optional, Generic, Callable, List, Awaitable
)

import attrs
import trio
import srctools.logger

__all__ = ['EventBus', 'APP_BUS', 'ValueChange', 'ObsValue']
LOGGER = srctools.logger.get_logger(__name__)
ArgT = TypeVar('ArgT')
ValueT = TypeVar('ValueT')
Value2T = TypeVar('Value2T')
NoneType: Type[None] = type(None)


class EventSpec(Generic[ArgT], List[Callable[[ArgT], Awaitable[Any]]]):
    """The data associated with a given event.

    To save a bit of space, combine the list of callbacks with the other
    args.
    """
    __slots__ = ['ctx', 'last_result', 'cur_calls']
    ctx: object
    last_result: ArgT
    cur_calls: int

    def __init__(self, ctx: object) -> None:
        super().__init__()
        self.ctx = ctx
        self.cur_calls = 0
        # Leave last_result unset as a sentinel.


def _get_arg_type(arg_type: object) -> type:
    """Given the arg type, pull out the actual type to key with."""
    if arg_type is None:  # Special case.
        return NoneType
    # Allow passing subscripted generics.
    origin: Optional[type] = get_origin(arg_type)
    if origin is not None:
        return origin
    if isinstance(arg_type, type):
        return arg_type
    raise ValueError(f'{arg_type!r} is not an argument type!')


class EventBus:
    """Stores functions to be called for a set of events."""
    # Type[ArgT] -> EventSpec[ArgT], but can't specify that.
    _events: dict[tuple[int, Type[Any]], EventSpec[Any]]

    def __init__(self) -> None:
        self._events = {}
        self.log = False

    @overload
    def register(
        self, ctx: object,
        arg_type: None,
        func: Callable[[None], Awaitable[Any]],
    ) -> None: ...
    @overload
    def register(
        self, ctx: object,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None: ...
    def register(
        self,
        ctx: object,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None:
        """Register the given function to be called.

        It will recieve the events with the same context object, and
        with an instance of the argument type (no subclasses).

        As a special case it can be registered with a None argument type
        instead of type(None).
        """
        key = (id(ctx), _get_arg_type(arg_type))
        try:
            spec = self._events[key]
        except KeyError:
            spec = self._events[key] = EventSpec[ArgT](ctx)
        spec.append(func)

    @overload
    async def register_and_prime(
        self, ctx: object,
        arg_type: None,
        func: Callable[[None], Awaitable[Any]],
    ) -> None: ...
    @overload
    async def register_and_prime(
        self, ctx: object,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None: ...
    async def register_and_prime(
        self,
        ctx: object,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None:
        """Register the given function, then immediately call with the last value if present."""
        key = (id(ctx), _get_arg_type(arg_type))
        try:
            spec = self._events[key]
        except KeyError:
            spec = self._events[key] = EventSpec[ArgT](ctx)
        spec.append(func)
        try:
            last_val = spec.last_result
        except AttributeError:
            await trio.sleep(0)  # Checkpoint.
        else:
            await func(last_val)

    async def __call__(self, ctx: object, arg: ArgT=None) -> None:
        """Run the specified event.

        This is re-entrant - if called whilst the same event is already being
        run, the second will be ignored.
        """
        spec: EventSpec[ArgT]
        try:
            spec = self._events[id(ctx), type(arg)]
        except KeyError:
            if self.log:
                LOGGER.debug('{:x} -> {!r}({!r}), not found.\nValid: {}', id(self), ctx, arg, self._events)
            return
        if self.log:
            LOGGER.debug('{:x} -> {!r}({!r}) = {}', id(self), ctx, arg, spec)

        if spec.cur_calls:
            try:
                if spec.last_result == arg:
                    return
            except AttributeError:
                pass

        spec.last_result = arg
        spec.cur_calls += 1
        try:
            async with trio.open_nursery() as nursery:
                for func in spec:
                    nursery.start_soon(func, arg)
        finally:
            spec.cur_calls -= 1

    @overload
    def unregister(
        self, ctx: object,
        arg_type: None,
        func: Callable[[None], Awaitable[Any]],
    ) -> None: ...
    @overload
    def unregister(
        self, ctx: object,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None: ...
    def unregister(
        self,
        ctx: object,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None:
        """Remove the given callback.

        If it is not registered, raise LookupError.
        """
        try:
            self._events[id(ctx), _get_arg_type(arg_type)].remove(func)
        except (KeyError, ValueError):
            raise LookupError(ctx, arg_type, func) from None

# Global manager for general events.
APP_BUS = EventBus()


@attrs.frozen
class ValueChange(Generic[ValueT]):
    """The event which is fired when a value changes."""
    old: ValueT
    new: ValueT


class ObsValue(Generic[ValueT]):
    """Holds a single value of any type, firing an event whenever it is altered."""
    def __init__(self, bus: EventBus, initial: ValueT) -> None:
        self.bus = bus
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
        await self.bus(self, ValueChange(old, new))

    def __repr__(self) -> str:
        return f'ObsValue({self.bus!r}, {self._value!r})'
