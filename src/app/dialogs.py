"""API for dialog boxes."""
from enum import Enum
from typing import ClassVar, Optional, Protocol, Literal

from transtoken import TransToken


DEFAULT_TITLE = TransToken.ui('BEEmod')


class Icon(Enum):
    """Kind of icon to display."""
    INFO = "info"
    QUESTION = "question"
    ERROR = "error"
    WARNING = "warning"

# Also can be exposed from TK: abort/retry/ignore, retry/cancel.
# Messageboxes have a default button.


class Dialogs(Protocol):
    """Interface exposed by ui_*.dialogs.

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
        detail: str='',
    ) -> None:
        """Show a message box with some information."""

        raise NotImplementedError

    async def ask_ok_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.INFO,
        detail: str='',
    ) -> bool:
        """Show a message box with "OK" and "Cancel" buttons."""
        raise NotImplementedError

    async def ask_yes_no(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str='',
    ) -> bool:
        """Show a message box with "Yes" and "No" buttons."""
        raise NotImplementedError

    async def ask_yes_no_cancel(
        self,
        message: TransToken,
        title: TransToken = DEFAULT_TITLE,
        icon: Icon = Icon.QUESTION,
        detail: str='',
    ) -> Optional[bool]:
        """Show a message box with "Yes", "No" and "Cancel" buttons."""
        raise NotImplementedError
