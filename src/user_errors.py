"""Common data for the compile user error support."""
from typing import Dict, List, Literal, Tuple, TypedDict
from enum import Enum
import attrs
from srctools import Vec

import utils


Kind = Literal["white", "black", "goo", "goopartial", "goofull", "back"]


class SimpleTile(TypedDict):
    """A super simplified version of tiledef data for the error window. This can be converted right to JSON."""
    pos: Tuple[float, float, float]
    orient: Literal["n", "s", "e", "w", "u", "d"]


@attrs.frozen
class ErrorInfo:
    """Data to display to the user."""
    message: str
    points: List[Tuple[float, float, float]]  # Points of interest in the map.
    faces: Dict[Kind, List[SimpleTile]]


DATA_LOC = utils.conf_location('compile_error.pickle')
SERVER_PORT = utils.conf_location('error_server_url.txt')
