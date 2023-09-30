"""Orders a series of steps, so certain resources are created before the steps that use them.

"""
from typing import Awaitable, Callable, Collection, Generic, Iterable, List, Set, Type, TypeVar
from collections import Counter
import math

import attrs
import srctools.logger
import trio


# The input parameter for all the steps, which contains all the inputs/outputs.
CtxT = TypeVar("CtxT")
# An enum which defines the resources passed in/out.
ResourceT = TypeVar("ResourceT")
Func = Callable[[CtxT], Awaitable[object]]
LOGGER = srctools.logger.get_logger(__name__)


class CycleError(Exception):
    """Raised if cyclic dependencies or other deadlocks occur."""


@attrs.define(eq=False, hash=False)
class Step(Generic[CtxT, ResourceT]):
    """Each individual step."""
    func: Func[CtxT]
    prereqs: Set[ResourceT]
    results: Collection[ResourceT]

    async def wrapper(
        self,
        ctx: CtxT,
        result_chan: trio.abc.SendChannel[Collection[ResourceT]],
    ) -> None:
        """Wraps the step functionality."""
        await self.func(ctx)
        await result_chan.send(self.results)


class StepOrder(Generic[CtxT, ResourceT]):
    """Orders a series of steps."""
    _steps: List[Step[CtxT, ResourceT]]
    _resources: Collection[ResourceT]
    _locked: bool

    def __init__(self, ctx_type: Type[CtxT], resources: Iterable[ResourceT]) -> None:
        """ctx_type is only defined to allow inferring the typevar."""
        self._steps = []
        self._resources = list(resources)
        self._locked = False

    def add_step(
        self,
        prereq: Collection[ResourceT],
        results: Collection[ResourceT],
    ) -> Callable[[Func[CtxT]], Func[CtxT]]:
        """Add a step."""
        if self._locked:
            raise RuntimeError("Cannot add steps after running has started.")

        def deco(func: Func[CtxT]) -> Func[CtxT]:
            """Decorate."""
            self._steps.append(Step(func, set(prereq), results))
            return func

        return deco

    async def run(self, ctx: CtxT) -> None:
        """Run the tasks."""
        self._locked = True
        # For each resource, the number of steps producing it that haven't been completed.
        awaiting_steps = Counter(result for step in self._steps for result in step.results)

        todo = list(self._steps)

        send: trio.MemorySendChannel[Collection[ResourceT]]
        rec: trio.MemoryReceiveChannel[Collection[ResourceT]]
        send, rec = trio.open_memory_channel(math.inf)
        completed: set[ResourceT] = set()
        running = 0
        LOGGER.info('Running {} steps.', len(todo))
        async with trio.open_nursery() as nursery:
            while todo:
                # Check if any steps have no prerequisites, and if so send them off.
                deferred: list[Step[CtxT, ResourceT]] = []
                for step in todo:
                    if step.prereqs <= completed:
                        LOGGER.debug('Starting step: {!r}', step)
                        nursery.start_soon(step.wrapper, ctx, send)
                        running += 1
                    else:
                        deferred.append(step)
                if running == 0 and len(todo) == len(deferred):
                    # A deadlock has occurred if we defer all steps, and there aren't any
                    # currently running. Either there's a dependency loop, or prerequisites
                    # without results to create them.
                    raise CycleError(f'Deadlock detected. Remaining tasks: {deferred}')
                todo = deferred

                # Wait for a step to complete, and account for its results.
                step_res = await rec.receive()
                running -= 1
                for res in step_res:
                    awaiting_steps[res] -= 1
                    if awaiting_steps[res] <= 0:
                        del awaiting_steps[res]  # Shrink, so values() skips this.
                        completed.add(res)
            # Once here, all steps have been started, so we can just wait for the nursery to close.
        LOGGER.info('Run complete.', len(todo))
