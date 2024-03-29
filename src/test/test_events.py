"""Test the events manager and collections."""
from typing import Dict
from unittest.mock import AsyncMock, call, create_autospec

import pytest
import trio

from event import Event, ObsValue, ValueChange


async def func_unary(arg: object) -> None:
    """Expected signature of event functions."""
    pass


async def test_simple_register() -> None:
    """Test registering events."""
    event = Event[int]()
    func1 = create_autospec(func_unary, name='func1')
    func2 = create_autospec(func_unary, name='func2')

    res = event.register(func1)
    assert res is func1

    func1.assert_not_awaited()
    func2.assert_not_awaited()

    await event(5)

    func1.assert_awaited_once_with(5)
    func1.reset_mock()

    await event(12)

    func1.assert_awaited_once_with(12)
    func1.reset_mock()


async def test_unregister() -> None:
    """Test unregistering events in the bus."""
    event = Event[bool]()
    func1 = create_autospec(func_unary, name='func1')
    func2 = create_autospec(func_unary, name='func2')
    func3 = create_autospec(func_unary, name='func3')

    event.register(func1)
    event.register(func2)
    await event(True)

    func1.assert_awaited_once_with(True)
    func2.assert_awaited_once_with(True)
    func3.assert_not_awaited()
    func1.reset_mock()
    func2.reset_mock()

    with pytest.raises(LookupError):
        event.unregister(func3)
    event.unregister(func1)
    with pytest.raises(LookupError):
        event.unregister(func1)  # No repeats.

    func1.assert_not_awaited()
    func2.assert_not_awaited()
    func3.assert_not_awaited()

    await event(False)

    func1.assert_not_awaited()
    func2.assert_awaited_once_with(False)
    func3.assert_not_awaited()


async def test_register_priming() -> None:
    """Test the priming version of registering."""
    event = Event[int]('prime_event')
    func1 = create_autospec(func_unary, name='func1')
    func2 = create_autospec(func_unary, name='func2')

    # If not fired, does nothing.
    await event.register_and_prime(func1)
    func1.assert_not_awaited()
    await event(5)
    func1.assert_awaited_once_with(5)

    func1.reset_mock()
    # Now it's been fired already, the late registry can be sent it.
    await event.register_and_prime(func2)
    func1.assert_not_awaited()  # This is unaffected.
    func2.assert_awaited_once_with(5)

    func1.reset_mock()
    func2.reset_mock()

    await event(10)
    func1.assert_awaited_once_with(10)
    func2.assert_awaited_once_with(10)


async def test_isolate() -> None:
    """Test the isolation context manager."""
    event = Event[int]('isolate')
    func1 = create_autospec(func_unary, name='func1')
    func2 = create_autospec(func_unary, name='func2')
    event.register(func1)
    await event(4)
    func1.assert_awaited_once_with(4)

    func1.reset_mock()
    rec: trio.MemoryReceiveChannel
    with event.isolate() as rec:
        with pytest.raises(ValueError):  # No nesting.
            with event.isolate():
                pass

        await event(5)
        func1.assert_not_awaited()
        assert await rec.receive() == (5, )

        await event.register_and_prime(func2)
        func1.assert_not_awaited()
        func2.assert_awaited_once_with(5)  # Still passed through.
        func2.reset_mock()

        await event(48)
        await event(36)
        for i in range(1024):  # Unlimited buffer.
            await event(i)

    func1.assert_not_awaited()
    func2.assert_not_awaited()

    assert await rec.receive() == (48, )
    assert await rec.receive() == (36, )
    for i in range(1024):
        assert await rec.receive() == (i, )
    # Finished here.
    with pytest.raises(trio.EndOfChannel):
        await rec.receive()


def test_valuechange() -> None:
    """Check ValueChange() produces the right values."""
    with pytest.raises(TypeError):
        ValueChange()  # type: ignore
    with pytest.raises(TypeError):
        ValueChange(1)  # type: ignore
    with pytest.raises(TypeError):
        ValueChange(1, 2, 3)  # type: ignore
    assert ValueChange(1, 2) == ValueChange(1, 2)
    assert ValueChange(old=2, new=3) == ValueChange(2, 3)


def test_valuechange_attrs() -> None:
    """Check the attributes act correctly."""
    examp = ValueChange(0, 1)
    assert examp.old == 0
    assert examp.new == 1
    # Readonly.
    with pytest.raises(AttributeError):
        examp.old = ()  # type: ignore
    with pytest.raises(AttributeError):
        examp.new = ()  # type: ignore


def test_valuechange_hash() -> None:
    """Check ValueChange() can be hashed and put in a dict key."""
    key = ValueChange(45, 38)
    assert hash(key) == hash(ValueChange(45.0, 38.0))
    dct: Dict[ValueChange[object], object] = {
        key: 45,
        ValueChange('text', 12): sum,
    }
    assert dct[key] == 45
    assert dct[ValueChange(45.0, 38)] == 45
    assert ValueChange('text', 12) in dct
    assert ValueChange(12, 'text') not in dct


async def test_obsval_getset() -> None:
    """Check getting/setting functions normally, unrelated to events."""
    holder: ObsValue[object] = ObsValue(45, 'obsval_getset')
    assert holder.value == 45

    await holder.set(32)
    assert holder.value == 32

    sent = object()
    await holder.set(sent)
    assert holder.value is sent

    await holder.set(holder)
    assert holder.value is holder


async def test_obsval_fires() -> None:
    """Check an event fires whenever the value changes."""
    holder: ObsValue[object] = ObsValue(0, 'obsval_getset')
    func1 = create_autospec(func_unary)
    holder.on_changed.register(func1)
    func1.assert_not_awaited()

    assert holder.value == 0
    func1.assert_not_awaited()

    await holder.set(1)
    func1.assert_awaited_once_with(ValueChange(0, 1))
    func1.reset_mock()

    await holder.set('v')
    func1.assert_awaited_once_with(ValueChange(1, 'v'))


async def test_obsvalue_set_during_event() -> None:
    """Test the case where the holder is set from the event callback."""
    # Here we're going to set up a chain of events to fire.
    # What we want to have happen:
    # Start at 0.
    # Set to 1.
    # That causes it to fire an event, which sets it to 2.
    # That event should see it set to 2.
    # The third will cause it to set it to 3.
    # A new event will then fire, setting it to 3 again.
    # No event will fire.
    holder = ObsValue(0, 'set_during')

    async def event(arg: ValueChange[int]) -> None:
        """Event fired when registered."""
        assert arg.new == holder.value, f"Wrong new val: {arg} != {holder.value}"
        await holder.set(min(3, arg.new + 1))

    mock = AsyncMock(side_effect=event)
    mock.assert_not_awaited()
    holder.on_changed.register(mock)
    await holder.set(1)
    assert holder.value == 3
    assert mock.call_count == 4
    mock.assert_has_calls([
        call(ValueChange(0, 1)),
        call(ValueChange(1, 2)),
        call(ValueChange(2, 3)),
        call(ValueChange(3, 3)),
    ])


async def test_obsval_repr() -> None:
    """Test the repr() of ObsValue."""
    holder: ObsValue[object] = ObsValue(0)
    assert repr(holder) == f'ObsValue(0, on_changed={holder.on_changed!r})'

    await holder.set([1, 2, 3])
    assert repr(holder) == f'ObsValue([1, 2, 3], on_changed={holder.on_changed!r})'

    await holder.set(None)
    assert repr(holder) == f'ObsValue(None, on_changed={holder.on_changed!r})'
