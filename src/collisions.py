"""Defines the region of space items occupy and computes collisions."""
from __future__ import annotations

import operator
from enum import Flag, auto as enum_auto
from typing import Optional
import attr
import functools

from srctools import Vec


class CollideType(Flag):
    """Type of collision."""
    NOTHING = 0
    SOLID = enum_auto()
    GRATING = enum_auto()
    GLASS = enum_auto()
    BRIDGE = enum_auto()
    FIZZLER = enum_auto()
    PHYSICS = enum_auto()
    ANTLINES = enum_auto()

    GRATE = GRATING

    # OR all defined members from above.
    EVERYTHING = functools.reduce(
        operator.or_,
        filter(lambda x: isinstance(x, int), vars().values()),
    )


@attr.frozen
class BBox:
    """An axis aligned volume for collision.

    This may either be a solid volume, or a plane (with one axis' min=max).
    """
    min_x: int
    min_y: int
    min_z: int
    max_x: int
    max_y: int
    max_z: int
    contents: CollideType

    def __init__(
        self,
        point1: Vec | tuple[int, int, int],
        point2: Vec | tuple[int, int, int],
        contents: CollideType = CollideType.SOLID,
    ) -> None:
        """Allow constructing from Vec, and flip values to make them min/max."""
        min_x, min_y, min_z = map(int, point1)
        max_x, max_y, max_z = map(int, point2)
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_y > max_y:
            min_y, max_y = max_y, min_y
        if min_z > max_z:
            min_z, max_z = max_z, min_z

        if (min_x != max_x) + (min_y != max_y) + (min_z != max_z) < 2:
            raise ValueError(
                f'({min_x} {min_y} {min_z}) - '
                f'({max_x} {max_y} {max_z}) '
                f'is not a full volume or plane!'
            )

        self.__attrs_init__(
            min_x, min_y, min_z,
            max_x, max_y, max_z,
            contents,
        )

    @property
    def mins(self) -> Vec:
        """Return the minimums, as a Vector."""
        return Vec(self.min_x, self.min_y, self.min_z)

    @property
    def maxes(self) -> Vec:
        """Return the minimums, as a Vector."""
        return Vec(self.max_x, self.max_y, self.max_z)

    @property
    def is_plane(self) -> bool:
        """Check if this is a plane, not a bounding volume."""
        return (
            self.min_x == self.max_x or
            self.min_y == self.max_y or
            self.min_z == self.max_z
        )

    @property
    def plane_normal(self) -> Optional[Vec]:
        """If a plane, returns the normal axis."""
        if self.min_x == self.max_x:
            return Vec(1, 0, 0)
        elif self.min_y == self.max_y:
            return Vec(0, 1, 0)
        elif self.min_z == self.max_z:
            return Vec(0, 0, 1)
        return None
