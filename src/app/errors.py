"""Handles displaying errors to the user that occur during operations."""
from __future__ import annotations

from typing import final

import attrs

from transtoken import TransToken


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
