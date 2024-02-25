"""Options specifically for app development."""
from typing_extensions import NoReturn
from typing import Callable, Tuple
from tkinter import ttk
import tkinter as tk
import pprint

from exceptiongroup import ExceptionGroup
from srctools import logger
import attrs
import trio

from app import TK_ROOT, background_run, tk_tools
from ui_tk.img import TK_IMG, label_to_user
from ui_tk import wid_transtoken


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

    with open('../dev/widget_tree.txt', 'w') as f:
        dump(TK_ROOT, '')
    LOGGER.info('Dump done!')


def crasher(exc: BaseException) -> Tuple[Callable[[], object], Callable[[], object]]:
    """Make a function that raises an exception, to test crash handlers. This returns a sync and async pair."""
    def fg_raise() -> NoReturn:
        """Raise in the foreground."""
        raise exc

    async def bg_raise() -> NoReturn:
        """Raise in the background."""
        await trio.sleep(1)
        raise exc

    return fg_raise, lambda: background_run(bg_raise)


def make_menu(menu: tk.Menu) -> None:
    """Create the TK menu bar."""
    menu.add_command(label='Dump widgets', command=dump_widgets)
    menu.add_command(label='Stats', command=make_stats_window())

    menu.add_cascade(label='Crash', menu=(crash_menu := tk.Menu(menu)))

    fg_single, bg_single = crasher(NotImplementedError('Crashing time!'))
    fg_group, bg_group = crasher(ExceptionGroup('A group', [
        ZeroDivisionError('Divided'),
        BufferError('Buffer'),
        MemoryError('RAM'),
    ]))

    crash_menu.add_command(label='Sync, Singluar', command=fg_single)
    crash_menu.add_command(label='Sync, Grouped', command=fg_group)
    crash_menu.add_command(label='Async, Singular', command=bg_single)
    crash_menu.add_command(label='Async, Grouped', command=bg_group)


def make_stats_window() -> Callable[[], object]:
    """Create the statistics window."""
    cancel_scope = trio.CancelScope()
    window = tk.Toplevel(TK_ROOT, name='statsWin')
    window.withdraw()
    window.protocol("WM_DELETE_WINDOW", lambda: cancel_scope.cancel())  # Late binding.

    label = ttk.Label(window, name='info', text='...', font='TkFixedFont')
    window.grid_columnconfigure(0, weight=1)
    window.grid_rowconfigure(0, weight=1)
    label.grid(row=0, column=0, sticky='NSEW')
    ticker_lbl = ttk.Label(window, name='ticker', text='-')
    ticker_lbl.grid(row=1, column=0)

    async def open_window() -> None:
        """Display the statistics window."""
        nonlocal cancel_scope
        if window.winfo_ismapped():
            return  # Already visible.
        with trio.CancelScope() as cancel_scope:
            window.wm_deiconify()
            tk_tools.center_win(window, TK_ROOT)
            ticker = False
            while not cancel_scope.cancel_called:
                label['text'] = '\n'.join([
                    TK_IMG.stats(),
                    wid_transtoken.stats(),
                    'Trio = ' + pprint.pformat(
                        attrs.asdict(trio.lowlevel.current_statistics(), recurse=True)
                    ),
                ])
                ticker = not ticker
                ticker_lbl['text'] = '|' if ticker else '-'
                await trio.sleep(1.0)
        window.wm_withdraw()

    return lambda: background_run(open_window)
