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
    TypeVar, Callable, overload, Generic,
    Any, Optional, Type,
    Dict, List, Tuple,
    Hashable,
    cast,
)

ArgT = TypeVar('ArgT')
CtxT = TypeVar('CtxT')
KeyT = TypeVar('KeyT', bound=Hashable)
ValueT = TypeVar('ValueT')
NoneType: Type[None] = type(None)


class EventManager:
    """Manages a set of events, and the associated callbacks."""
    _cbacks: Dict[Tuple[Any, Type[Any]], List[Callable]]
    _last_result: Dict[Tuple[Any, Type[Any]], Any]
    _running: Dict[Tuple[Any, Type[Any]], bool]

    def __init__(self) -> None:
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
            arg_type = cast(Type[ArgT], NoneType)
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


# Can't combine Generic and NamedTuple, so need to paste in the source code
# here.
# class ValueChange(NamedTuple, Generic[KeyT, ValueT]):
class ValueChange(tuple, Generic[KeyT, ValueT]):
    """The event which is fired when a value changes.

    The key is the index/key that changed, or None for ObsValue.
    """
    __slots__ = ()

    _fields = ('old', 'new', 'key')

    def __new__(cls, old: ValueT, new: ValueT, key: KeyT) -> 'ValueChange':
        """Create new instance of ValueChange(old, new, key)"""
        return tuple.__new__(cls, (old, new, key))

    @classmethod
    def _make(cls, iterable) -> 'ValueChange':
        """Make a new ValueChange object from a sequence or iterable."""
        result = tuple.__new__(cls, iterable)
        if len(result) != 3:
            raise TypeError('Expected 3 arguments, got %d' % len(result))
        return result

    def _replace(self, **kwds) -> 'ValueChange':
        """Return a new ValueChange object replacing specified fields with
        new values"""
        result = self._make(map(kwds.pop, ('old', 'new', 'key'), self))
        if kwds:
            raise ValueError('Got unexpected field names: %r' % list(kwds))
        return result

    def __repr__(self) -> str:
        """Return a nicely formatted representation string"""
        return 'ValueChange(old={!r}, new={!r}, key={!r})'.format(*self)

    def __getnewargs__(self):
        """Return self as a plain tuple.  Used by copy and pickle."""
        return tuple(self)

    @property
    def old(self) -> ValueT:
        """The original value."""
        return self[0]

    @property
    def new(self) -> ValueT:
        """The new value."""
        return self[0]

    @property
    def key(self) -> KeyT:
        """The key used to set the value, or None for ObsValue."""
        return self[2]

    @property
    def ind(self) -> KeyT:
        """The index changed, or None for ObsValue."""
        return self[2]


class ObsValue(Generic[ValueT]):
    """Holds a single value of any type, firing an event whenever it is
    altered."""

    def __init__(self, man: EventManager, initial: ValueT) -> None:
        self.man = man
        self._value = initial

    @property
    def value(self) -> ValueT:
        """Get the value."""
        return self._value

    @value.setter
    def value(self, new: ValueT) -> None:
        """Set the value, and fire the event."""
        # Note: fire the event AFTER we change the contents.
        old = self._value
        self._value = new
        # TODO: MyPy doesn't think isinstance(None, Hashable) is true.
        self.man(self, ValueChange(old, new, None))  # type: ignore

    def __repr__(self) -> str:
        return f'ObsValue({self.man!r}, {self._value!r})'
