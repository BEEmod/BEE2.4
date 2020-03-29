"""Test the events manager and collections."""
import sys
from contextlib import contextmanager

import pytest
from unittest.mock import Mock, create_autospec, call

from event import EventManager, ValueChange, ObsValue, ObsList


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


def test_valuechange() -> None:
    """Check ValueChange() produces the right values."""
    with pytest.raises(TypeError):
        ValueChange()
    with pytest.raises(TypeError):
        ValueChange(1)
    with pytest.raises(TypeError):
        ValueChange(1, 2)
    assert ValueChange(1, 2, 3) == (1, 2, 3)
    assert ValueChange(key=5, old=2, new=3) == (2, 3, 5)
    examp = ValueChange(0, 1, 'hi')
    assert list(examp) == [0, 1, 'hi']
    assert examp.ind is examp.key is examp[2] == 'hi'
    assert examp.old is examp[0] == 0
    assert examp.new is examp[1] == 1
    assert examp == ValueChange(0, 1, 'hi')


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

try:
    from test.list_tests import CommonTest as CPyListTest
except ImportError:
    # No test package installed, can only run the ones here.
    from unittest import TestCase as CPyListTest

    def test_no_cpython():
        """Log that the tests aren't importable."""
        pytest.fail("No test.list_tests to import!")


class CPythonObsTests(CPyListTest):
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


# Don't test this itself.
del CPyListTest


def test_repr() -> None:
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
    seq = ObsList(man, range(10))
    event = create_autospec(event_func)
    man.register(seq, ValueChange, event)

    seq.reverse()
    assert event.call_count == 10
    event.assert_has_calls([
        call(ValueChange(0, 9, 0)),
        call(ValueChange(1, 8, 1)),
        call(ValueChange(2, 7, 2)),
        call(ValueChange(3, 6, 3)),
        call(ValueChange(4, 5, 4)),
        call(ValueChange(5, 4, 5)),
        call(ValueChange(6, 3, 6)),
        call(ValueChange(7, 2, 7)),
        call(ValueChange(8, 1, 8)),
        call(ValueChange(9, 0, 9)),
    ])
    # Check odd lengths.
    assert seq.pop() == 0
    event.reset_mock()

    seq.reverse()
    assert event.call_count == 9
    event.assert_has_calls([
        call(ValueChange(9, 1, 0)),
        call(ValueChange(8, 2, 1)),
        call(ValueChange(7, 3, 2)),
        call(ValueChange(6, 4, 3)),
        call(ValueChange(5, 5, 4)),
        call(ValueChange(4, 6, 5)),
        call(ValueChange(3, 7, 6)),
        call(ValueChange(2, 8, 7)),
        call(ValueChange(1, 9, 8)),
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
