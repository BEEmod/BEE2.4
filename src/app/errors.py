"""Handles displaying errors to the user that occur during operations."""
from __future__ import annotations
from typing import Awaitable, ClassVar, Generator, Iterator, Protocol, final
from contextlib import contextmanager
from exceptiongroup import BaseExceptionGroup, ExceptionGroup
import types

import attrs
import srctools.logger

from transtoken import TransToken


LOGGER = srctools.logger.get_logger(__name__)
DEFAULT_TITLE = TransToken.ui("BEEmod Error")
DEFAULT_DESC = TransToken.ui_plural(
    "An error occurred while performing this task:",
    "Multiple errors occurred while performing this task:",
)


@final
@attrs.define(init=False)
class AppError(Exception):
    """An error that occurs when using the app, that should be displayed to the user."""
    message: TransToken

    def __init__(self, message: TransToken) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return f"AppError: {self.message}"


class Handler(Protocol):
    """The signature of handler functions."""
    def __call__(self, title: TransToken, desc: TransToken, errors: list[AppError]) -> Awaitable[object]:
        ...


def _collapse_excgroup(group: BaseExceptionGroup[AppError]) -> Iterator[AppError]:
    """Extract all the AppErrors from this group.

    BaseExceptionGroup.subgroup() preserves the original structure, but we don't really care.
    """
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            yield from _collapse_excgroup(exc)
        else:
            yield exc

@final
class ErrorUI:
    """A context manager which handles processing the errors."""
    title: TransToken
    desc: TransToken
    _errors: list[AppError]

    _handler: ClassVar[Handler | None] = None

    @classmethod
    @contextmanager
    def install_handler(
        cls, handler: Handler,
    ) -> Generator[None, None, None]:
        """Install the handler for displaying errors."""
        if cls._handler is not None:
            raise ValueError("Handler already installed!")
        try:
            cls._handler = handler
            yield
        finally:
            cls._handler = None

    def __init__(
        self,
        title: TransToken = DEFAULT_TITLE,
        desc: TransToken = DEFAULT_DESC,
    ) -> None:
        """Create a UI handler. install_handler() must already be running."""
        if self._handler is None:
            LOGGER.warning("ErrorUI initialised with no handler running!")
        self.title = title
        self.desc = desc
        self._errors = []

    def __repr__(self) -> str:
        return f"<ErrorUI, title={self.title}, {len(self._errors)} errors>"

    @property
    def failed(self) -> bool:
        """Check if the operation has failed."""
        return bool(self._errors)

    def add(self, error: AppError | ExceptionGroup | BaseExceptionGroup) -> None:
        """Log an error having occurred, while still running code.

        If an exception group is passed, this will extract the AppErrors, reraising others.
        """
        if isinstance(error, AppError):
            self._errors.append(error)
        else:
            matching, rest = error.split(AppError)
            if matching is not None:
                self._errors.extend(_collapse_excgroup(matching))
            if rest is not None:
                raise rest

    async def __aenter__(self) -> ErrorUI:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> bool:
        if isinstance(exc_val, AppError):
            self._errors.append(exc_val)
            exc_val = None
        elif isinstance(exc_val, BaseExceptionGroup):
            matching, rest = exc_val.split(AppError)
            # We only handle if it's all AppError. If not, re-raise it unchanged.
            if rest is None:
                # Swallow.
                exc_val = None
                # Matching may be recursively nested exceptions, collapse all that.
                if matching is not None:
                    self._errors.extend(_collapse_excgroup(matching))

        if exc_val is not None:
            # Caught something else, don't suppress.
            if self._errors:
                # Combine both in an exception group.
                raise BaseExceptionGroup(
                    "ErrorUI block raised",
                    [*self._errors, exc_val],
                )

            # Just some other exception, leave it unaltered.
            return False

        if self._errors:
            desc = self.desc.format(n=len(self._errors))
            # We had an error.
            if self._handler is None:
                LOGGER.error(
                    "ErrorUI block failed, but no handler installed!\ntitle={}\ndesc={}\n{}",
                    self.title,
                    desc,
                    "\n".join(map(str, self._errors)),
                )
            else:
                LOGGER.error(
                    "ErrorUI block failed.\ntitle={}\ndesc={}\n{}",
                    self.title,
                    desc,
                    "\n".join(map(str, self._errors)),
                )
                # Do NOT pass self!
                await ErrorUI._handler(self.title, desc, self._errors)
        return True
