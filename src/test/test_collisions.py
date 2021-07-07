"""Test the collisions module."""
from __future__ import annotations

import pytest

from srctools import Vec
from collisions import BBox, CollideType


def assert_bbox(
    bbox: BBox,
    mins: tuple[int, int, int],
    maxes: tuple[int, int, int],
    contents: CollideType,
    msg='',
) -> None:
    """Test the bbox matches the given values."""
    # Don't show in pytest tracebacks.
    __tracebackhide__ = True
    if msg:
        msg = ': ' + msg
    x1, y1, z1 = mins
    x2, y2, z2 = maxes
    if bbox.contents is not contents:
        pytest.fail(f'{bbox}.contents != {contents}{msg}')
    if (
        bbox.min_x != x1 or bbox.min_y != y1 or bbox.min_z != z1 or
        bbox.max_x != x2 or bbox.max_y != y2 or bbox.max_z != z2
    ):
        pytest.fail(f'{bbox}.mins != ({x1} {y1} {z1}) ({x2} {y2} {z2}){msg}')


def test_bbox_construction() -> None:
    bb = BBox(Vec(1, 2, 3), Vec(4, 5, 6))
    # Check assert_bbox() is correct.
    assert bb.min_x == 1
    assert bb.min_y == 2
    assert bb.min_z == 3
    assert bb.max_x == 4
    assert bb.max_y == 5
    assert bb.max_z == 6
    assert bb.contents is CollideType.SOLID
    assert_bbox(bb, (1, 2, 3), (4, 5, 6), CollideType.SOLID)

    assert_bbox(
        BBox(Vec(4, 2, 6), Vec(1, 5, 3), CollideType.FIZZLER | CollideType.ANTLINES),
        (1, 2, 3), (4, 5, 6),
        CollideType.FIZZLER | CollideType.ANTLINES,
    )
    assert_bbox(
        BBox((-50, 80, -60), (30, -40, 95), CollideType.GLASS),
        (-50, -40, -60), (30, 80, 95),
        CollideType.GLASS,
    )

    plane_x = BBox([80, 90, 10], [80, 250, 40], CollideType.GRATE)
    assert plane_x.is_plane
    assert plane_x.plane_normal == Vec(1, 0, 0)
    assert_bbox(plane_x, (80, 90, 10), (80, 250, 40), CollideType.GRATE)

    plane_y = BBox([80, 250, 10], [110, 250, 40], CollideType.GRATE)
    assert plane_y.is_plane
    assert plane_y.plane_normal == Vec(0, 1, 0)
    assert_bbox(plane_y, (80, 250, 10), (110, 250, 40), CollideType.GRATE)

    plane_z = BBox([80, 250, 40], [110, 90, 40], CollideType.GRATE)
    assert plane_z.is_plane
    assert plane_z.plane_normal == Vec(0, 0, 1)
    assert_bbox(plane_z, (80, 90, 40), (110, 250, 40), CollideType.GRATE)


def test_illegal_bbox() -> None:
    """A line or point segement is not allowed."""
    with pytest.raises(ValueError):
        BBox(Vec(1, 2, 3), Vec(1, 2, 3))
    with pytest.raises(ValueError):
        BBox(Vec(1, 2, 3), Vec(10, 2, 3))
    with pytest.raises(ValueError):
        BBox(Vec(1, 2, 3), Vec(1, 20, 3))
    with pytest.raises(ValueError):
        BBox(Vec(1, 2, 3), Vec(1, 2, 30))


def test_bbox_vecs() -> None:
    """Test that the vector properties don't return the same object."""
    bb = BBox((40, 60, 80), (120, 450, 730))
    assert bb.mins == Vec(40.0, 60.0, 80.0)
    assert bb.maxes == Vec(120.0, 450.0, 730.0)
    assert bb.mins is not bb.mins
    assert bb.maxes is not bb.maxes

def test_bbox_is_frozen() -> None:
    bb = BBox((40, 60, 80), (120, 450, 730), CollideType.PHYSICS)
    with pytest.raises(AttributeError):
        bb.min_x = 100
    with pytest.raises(AttributeError):
        bb.min_y = 100
    with pytest.raises(AttributeError):
        bb.min_z = 100

    with pytest.raises(AttributeError):
        bb.max_x = 100
    with pytest.raises(AttributeError):
        bb.max_y = 100
    with pytest.raises(AttributeError):
        bb.max_z = 100
    assert_bbox(bb, (40, 60, 80), (120, 450, 730), CollideType.PHYSICS)

    hash(bb)  # Check it can be hashed.
    assert hash(bb) != hash(BBox((40, 60, 81), (120, 450, 730), CollideType.PHYSICS))
