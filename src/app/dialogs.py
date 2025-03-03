"""API for dialog boxes."""
from typing import ClassVar, Literal

from collections.abc import Callable
from enum import Enum
import abc

from transtoken import AppError, TransToken


type Btn3 = Literal[0, 1, 2]
DEFAULT_TITLE = TransToken.ui('BEEmod')
# Here to allow reuse, and for WX to use builtin if possible.
TRANS_BTN_SKIP = TransToken.ui('Skip')
TRANS_BTN_DISCARD = TransToken.ui('Discard')
TRANS_BTN_QUIT = TransToken.ui('Quit')


class Icon(Enum):
    """Kind of icon to display."""
    INFO = "info"
    QUESTION = "question"
    ERROR = "error"
    WARNING = "warning"

# Also can be exposed from TK: abort/retry/ignore, retry/cancel.
# Messageboxes have a default button.


def validate_non_empty(value: str) -> str:
    """Check that the prompt has a value."""
    if not value.strip():
        raise AppError(TransToken.ui("A value must be provided!"))
    return value


class Dialogs(abc.ABC):
    """Interface exposed by ui_*.dialogs.

    This is passed in to processing code, allowing it to do some basic UI interaction.
    These block in Tkinter, but they're still async in case other libs can avoid that.
    """
    INFO: ClassVar[Literal[Icon.INFO]]
    ERROR: ClassVar[Literal[Icon.ERROR]]
    QUESTION: ClassVar[Literal[Icon.QUESTION]]
    WARNING: ClassVar[Literal[Icon.WARNING]]

    @abc.abstractmethod
    async def show_info(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> None:
        """Show a message box with some information."""

        raise NotImplementedError

    @abc.abstractmethod
    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        raise NotImplementedError

    @abc.abstractmethod
    async def ask_yes_no(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool:
        """Show a message box with "Yes" and "No" buttons."""
        raise NotImplementedError

    @abc.abstractmethod
    async def ask_yes_no_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool | None:
        """Show a message box with "Yes", "No" and "Cancel" buttons."""
        raise NotImplementedError

    @abc.abstractmethod
    async def ask_custom(
        self,
        message: TransToken,
        button_1: TransToken,
        button_2: TransToken,
        button_3: TransToken | None = None,
        *,
        cancel: Btn3,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
    ) -> Btn3:
        """Show a message box with 2 or 3 custom buttons.

        The button passed to cancel will be returned if the X is pressed.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def prompt(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        initial_value: TransToken = TransToken.BLANK,
        validator: Callable[[str], str] = validate_non_empty,
    ) -> str | None:
        """Ask the user to enter a string."""
        raise NotImplementedError

    @abc.abstractmethod
    async def ask_open_filename(
        self,
        title: TransToken = DEFAULT_TITLE,
        file_types: tuple[TransToken, str] | None = None,
    ) -> str:
        """Ask the user to open a filename, optionally with a file filter.

        The filter should be a description, plus an extension like `.txt`.
        """
        raise NotImplementedError


async def test_generic_msg(dialog: Dialogs) -> None:
    """Test the dialog implementation for messageboxes."""
    import pytest
    # No need to translate tests.
    tt = TransToken.untranslated

    await dialog.show_info(tt("Info dialog."))
    await dialog.show_info(tt("Question dialog"), title=tt("A title"), icon=Icon.QUESTION)
    await dialog.show_info(tt("Warning dialog"), title=tt("A title"), icon=Icon.WARNING)
    await dialog.show_info(tt("Error dialog"), title=tt("A title"), icon=Icon.ERROR)

    assert await dialog.ask_ok_cancel(tt("Press Ok for warning"), icon=Icon.WARNING) is True
    assert await dialog.ask_ok_cancel(tt("Press Cancel for error"), icon=Icon.ERROR) is False
    assert await dialog.ask_ok_cancel(tt("Press X")) is False

    assert await dialog.ask_yes_no(tt("Press Yes for question"), icon=Icon.QUESTION) is True
    assert await dialog.ask_yes_no(tt("Press No for warning"), icon=Icon.WARNING) is False

    assert await dialog.ask_yes_no_cancel(tt("Press yes")) is True
    assert await dialog.ask_yes_no_cancel(tt("Press no")) is False
    assert await dialog.ask_yes_no_cancel(tt("Press cancel")) is None
    assert await dialog.ask_yes_no_cancel(tt("Press X")) is None

    left = tt("Left")
    mid = tt("Center")
    right = tt("Right")

    with pytest.raises(ValueError):
        await dialog.ask_custom(tt("Invalid cancellation"), left, right, cancel=2)

    assert await dialog.ask_custom(tt("Press Left for info"), left, right, icon=Icon.INFO, cancel=0) == 0
    assert await dialog.ask_custom(tt("Press Right for question"), left, right, icon=Icon.QUESTION, cancel=1) == 1
    assert await dialog.ask_custom(tt("Press X for warning"), left, right, icon=Icon.WARNING, cancel=0) == 0
    assert await dialog.ask_custom(tt("Press X for error"), left, right, icon=Icon.ERROR, cancel=1) == 1

    cancel: Literal[0, 1, 2]
    for cancel in (0, 1, 2):
        assert await dialog.ask_custom(tt("Press Left for info"), left, mid, right, icon=Icon.INFO, cancel=cancel) == 0
        assert await dialog.ask_custom(tt("Press Center for question"), left, mid, right, icon=Icon.QUESTION, cancel=cancel) == 1
        assert await dialog.ask_custom(tt("Press Right for warning"), left, mid, right, icon=Icon.WARNING, cancel=cancel) == 2
        assert await dialog.ask_custom(tt("Press X for error"), left, mid, right, icon=Icon.ERROR, cancel=cancel) == cancel


async def test_generic_prompt(dialog: Dialogs) -> None:
    """Test the dialog implementation for prompts."""
    # No need to translate tests.
    tt = TransToken.untranslated

    def test_validator(value: str) -> str:
        """Testing validator."""
        validate_non_empty(value)
        if not value.isupper():
            raise AppError(TransToken.untranslated('Value must be uppercase!'))
        return value.lower()

    res = await dialog.prompt(
        tt('Test lowercase is banned, then enter "HELLO"'),
        title=tt("A title"),
        initial_value=tt('lowercase'),
        validator=test_validator,
    )
    assert res == 'hello', repr(res)

    res = await dialog.prompt(tt('Press cancel'))
    assert res is None, repr(res)

    res = await dialog.prompt(tt('Press X'))
    assert res is None, repr(res)


async def test_generic_files(dialog: Dialogs) -> None:
    """Test the dialog implementation for file windows."""
    # No need to translate tests.
    tt = TransToken.untranslated
    res = await dialog.ask_open_filename(title=tt('Pick any file'))
    print(f'Picked: {res!r}')
    res = await dialog.ask_open_filename(
        title=tt('Pick a PNG image'),
        file_types=(tt('PNG images'), '.png'),
    )
    print(f'Picked: {res!r}')
