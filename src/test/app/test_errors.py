from app.errors import AppError
from transtoken import TransToken


def test_exception() -> None:
    """Test the exception behaviour."""
    msg = TransToken.untranslated("The message")

    err = AppError(msg)
    assert err.message is msg
    assert err.args == (msg, )

    assert str(err) == "AppError: The message"
