"""Manages PeTI item connections."""
from enum import Enum
from srctools import Entity

from typing import Iterable


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 0  # Normal / unconfigured input
    # Becomes one of the others based on item preference.

    PRIMARY = TBEAM_IO = 1  # A Type, 'normal'
    SECONDARY = TBEAM_DIR = 2  # B Type, 'alt'

    BOTH = 3  # Trigger both simultaneously.


class Connection:
    """Represents an item connection."""

    def __init__(
        self,
        in_inst: Entity,
        out_inst: Entity,
        conn_type=ConnType.DEFAULT,
        toggle: Entity=None,
        panels: Iterable[Entity]=(),
    ):
        self.in_inst = in_inst
        self.out_inst = out_inst
        self.type = conn_type
        self.ind_panels = list(panels)
        self.ind_toggle = toggle
