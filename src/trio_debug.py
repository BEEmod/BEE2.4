"""Instrumentation which outputs statistics about Trio tasks."""
from typing import Any
from typing_extensions import override

import pprint
import time
import types

from aioresult import ResultCapture
import srctools.logger
import trio


LOGGER = srctools.logger.get_logger(__name__)


class SmallRepr(pprint.PrettyPrinter):
    """Exclude values with large reprs."""
    @override
    def format(
        self,
        object: object,
        context: dict[int, Any],
        maxlevels: int,
        level: int,
    ) -> tuple[str, bool, bool]:
        """Format each sub-item."""
        if isinstance(object, ResultCapture):
            return self.format((
                'ResultCapture',
                object.routine,
                *object.args,
            ), context, maxlevels, level)

        result, readable, recursive = super().format(object, context, maxlevels, level)
        if len(result) > 200 and level > 0:
            return f'{type(object).__qualname__}(...)', False, False
        else:
            return result, readable, recursive


class Tracer(trio.abc.Instrument):
    """Track tasks to detect slow ones."""
    def __init__(self) -> None:
        self.slow: list[tuple[float, str]] = []
        self.blocking: list[tuple[float, str]] = []
        self.elapsed: dict[trio.lowlevel.Task, float] = {}
        # (time, line number)
        self.start_point: dict[trio.lowlevel.Task, tuple[float, int]] = {}
        self.args: dict[trio.lowlevel.Task, dict[str, object]] = {}
        self.formatter = SmallRepr(compact=True)

    @staticmethod
    def _get_coro(task: trio.lowlevel.Task) -> types.CoroutineType:
        """Assert that the task's coroutine is a Python coroutine."""
        assert isinstance(task.coro, types.CoroutineType)
        return task.coro

    def _get_linenum(self, task: trio.lowlevel.Task) -> int:
        coro = self._get_coro(task)
        if (frame := coro.cr_frame) is not None:
            return frame.f_lineno
        else:
            return coro.cr_code.co_firstlineno

    @override
    def task_spawned(self, task: trio.lowlevel.Task) -> None:
        """Setup vars when a task is spawned."""
        self.elapsed[task] = 0.0
        if (frame := self._get_coro(task).cr_frame) is not None:
            self.args[task] = frame.f_locals.copy()
        else:
            self.args[task] = {'???': '???'}

    @override
    def before_task_step(self, task: trio.lowlevel.Task) -> None:
        """Begin timing this task."""
        self.start_point[task] = time.perf_counter(), self._get_linenum(task)

    @override
    def after_task_step(self, task: trio.lowlevel.Task) -> None:
        """Count up the time."""
        cur_time = time.perf_counter()
        try:
            start = self.start_point.pop(task)
        except KeyError:
            pass
        else:
            prev, start_line = start
            change = cur_time - prev
            self.elapsed[task] += change
            if change > (5/1000):
                self.blocking.append((
                    change,
                    f'Block for={change*1000:.02f}ms: '
                    f'{task!r}:{start_line}-{self._get_linenum(task)}, '
                    f'args={self.get_args(task)}'
                ))

    @override
    def task_exited(self, task: trio.lowlevel.Task) -> None:
        """Log results when exited."""
        cur_time = time.perf_counter()
        elapsed = self.elapsed.pop(task, 0.0)
        start = self.start_point.pop(task, None)
        if start is not None:
            prev, _ = start
            elapsed += cur_time - prev

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
        if not self.slow and not self.blocking:
            return

        LOGGER.info('Slow tasks\n{}', '\n'.join([
            msg for _, msg in
            sorted(self.slow, key=lambda t: t[0], reverse=True)
        ]))
        LOGGER.info('Blocking tasks\n{}', '\n'.join([
            msg for _, msg in
            sorted(self.blocking, key=lambda t: t[0], reverse=True)
        ]))
