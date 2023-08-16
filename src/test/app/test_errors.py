from exceptiongroup import ExceptionGroup

import pytest
import trio

from app.errors import AppError, ErrorUI
from transtoken import TransToken


@pytest.fixture(scope="module", autouse=True)
def reset_handler() -> None:
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
        assert not error_block.failed
    assert ErrorUI._handler is None


async def test_nonfatal() -> None:
    """Test the behaviour of non-fatal .add() errors."""
    orig_title = TransToken.untranslated("The title")
    orig_desc = TransToken.untranslated("the description, n={n}")
    caught_errors: list[AppError] = []

    async def catch(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
        """Catch the errors that occur."""
        assert title is orig_title
        assert str(desc) == "the description, n=4"
        caught_errors.extend(errors)

    exc1 = AppError(TransToken.untranslated("Error 1"))
    exc2 = AppError(TransToken.untranslated("Error 2"))
    exc3 = AppError(TransToken.untranslated("Error 3"))
    exc4 = AppError(TransToken.untranslated("Error 4"))
    unrelated = BufferError("Whatever")

    task: list[str] = []
    success = False
    with ErrorUI.install_handler(catch):
        async with ErrorUI(orig_title, orig_desc) as error_block:
            assert not error_block.failed
            task.append("before")

            error_block.add(exc1)
            assert error_block.failed  # now failed.
            task.append("mid")

            error_block.add(ExceptionGroup("two", [exc2, exc3]))
            # Does not raise.

            with pytest.raises(ExceptionGroup) as reraised:
                error_block.add(ExceptionGroup("stuff", [exc4, unrelated]))
            # unrelated should have been re-raised.
            assert isinstance(reraised.value, ExceptionGroup)
            assert reraised.value.message == "stuff"
            assert reraised.value.exceptions == (unrelated, )

            task.append("after")
            assert error_block.failed  # still failed.
        success = True  # The async-with did not raise.

    assert success
    assert task == ["before", "mid", "after"]
    assert error_block.failed
    assert caught_errors == [exc1, exc2, exc3, exc4]
