"""Test the SliceKey utiliy class."""
import pytest
from srctools.math import Matrix, Vec, FrozenVec

from utils import SliceKey


def test_constructor() -> None:
    """Test constructing SliceKeys."""
    key = SliceKey(Vec(0, 0, 1), 48.0)
    assert key.normal is Vec.T  # The normal is always these constants.
    assert key.distance == 48.0

    key = SliceKey(FrozenVec(-1, 0, 0), 192.84)
    assert key.normal is Vec.W
    assert key.distance == 192.84

    key = SliceKey((0, -1.00000000001, 0.0), (48.0, 26.8, 192.12))
    assert key.normal is Vec.S
    assert key.distance == -26.8

    with pytest.raises(ValueError):
        SliceKey(Vec(), 12)
    with pytest.raises(ValueError):
        SliceKey(Matrix.from_yaw(45).forward(), 8)


def test_equality() -> None:
    """Test equality between SliceKeys."""
    key = SliceKey(Vec.N, 38.0)
    good = SliceKey((0, 1, 0), 38)
    bad1 = SliceKey((0, 0, -1), 38)
    bad2 = SliceKey(Vec.N, -38.0)

    assert key == good
    assert not (key == bad1)
    assert not (key == bad2)

    assert not (key != good)
    assert key != bad1
    assert key != bad2

    assert hash(key) == hash(good)
    assert hash(key) != hash(bad1)
    assert hash(key) != hash(bad2)


def test_orients() -> None:
    """Test the orientations are correct."""
    # We know Matrix.from_angle() is right, just need to check the correct ones are produced.
    assert SliceKey(Vec.N, 12).orient.up() == Vec.N
    assert SliceKey(Vec.S, 12).orient.up() == Vec.S
    assert SliceKey(Vec.E, 12).orient.up() == Vec.E
    assert SliceKey(Vec.W, 12).orient.up() == Vec.W
    assert SliceKey(Vec.T, 12).orient.up() == Vec.T
    assert SliceKey(Vec.B, 12).orient.up() == Vec.B

    assert SliceKey(Vec.N, 12).orient.left() == Vec.T
    assert SliceKey(Vec.S, 12).orient.left() == Vec.T
    assert SliceKey(Vec.E, 12).orient.left() == Vec.T
    assert SliceKey(Vec.W, 12).orient.left() == Vec.T
    assert SliceKey(Vec.T, 12).orient.left() == Vec.N
    assert SliceKey(Vec.B, 12).orient.left() == Vec.N

    assert SliceKey(Vec.N, 12).orient.forward() == Vec.W
    assert SliceKey(Vec.S, 12).orient.forward() == Vec.E
    assert SliceKey(Vec.E, 12).orient.forward() == Vec.N
    assert SliceKey(Vec.W, 12).orient.forward() == Vec.S
    assert SliceKey(Vec.T, 12).orient.forward() == Vec.E
    assert SliceKey(Vec.B, 12).orient.forward() == Vec.W


@pytest.mark.parametrize('normal', [
    Vec.N, Vec.S, Vec.E, Vec.W, Vec.T, Vec.B
])
def test_orient_roundtrip(normal: Vec) -> None:
    orient = SliceKey(normal, 123).orient
    assert orient.to_angle() == Matrix.from_angle(orient.to_angle()).to_angle()
