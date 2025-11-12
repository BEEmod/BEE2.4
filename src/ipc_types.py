"""Defines types for the messages that can be passed to loadscreen/bg_daemon."""
from typing import Literal, NewType, TypedDict

import attrs

from transtoken import TransToken


StageID = NewType('StageID', str)
ScreenID = NewType('ScreenID', int)


class LoadTranslations[ValT: (TransToken, str)](TypedDict):
    """Small set of translated strings, passed from the main process.

    This is a TransToken dict in the main process, but reified into str on the daemon.
    """
    skip: ValT
    version: ValT
    cancel: ValT
    clear: ValT
    copy: ValT
    log_title: ValT
    log_show: ValT
    level_debug: ValT
    level_info: ValT
    level_warn: ValT
    splash_title: ValT
    splash_title_author: ValT
    splash_author: ValT


@attrs.frozen
class SplashInfo:
    """Information about the selected splash screen, for displaying credits."""
    title: str
    author: str
    workshop_id: int | None

    @property
    def workshop_link(self) -> str | None:
        """Return the URL for its webpage."""
        if self.workshop_id is None:
            return None
        return f'https://steamcommunity.com/sharedfiles/filedetails/?id={self.workshop_id}'

    def format_title(self, translations: LoadTranslations[str]) -> str:
        """Combine title and author for the splash screen."""
        if self.title and self.author:
            return translations['splash_title_author'].format(title=self.title, author=self.author)
        elif self.title:
            return translations['splash_title'].format(title=self.title)
        elif self.author:
            return translations['splash_author'].format(author=self.author)
        else:
            return ''


@attrs.frozen
class Load2Daemon_SetForceOnTop:
    """Set the window-on-top behaviour for loadscreens."""
    on_top: bool


@attrs.frozen
class Load2Daemon_UpdateTranslations:
    """Update text on loading screens."""
    translations: LoadTranslations[str]


@attrs.frozen
class Load2Daemon_Init:
    """Create a screen."""
    scr_id: ScreenID
    is_splash: bool
    title: str
    stages: list[tuple[StageID, str]]


@attrs.frozen
class ScreenOp:
    """A screen -> daemon message involving a single screen."""
    screen: ScreenID


@attrs.frozen
class StageOp(ScreenOp):
    """A screen -> daemon message involving a screen and stage."""
    stage: StageID


@attrs.frozen
class Load2Daemon_SetLength(StageOp):
    size: int


@attrs.frozen
class Load2Daemon_Set(StageOp):
    value: int


class Load2Daemon_Skip(StageOp):
    pass


class Load2Daemon_Hide(ScreenOp):
    pass


@attrs.frozen
class Load2Daemon_SetIsCompact(ScreenOp):
    """Set the is-compact state for the main splash screen."""
    compact: bool


class Load2Daemon_Reset(ScreenOp):
    pass


class Load2Daemon_Destroy(ScreenOp):
    pass


@attrs.frozen
class Load2Daemon_Show(ScreenOp):
    """Display the specified loading screen.

    This passes along newly translated titles and max lengths.
    """
    title: str
    stages: list[tuple[str, int]]


@attrs.frozen
class Daemon2Load_Cancel:
    """The cancel button was pressed on this screen."""
    screen: ScreenID


@attrs.frozen
class Daemon2Load_MainSetCompact:
    """Store the new is-compact state for the main splash screen."""
    compact: bool


@attrs.frozen
class Daemon2Load_MainSetSplash:
    """Transmit the selected splash screen for the help menu to display."""
    info: SplashInfo


type ARGS_SEND_LOAD = (
    Load2Daemon_SetForceOnTop | Load2Daemon_UpdateTranslations | Load2Daemon_SetIsCompact
    | Load2Daemon_Init | Load2Daemon_SetLength | Load2Daemon_Set | Load2Daemon_Skip
    | Load2Daemon_Hide | Load2Daemon_Reset | Load2Daemon_Destroy | Load2Daemon_Show
)
type ARGS_REPLY_LOAD = Daemon2Load_Cancel | Daemon2Load_MainSetCompact | Daemon2Load_MainSetSplash
type ARGS_SEND_LOGGING = (  # logging -> daemon
    tuple[Literal['log'], str, str] |
    tuple[Literal['visible'], bool] |
    tuple[Literal['level'], str]
)
type ARGS_REPLY_LOGGING = (  # daemon -> logging
    tuple[Literal['level'], str] |
    tuple[Literal['visible'], bool]
)
