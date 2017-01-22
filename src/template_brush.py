"""Templates are sets of brushes which can be copied into the map."""
from collections import namedtuple
from enum import Enum

from srctools import Entity, Solid, Side
import conditions

from typing import (
    Iterable,
    Dict, List, Set,
)

TEMPLATES = {}


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

