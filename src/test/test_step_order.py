"""Test the StepOrder system."""
from enum import Enum

import pytest
import trio

from step_order import StepOrder, CycleError


class Resource(Enum):
    """Sample resource."""
    A = "a"
    B = "b"
    C = "c"


async def test_basic(autojump_clock: trio.abc.Clock) -> None:
    """Test that steps are run."""
    order = StepOrder(object, Resource)
    log: list[str] = []
    data = object()

    @order.add_step(prereq=[], results=[Resource.A])
    async def step_1(ctx: object) -> None:
        assert ctx is data
        log.append('start 1')
        await trio.sleep(1)  # Do "work."
        log.append('end 1')

    @order.add_step(prereq=[Resource.A, Resource.B], results=[Resource.C])
    async def step_3(ctx: object) -> None:
        assert ctx is data
        log.append('start 3')
        await trio.sleep(1)
        log.append('end 3')

    @order.add_step(prereq=[Resource.A], results=[Resource.B])
    async def step_2(ctx: object) -> None:
        assert ctx is data
        log.append('start 2')
        await trio.sleep(1)
        log.append('end 2')

    @order.add_step(prereq=[Resource.C], results=[])
    async def step_4(ctx: object) -> None:
        assert ctx is data
        log.append('start 4')
        await trio.sleep(1)
        log.append('end 4')

    await order.run(data)
    assert log == [
        "start 1",
        "end 1",
        "start 2",
        "end 2",
        "start 3",
        "end 3",
        "start 4",
        "end 4",
    ]


async def test_direct_cycle(autojump_clock: trio.abc.Clock) -> None:
    """Test that a direct cycle causes an error."""
    order = StepOrder(object, Resource)
    log: list[str] = []

    @order.add_step(prereq=[], results=[Resource.A])
    async def step_1(ctx: object) -> None:
        """Prerequisite to everything."""
        log.append('step 1')

    @order.add_step(prereq=[Resource.A], results=[])
    async def step_2(ctx: object) -> None:
        """This is started when the cycle occurs, but is able to run."""
        log.append('step 2')

    @order.add_step(prereq=[Resource.A, Resource.B], results=[Resource.C])
    async def step_3(ctx: object) -> None:
        pytest.fail("Shouldn't run.")

    @order.add_step(prereq=[Resource.C], results=[Resource.B])
    async def step_4(ctx: object) -> None:
        pytest.fail("Shouldn't run.")

    with pytest.raises(CycleError):
        await order.run(None)

    assert log == ['step 1', 'step 2']  # These still ran.
