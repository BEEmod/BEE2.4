"""Handles displaying errors to the user that occur during operations."""
from __future__ import annotations

from enum import Enum, auto
from typing import Awaitable, ClassVar, Generator, Iterator, Protocol, Union, final
from typing_extensions import TypeAlias
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


class Result(Enum):
    """Represents the result of the operation."""
    SUCCEEDED = auto()  # No errors at all.
    PARTIAL = auto()  # add() was called, no exceptions = was partially successful.
    FAILED = auto()  # An exception was raised, complete failure.

    @property
    def failed(self) -> bool:
        """Check if it failed."""
        return self.name in ['PARTIAL', 'FAILED']


@final
@attrs.define(init=False)
class AppError(Exception):
    """An error that occurs when using the app, that should be displayed to the user."""
    message: TransToken
    fatal: bool

    def __init__(self, message: TransToken) -> None:
        super().__init__(message)
        self.message = message
        self.fatal = False

    def __str__(self) -> str:
        return f"AppError: {self.message}"


class Handler(Protocol):
    """The signature of handler functions."""
    def __call__(self, title: TransToken, desc: TransToken, errors: list[AppError]) -> Awaitable[object]:
        ...


def _collapse_excgroup(group: BaseExceptionGroup[AppError], fatal: bool) -> Iterator[AppError]:
    """Extract all the ``AppError``s from this group.

    ``BaseExceptionGroup.subgroup()`` preserves the original structure, but we don't really care.
    ``fatal`` is applied to all yielded ``AppError``s.
    """
    for exc in group.exceptions:
        if isinstance(exc, BaseExceptionGroup):
            yield from _collapse_excgroup(exc, fatal)
        else:
            exc.fatal = fatal
            yield exc


@final
class ErrorUI:
    """A context manager which handles processing the errors."""
    title: TransToken
    desc: TransToken
    _errors: list[AppError]
    _fatal_error: bool  # If set, error was caught in __aexit__

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
        self._fatal_error = False

    def __repr__(self) -> str:
        return f"<ErrorUI, title={self.title}, {len(self._errors)} errors>"

    @property
    def result(self) -> Result:
        """Check the result of the operation."""
        if self._fatal_error:
            return Result.FAILED
        if self._errors:
            return Result.PARTIAL
        return Result.SUCCEEDED

    def add(self, error: AppError | ExceptionGroup[Exception] | BaseExceptionGroup[BaseException]) -> None:
        """Log an error having occurred, while still running code.

        If an exception group is passed, this will extract the AppErrors, reraising others.
        """
        if isinstance(error, AppError):
            self._errors.append(error)
        else:
            matching, rest = error.split(AppError)
            if matching is not None:
                self._errors.extend(_collapse_excgroup(matching, False))
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
        if exc_val is not None:
            # Any exception getting here means we failed.
            self._fatal_error = True

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
                    self._errors.extend(_collapse_excgroup(matching, True))

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
            if ErrorUI._handler is None:
                LOGGER.error(
                    "ErrorUI block failed, but no handler installed!\ntitle={}\ndesc={}\n{}",
                    self.title,
                    desc,
                    "\n".join([str(err.message) for err in self._errors]),
                )
            else:
                LOGGER.error(
                    "ErrorUI block failed.\ntitle={}\ndesc={}\n{}",
                    self.title,
                    desc,
                    "\n".join([str(err.message) for err in self._errors]),
                )
                # Use class, do not pass self!
                await ErrorUI._handler(self.title, desc, self._errors)
        return True
