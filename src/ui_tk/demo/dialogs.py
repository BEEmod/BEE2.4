import tkinter.constants

import trio

from app.dialogs import test_generic_msg, test_generic_prompt, test_generic_files
from ui_tk.dialogs import DIALOG
from ui_tk import TK_ROOT


async def test(core_nursery: trio.Nursery) -> None:
    """Test the TK implementation."""
    TK_ROOT.deiconify()

    label = tkinter.Label(TK_ROOT, text='Hello: |')
    label.pack()

    tkinter.Button(
        TK_ROOT, text='Test messages',
        command=lambda: nursery.start_soon(test_generic_msg, DIALOG),
    ).pack()
    tkinter.Button(
        TK_ROOT, text='Test prompt',
        command=lambda: nursery.start_soon(test_generic_prompt, DIALOG),
    ).pack()
    tkinter.Button(
        TK_ROOT, text='Test file dialogs',
        command=lambda: nursery.start_soon(test_generic_files, DIALOG),
    ).pack()

    async with trio.open_nursery() as nursery:
        TK_ROOT.wm_protocol('WM_DELETE_WINDOW', nursery.cancel_scope.cancel)
        # Prove that the event loop is running.
        while True:
            await trio.sleep(1.0)
            label['text'] = 'Hello: -'
            await trio.sleep(1.0)
            label['text'] = 'Hello: |'
