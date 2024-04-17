"""Options specifically for app development."""
from __future__ import annotations
from typing_extensions import NoReturn
from collections.abc import Callable
from tkinter import ttk
import tkinter as tk
import pprint

from exceptiongroup import ExceptionGroup
from srctools import logger
import attrs
import trio
import trio_util

from app import TK_ROOT, tk_tools
from ui_tk.img import TK_IMG, label_to_user
from ui_tk import wid_transtoken
import utils


LOGGER = logger.get_logger(__name__)


def dump_widgets() -> None:
    """Dump a tree of widgets."""

    def dump(widget: tk.Misc, indent: str) -> None:
        """Dump em."""
        f.write(f'{indent}{widget} ({type(widget).__qualname__})')
        if widget in label_to_user:
            f.write(f'.img = {label_to_user[widget].cur_handle!r}')  # type: ignore
        children = widget.winfo_children()
        if children:
            indent += '\t'
            f.write(': [\n')
            for child in children:
                dump(child, indent)
            f.write(indent + ']\n')
        else:
            f.write('\n')

    with open('../reports/widget_tree.txt', 'w') as f:
        dump(TK_ROOT, '')
    LOGGER.info('Dump done!')


def dump_tasktree() -> str:
    """Write out the full tree of tasks."""
    try:
        import stackscope
    except ImportError:
        # Don't add this as a dependency.
        return '<No stackscope module>'
    stack = stackscope.extract(trio.lowlevel.current_root_task(), recurse_child_tasks=True)
    with open('../reports/tasks.txt', 'w', encoding='utf8') as f:
        f.write(str(stack))
    return str(stack)


def stats_trio() -> str:
    """Include trio's stats."""
    return 'Trio = ' + pprint.pformat(
        attrs.asdict(trio.lowlevel.current_statistics(), recurse=True)
    )


def crasher(nursery: trio.Nursery, exc: BaseException) -> tuple[Callable[[], object], Callable[[], object]]:
    """Make a function that raises an exception, to test crash handlers. This returns a sync and async pair."""
    def fg_raise() -> NoReturn:
        """Raise in the foreground."""
        raise exc

    async def bg_raise() -> NoReturn:
        """Raise in the background."""
        await trio.sleep(1)
        raise exc

    return fg_raise, lambda: nursery.start_soon(bg_raise)


async def menu_task(menu: tk.Menu) -> None:
    """Create the TK menu bar."""
    async with trio.open_nursery() as nursery:
        fg_single, bg_single = crasher(nursery, NotImplementedError('Crashing time!'))
        fg_group, bg_group = crasher(nursery, ExceptionGroup('A group', [
            ZeroDivisionError('Divided'),
            BufferError('Buffer'),
            MemoryError('RAM'),
        ]))

        menu.add_command(label='Dump widgets', command=dump_widgets)
        menu.add_command(label='Stats', command=await nursery.start(stats_window_task))
        menu.add_command(label='Dump Tasks', command=dump_tasktree)

        menu.add_cascade(label='Crash', menu=(crash_menu := tk.Menu(menu)))

        crash_menu.add_command(label='Sync, Singluar', command=fg_single)
        crash_menu.add_command(label='Sync, Grouped', command=fg_group)
        crash_menu.add_command(label='Async, Singular', command=bg_single)
        crash_menu.add_command(label='Async, Grouped', command=bg_group)
        await trio.sleep_forever()


async def stats_window_task(task_status: trio.TaskStatus[Callable[[], object]]) -> None:
    """Create the statistics window."""
    window = tk.Toplevel(TK_ROOT, name='statsWin')
    window.withdraw()

    label = ttk.Label(window, name='info', text='...', font='TkFixedFont')
    window.grid_columnconfigure(0, weight=1)
    window.grid_rowconfigure(0, weight=1)
    label.grid(row=0, column=0, sticky='NSEW')
    ticker_lbl = ttk.Label(window, name='ticker', text='-')
    ticker_lbl.grid(row=1, column=0)

    open_val = trio_util.AsyncBool()
    window.protocol("WM_DELETE_WINDOW", utils.val_setter(open_val, False))

    stat_funcs = [
        TK_IMG.stats,
        wid_transtoken.stats,
        stats_trio,
    ]

    task_status.started(utils.val_setter(open_val, True))
    while True:
        await open_val.wait_value(True)
        window.wm_deiconify()
        tk_tools.center_win(window, TK_ROOT)
        ticker = False
        async with trio_util.move_on_when(open_val.wait_value, False):
            while True:
                label['text'] = '\n'.join([func() for func in stat_funcs])
                ticker = not ticker
                ticker_lbl['text'] = '|' if ticker else '-'
                await trio.sleep(1.0)
        window.wm_withdraw()
