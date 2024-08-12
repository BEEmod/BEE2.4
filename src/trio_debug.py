"""Instrumentation which outputs statistics about Trio tasks."""
from typing_extensions import override
from typing import Any
import pprint
import time

from aioresult import ResultCapture
import srctools.logger
import trio


LOGGER = srctools.logger.get_logger(__name__)


class SmallRepr(pprint.PrettyPrinter):
    """Exclude values with large reprs."""
    @override
    def format(
        self,
        target: object,
        context: dict[int, Any],
        maxlevels: int,
        level: int,
        /,
    ) -> tuple[str, bool, bool]:
        """Format each sub-item."""
        if isinstance(target, ResultCapture):
            return self.format((
                'ResultCapture',
                target.routine,
                *target.args,
            ), context, maxlevels, level)

        result, readable, recursive = super().format(target, context, maxlevels, level)
        if len(result) > 200 and level > 0:
            return f'{type(target).__qualname__}(...)', False, False
        else:
            return result, readable, recursive


class Tracer(trio.abc.Instrument):
    """Track tasks to detect slow ones."""
    def __init__(self) -> None:
        self.slow: list[tuple[float, str]] = []
        self.elapsed: dict[trio.lowlevel.Task, float] = {}
        self.start_time: dict[trio.lowlevel.Task, float | None] = {}
        self.args: dict[trio.lowlevel.Task, dict[str, object]] = {}
        self.formatter = SmallRepr(compact=True)

    @override
    def task_spawned(self, task: trio.lowlevel.Task) -> None:
        """Setup vars when a task is spawned."""
        self.elapsed[task] = 0.0
        self.start_time[task] = None
        if task.coro.cr_frame is not None:
            self.args[task] = task.coro.cr_frame.f_locals.copy()
        else:
            self.args[task] = {'???': '???'}

    @override
    def before_task_step(self, task: trio.lowlevel.Task) -> None:
        """Begin timing this task."""
        self.start_time[task] = time.perf_counter()

    @override
    def after_task_step(self, task: trio.lowlevel.Task) -> None:
        """Count up the time."""
        cur_time = time.perf_counter()
        try:
            prev = self.start_time[task]
        except KeyError:
            pass
        else:
            if prev is not None:
                change = cur_time - prev
                self.elapsed[task] += change
                self.start_time[task] = None
                if change > (5/1000):
                    LOGGER.warning(
                        'Task didn\'t yield ({:.02f}ms): {!r}:{}, args={}',
                        change*1000,
                        task, task.coro.cr_code.co_firstlineno,
                        self.get_args(task),
                    )

    @override
    def task_exited(self, task: trio.lowlevel.Task) -> None:
        """Log results when exited."""
        cur_time = time.perf_counter()
        elapsed = self.elapsed.pop(task, 0.0)
        start = self.start_time.pop(task, None)
        if start is not None:
            elapsed += cur_time - start

        if elapsed > 0.1:
            self.slow.append((elapsed, f'Task time={elapsed:.06}: {task!r}, args={self.get_args(task)}'))
        self.args.pop(task, None)

    def get_args(self, task: trio.lowlevel.Task) -> object:
        """Get the args for a task."""
        args = self.args.pop(task, srctools.EmptyMapping)
        return self.formatter.pformat({
            name: val
            for name, val in args.items()
            if 'KI_PROTECTION' not in name  # Trio flag.
        })

    def display_slow(self) -> None:
        """Print out a list of 'slow' tasks."""
        if not self.slow:
            return

        LOGGER.info('Slow tasks\n{}', '\n'.join([
            msg for _, msg in
            sorted(self.slow, key=lambda t: t[1], reverse=True)
        ]))
