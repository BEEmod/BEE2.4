"""Test the events manager and collections."""
from unittest.mock import create_autospec

import pytest
import trio

from event import Event


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
