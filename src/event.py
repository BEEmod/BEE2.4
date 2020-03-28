"""Handle UI 'events' and propagate them to all interested callers.

This allows each UI segment to be less coupled to all other code which
may modify it.

Events are a combination of a specific argument type, and a context
(which may be None). When fired, all callbacks registed with the same
context, and the same type of argument will be called with the arg.

A set of observable collections are provided, which fire off events
whenever they are modified.
"""
import itertools
from abc import abstractmethod
from collections import defaultdict
from typing import (
    TypeVar, Callable, overload, Generic,
    Any, Optional, Type,
    Dict, List, Tuple,
    Hashable, Iterable,
    MutableSequence, MutableMapping,
    cast,
    Union,
    Iterator,
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
    _running: Dict[Tuple[Any, Type[Any]], int]

    def __init__(self) -> None:
        self._cbacks = defaultdict(list)
        self._last_result = {}
        self._running = defaultdict(int)

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

        if self._running[key]:
            try:
                if self._last_result[key] == arg:
                    return
            except KeyError:
                pass

        self._last_result[key] = arg
        self._running[key] += 1
        try:
            for func in self._cbacks[key]:
                func(arg)
        finally:
            self._running[key] -= 1

    @overload
    def unregister(
        self, ctx: CtxT,
        arg_type: None,
        func: Callable[[None], Any],
    ) -> None: ...
    @overload
    def unregister(
        self, ctx: CtxT,
        arg_type: Type[ArgT],
        func: Callable[[ArgT], Any],
    ) -> None: ...
    def unregister(
        self,
        ctx: CtxT,
        arg_type: Optional[Type[ArgT]],
        func: Callable[[ArgT], Any],
    ) -> None:
        """Remove the given callback.

        If it is not registered, raise LookupError.
        """
        if arg_type is None:
            arg_type = cast(Type[ArgT], NoneType)
        try:
            self._cbacks[ctx, arg_type].remove(func)
        except ValueError:
            raise KeyError(ctx, arg_type, func) from None

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
        return self[1]

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


class ObsList(Generic[ValueT], MutableSequence[ValueT]):
    """A sequence class which can be altered, and fires events whenever
    changed.

    If multiple values are removed at once, each will individually fire an event.
    If an item is added or removed, None will be substituted as appropriate.
    """
    man: EventManager
    _data: List[ValueT]

    def __init__(
        self,
        man: EventManager,
        initial: Iterable[ValueT] = (),
    ) -> None:
        self.man = man
        self._data = list(initial)

    def __len__(self) -> int:
        return len(self._data)

    def _fire(self, index: int, orig: ValueT, new: ValueT) -> None:
        """Internally fire an event. Doesn't fire if it's the same."""
        # if orig != new and orig != self._data[index]:
        self.man(self, ValueChange(orig, new, index))

    # First, all read methods delegate unchanged.

    @overload
    @abstractmethod
    def __getitem__(self, i: int) -> ValueT: ...

    @overload
    @abstractmethod
    def __getitem__(self, s: slice) -> List[ValueT]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[List[ValueT], ValueT]:
        """Indexing a ObsSeq will return the individual item, or a list of items."""
        return self._data[index]

    def __iter__(self) -> Iterator[ValueT]:
        return iter(self._data)

    def __contains__(self, value: Any) -> bool:
        return value in self._data

    def __reversed__(self) -> Iterator[ValueT]:
        return reversed(self._data)

    def index(self, value: ValueT, start: int = 0, stop: int = None) -> int:
        """S.index(value, [start, [stop]]) -> integer -- return first index of value.
           Raises ValueError if the value is not present.
        """
        if stop is None:
            stop = len(self._data)
        return self._data.index(value, start, stop)

    def count(self, value: Any) -> int:
        """S.count(value) -> integer -- return number of occurrences of value"""
        return self._data.count(value)

    @overload
    @abstractmethod
    def __setitem__(self, index: int, item: ValueT) -> None: ...

    @overload
    @abstractmethod
    def __setitem__(self, index: slice, item: Iterable[ValueT]) -> None: ...

    def __setitem__(self, index: Union[int, slice], item: ValueT) -> None:
        if isinstance(index, slice):
            # Complicated. We have to determine if this is going to shrink,
            # expand or keep the same size.
            start, stop, step = index.indices(len(self._data))
            indices = range(start, stop, step)
            new_vals = list(item)
            replaced = self._data[index]
            if len(replaced) != len(new_vals):
                # We have different counts, so we're resizing.
                tail_start = max(max(indices), len(self._data)-1)
                tail = self._data[tail_start:]
            else:
                tail_start = 0
                tail = ()

            self._data[index] = new_vals
            # First, do the directly changed values.
            for pos, old, new in zip(indices, replaced, new_vals):
                self._fire(pos, old, new)

            if not tail:
                return

            # Now do everything after there which shifts.
            for pos, orig_pos in enumerate(range(tail_start, len(self._data))):
                pass
        else:
            old = self._data[index]
            self._data[index] = item
            self._fire(index, old, item)

    @overload
    @abstractmethod
    def __delitem__(self, index: int) -> None: ...

    @overload
    @abstractmethod
    def __delitem__(self, index: slice) -> None: ...

    def __delitem__(self, index: Union[int, slice]) -> None:
        if isinstance(index, slice):
            start, stop, step  = index.indices(len(self._data))
            start = min(start, stop)
        else:
            start = index

        orig_copy = self._data[start:]
        del self._data[index]
        for pos, orig in enumerate(orig_copy, start=start):
            if pos < len(self._data):
                new = self._data[pos]
            else:
                new = None
            self._fire(pos, orig, new)

    def insert(self, index: int, object: ValueT) -> None:
        """Inserting an item changes the index, plus everything after it."""
        size = len(self._data)
        self._data.insert(index, object)
        for pos in range(index, size):
            self._fire(pos, self._data[pos + 1], self._data[pos])
        self._fire(size, None, self._data[-1])

    def append(self, item: ValueT) -> None:
        """Appending adds the item to the end."""
        pos = len(self._data)
        self._data.append(item)
        self.man(self, ValueChange(None, item, pos))

    def clear(self) -> None:
        """Clearing a list fires the event on every value."""
        orig = self._data[:]
        self._data.clear()
        for index, item in enumerate(orig):
            self.man(self, ValueChange(item, None, index))

    def extend(self, iterable: Iterable[ValueT]) -> None:
        """Extend fires the event for each new item."""
        pos_start = len(self._data)
        new_values = list(iterable)
        self._data += new_values
        for index, item in enumerate(new_values, pos_start):
            self.man(self, ValueChange(item, None, index))

    def reverse(self) -> None:
        """Reverse causes the event to fire on every item."""
        self._data.reverse()
        size = len(self._data) - 1
        for new_ind, item in enumerate(reversed(self._data)):
            old_ind = size - new_ind
            self._fire(old_ind, self._data[old_ind], item)

    def pop(self, index: int = -1) -> ValueT:
        """S.pop([index]) -> item -- remove and return item at index (default last).
           Raise IndexError if list is empty or index is out of range.
        """
        if index < 0:
            index += len(self._data)
        value = self._data.pop(index)
        self._fire(index, value, None)
        return value
