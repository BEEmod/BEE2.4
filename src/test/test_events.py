"""Test the events manager and collections."""
from contextlib import contextmanager

import pytest
from unittest.mock import Mock, create_autospec, call

from event import EventManager, ValueChange, ObsValue


@contextmanager
def fires(man: EventManager, match_ctx, match_arg, msg=''):
    """Verify the code fires the given event."""
    is_fired = False

    def event_func(ctx, arg):
        nonlocal is_fired
        assert match_ctx is ctx, f"{match_ctx} is not {ctx}: {msg}"
        assert match_arg == arg, f"{match_arg} != {arg}: {msg}"
        is_fired = True

    man.register(match_ctx, type(match_arg), event_func)
    try:
        yield
        if not is_fired:
            pytest.fail("Not fired: " + msg)
    finally:
        man.unregister(match_ctx, type(match_arg), event_func)


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

    with pytest.raises(KeyError):
        man.unregister(ctx, int, func1)
    with pytest.raises(KeyError):
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

    with pytest.raises(KeyError):
        man.unregister(ctx, int, func1)
    with pytest.raises(KeyError):
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
