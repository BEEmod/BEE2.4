
from app import TK_ROOT
from transtoken import TransToken
from ui_tk.dialogs import DIALOG


async def test() -> None:
    TK_ROOT.deiconify()

    tt = TransToken.untranslated

    await DIALOG.show_info(tt("Info dialog."))
    await DIALOG.show_info(tt("Question dialog"), title=tt("A title"), icon=DIALOG.QUESTION)
    await DIALOG.show_info(tt("Warning dialog"), title=tt("A title"), icon=DIALOG.WARNING)
    await DIALOG.show_info(tt("Error dialog"), title=tt("A title"), icon=DIALOG.ERROR)

    assert await DIALOG.ask_ok_cancel(tt("Press Ok for warning"), icon=DIALOG.WARNING) is True
    assert await DIALOG.ask_ok_cancel(tt("Press Cancel for error"), icon=DIALOG.ERROR) is False
    assert await DIALOG.ask_ok_cancel(tt("Press X")) is False

    assert await DIALOG.ask_yes_no(tt("Press Yes for question"), icon=DIALOG.QUESTION) is True
    assert await DIALOG.ask_yes_no(tt("Press No for warning"), icon=DIALOG.WARNING) is False

    assert await DIALOG.ask_yes_no_cancel(tt("Press yes")) is True
    assert await DIALOG.ask_yes_no_cancel(tt("Press no")) is False
    assert await DIALOG.ask_yes_no_cancel(tt("Press cancel")) is None
    assert await DIALOG.ask_yes_no_cancel(tt("Press X")) is None
