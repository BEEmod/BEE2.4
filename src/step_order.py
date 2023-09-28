"""Orders a series of steps, so certain resources are created before the steps that use them.

"""
import sys
from collections import Counter
from typing import Awaitable, Callable, Collection, Generic, List, Mapping, TypeVar, Union

import attrs
import trio


# The input parameter for all the steps, which contains all the inputs/outputs.
CtxT = TypeVar("CtxT")
# An enum which defines the resources passed in/out.
ResourceT = TypeVar("ResourceT")
Func = Callable[[CtxT], Awaitable[object]]


@attrs.define(eq=False, hash=False)
class Step(Generic[CtxT, ResourceT]):
    """Each individual step."""
    func: Func[CtxT]
    prereqs: Collection[ResourceT]
    results: Collection[ResourceT]

    async def wrapper(
        self,
        ctx: CtxT,
        events: Mapping[ResourceT, trio.Event],
        result_chan: trio.abc.SendChannel[ResourceT],
    ) -> None:
        """Wraps the step functionality."""
        for res in self.prereqs:
            await events[res].wait()
        await self.func(ctx)
        for res in self.results:
            await result_chan.send(res)


class StepOrder(Generic[CtxT, ResourceT]):
    """Orders a series of steps."""
    _steps: List[Step[CtxT, ResourceT]]
    _resources: Collection[ResourceT]
    _locked: bool

    def __init__(self, resources: Collection[ResourceT]) -> None:
        self._steps = []
        self._resources = resources
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
            self._steps.append(Step(func, prereq, results))
            return func

        return deco

    def check(self) -> None:
        """On dev, check there's no cycles."""
        if sys.version_info < (3, 11):
            return  # 3.11+ version will do the checking.
        from graphlib import TopologicalSorter
        sorter: TopologicalSorter[Union[Step[CtxT, ResourceT], ResourceT]] = TopologicalSorter()
        for step in self._steps:
            if len(step.prereqs) > 0:
                sorter.add(step, *step.prereqs)
            for res in step.results:
                sorter.add(res, step)
        sorter.prepare()

    async def run(self, ctx: CtxT) -> None:
        """Run the tasks."""
        if not self._locked:
            self.check()
        self._locked = True
        events = {
            res: trio.Event()
            for res in self._resources
        }
        awaiting_steps = Counter(prereq for step in self._steps for prereq in step.prereqs)

        send: trio.MemorySendChannel[ResourceT]
        rec: trio.MemoryReceiveChannel[ResourceT]
        send, rec = trio.open_memory_channel(0)
        async with trio.open_nursery() as nursery:
            for task in self._steps:
                nursery.start_soon(task.wrapper, ctx, events, send)
            async for res in rec:
                awaiting_steps[res] -= 1
                if awaiting_steps[res] <= 0:
                    events[res].set()
                    del awaiting_steps[res]  # Shrink, so values() skips this.
                    if not any(awaiting_steps.values()):
                        break
            rec.close()
