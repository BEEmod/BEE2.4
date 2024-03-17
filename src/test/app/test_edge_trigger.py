"""Test the edge trigger class."""
from typing import Tuple
from typing_extensions import assert_type

from trio.testing import Sequencer
import trio
import pytest

from app import EdgeTrigger


async def test_basic_operation() -> None:
    """Test the full sequence."""
    trigger = EdgeTrigger[int, int]()
    seq = Sequencer()
    state = 'pre'

    # Can't trigger when no task is waiting.
    with pytest.raises(ValueError):
        trigger.trigger()  # type: ignore

    async def wait_task() -> None:
        """Wait for the trigger."""
        nonlocal state
        async with seq(0):
            pass
        assert state == 'pre'

        async with seq(2):
            state = 'wait'
        result = await trigger.wait()
        assert_type(result, Tuple[int, int])
        assert result == (4, 2)
        assert state == 'trigger'
        state = 'complete'

    async def trigger_task() -> None:
        """Trigger the event."""
        nonlocal state
        async with seq(1):
            assert state == 'pre'
            with pytest.raises(ValueError):
                trigger.trigger(1, 2)  # Can't trigger yet.

        async with seq(3):
            assert state == 'wait'
        state = 'trigger'
        trigger.trigger(3, 5)
        trigger.trigger(4, 2)  # Last result wins.

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_task)
        nursery.start_soon(trigger_task)
    assert state == 'complete'


async def test_single_arg() -> None:
    """Test special behaviour with one arg - unwrap the tuple."""
    trigger = EdgeTrigger[str]()
    event = trio.Event()

    async def wait_task() -> None:
        """Wait for the trigger."""
        event.set()
        value = await trigger.wait()
        assert_type(value, str)
        assert value == 'result'

    async def trigger_task() -> None:
        """Trigger the event."""
        await event.wait()  # Force correct sequencing.
        trigger.trigger('result')

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_task)
        nursery.start_soon(trigger_task)


async def test_no_arg() -> None:
    """Test special behaviour with no args - return None."""
    trigger = EdgeTrigger[()]()
    event = trio.Event()

    async def wait_task() -> None:
        """Wait for the trigger."""
        event.set()
        value = await trigger.wait()  # type: ignore[func-returns-value]
        assert_type(value, None)
        assert value is None

    async def trigger_task() -> None:
        """Trigger the event."""
        await event.wait()  # Force correct sequencing.
        trigger.trigger()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(wait_task)
        nursery.start_soon(trigger_task)
