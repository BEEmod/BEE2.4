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
    overload, cast, TypeVar, Any, Type,
    Optional, Generic, Callable, List, Awaitable,
)

import attr
import trio

__all__ = ['EventManager', 'APP_EVENTS', 'ValueChange', 'ObsValue']

ArgT = TypeVar('ArgT')
CtxT = TypeVar('CtxT')
ValueT = TypeVar('ValueT')
Value2T = TypeVar('Value2T')
NoneType = Type[None]


class EventSpec(Generic[ArgT], List[Callable[[ArgT], Awaitable[Any]]]):
    """The data associated with a given event.

    To save a bit of space, combine the list of callbacks with the other
    args.
    """
    __slots__ = ['ctx', 'last_result', 'cur_calls']
    ctx: Any
    last_result: ArgT
    cur_calls: int

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        self.cur_calls = 0
        # Leave last_result unset as a sentinel.


class EventManager:
    """Manages a set of events, and the associated callbacks."""
    # Type[ArgT] -> EventSpec[ArgT], but can't specify that.
    _events: dict[tuple[int, Type[Any]], EventSpec[Any]]

    def __init__(self) -> None:
        self._events = {}

    @overload
    def register(
        self, ctx: CtxT,
        arg_type: None,
        func: Callable[[None], Awaitable[Any]],
    ) -> None: ...
    @overload
    def register(
        self, ctx: CtxT,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None: ...
    def register(
        self,
        ctx: CtxT,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None:
        """Register the given function to be called.

        It will recieve the events with the same context object, and
        with an instance of the argument type (no subclasses).

        As a special case it can be registered with a None argument type
        instead of type(None).
        """
        if arg_type is None:
            arg_type = cast('Type[ArgT]', NoneType)
        key = (id(ctx), arg_type)
        try:
            spec = self._events[key]
        except KeyError:
            spec = self._events[key] = EventSpec[ArgT](ctx)
        spec.append(func)

    @overload
    async def register_and_prime(
        self, ctx: CtxT,
        arg_type: None,
        func: Callable[[None], Awaitable[Any]],
    ) -> None: ...
    @overload
    async def register_and_prime(
        self, ctx: CtxT,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None: ...
    async def register_and_prime(
        self,
        ctx: CtxT,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None:
        """Register the given function, then immediately call with the last value if present."""
        if arg_type is None:
            arg_type = cast('Type[ArgT]', NoneType)
        key = (id(ctx), arg_type)
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

    async def __call__(self, ctx: CtxT, arg: ArgT=None) -> None:
        """Run the specified event.

        This is re-entrant - if called whilst the same event is already being
        run, the second will be ignored.
        """
        spec: EventSpec[ArgT]
        try:
            spec = self._events[id(ctx), type(arg)]
        except KeyError:
            return

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
        self, ctx: CtxT,
        arg_type: None,
        func: Callable[[None], Awaitable[Any]],
    ) -> None: ...
    @overload
    def unregister(
        self, ctx: CtxT,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None: ...
    def unregister(
        self,
        ctx: CtxT,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Awaitable[Any]],
    ) -> None:
        """Remove the given callback.

        If it is not registered, raise LookupError.
        """
        if arg_type is None:
            arg_type = cast(Type[ArgT], type(None))
        try:
            self._events[id(ctx), arg_type].remove(func)
        except (KeyError, ValueError):
            raise LookupError(ctx, arg_type, func) from None

# Global manager for general events.
APP_EVENTS = EventManager()


@attr.frozen
class ValueChange(Generic[ValueT]):
    """The event which is fired when a value changes."""
    old: ValueT
    new: ValueT


class ObsValue(Generic[ValueT]):
    """Holds a single value of any type, firing an event whenever it is altered."""
    def __init__(self, man: EventManager, initial: ValueT) -> None:
        self.man = man
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
        await self.man(self, ValueChange(old, new))

    def __repr__(self) -> str:
        return f'ObsValue({self.man!r}, {self._value!r})'
