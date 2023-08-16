"""Handles displaying errors to the user that occur during operations."""
from __future__ import annotations
from typing import overload

import attrs

from transtoken import TransToken


@attrs.define(init=False)
class AppError(Exception):
    """An error that occurs when using the app, that should be displayed to the user."""
    title: TransToken | None
    message: TransToken

    @overload
    def __init__(self, title: TransToken, message: TransToken, /) -> None: ...
    @overload
    def __init__(self, message: TransToken, *, title: TransToken=...) -> None: ...

    def __init__(self, *args: TransToken, **kwargs: TransToken) -> None:
        if len(args) == 2:
            self.title, self.message = args
        elif len(args) == 1:
            [self.message] = args
            self.title = kwargs.pop("title", None)
        elif len(args) > 2:
            raise TypeError(f"AppError takes from 1 to 2 positional arguments but {len(args)} were given")
        elif len(args) == 0:
            try:
                self.message = kwargs.pop("message")
            except KeyError:
                raise TypeError("AppError missing 1 required positional argument: 'message'") from None
            self.title = kwargs.pop("title", None)
        if kwargs:
            raise TypeError(f"AppError got unexpected keyword argument(s): {', '.join(kwargs)}")

        super().__init__((self.title, self.message))

    def __str__(self) -> str:
        if self.title is not None:
            return f"AppError ({self.title}): {self.message}"
        else:
            return f"AppError: {self.message}"
