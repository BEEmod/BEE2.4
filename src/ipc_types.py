"""Defines types for the messages that can be passed to loadscreen/bg_daemon."""
from typing import Dict, List, Literal, Tuple, TypeAlias, Union


ARGS_SEND_LOAD: TypeAlias = Union[  # loadscreen -> daemon
    Tuple[Literal['set_is_compact'], int, Tuple[bool]],
    Tuple[Literal['set_force_ontop'], None, bool],
    Tuple[Literal['quit_daemon'], None, None],
    Tuple[Literal['set_length'], int, int],
    Tuple[Literal['update_translations'], int, Dict[str, str]],
    Tuple[Literal['reset'], int, Tuple[()]],
    Tuple[Literal['destroy'], int, Tuple[()]],
    Tuple[Literal['hide'], int, Tuple[()]],
    Tuple[Literal['show'], int, Tuple[str, List[str]]],
]
ARGS_REPLY_LOAD: TypeAlias = Union[  # daemon -> loadscreen
    Tuple[Literal['main_set_compact'], bool],
    Tuple[Literal['quit'], None],
    Tuple[Literal['cancel'], int],
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
