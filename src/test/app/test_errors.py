"""Test the ErrorUI handling system."""

import pytest
import trio.lowlevel

from app.errors import ErrorUI, Result
from transtoken import AppError, TransToken


@pytest.fixture(scope="module", autouse=True)
def _reset_handler() -> None:
    """To ensure only relevant tests fail, reset the handler manually."""
    print("Resetting handler.")
    ErrorUI._handler = None


def test_exception() -> None:
    """Test the exception behaviour."""
    msg = TransToken.untranslated("The message")

    err = AppError(msg)
    assert err.message is msg
    assert err.args == (msg, )

    assert str(err) == "AppError: The message"


async def handler_fail(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
    """Should never be used."""
    await trio.lowlevel.checkpoint()
    pytest.fail("Handler called!")


def test_handler_install() -> None:
    """Test installing correctly prevents reentrancy and handles exceptions."""
    assert ErrorUI._handler is None
    with ErrorUI.install_handler(handler_fail):
        assert ErrorUI._handler is handler_fail

    assert ErrorUI._handler is None

    with pytest.raises(ZeroDivisionError):
        assert ErrorUI._handler is None
        with ErrorUI.install_handler(handler_fail):
            assert ErrorUI._handler is handler_fail
            raise ZeroDivisionError

    assert ErrorUI._handler is None

    with ErrorUI.install_handler(handler_fail):
        with pytest.raises(ValueError, match="already installed"):
            with ErrorUI.install_handler(handler_fail):
                pass
        assert ErrorUI._handler is handler_fail
    assert ErrorUI._handler is None


async def test_success() -> None:
    """Test code running successfully."""
    with ErrorUI.install_handler(handler_fail):
        async with ErrorUI() as error_block:
            pass
        assert error_block.result is Result.SUCCEEDED
    assert ErrorUI._handler is None


async def test_nonfatal() -> None:
    """Test the behaviour of non-fatal .add() errors."""
    orig_title = TransToken.untranslated("The title")
    orig_error = TransToken.untranslated("nonfatal error, n={n}")
    orig_warn = TransToken.untranslated("nonfatal warn, n={n}")
    caught_errors: list[AppError] = []

    async def catch(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
        """Catch the errors that occur."""
        assert title is orig_title
        assert str(desc) == "nonfatal warn, n=5"
        caught_errors.extend(errors)
        await trio.lowlevel.checkpoint()

    exc1 = AppError(TransToken.untranslated("Error 1"))
    exc2 = AppError(TransToken.untranslated("Error 2"))
    exc3 = AppError(TransToken.untranslated("Error 3"))
    exc4 = AppError(TransToken.untranslated("Error 4"))
    exc5 = AppError(TransToken.untranslated("Error 5"))
    unrelated = BufferError("Whatever")

    task: list[str] = []
    with ErrorUI.install_handler(catch):
        async with ErrorUI(title=orig_title, error_desc=orig_error, warn_desc=orig_warn) as error_block:
            assert error_block.result is Result.SUCCEEDED
            task.append("before")

            error_block.add(exc1)
            # Enum assert above makes Mypy think this cannot occur.
            assert error_block.result is Result.PARTIAL  # type: ignore[comparison-overlap]
            task.append("mid")

            error_block.add(ExceptionGroup("two", [
                exc2,
                ExceptionGroup("three", [exc3]),
            ]))
            # Does not raise.

            with pytest.raises(ExceptionGroup) as reraised:
                error_block.add(ExceptionGroup("stuff", [
                    exc4,
                    ExceptionGroup("more", [exc5]),
                    unrelated,
                ]))
            # unrelated should have been re-raised.
            assert isinstance(reraised.value, ExceptionGroup)
            assert reraised.value.message == "stuff"
            assert reraised.value.exceptions == (unrelated, )

            task.append("after")
            assert error_block.result is Result.PARTIAL  # We caught the rest, not fatal.
        success = True  # The async-with did not raise.

    assert success
    assert task == ["before", "mid", "after"]
    assert error_block.result is Result.PARTIAL
    assert caught_errors == [exc1, exc2, exc3, exc4, exc5]


async def test_fatal_only_err() -> None:
    """Test raising only an AppError inside the block."""
    orig_title = TransToken.untranslated("The title")
    orig_error = TransToken.untranslated("fatal_only_error error, n={n}")
    orig_warn = TransToken.untranslated("fatal_only_error warn, n={n}")
    caught_errors: list[AppError] = []

    async def catch(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
        """Catch the errors that occur."""
        assert title is orig_title
        assert str(desc) == "fatal_only_error error, n=2"
        caught_errors.extend(errors)
        await trio.lowlevel.checkpoint()

    exc1 = AppError(TransToken.untranslated("Error 1"))
    exc2 = AppError(TransToken.untranslated("Error 2"))

    task: list[str] = []
    with ErrorUI.install_handler(catch):
        async with ErrorUI(title=orig_title, error_desc=orig_error, warn_desc=orig_warn) as error_block:
            assert error_block.result is Result.SUCCEEDED
            task.append("before")

            error_block.add(exc1)
            assert error_block.result is Result.PARTIAL  # type: ignore[comparison-overlap]
            task.append("mid")

            raise exc2

    assert task == ["before", "mid"]
    assert error_block.result is Result.FAILED
    assert caught_errors == [exc1, exc2]


async def test_fatal_exc() -> None:
    """Test raising some exception, after nonfatal errors were added."""
    exc = AppError(TransToken.untranslated("Some Error"))
    unrelated = LookupError("something")

    task: list[str] = []
    with pytest.raises(ExceptionGroup) as group_catch, ErrorUI.install_handler(handler_fail):
        async with ErrorUI() as error_block:
            assert error_block.result is Result.SUCCEEDED
            task.append("before")

            error_block.add(exc)
            assert error_block.result is Result.PARTIAL  # type: ignore[comparison-overlap]
            task.append("mid")

            raise unrelated

    assert isinstance(group_catch.value, ExceptionGroup)
    assert error_block.result is Result.FAILED
    assert group_catch.value.message == "ErrorUI block raised"
    assert group_catch.value.exceptions == (exc, unrelated)


async def test_fatal_group() -> None:
    """Test raising both an AppError and other exception inside the block."""
    exc1 = AppError(TransToken.untranslated("Error 1"))
    exc2 = AppError(TransToken.untranslated("Error 2"))
    unrelated = LookupError("something")
    group = ExceptionGroup("group name", [exc2, unrelated])

    task: list[str] = []
    with pytest.raises(ExceptionGroup) as group_catch, ErrorUI.install_handler(handler_fail):
        async with ErrorUI() as error_block:
            assert error_block.result is Result.SUCCEEDED
            task.append("before")

            error_block.add(exc1)
            assert error_block.result is Result.PARTIAL  # type: ignore[comparison-overlap]
            task.append("mid")

            raise group

    assert isinstance(group_catch.value, ExceptionGroup)
    assert error_block.result is Result.FAILED
    assert group_catch.value.message == "ErrorUI block raised"
    assert group_catch.value.exceptions == (exc1, group)
    # No special handling, exc2 doesn't make it in.


async def test_cancel() -> None:
    """Test cancelling the error handler is detected."""
    with ErrorUI.install_handler(handler_fail), trio.CancelScope() as scope:
        async with ErrorUI() as error_block:
            assert error_block.result is Result.SUCCEEDED
            scope.cancel()
            await trio.lowlevel.checkpoint()
            raise AssertionError('Not cancelled?')
    assert error_block.result is Result.CANCELLED


async def test_multi_cancel(autojump_clock: trio.abc.Clock) -> None:
    """Test a cancellation while another exception is raised."""
    with (
        pytest.raises(BaseExceptionGroup) as group,
        ErrorUI.install_handler(handler_fail),
        trio.CancelScope() as scope,
    ):
        async with ErrorUI() as error_block:
            assert error_block.result is Result.SUCCEEDED
            scope.cancel()
            try:
                await trio.lowlevel.checkpoint()
            except trio.Cancelled as cancelled:
                # Simulate exception group.
                raise BaseExceptionGroup('Combined', [
                    BufferError(),
                    BaseExceptionGroup('Child', [cancelled, ZeroDivisionError()])
                ]) from None
            raise AssertionError('Not cancelled?')
    assert error_block.result is Result.FAILED
    assert group.group_contains(BufferError)
    assert group.group_contains(ZeroDivisionError)
