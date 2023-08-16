import pytest

from app.errors import AppError
from transtoken import TransToken


def test_error_construction() -> None:
    """Test various constructor signatures."""
    msg = TransToken.untranslated("Message")
    title = TransToken.untranslated("Title")

    err = AppError(msg)
    assert err.title is None
    assert err.message is msg

    err = AppError(message=msg)
    assert err.title is None
    assert err.message is msg

    err = AppError(title, msg)
    assert err.title is title
    assert err.message is msg

    err = AppError(msg, title=title)
    assert err.title is title
    assert err.message is msg

    err = AppError(title=title, message=msg)
    assert err.title is title
    assert err.message is msg

    err = AppError(message=msg, title=title)
    assert err.title is title
    assert err.message is msg

    with pytest.raises(TypeError):
        AppError()  # type: ignore

    with pytest.raises(TypeError):
        AppError(msg, title, TransToken.BLANK)  # type: ignore

    with pytest.raises(TypeError):
        AppError(title, message=msg)  # type: ignore

    with pytest.raises(TypeError):
        AppError(title, msg, message=msg)  # type: ignore

    with pytest.raises(TypeError):
        AppError(title, msg, title=title)  # type: ignore
