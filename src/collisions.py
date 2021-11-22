"""Defines the region of space items occupy and computes collisions."""
from __future__ import annotations

import operator
from enum import Flag, auto as enum_auto
import attr
import functools

from srctools.math import Vec, Angle, Matrix, to_matrix


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
        point1: Vec | tuple[int|float, int|float, int|float],
        point2: Vec | tuple[int|float, int|float, int|float],
        contents: CollideType = CollideType.SOLID,
    ) -> None:
        """Allow constructing from Vec, and flip values to make them min/max."""
        min_x, min_y, min_z = map(round, point1)
        max_x, max_y, max_z = map(round, point2)
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
    def center(self) -> Vec:
        """Return the center of the bounding box, as a Vector."""
        return Vec(
            (self.min_x + self.max_x) / 2.0,
            (self.min_y + self.max_y) / 2.0,
            (self.min_z + self.max_z) / 2.0,
        )

    @property
    def size(self) -> Vec:
        """Return the size of the bounding box, as a Vector."""
        return Vec(
            self.max_x - self.min_x,
            self.max_y - self.min_y,
            self.max_z - self.min_z,
        )

    @property
    def is_plane(self) -> bool:
        """Check if this is a plane, not a bounding volume."""
        return (
            self.min_x == self.max_x or
            self.min_y == self.max_y or
            self.min_z == self.max_z
        )

    @property
    def plane_normal(self) -> Vec | None:
        """If a plane, returns the normal axis."""
        if self.min_x == self.max_x:
            return Vec(1.0, 0.0, 0.0)
        elif self.min_y == self.max_y:
            return Vec(0.0, 1.0, 0.0)
        elif self.min_z == self.max_z:
            return Vec(0.0, 0.0, 1.0)
        return None

    def intersect(self, other: BBox) -> BBox | None:
        """Check if another bbox collides with this one.

        If so, return the bbox representing the overlap.
        """
        comb = self.contents & other.contents
        if comb is CollideType.NOTHING:
            return None
        # We do each axis one at a time. First do a separating-axis test
        # on either side, if that passes we don't collide.
        if self.max_x < other.min_x or self.min_x > other.max_x:
            return None
        # They overlap, so compare the min/max pairs to get the intersection interval.
        # If that's negative, we fail also.
        min_x = max(self.min_x, other.min_x)
        max_x = min(self.max_x, other.max_x)
        if min_x > max_x:
            return None

        # Then repeat for the other axes.
        if self.max_y < other.min_y or self.min_y > other.max_y:
            return None

        min_y = max(self.min_y, other.min_y)
        max_y = min(self.max_y, other.max_y)
        if min_y > max_y:
            return None

        if self.max_z < other.min_z or self.min_z > other.max_z:
            return None

        min_z = max(self.min_z, other.min_z)
        max_z = min(self.max_z, other.max_z)
        if min_z > max_z:
            return None

        try:
            return BBox(
                (min_x, min_y, min_z),
                (max_x, max_y, max_z),
                comb,
            )
        except ValueError:  # Edge or corner, don't count those.
            return None

    def __matmul__(self, other: Angle | Matrix) -> BBox:
        """Rotate the bounding box by an angle. This should be multiples of 90 degrees."""
        # https://gamemath.com/book/geomprims.html#transforming_aabbs
        m = to_matrix(other)

        if m[0, 0] > 0.0:
            min_x = m[0, 0] * self.min_x
            max_x = m[0, 0] * self.max_x
        else:
            min_x = m[0, 0] * self.max_x
            max_x = m[0, 0] * self.min_x

        if m[0, 1] > 0.0:
            min_y = m[0, 1] * self.min_x
            max_y = m[0, 1] * self.max_x
        else:
            min_y = m[0, 1] * self.max_x
            max_y = m[0, 1] * self.min_x

        if m[0, 2] > 0.0:
            min_z = m[0, 2] * self.min_x
            max_z = m[0, 2] * self.max_x
        else:
            min_z = m[0, 2] * self.max_x
            max_z = m[0, 2] * self.min_x

        if m[1, 0] > 0.0:
            min_x += m[1, 0] * self.min_y
            max_x += m[1, 0] * self.max_y
        else:
            min_x += m[1, 0] * self.max_y
            max_x += m[1, 0] * self.min_y

        if m[1, 1] > 0.0:
            min_y += m[1, 1] * self.min_y
            max_y += m[1, 1] * self.max_y
        else:
            min_y += m[1, 1] * self.max_y
            max_y += m[1, 1] * self.min_y

        if m[1, 2] > 0.0:
            min_z += m[1, 2] * self.min_y
            max_z += m[1, 2] * self.max_y
        else:
            min_z += m[1, 2] * self.max_y
            max_z += m[1, 2] * self.min_y

        if m[2, 0] > 0.0:
            min_x += m[2, 0] * self.min_z
            max_x += m[2, 0] * self.max_z
        else:
            min_x += m[2, 0] * self.max_z
            max_x += m[2, 0] * self.min_z

        if m[2, 1] > 0.0:
            min_y += m[2, 1] * self.min_z
            max_y += m[2, 1] * self.max_z
        else:
            min_y += m[2, 1] * self.max_z
            max_y += m[2, 1] * self.min_z

        if m[2, 2] > 0.0:
            min_z += m[2, 2] * self.min_z
            max_z += m[2, 2] * self.max_z
        else:
            min_z += m[2, 2] * self.max_z
            max_z += m[2, 2] * self.min_z
        return BBox(
            (min_x, min_y, min_z),
            (max_x, max_y, max_z),
            self.contents,
        )

    def __add__(self, other: Vec | tuple[float, float, float]) -> BBox:
        """Add a vector to the mins and maxes."""
        if isinstance(other, BBox):  # Special-case error.
            raise TypeError('Two bounding boxes cannot be added!')
        return BBox(self.mins + other, self.maxes + other, self.contents)

    def __sub__(self, other: Vec | tuple[float, float, float]) -> BBox:
        """Add a vector to the mins and maxes."""
        return BBox(self.mins - other, self.maxes - other, self.contents)

    # radd/rsub intentionally omitted. Don't allow inverting, that's nonsensical.
