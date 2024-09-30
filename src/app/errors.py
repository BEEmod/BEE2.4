"""Handles displaying errors to the user that occur during operations."""
from typing import ClassVar, Protocol, Self, final

from collections.abc import Awaitable, Generator, Iterator
from contextlib import contextmanager
from enum import Enum, auto
import types


import srctools.logger
import trio

from transtoken import TransToken
from transtoken import AppError as AppError  # TODO: Move back to this module, once app no longer imports tk.


LOGGER = srctools.logger.get_logger(__name__)
DEFAULT_TITLE = TransToken.ui("BEEmod Error")
DEFAULT_ERROR_DESC = TransToken.ui_plural(
    "An error occurred while performing this task:",
    "Multiple errors occurred while performing this task:",
)
DEFAULT_WARN_DESC = TransToken.ui_plural(
    "An error occurred while performing this task, but it was partially successful:",
    "Multiple errors occurred while performing this task, but it was partially successful:",
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


type WarningExc = AppError | ExceptionGroup[Exception] | BaseExceptionGroup[BaseException]


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


async def console_handler(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
    """Implements an error handler which logs to the console. Useful for testing code."""
    LOGGER.error(
        '{!s}: {!s}',
        title, desc,
        exc_info=ExceptionGroup('', errors),
    )
    await trio.lowlevel.checkpoint()


@final
class ErrorUI:
    """A context manager which handles processing the errors."""
    title: TransToken
    error_desc: TransToken
    warn_desc: TransToken
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
        self, *,
        title: TransToken = DEFAULT_TITLE,
        error_desc: TransToken = DEFAULT_ERROR_DESC,
        warn_desc: TransToken = DEFAULT_WARN_DESC,
    ) -> None:
        """Create a UI handler. install_handler() must already be running."""
        if self._handler is None:
            LOGGER.warning("ErrorUI initialised with no handler running!")
        self.title = title
        self.error_desc = error_desc
        self.warn_desc = warn_desc
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

    def add(self, error: WarningExc | TransToken) -> None:
        """Log an error having occurred, while still continuing to run.

        The result will be PARTIAL at best.
        If an exception group is passed, this will extract the AppErrors, reraising others.
        A TransToken can be supplied for convenience, which is wrapped in an AppError.
        """
        match error:
            case TransToken():
                self._errors.append(AppError(error))
            case AppError():
                self._errors.append(error)
            case _:
                matching, rest = error.split(AppError)
                if matching is not None:
                    self._errors.extend(_collapse_excgroup(matching, False))
                if rest is not None:
                    raise rest

    async def __aenter__(self) -> Self:
        await trio.lowlevel.checkpoint()
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
            exc_val.fatal = True
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
            desc = self.error_desc if self._fatal_error else self.warn_desc
            desc = desc.format(n=len(self._errors))
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
                # This is a class-level callable, do not pass self.
                await ErrorUI._handler(self.title, desc, self._errors)
        return True
