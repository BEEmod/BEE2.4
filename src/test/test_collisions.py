"""Test the collisions module."""
from __future__ import annotations

import math
from typing import Iterable, Tuple, no_type_check
from pathlib import Path
import pytest

from srctools import Angle, Matrix, VMF, Vec, Keyvalues, Solid
from collisions import BBox, CollideType

tuple3 = Tuple[int, int, int]


def assert_bbox(
    bbox: BBox,
    mins: Iterable[int | float],
    maxes: Iterable[int | float],
    contents: CollideType,
    tags: set[str],
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
    if bbox.tags != tags:
        pytest.fail(f'{bbox}.tags != {tags!r}{msg}')
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
    assert_bbox(bb, (1, 2, 3), (4, 5, 6), CollideType.SOLID, set())

    assert_bbox(
        BBox(Vec(4.1, 1.9, 6), Vec(1, 5.1, 2.85), contents=CollideType.FIZZLER | CollideType.ANTLINES),
        (1, 2, 3), (4, 5, 6),
        CollideType.FIZZLER | CollideType.ANTLINES,
        set(),
    )
    assert_bbox(
        BBox(-50, 80, -60, 30, -40, 95, contents=CollideType.GLASS, tags='tag1'),
        (-50, -40, -60), (30, 80, 95),
        CollideType.GLASS,
        {'tag1', },
    )

    plane_x = BBox(80, 90.0, 10, 80.0, 250, 40.0, contents=CollideType.GRATE)
    assert plane_x.is_plane
    assert plane_x.plane_normal == Vec(1, 0, 0)
    assert_bbox(plane_x, (80, 90, 10), (80, 250, 40), CollideType.GRATE, set())

    plane_x = BBox(80.0, 90.0, 10, 80, 250, 40.0, contents=CollideType.GRATE)
    assert plane_x.is_plane
    assert plane_x.plane_normal == Vec(1, 0, 0)
    assert_bbox(plane_x, (80, 90, 10), (80, 250, 40), CollideType.GRATE, set())

    plane_y = BBox(80, 250, 10.0, 110.0, 250, 40, contents=CollideType.GRATE)
    assert plane_y.is_plane
    assert plane_y.plane_normal == Vec(0, 1, 0)
    assert_bbox(plane_y, (80, 250, 10), (110, 250, 40), CollideType.GRATE, set())

    plane_z = BBox(80, 250, 40, 110, 90, 40, contents=CollideType.GRATE)
    assert plane_z.is_plane
    assert plane_z.plane_normal == Vec(0, 0, 1)
    assert_bbox(plane_z, (80, 90, 40), (110, 250, 40), CollideType.GRATE, set())

    assert BBox(-10, -10, -10, +10, +10, +10).tags == frozenset({})
    assert BBox(
        -10, -10, -10, +10, +10, +10, contents=CollideType.BRIDGE,
        tags='tags',  # Special case, not iterated.
    ).tags == frozenset({'tags'})
    assert BBox(
        -10, -10, -10, +10, +10, +10,
        tags=['a', 'b', 'embed'],
    ).tags == frozenset({'a', 'b', 'embed'})


@no_type_check
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
    bb = BBox(30, 60, 80, 120, 451, 730)

    assert bb.mins == Vec(30.0, 60.0, 80.0)
    assert bb.mins is not bb.mins

    assert bb.maxes == Vec(120.0, 451.0, 730.0)
    assert bb.maxes is not bb.maxes

    assert bb.size == Vec(90.0, 391.0, 650.0)
    assert bb.size is not bb.size

    assert bb.center == Vec(75.0, 255.5, 405.0)
    assert bb.center is not bb.center


@no_type_check
def test_bbox_is_frozen() -> None:
    """Test modification is not possible."""
    bb = BBox(40, 60, 80, 120, 450, 730, contents=CollideType.PHYSICS)
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

    with pytest.raises(AttributeError):
        bb.contents = CollideType.GRATE
    with pytest.raises(AttributeError):
        bb.tags = frozenset({'tag1', 'tag2', 'tag3'})
    with pytest.raises(AttributeError):
        bb.tags.add('extra')  # noqa
    # Check all these assignments didn't actually do anything.
    assert_bbox(bb, (40, 60, 80), (120, 450, 730), CollideType.PHYSICS, set())


def test_bbox_hash() -> None:
    """Test hashability of bboxes."""
    bb = BBox(40, 60, 80, 120, 450, 730, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'})
    hash(bb)  # Check it can be hashed.

    # Check each value changes the hash.
    assert hash(bb) != hash(BBox(45, 40, 80, 120, 450, 730, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 59, 80, 120, 450, 730, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 60, 81, 120, 450, 730, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 60, 80, 121, 450, 730, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 60, 80, 120, 455, 730, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 60, 80, 120, 450, 732, contents=CollideType.PHYSICS, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 60, 80, 120, 450, 730, contents=CollideType.ANTLINES, tags={'tag1', 'tag2'}))
    assert hash(bb) != hash(BBox(40, 60, 80, 120, 450, 732, contents=CollideType.PHYSICS, tags={'tag1', 'tag3'}))


def reorder(coord: tuple3, order: str, x: int, y: int, z: int) -> Vec:
    """Reorder the coords by these axes."""
    assoc = dict(zip('xyz', coord))
    return Vec(x + assoc[order[0]], y + assoc[order[1]], z + assoc[order[2]])


def test_reorder_helper() -> None:
    """Test the reorder helper."""
    assert reorder((1, 2, 3), 'xyz', 0, 0, 0) == Vec(1, 2, 3)
    assert reorder((1, 2, 3), 'yzx', 0, 0, 0) == Vec(2, 3, 1)
    assert reorder((1, 2, 3), 'zyx', 0, 0, 0) == Vec(3, 2, 1)
    assert reorder((1, 2, 3), 'xzy', 0, 0, 0) == Vec(1, 3, 2)
    assert reorder((-10, 30, 0), 'xyz', 8, 6, 12) == Vec(-2, 36, 12)


def get_intersect_testcases() -> Iterable:
    """Use a VMF to make it easier to generate the bounding boxes."""
    with Path(__file__, '../bbox_samples.vmf').open() as f:
        vmf = VMF.parse(Keyvalues.parse(f))

    def process(brush: Solid | None) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
        """Extract the bounding box from the brush."""
        if brush is None:
            return None
        bb_min, bb_max = brush.get_bbox()
        for vec in [bb_min, bb_max]:
            for ax in 'xyz':
                # If one thick, make zero thick so we can test planes.
                if abs(vec[ax]) == 63:
                    vec[ax] = math.copysign(64, vec[ax])
        return (tuple(map(int, bb_min)), tuple(map(int, bb_max)))

    for ent in vmf.entities:
        test = expected = None
        for solid in ent.solids:
            if solid.sides[0].mat.casefold() == 'tools/toolsskip':
                expected = solid
            if solid.sides[0].mat.casefold() == 'tools/toolstrigger':
                test = solid
        if test is None:
            raise ValueError(ent.id)
        yield (*process(test), process(expected))


@pytest.mark.parametrize('mins, maxs, success', list(get_intersect_testcases()))
@pytest.mark.parametrize('axes', ['xyz', 'yxz', 'zxy'])
@pytest.mark.parametrize('x', [-128, 0, 129])
@pytest.mark.parametrize('y', [-128, 0, 129])
@pytest.mark.parametrize('z', [-128, 0, 129])
def test_bbox_intersection(
    mins: tuple3, maxs: tuple3,
    x: int, y: int, z: int,
    success: tuple[tuple3, tuple3] | None, axes: str,
) -> None:
    """Test intersection founction for bounding boxes.

    We parameterise by swapping all the axes, and offsetting so it's in all the quadrants.
    """
    bbox1 = BBox(x-64, y-64, z-64, x+64, y+64, z+64, contents=CollideType.EVERYTHING)
    bbox2 = BBox(reorder(mins, axes, x, y, z), reorder(maxs, axes, x, y, z), contents=CollideType.EVERYTHING)
    result = bbox1.intersect(bbox2)
    # assert result == bbox2.intersect(bbox1)  # Check order is irrelevant.
    if success is None:
        assert result is None
    else:
        exp_a, exp_b = success
        expected = BBox(reorder(exp_a, axes, x, y, z), reorder(exp_b, axes, x, y, z), contents=CollideType.EVERYTHING)
        assert result == expected


@pytest.mark.parametrize('pitch', range(0, 360, 90))
@pytest.mark.parametrize('yaw', range(0, 360, 90))
@pytest.mark.parametrize('roll', range(0, 360, 90))
def test_bbox_rotation(
    pitch: float, yaw: float, roll: float,
) -> None:
    """Test the rotation logic against the slow direct approach."""
    ang = Angle(pitch, yaw, roll)
    bb_start = BBox(100, 200, 300, 300, 450, 600, contents=CollideType.ANTLINES, tags='blah')
    # Directly compute, by rotating all the angles,
    points = [
        Vec(x, y, z)
        for x in [100, 300]
        for y in [200, 450]
        for z in [300, 600]
    ]
    result_ang = bb_start @ ang
    result_mat = bb_start @ Matrix.from_angle(ang)
    assert result_ang == result_mat

    bb_min, bb_max = Vec.bbox(
        point @ ang for point in points
    )
    assert_bbox(result_mat, round(bb_min, 0), round(bb_max, 0), CollideType.ANTLINES, {'blah'})


def test_bbox_addition() -> None:
    """Test adding to bbox to shift them around."""
    bb = BBox(40, 60, 80, 120, 450, 730, contents=CollideType.ANTLINES, tags={'a', 'b'})
    assert_bbox(
        bb + Vec(10, -30, 45),
        (50, 30, 125), (130, 420, 775),
        CollideType.ANTLINES, {'a', 'b'}
    )
    assert_bbox(
        bb + (10, -30, 45),
        (50, 30, 125), (130, 420, 775),
        CollideType.ANTLINES, {'a', 'b'}
    )
    assert_bbox(
        bb - Vec(10, 20, -15),
        (30, 40, 95), (110, 430, 745),
        CollideType.ANTLINES, {'a', 'b'}
    )
    assert_bbox(
        bb - (10, 20, -15),
        (30, 40, 95), (110, 430, 745),
        CollideType.ANTLINES, {'a', 'b'}
    )


def test_bbox_parse_block() -> None:
    """Test parsing of a block-shaped bbox from a VMF."""
    vmf = VMF()
    ent = vmf.create_ent(
        'bee2_collision_bbox',
        coll_deco=1,
        coll_physics=1,
        coll_grating=0,
        tags='standard excellent',
    )
    ent.solids.append(vmf.make_prism(Vec(80, 10, 40), Vec(150, 220, 70)).solid)
    ent.solids.append(vmf.make_prism(Vec(-30, 45, 80), Vec(-20, 60, 120)).solid)
    bb2, bb1 =  BBox.from_ent(ent)
    # Allow it to produce in either order.
    if bb1.min_x == -30:
        bb1, bb2 = bb2, bb1
    assert_bbox(
        bb1,
        (80, 10, 40), (150, 220, 70),
        CollideType.DECORATION | CollideType.PHYSICS,
        {'standard', 'excellent'},
    )
    assert_bbox(
        bb2,
        (-30, 45, 80), (-20, 60, 120),
        CollideType.DECORATION | CollideType.PHYSICS,
        {'standard', 'excellent'},
    )


@pytest.mark.parametrize('axis, mins, maxes', [
    ('west',   (80, 10, 40),  (80, 220, 70)),   # -X
    ('east',   (150, 10, 40), (150, 220, 70)),  # +X
    ('south',  (80, 10, 40),  (150, 10, 70)),   # -Y
    ('north',  (80, 220, 40), (150, 220, 70)),  # +Y
    ('bottom', (80, 10, 40),  (150, 220, 40)),  # -Z
    ('top',    (80, 10, 70),  (150, 220, 70)),  # +Z
], ids=['-x', '+x', '-y', '+y', '-z', '+z'])
def test_bbox_parse_plane(axis: str, mins: tuple3, maxes: tuple3) -> None:
    """Test parsing planar bboxes from a VMF.

    With 5 skip sides, the brush is flattened into the remaining plane.
    """
    vmf = VMF()
    ent = vmf.create_ent('bee2_collision_bbox', coll_solid=1)
    prism = vmf.make_prism(Vec(80, 10, 40), Vec(150, 220, 70), mat='tools/toolsskip')
    getattr(prism, axis).mat = 'tools/toolsclip'
    ent.solids.append(prism.solid)
    [bbox] = BBox.from_ent(ent)
    assert_bbox(bbox, mins, maxes, CollideType.SOLID, set())
