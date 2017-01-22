"""Templates are sets of brushes which can be copied into the map."""
from collections import namedtuple
from enum import Enum

from srctools import Entity, Solid, Side
import conditions

from typing import (
    Iterable, NamedTuple,
    Dict, List, Set,
)

TEMPLATES = {}


class SWITCH_TYPE(Enum):
    """The methods useable for switch options."""
    FIRST = 'first'  # choose the first match
    LAST = 'last'  # choose the last match
    RANDOM = 'random'  # Randomly choose
    ALL = 'all'  # Run all matching commands


class TEMP_TYPES(Enum):
    """Value used for import_template()'s force_type parameter.
    """
    default = 0  # Based on the original VMF settings
    world = 1  # Import and add to world
    detail = 2  # Import as a func_detail

ExportedTemplate = NamedTuple('ExportedTemplate', [
    ('world', List[Solid]),
    ('detail', List[Solid]),
    ('overlay', List[Entity]),
    ('orig_ids', Dict[str, str]),
])

class Template:
    def __init__(
        self,
        temp_id,
        brushes: Dict[str, List[Solid]],
        details: Dict[str, List[Solid]],
        overlays: Dict[str, List[Entity]],
        realign_faces: Iterable[str],
        overlay_transfer_faces: Iterable[str],
    ):
        self.id = temp_id
        self.brushes = brushes
        self.details = details
        self.overlays = overlays

        self.realign_faces = set(realign_faces)
        self.overlay_faces = set(overlay_transfer_faces)

