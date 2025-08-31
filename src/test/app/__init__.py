from collections.abc import Generator

import pytest
import trio.lowlevel

from app import DEV_MODE
from app.errors import ErrorUI
from transtoken import TransToken, AppError


@pytest.fixture
def cap_error_ui() -> Generator[list[AppError], None, None]:
    """Install a handler for ErrorUI which stores errors."""
    capture = []

    async def handler(title: TransToken, desc: TransToken, errors: list[AppError]) -> None:
        """Ignore description, handle errors."""
        await trio.lowlevel.checkpoint()
        capture.extend(errors)

    with ErrorUI.install_handler(handler):
        yield capture


@pytest.fixture
def force_devmode() -> Generator[None, None, None]:
    """While inside the fixture, force the app's devmode on."""
    old = DEV_MODE.value
    try:
        DEV_MODE.value = True
        yield
    finally:
        DEV_MODE.value = old
