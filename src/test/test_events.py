"""Test the events manager and collections."""
import sys

import pytest
from unittest.mock import Mock, create_autospec, call

from event import EventManager, ValueChange, ObsValue, ObsList, ObsMap


def event_func(arg):
    """Expected signature of event functions."""
    pass


def test_simple_register() -> None:
    """"Test registering events in the manager."""
    man = EventManager()
    func1 = create_autospec(event_func)
    func2 = create_autospec(event_func)
    ctx1 = object()
    ctx2 = object()

    man.register(ctx1, int, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx1, 5)

    func1.assert_called_once_with(5)
    func2.assert_not_called()
    func1.reset_mock()

    # Different context, not fired.
    man(ctx2, 12)

    func1.assert_not_called()
    func2.assert_not_called()

    man.register(ctx2, int, func2)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx2, 34)
    func1.assert_not_called()
    func2.assert_called_once_with(34)
    func2.reset_mock()


def test_unregister() -> None:
    """"Test unregistering events in the manager."""
    man = EventManager()
    func1 = create_autospec(event_func)
    func2 = create_autospec(event_func)
    ctx = object()

    man.register(ctx, bool, func1)
    man.register(ctx, bool, func2)
    man(ctx, True)

    func1.assert_called_once_with(True)
    func2.assert_called_once_with(True)
    func1.reset_mock()
    func2.reset_mock()

    with pytest.raises(LookupError):
        man.unregister(ctx, int, func1)
    with pytest.raises(LookupError):
        man.unregister(45, bool, func1)
    man.unregister(ctx, bool, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx, False)

    func1.assert_not_called()
    func2.assert_called_once_with(False)


def test_register_nonearg() -> None:
    """"Test registering events with no arg in the manager."""
    man = EventManager()
    func1 = Mock()
    func2 = create_autospec(event_func)
    ctx1 = object()
    ctx2 = object()

    man.register(ctx1, None, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx1)

    func1.assert_called_once_with(None)
    func2.assert_not_called()
    func1.reset_mock()

    # Different context, not fired.
    man(ctx2)

    func1.assert_not_called()
    func2.assert_not_called()

    man.register(ctx2, None, func2)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx2, None)
    func1.assert_not_called()
    func2.assert_called_once_with(None)
    func2.reset_mock()


def test_unregister_nonearg() -> None:
    """"Test unregistering events in the manager."""
    man = EventManager()
    func1 = create_autospec(event_func)
    func2 = create_autospec(event_func)
    ctx = object()

    man.register(ctx, None, func1)
    man.register(ctx, None, func2)
    man(ctx)

    func1.assert_called_once_with(None)
    func2.assert_called_once_with(None)
    func1.reset_mock()
    func2.reset_mock()

    with pytest.raises(LookupError):
        man.unregister(ctx, int, func1)
    with pytest.raises(LookupError):
        man.unregister(45, None, func1)
    man.unregister(ctx, None, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx)

    func1.assert_not_called()
    func2.assert_called_once_with(None)


def test_register_priming() -> None:
    """Test the 'prime' keyword argument for events."""
    man = EventManager()
    func1 = create_autospec(event_func, name='func1')
    func2 = create_autospec(event_func, name='func2')

    # If not fired, does nothing.
    man.register(None, int, func1, prime=True)
    func1.assert_not_called()
    man(None, 5)
    func1.assert_called_once_with(5)

    func1.reset_mock()
    # Now it's been fired already, the late registry can be sent it.
    man.register(None, int, func2, prime=True)
    func1.assert_not_called()  # This is unaffected.
    func2.assert_called_once_with(5)

    func1.reset_mock()
    func2.reset_mock()

    man(None, 10)
    func1.assert_called_once_with(10)
    func2.assert_called_once_with(10)


def test_valuechange() -> None:
    """Check ValueChange() produces the right values."""
    with pytest.raises(TypeError):
        ValueChange()
    with pytest.raises(TypeError):
        ValueChange(1)
    with pytest.raises(TypeError):
        ValueChange(1, 2)
    with pytest.raises(TypeError):
        ValueChange(1, 2, key=4, ind=6)
    with pytest.raises(TypeError):
        ValueChange(1, 2, 3, 4)
    assert ValueChange(1, 2, 3) == ValueChange(1, 2, 3)
    assert ValueChange(2, 5, key=10) == ValueChange(2, 5, 10)
    assert ValueChange(2, 5, ind=10) == ValueChange(2, 5, 10)
    assert ValueChange(ind=5, old=2, new=3) == ValueChange(2, 3, 5)
    assert ValueChange(key=5, old=2, new=3) == ValueChange(2, 3, 5)
    assert ValueChange(ind=5, old=2, new=3) == ValueChange(2, 3, 5)
    examp = ValueChange(0, 1, 'hi')
    assert examp.ind is examp.key == 'hi'
    assert examp.old == 0
    assert examp.new == 1
    assert examp == ValueChange(0, 1, 'hi')
    assert hash(examp) == hash(ValueChange(0.0, 1.0, 'hi'))


def test_obsval_getset() -> None:
    """Check getting/setting functions normally, unrelated to events."""
    man = EventManager()
    holder = ObsValue(man, 45)
    assert holder.value == 45
    holder.value = 32
    assert holder.value == 32
    sent = object()
    holder.value = sent
    assert holder.value is sent
    holder.value = holder
    assert holder.value is holder


def test_obsval_fires() -> None:
    """Check an event fires whenever the value changes."""
    man = EventManager()
    holder = ObsValue(man, 0)
    func1 = create_autospec(event_func)
    man.register(holder, ValueChange, func1)
    func1.assert_not_called()

    assert holder.value == 0
    func1.assert_not_called()

    holder.value = 1
    func1.assert_called_once_with(ValueChange(0, 1, None))
    func1.reset_mock()

    holder.value = 'v'

    func1.assert_called_once_with(ValueChange(1, 'v', None))


def test_obsvalue_set_during_event() -> None:
    """Test the case where the holder is set from the event callback."""
    # Here we're going to setup a chain of events to fire.
    # What we want to have happen:
    # Start at 0.
    # Set to 1.
    # That causes it to fire an event, which sets it to 2.
    # That event should see it set to 2.
    # The third will cause it to set it to 3.
    # A new event will then fire, setting it to 3 again.
    # No event will fire.
    man = EventManager()
    holder = ObsValue(man, 0)

    def event(arg: ValueChange):
        assert arg.ind is arg.key is None, f"Bad key: {arg}"
        assert arg.new == holder.value, f"Wrong new val: {arg} != {holder.value}"
        holder.value = min(3, arg.new + 1)

    mock = Mock(side_effect=event)
    mock.assert_not_called()
    man.register(holder, ValueChange, mock)
    holder.value = 1
    assert holder.value == 3
    assert mock.call_count == 4
    mock.assert_has_calls([
        call(ValueChange(0, 1, None)),
        call(ValueChange(1, 2, None)),
        call(ValueChange(2, 3, None)),
        call(ValueChange(3, 3, None)),
    ])


def test_obsval_repr() -> None:
    """Test the repr() of ObsValue."""
    man = EventManager()
    holder = ObsValue(man, 0)

    assert repr(holder) == f'ObsValue({man!r}, 0)'
    holder.value = [1, 2, 3]
    assert repr(holder) == f'ObsValue({man!r}, [1, 2, 3])'
    holder.value = None
    assert repr(holder) == f'ObsValue({man!r}, None)'


try:
    from test.list_tests import CommonTest as CPyListTest
    from test.mapping_tests import TestHashMappingProtocol as CPyMapTest
except ImportError:
    # No test package installed, can only run the ones here.
    from unittest import TestCase as CPyListTest, TestCase as CPyMapTest

    def test_no_cpython():
        """Log that the tests aren't importable."""
        pytest.fail("No test.list_tests and test.mapping_tests to import!")

class CPythonObsListTests(CPyListTest):
    """Use CPython's own tests.

    This should comprehensively test that it does the same thing
    as the original list type.
    """
    def test_init(self):
        man = EventManager()
        # Iterable arg is optional
        self.assertEqual(self.type2test([]), self.type2test())

        # Init clears previous values
        a = self.type2test([1, 2, 3])
        a.__init__(man)
        self.assertEqual(a, self.type2test([]))

        # Init overwrites previous values
        a = self.type2test([1, 2, 3])
        a.__init__(man, [4, 5, 6])
        self.assertEqual(a, self.type2test([4, 5, 6]))

        # Mutables always return a new object
        b = self.type2test(a)
        self.assertNotEqual(id(a), id(b))
        self.assertEqual(a, b)

    @staticmethod
    def type2test(it=()):
        """Replicate the normal list's parameters, so it can test this."""
        return ObsList(EventManager(), it)

    # copy() for us isn't useful or well defined.
    # Context is compared by identity, so it won't fire the events.
    # But returning a list is odd as well.
    test_copy = None

    # This is a extension type check, not Python code.
    test_free_after_iterating = None

    # Our repr() is and should be different.
    test_repr = None

    def test_addmul(self) -> None:
        """Eliminate the subclass test, type2test isn't valid."""
        u1 = self.type2test([0])
        u2 = self.type2test([0, 1])
        self.assertEqual(u1, u1 + self.type2test())
        self.assertEqual(u1, self.type2test() + u1)
        self.assertEqual(u1 + self.type2test([1]), u2)
        self.assertEqual(self.type2test([-1]) + u1, self.type2test([-1, 0]))
        self.assertEqual(self.type2test(), u2 * 0)
        self.assertEqual(self.type2test(), 0 * u2)
        self.assertEqual(self.type2test(), u2 * 0)
        self.assertEqual(self.type2test(), 0 * u2)
        self.assertEqual(u2, u2 * 1)
        self.assertEqual(u2, 1 * u2)
        self.assertEqual(u2, u2 * 1)
        self.assertEqual(u2, 1 * u2)
        self.assertEqual(u2 + u2, u2 * 2)
        self.assertEqual(u2 + u2, 2 * u2)
        self.assertEqual(u2 + u2, u2 * 2)
        self.assertEqual(u2 + u2, 2 * u2)
        self.assertEqual(u2 + u2 + u2, u2 * 3)
        self.assertEqual(u2 + u2 + u2, 3 * u2)

    def test_getitemoverwriteiter(self):
        """Needs an override to pass EventManager in."""
        # Verify that __getitem__ overrides are not recognized by __iter__
        class T(ObsList):
            def __getitem__(self, key):
                return str(key) + '!!!'
        self.assertEqual(next(iter(T(EventManager(), (1, 2)))), 1)


class CPythonObsMapTests(CPyMapTest):
    """Use CPython's own tests.

    This should comprehensively test that it does the same thing
    as the original dict type.
    """
    type2test = ObsMap
    man = EventManager()
    event_fail = False

    def _reference(self):
        """Return a dictionary of values which are invariant by storage
        in the object under test."""
        return self._full_mapping({"1": "2", "key1": "value1", "key2": (1, 2, 3)})

    def _empty_mapping(self):
        """Return an empty mapping object"""
        return self._full_mapping({})

    def _full_mapping(self, data):
        """Return a mapping object with the value contained in data
        dictionary"""
        dct = ObsMap(self.man, data)
        if self.event_fail:
            dct.man.register(dct, ValueChange, pytest.fail)
        return dct

    # fromkeys() for us isn't useful.
    test_fromkeys = None

    # Our constructor is different.
    test_constructor = None

    # Our repr() is and should be different.
    test_repr = None

    def test_read(self):
        """Fail if any event is fired."""
        self.man = EventManager()
        try:
            self.event_fail = True
            super().test_read()
        finally:
            self.event_fail = False
            self.man = EventManager()


# Don't test these themselves.
del CPyListTest, CPyMapTest


def test_obslist_repr() -> None:
    """Replicate the original list checks."""
    man = EventManager()
    l0 = []
    l2 = [0, 1, 2]
    a0 = ObsList(man, l0)
    a2 = ObsList(man, l2)

    assert str(a0) == repr(a0) == f"ObsList({man!r}, [])"
    assert str(a2) == repr(a2) == f"ObsList({man!r}, [0, 1, 2])"

    a2.append(a2)
    a2.append(3)
    assert str(a2) == repr(a2) == f"ObsList({man!r}, [0, 1, 2, ObsList(...), 3])"

    l0 = []
    for i in range(sys.getrecursionlimit() + 100):
        l0 = [l0]
    a1 = ObsList(man, l0)
    with pytest.raises(RecursionError):
        repr(a1)


def test_obslist_reading() -> None:
    """Test reading functions do what is expected."""
    man = EventManager()
    seq = ObsList(man, [1, 2, 3, 3, 4])
    # If any event fires, we fail.
    man.register(seq, ValueChange, pytest.fail)
    assert seq[0] == 1
    assert seq[1] == 2
    assert seq[2] == 3
    assert len(seq) == 5
    assert seq[:2] == [1, 2]
    assert seq[1:] == [2, 3, 3, 4]
    assert seq[2:0:-1] == [3, 2]
    assert 2 in seq
    assert 5 not in seq
    assert FileNotFoundError not in seq  # Random object.
    assert seq.index(2) == 1
    assert list(seq) == [1, 2, 3, 3, 4]
    assert list(reversed(seq)) == [4, 3, 3, 2, 1]
    assert seq.count(2) == 1
    assert seq.count(3) == 2
    assert seq.count(9) == 0

    with pytest.raises(ValueError):
        seq.index(95)


def test_obslist_deletion() -> None:
    """Test deleting items from the sequence."""
    man = EventManager()
    seq = ObsList(man, range(10))
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    del seq[7]
    assert event.call_count == 3
    event.assert_has_calls([
        call(ValueChange(7, 8, 7)),
        call(ValueChange(8, 9, 8)),
        call(ValueChange(9, None, 9)),
    ])


def test_obslist_slice_assignment_shrink() -> None:
    """Test deleting items from the list with slice assignment."""
    man = EventManager()
    seq = ObsList(man, range(10))
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    seq[3:9] = ['a', 'b', 'c']
    assert event.call_count == 7
    event.assert_has_calls([
        call(ValueChange(3, 'a', 3)),
        call(ValueChange(4, 'b', 4)),
        call(ValueChange(5, 'c', 5)),
        call(ValueChange(6, 9, 6)),
        call(ValueChange(7, None, 7)),
        call(ValueChange(8, None, 8)),
        call(ValueChange(9, None, 9)),
    ])


def test_obslist_slice_assignment_grow() -> None:
    """Test adding items to the list with slice assignment."""
    man = EventManager()
    seq = ObsList(man, range(10))
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    seq[3:4] = ['a', 'b', 'c', 'd', 'e', 'f']
    assert event.call_count == 12
    event.assert_has_calls([
        call(ValueChange(3, 'a', 3)),
        call(ValueChange(4, 'b', 4)),
        call(ValueChange(5, 'c', 5)),
        call(ValueChange(6, 'd', 6)),
        call(ValueChange(7, 'e', 7)),
        call(ValueChange(8, 'f', 8)),
        call(ValueChange(9, 4, 9)),
        call(ValueChange(None, 5, 10)),
        call(ValueChange(None, 6, 11)),
        call(ValueChange(None, 7, 12)),
        call(ValueChange(None, 8, 13)),
        call(ValueChange(None, 9, 14)),
    ])


def test_obslist_slice_assignment_same() -> None:
    """Test modifying the list with slice assignment, while keeping the length."""
    man = EventManager()
    seq = ObsList(man, range(10))
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    seq[5:2:-1] = ['a', 'b', 'c']
    assert event.call_count == 3
    event.assert_has_calls([
        call(ValueChange(3, 'c', 3)),
        call(ValueChange(4, 'b', 4)),
        call(ValueChange(5, 'a', 5)),
    ])


def test_obslist_reverse() -> None:
    """Test the inplace reverse fires events."""
    man = EventManager()
    # x10 to distinguish ind/keys.
    seq = ObsList(man, (x * 10 for x in range(10)))
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    seq.reverse()
    assert event.call_count == 10
    event.assert_has_calls([
        call(ValueChange( 0, 90, 0)),
        call(ValueChange(10, 80, 1)),
        call(ValueChange(20, 70, 2)),
        call(ValueChange(30, 60, 3)),
        call(ValueChange(40, 50, 4)),
        call(ValueChange(50, 40, 5)),
        call(ValueChange(60, 30, 6)),
        call(ValueChange(70, 20, 7)),
        call(ValueChange(80, 10, 8)),
        call(ValueChange(90,  0, 9)),
    ])
    # Check odd lengths.
    assert seq.pop() == 0
    event.reset_mock()

    seq.reverse()
    assert event.call_count == 9
    event.assert_has_calls([
        call(ValueChange(90, 10, 0)),
        call(ValueChange(80, 20, 1)),
        call(ValueChange(70, 30, 2)),
        call(ValueChange(60, 40, 3)),
        call(ValueChange(50, 50, 4)),
        call(ValueChange(40, 60, 5)),
        call(ValueChange(30, 70, 6)),
        call(ValueChange(20, 80, 7)),
        call(ValueChange(10, 90, 8)),
    ])


def test_obslist_sort() -> None:
    """Test the inplace sort fires events."""
    man = EventManager()
    seq = ObsList(man, [-3, 4, -2, 8, 3, 5, -9])
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    seq.sort()
    assert event.call_count == 5
    event.assert_has_calls([
        call(ValueChange(-3, -9, 0)),
        call(ValueChange(+4, -3, 1)),
        # call(ValueChange(-2, -2, 2)),
        call(ValueChange(+8, +3, 3)),
        call(ValueChange(+3, +4, 4)),
        # call(ValueChange(+5, +5, 5)),
        call(ValueChange(-9, +8, 6)),
    ])
    event.reset_mock()

    seq.sort(key=abs, reverse=True)
    assert event.call_count == 6
    event.assert_has_calls([
        # call(ValueChange(-9, -9, 0)),
        call(ValueChange(-3, +8, 1)),
        call(ValueChange(-2, +5, 2)),
        call(ValueChange(+3, +4, 3)),
        call(ValueChange(+4, -3, 4)),
        call(ValueChange(+5, +3, 5)),
        call(ValueChange(+8, -2, 6)),
    ])


def test_obsmap_repr():
    """Same as test.test_mapping.TestHashMappingProtocol, but with our repr."""
    man = EventManager()
    man_repr = repr(man)  # Contains the memory address.
    d = ObsMap(man)
    assert repr(d) == 'ObsMap(%, {})'.replace('%', man_repr)
    d[1] = 2
    assert repr(d) == 'ObsMap(%, {1: 2})'.replace('%', man_repr)

    d = ObsMap(man)
    d[1] = d
    assert repr(d) == 'ObsMap(%, {1: ObsMap(...)})'.replace('%', man_repr)

    class Exc(Exception): pass

    class BadRepr(object):
        def __repr__(self):
            raise Exc()

    d = ObsMap(man, {1: BadRepr()})
    with pytest.raises(Exc):
        repr(d)


def test_obsmap_setting():
    man = EventManager()
    dct: ObsMap = ObsMap(man, {1: False})
    event = create_autospec(event_func)
    man.register(dct, ValueChange, event)
    assert event.call_count == 0

    dct[1] = True
    event.assert_has_calls([
        call(ValueChange(False, True, key=1))
    ])
    event.reset_mock()

    o = object()
    dct[78] = o
    dct['hello'] = 'bye'
    dct[78] = 'blah'
    dct['hello'] = dct[78]
    event.assert_has_calls([
        call(ValueChange(None, o, key=78)),
        call(ValueChange(None, 'bye', key='hello')),
        call(ValueChange(o, 'blah', key=78)),
        call(ValueChange('bye', 'blah', key='hello')),
    ])
    event.reset_mock()

    del dct[78]
    event.assert_has_calls([
        call(ValueChange('blah', None, key=78)),
    ])
    event.reset_mock()

    dct[78] = 'test'
    event.assert_has_calls([
        call(ValueChange(None, 'test', key=78)),
    ])
    event.reset_mock()


def test_obsmap_setdefault():
    """An event should only fire if the key isn't present."""
    man = EventManager()
    dct: ObsMap = ObsMap(man, {'present': True})
    event = create_autospec(event_func)
    man.register(dct, ValueChange, event)

    assert dct.setdefault('present', 45) == True
    assert event.call_count == 0
    event.reset_mock()

    assert dct.setdefault('missing', 70) == 70
    event.assert_has_calls([
        call(ValueChange(None, 70, 'missing'))
    ])
    event.reset_mock()
    assert dct['missing'] == 70
    assert dct.setdefault('missing', 30) == 70
    assert event.call_count == 0
