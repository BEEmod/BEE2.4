"""Allows searching and selecting various resources."""
import abc
from abc import ABC
from typing import TypeGuard

import trio

import trio_util
from app.gameMan import Game, selected_game, is_valid_game
from async_util import EdgeTrigger
from trio_util import AsyncBool, AsyncValue


class Browser(ABC):
    """Base functionality - reload if game changes, only allow opening once."""
    def __init__(self) -> None:
        self._ready = AsyncBool(False)
        self._wants_open = AsyncBool(False)
        self.result: EdgeTrigger[str | None] = EdgeTrigger()
        # If non-none, a user is trying to browse.
        self._close_event: trio.Event | None = None

    async def task(self) -> None:
        """Handles main flow."""
        while True:
            self._ready.value = False
            self._ui_hide_window()
            game = await selected_game.wait_value(is_valid_game)
            async with trio_util.move_on_when(selected_game.wait_transition):
                await self._reload(game)
                self._ready.value = True
                while True:
                    await self.result.ready.wait_value(True)
                    self._ui_show_window()
                    await self.result.ready.wait_value(False)
                    self._ui_hide_window()

    async def browse(self, existing: str) -> str | None:
        """Browse for a value."""
        await self._ready.wait_value(True)
        while self.result.ready.value:
            self.result.trigger(None)
            self._ui_hide_window()
            await trio.sleep(0.25)
        return await self.result.wait()

    def _evt_cancel(self, _: object = None) -> None:
        """Close the browser, cancelling."""
        self.result.trigger(None)

    def _evt_ok(self, value: str) -> None:
        """Successfully select a value."""
        self.result.trigger(value)

    async def _reload(self, game: Game) -> None:
        """Reload data for the new game."""

    @abc.abstractmethod
    def _ui_show_window(self) -> None:
        """Show the window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_hide_window(self) -> None:
        """Hide the window."""
        raise NotImplementedError


class SoundBrowser(Browser, ABC):
    """Browses for soundscripts, raw sounds or choreo scenes, like Hammer's."""
    def __init__(self) -> None:
        super().__init__()
        self.mode = ...

    async def task(self) -> None:
        """Reloads """
