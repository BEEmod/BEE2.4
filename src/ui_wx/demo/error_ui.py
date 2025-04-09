"""Test the errorUI display."""
from collections.abc import Awaitable, Callable

import trio
import wx

from ui_wx import MAIN_WINDOW
from app.errors import ErrorUI
from transtoken import AppError, TransToken


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
        async with ErrorUI():
            raise ExceptionGroup('Fail', [
                AppError(tt('The first error\nwith multiple lines.')),
                AppError(tt('The second error\nwith multiple lines, '
                            'this one has lots and lots and lots of text.')),
            ])

    sizer = wx.BoxSizer(wx.VERTICAL)

    def add(label: str, func: Callable[[], Awaitable[None]]) -> None:
        """Add a button."""
        button = wx.Button(MAIN_WINDOW, label=label)
        button.Bind(wx.EVT_BUTTON, lambda evt: nursery.start_soon(func))
        sizer.Add(button, wx.SizerFlags().Left())

    add('Single Warn', single_warn)
    add('Multi Warn', multi_warn)
    add('Single Error', single_error)
    add('Multi Error', multi_error)
    MAIN_WINDOW.SetSizerAndFit(sizer)
    MAIN_WINDOW.Layout()

    async with trio.open_nursery() as nursery:
        MAIN_WINDOW.Bind(wx.EVT_CLOSE, lambda evt: nursery.cancel_scope.cancel())
        MAIN_WINDOW.Show()
        await trio.sleep_forever()
