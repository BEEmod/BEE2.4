"""API for dialog boxes."""
from typing import ClassVar, Protocol, Literal

from collections.abc import Callable
from enum import Enum

from transtoken import AppError, TransToken


DEFAULT_TITLE = TransToken.ui('BEEmod')


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


class Dialogs(Protocol):
    """Interface exposed by ui_*.dialogs.

    This is passed in to processing code, allowing it to do some basic UI interaction.
    These block in Tkinter, but they're still async in case other libs can avoid that.
    """
    INFO: ClassVar[Literal[Icon.INFO]]
    ERROR: ClassVar[Literal[Icon.ERROR]]
    WARNING: ClassVar[Literal[Icon.WARNING]]

    async def show_info(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> None:
        """Show a message box with some information."""

        raise NotImplementedError

    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str = '',
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        raise NotImplementedError

    async def ask_yes_no(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool:
        """Show a message box with "Yes" and "No" buttons."""
        raise NotImplementedError

    async def ask_yes_no_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str = '',
    ) -> bool | None:
        """Show a message box with "Yes", "No" and "Cancel" buttons."""
        raise NotImplementedError

    async def prompt(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        initial_value: TransToken = TransToken.BLANK,
        validator: Callable[[str], str] = validate_non_empty,
    ) -> str | None:
        """Ask the user to enter a string."""
