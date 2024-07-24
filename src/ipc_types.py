"""Defines types for the messages that can be passed to loadscreen/bg_daemon."""
from typing_extensions import Literal, NewType

import attrs


StageID = NewType('StageID', str)
ScreenID = NewType('ScreenID', int)


@attrs.frozen
class Load2Daemon_SetForceOnTop:
    """Set the window-on-top behaviour for loadscreens."""
    on_top: bool


@attrs.frozen
class Load2Daemon_UpdateTranslations:
    """Update text on loading screens."""
    translations: dict[str, str]


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
    """Display the specified loading screen, passing along freshly translated stage titles."""
    title: str
    stage_names: list[str]


@attrs.frozen
class Daemon2Load_Cancel:
    """The cancel button was pressed on this screen."""
    screen: ScreenID


@attrs.frozen
class Daemon2Load_MainSetCompact:
    """Store the new is-compact state for the main splash screen."""
    compact: bool


type ARGS_SEND_LOAD = (
    Load2Daemon_SetForceOnTop | Load2Daemon_UpdateTranslations | Load2Daemon_SetIsCompact
    | Load2Daemon_Init | Load2Daemon_SetLength | Load2Daemon_Set | Load2Daemon_Skip
    | Load2Daemon_Hide | Load2Daemon_Reset | Load2Daemon_Destroy | Load2Daemon_Show
)
type ARGS_REPLY_LOAD = Daemon2Load_Cancel | Daemon2Load_MainSetCompact
type ARGS_SEND_LOGGING = (  # logging -> daemon
    tuple[Literal['log'], str, str] |
    tuple[Literal['visible'], bool] |
    tuple[Literal['level'], str]
)
type ARGS_REPLY_LOGGING = (  # daemon -> logging
    tuple[Literal['level'], str] |
    tuple[Literal['visible'], bool] |
    tuple[Literal['quit'], None]
)
