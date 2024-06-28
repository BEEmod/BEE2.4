import tkinter.constants

import trio

from transtoken import TransToken
from app.dialogs import test_generic
from ui_tk.dialogs import DIALOG
from ui_tk import TK_ROOT


async def test(core_nursery: trio.Nursery) -> None:
    """Test the TK implementation."""
    TK_ROOT.deiconify()

    label = tkinter.Label(TK_ROOT, text='Hello: |')
    label.pack()
    scope = trio.CancelScope()

    async def ticker() -> None:
        """Prove that the event loop is running."""
        with scope:
            while True:
                await trio.sleep(1.0)
                label['text'] = 'Hello: -'
                await trio.sleep(1.0)
                label['text'] = 'Hello: |'

    tt = TransToken.untranslated

    async with trio.open_nursery() as nursery:
        nursery.start_soon(ticker)

        await test_generic(DIALOG)

        scope.cancel()
