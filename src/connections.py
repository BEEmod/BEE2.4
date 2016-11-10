"""Manages PeTI item connections."""
from enum import Enum
from srctools import Entity


class ConnType(Enum):
    """Kind of Input A/B type, or TBeam type."""
    DEFAULT = 0  # Normal / unconfigured input

    PRIMARY = TBEAM_IO = 1
    SECONDARY = TBEAM_DIR = 2

    BOTH = 3  # Trigger both simultaneously.


class Connection:
    """Represents an item connection."""

    def __init__(
        self,
        in_inst: Entity,
        out_inst: Entity,
        conn_type=ConnType.DEFAULT,

    ):
        self.in_inst = in_inst
        self.out_inst = out_inst
        self.type = conn_type

