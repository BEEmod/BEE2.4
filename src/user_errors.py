"""Common data for the compile user error support."""
from typing import List

import attrs
from srctools import Vec

import utils


@attrs.frozen
class ErrorInfo:
    """Data to display to the user."""
    message: str
    points: List[Vec] # Points of interest in the map.


DATA_LOC = utils.conf_location('compile_error.pickle')
SERVER_PORT = utils.conf_location('error_server_url.txt')
