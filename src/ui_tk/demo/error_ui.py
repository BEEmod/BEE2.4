from tkinter import ttk

import trio

from app.errors import ErrorUI
from transtoken import AppError, TransToken
from ui_tk import TK_ROOT


async def test(core_nursery: trio.Nursery) -> None:
    """Test the ErrorUI display."""
    tt = TransToken.untranslated

    async def single_warn() -> None:
        """Display a single warning message."""
        async with ErrorUI() as errors:
            errors.add(tt('A single warning message\nwith multiple lines.'))

    async def multi_warn() -> None:
        """Display multiple warnning messages."""
        async with ErrorUI() as errors:
            for i in range(1, 11):
                errors.add(tt(f'Warning message #{i}'))

    async def single_error() -> None:
        """Display a single error."""
        async with ErrorUI():
            raise AppError(tt('A fatal error\nwith lots\nand lots and lots and lots of text'))

    async def multi_error() -> None:
        """Display multiple errors."""
        async with ErrorUI() as errors:
            errors.add(tt('A warning'))
            errors.add(tt('Another warning'))
            raise ExceptionGroup('Fail', [
                AppError(tt('The first error\nwith multiple lines.')),
                AppError(tt('The second error\nwith multiple lines, '
                            'this one has lots and lots and lots of text.')),
            ])

    async with trio.open_nursery() as nursery:
        TK_ROOT.deiconify()
        ttk.Button(
            TK_ROOT,
            text='Single Warn',
            command=lambda: nursery.start_soon(single_warn)
        ).grid(row=0, column=0, padx=(16, 4), pady=(16, 4))
        ttk.Button(
            TK_ROOT,
            text='Multi Warn',
            command=lambda: nursery.start_soon(multi_warn)
        ).grid(row=1, column=0, padx=(16, 4), pady=(4, 16))
        ttk.Button(
            TK_ROOT,
            text='Single Error',
            command=lambda: nursery.start_soon(single_error)
        ).grid(row=0, column=1, padx=(4, 16), pady=(16, 4))
        ttk.Button(
            TK_ROOT,
            text='Multi Error',
            command=lambda: nursery.start_soon(multi_error)
        ).grid(row=1, column=1, padx=(4, 16), pady=(4, 16))

        with trio.CancelScope() as scope:
            TK_ROOT.wm_protocol('WM_DELETE_WINDOW', scope.cancel)
            await trio.sleep_forever()
