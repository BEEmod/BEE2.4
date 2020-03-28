"""Handle UI 'events' and propagate them to all interested callers.

This allows each UI segment to be less coupled to all other code which
may modify it.

Events are a combination of a specific argument type, and a context
(which may be None). When fired, all callbacks registed with the same
context, and the same type of argument will be called with the arg.

A set of observable collections are provided, which fire off events
whenever they are modified.
"""
from collections import defaultdict
from typing import (
    TypeVar, Callable, overload,
    Any, Optional, Type,
    Dict, List, Tuple,
    Hashable
)

ArgT = TypeVar('ArgT')
CtxT = TypeVar('CtxT')
NoneType: Type[None] = type(None)


class EventManager:
    """Manages a set of events, and the associated callbacks."""
    _cbacks: Dict[Tuple[CtxT, Type[ArgT]], List[Callable]]
    _last_result: Dict[Tuple[CtxT, Type[ArgT]], Any]
    _running: Dict[Tuple[CtxT, Type[ArgT]], bool]

    def __init__(self):
        self._cbacks = defaultdict(list)
        self._last_result = {}
        self._running = {}

    @overload
    def register(
        self, ctx: CtxT,
        arg_type: None,
        func: Callable[[None], Any],
        *, prime: bool=False,
    ) -> None: ...
    @overload
    def register(
        self, ctx: CtxT,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Any],
        *, prime: bool=False,
    ) -> None: ...
    def register(
        self,
        ctx: CtxT,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Any],
        *,
        prime: bool=False,
    ) -> None:
        """Register the given function to be called.

        It will recieve the events with the same context object, and
        with an instance of the argument type (no subclasses).
        If prime is True and the event was already fired, it will be called
        immediately with the last value.

        As a special case it can be registered with a None argument type
        instead of type(None).
        """
        if arg_type is None:
            arg_type = NoneType
        key = (ctx, arg_type)
        self._cbacks[key].append(func)
        if prime:
            try:
                last_val = self._last_result[key]
            except KeyError:
                pass
            else:
                func(last_val)

    def __call__(self, ctx: CtxT, arg: ArgT=None) -> None:
        """Run the specified event.

        This is re-entrant - if called whilst the same event is already being
        run, the second will be ignored.
        """
        key = (ctx, type(arg))
        self._last_result[key] = arg

        if self._running.get(key):
            return
        self._running[key] = True
        try:
            for func in self._cbacks[key]:
                func(arg)
        finally:
            self._running[key] = False

# Global manager for general events.
APP_EVENTS = EventManager()
