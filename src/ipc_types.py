"""Defines types for the messages that can be passed to loadscreen/bg_daemon."""
from typing import Dict, List, Tuple, Union
from typing_extensions import Literal, NewType, TypeAlias

StageID = NewType('StageID', str)
ScreenID = NewType('ScreenID', int)


ARGS_SEND_LOAD: TypeAlias = Union[  # loadscreen -> daemon
    Tuple[Literal['set_force_ontop'], None, bool],
    Tuple[Literal['quit_daemon'], None, None],
    Tuple[Literal['update_translations'], None, Dict[str, str]],
    Tuple[Literal['set_is_compact'], ScreenID, Tuple[bool]],
    Tuple[Literal['init'], ScreenID, Tuple[bool, str, List[Tuple[ScreenID, str]]]],
    Tuple[Literal['set_length'], ScreenID, Tuple[StageID, int]],
    Tuple[Literal['step'], ScreenID, Tuple[StageID]],
    Tuple[Literal['reset'], ScreenID, Tuple[()]],
    Tuple[Literal['destroy'], ScreenID, Tuple[()]],
    Tuple[Literal['hide'], ScreenID, Tuple[()]],
    Tuple[Literal['show'], ScreenID, Tuple[str, List[str]]],
]
ARGS_REPLY_LOAD: TypeAlias = Union[  # daemon -> loadscreen
    Tuple[Literal['main_set_compact'], bool],
    Tuple[Literal['quit'], None],
    Tuple[Literal['cancel'], ScreenID],
]
ARGS_SEND_LOGGING: TypeAlias = Union[  # logging -> daemon
    Tuple[Literal['log'], str, str],
    Tuple[Literal['visible'], bool, None],
    Tuple[Literal['level'], str | int, None],
]
ARGS_REPLY_LOGGING: TypeAlias = Union[  # daemon -> logging
    Tuple[Literal['level'], str],
    Tuple[Literal['visible'], bool],
    Tuple[Literal['quit'], None],
]
