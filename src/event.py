"""Handle UI 'events' and propagate them to all interested callers.

This allows each UI segment to be less coupled to all other code which
may modify it.

Events are a combination of a specific argument type, and a context
(which may be None). When fired, all callbacks registed with the same
context, and the same type of argument will be called with the arg.

A set of observable collections are provided, which fire off events
whenever they are modified.
"""
from abc import abstractmethod
from reprlib import recursive_repr
from typing import (
    overload, cast,
    TypeVar, Any, Type,
    Optional, Union, Generic, Callable,
    Dict, List, Tuple,
    Hashable, Iterable, Iterator,
    MutableSequence, MutableMapping,
    Sequence, Mapping,
    KeysView, ValuesView, ItemsView,
)

__all__ = [
    'EventManager', 'APP_EVENTS',
    'ObsValue', 'ObsList',
    'ArgT', 'CtxT', 'KeyT', 'ValueT',
]

ArgT = TypeVar('ArgT')
CtxT = TypeVar('CtxT')
KeyT = TypeVar('KeyT', bound=Hashable)
ValueT = TypeVar('ValueT')
NoneType: Type[None] = type(None)
_UNSET = object()


class EventSpec(Generic[ArgT], List[Callable[[ArgT], Any]]):
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
    _events: Dict[Tuple[int, Type[ArgT]], EventSpec[ArgT]]

    def __init__(self) -> None:
        self._events = {}

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
        key = (id(ctx), arg_type)
        try:
            spec = self._events[key]
        except KeyError:
            spec = self._events[key] = EventSpec[ArgT](ctx)
        spec.append(func)
        if prime:
            try:
                last_val = spec.last_result
            except AttributeError:
                pass
            else:
                func(last_val)

    def __call__(self, ctx: CtxT, arg: ArgT=None) -> None:
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
            for func in spec:
                func(arg)
        finally:
            spec.cur_calls -= 1

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
            self._events[id(ctx), arg_type].remove(func)
        except (KeyError, ValueError):
            raise LookupError(ctx, arg_type, func) from None

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

    @recursive_repr('ObsList(...)')
    def __repr__(self) -> str:
        return f'ObsList({self.man!r}, {self._data!r})'

    def _fire(self, index: int, orig: Optional[ValueT], new: Optional[ValueT]) -> None:
        """Internally fire an event. Doesn't fire if it's the same."""
        self.man(self, ValueChange(orig, new, index))

    def _check_tail(self, orig: List[ValueT], start: int) -> None:
        """Used to fire off events when doing bulk changes.

        When adding/removing values, we change everything after a certain
        point. orig should be self._data[start:] before the change.
        This will then check what changed, and fire the events appropriately.
        """
        # First, determine how long both of these are.
        len_old = len(orig)
        len_new = len(self._data) - start
        # Regardless of the lengths, first fire off the common components.
        for pos in range(min(len_old, len_new)):
            old = orig[pos]
            new = self._data[start + pos]
            if old is not new:
                self._fire(start + pos, old, new)

        if len_new > len_old:
            # We appended stuff (or shifted them down).
            for pos in range(len_old, len_new):
                self._fire(start + pos, None, self._data[start + pos])
        elif len_new < len_old:
            # We removed stuff.
            for pos in range(len_new, len_old):
                self._fire(start + pos, orig[pos], None)

    # First, all read methods delegate unchanged.

    def __len__(self) -> int:
        return len(self._data)

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

    def __setitem__(self, index: Union[int, slice], item: Union[ValueT, Iterable[ValueT]]) -> None:
        if isinstance(index, slice):
            # Find the smallest index we change.
            start = min(range(*index.indices(len(self._data))), default=0)
            tail = self._data[start:]
            self._data[index] = item

            self._check_tail(tail, start)
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
            start, stop, step = index.indices(len(self._data))
            start = min(start, stop)
        elif index < 0:
            start = index + len(self._data)
        else:
            start = index

        orig_copy = self._data[start:]
        del self._data[index]
        new: Optional[ValueT]
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
        self._data.extend(iterable)
        for index in range(pos_start, len(self._data)):
            self._fire(index, None, self._data[index])

    def reverse(self) -> None:
        """Reverse causes the event to fire on every item."""
        self._data.reverse()
        size = len(self._data) - 1
        for new_ind, item in enumerate(reversed(self._data)):
            old_ind = size - new_ind
            self._fire(new_ind, item, self._data[new_ind])

    def pop(self, index: int = -1) -> ValueT:
        """S.pop([index]) -> item -- remove and return item at index (default last).
           Raise IndexError if list is empty or index is out of range.
        """
        if index < 0:
            index += len(self._data)
        value = self._data.pop(index)
        self._fire(index, value, None)
        return value

    def sort(
        self, *,
        key: Callable[[ValueT], Any] = None,
        reverse: bool = False,
    ) -> None:
        """Sort the list in-place.

        Events will fire on all the locations.
        """
        orig = self._data[:]
        self._data.sort(key=key, reverse=reverse)
        self._check_tail(orig, 0)

    def __add__(self, other: Sequence[ValueT]) -> List[ValueT]:
        """Concatenate another sequence with this one.

        This produces a normal list."""
        if isinstance(other, ObsList):
            return self._data + other._data
        copy = self._data[:]
        copy.extend(other)
        return copy

    def __radd__(self, other: Sequence[ValueT]) -> List[ValueT]:
        """Prepend another sequence with this one.

        This produces a normal list."""
        if isinstance(other, ObsList):
            return other._data + self._data
        return list(other) + self._data

    def __iadd__(self, other: Sequence[ValueT]) -> 'ObsList[ValueT]':
        """Append another sequence to this one."""
        self.extend(other)
        return self

    def __mul__(self, count: int) -> List[ValueT]:
        """Repeat the contents the given number of times."""
        return self._data * count

    def __rmul__(self, count: int) -> List[ValueT]:
        """Repeat the contents the given number of times."""
        return count * self._data

    def __imul__(self, count: int) -> 'ObsList[ValueT]':
        """Repeat the contents the given number of times."""
        pos_start = len(self._data)
        self._data *= count
        for pos in range(pos_start, len(self._data)):
            self._fire(pos, None, self._data[pos])
        return self

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ObsList):
            return self._data == other._data
        else:
            # Use special method so it returns NotImplemented
            # where required.
            return self._data.__eq__(other)

    def __ne__(self, other: object) -> bool:
        if isinstance(other, ObsList):
            return self._data != other._data
        else:
            # Use special method so it returns NotImplemented
            # where required.
            return self._data.__ne__(other)


class ObsMap(Generic[KeyT, ValueT], MutableMapping[KeyT, ValueT]):
    """A mapping which can be altered, and fires events whenever changed.

    If multiple values are modified at once, each will individually fire an event.
    If a key is added or removed, None will be substituted as appropriate.
    """
    man: EventManager
    _data: Dict[KeyT, ValueT]

    def __init__(
        self,
        man: EventManager,
        initial: Union[Mapping[KeyT, ValueT], Iterable[Tuple[KeyT, ValueT]]] = (),
    ) -> None:
        self.man = man
        self._data = dict(initial)

    @recursive_repr('ObsMap(...)')
    def __repr__(self) -> str:
        return f'ObsMap({self.man!r}, {self._data!r})'

    def _fire(self, key: KeyT, orig: ValueT, new: ValueT) -> None:
        """Internally fire an event."""
        self.man(self, ValueChange(orig, new, key))

    def __getitem__(self, k: KeyT) -> ValueT:
        return self._data[k]

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[KeyT]:
        return iter(self._data)

    def __contains__(self, key: KeyT) -> bool:
        return key in self._data

    @overload
    def get(self, k: KeyT) -> Optional[ValueT]: ...
    @overload
    def get(self, k: KeyT, default: Union[ValueT, ArgT]) -> Union[ValueT, ArgT]: ...

    def get(self, k: KeyT, default: Union[ValueT, ArgT] = None) -> Optional[ValueT, ArgT]:
        """Return map[k], or default if key is not present."""
        return self._data.get(k, default)

    def keys(self) -> KeysView[KeyT]:
        """Return a view over the mapping's keys."""
        return self._data.keys()

    def values(self) -> ValuesView[ValueT]:
        """Return a view over the mapping's values."""
        return self._data.values()

    def items(self) -> ItemsView[KeyT, ValueT]:
        """Return a view over the mapping's values."""
        return self._data.items()

    def __setitem__(self, key: KeyT, value: ValueT) -> None:
        """Set a value, then fire the event."""
        old = self._data.get(key, None)
        self._data[key] = value
        self._fire(key, old, value)

    def __delitem__(self, key: KeyT) -> None:
        """Remove the given key."""
        old = self._data.pop(key)
        # Raises the KeyError for us.
        self._fire(key, old, None)

    def clear(self) -> None:
        """Remove all values."""
        values = list(self._data.items())
        self._data.clear()
        for key, value in values:
            self._fire(key, value, None)

    @overload
    def pop(self, k: KeyT) -> ValueT: ...
    @overload
    def pop(self, k: KeyT, default: Union[ValueT, ArgT] = ...) -> Union[ValueT, ArgT]: ...

    def pop(self, k: KeyT, default: Union[ValueT, ArgT] = _UNSET) -> Union[ValueT, ArgT]:
        """Remove the specified key and return the corresponding value.

        If key is not found, the default is returned if given, otherwise KeyError is raised.
        """
        try:
            old = self._data.pop(k)
        except KeyError:
            if default is not _UNSET:
                return default
            raise  # Already got the KeyError we want.
        self._fire(k, old, None)
        return old

    def popitem(self) -> Tuple[KeyT, ValueT]:
        """Remove and return some (key, value) pair as a 2-tuple; but raise KeyError if D is empty."""
        keyvalue = key, value = self._data.popitem()
        self._fire(key, value, None)
        return keyvalue
