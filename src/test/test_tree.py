"""Test the tree wrapper."""
from srctools import Vec
from tree import RTree
from random import Random


def test_duplicate_insertion() -> None:
    """Test inserting values with the same bbox."""
    tree: RTree[str] = RTree()
    tree.insert(Vec(10, 20, 30), Vec(40, 50, 60), 'value1')
    tree.insert(Vec(50, 20, 30), Vec(80, 65, 60), 'another')
    tree.insert(Vec(10, 20, 30), Vec(40, 50, 60), 'value2')
    assert len(tree) == 3
    # Iterating produces both values.
    assert {
        (*mins, *maxes, val)
        for mins, maxes, val in tree
    } == {
        (10, 20, 30, 40, 50, 60, 'value1'),
        (50, 20, 30, 80, 65, 60, 'another'),
        (10, 20, 30, 40, 50, 60, 'value2'),
    }
    # Check all vecs are unique.
    vecs = [
        vec for mins, maxes, _ in tree
        for vec in [mins, maxes]
    ]
    assert len(set(map(id, vecs))) == 6, list(tree)
    # Check we can delete one.
    tree.remove(Vec(10, 20, 30), Vec(40, 50, 60), 'value1')
    assert {
        (*mins, *maxes, val)
        for mins, maxes, val in tree
    } == {
        (50, 20, 30, 80, 65, 60, 'another'),
        (10, 20, 30, 40, 50, 60, 'value2'),
    }


def test_bbox() -> None:
    """Test the bounding box behaviour against a brute-force loop."""
    rand = Random(1234)  # Ensure reproducibility.
    SIZE = 128.0
    # Build a set of points and keys.
    points = [
        (
            Vec(rand.uniform(-SIZE, SIZE), rand.uniform(-SIZE, SIZE), rand.uniform(-SIZE, SIZE)),
            Vec(rand.uniform(-SIZE, SIZE), rand.uniform(-SIZE, SIZE), rand.uniform(-SIZE, SIZE)),
            rand.getrandbits(64).to_bytes(8, 'little')
        )
        for _ in range(200)
    ]
    tree: RTree[bytes] = RTree()
    for a, b, data in points:
        tree.insert(a, b, data)

    # Pick a random bounding box.
    bb_min, bb_max = Vec.bbox(Vec(
        rand.uniform(-SIZE, SIZE),
        rand.uniform(-SIZE, SIZE),
        rand.uniform(-SIZE, SIZE),
    ), Vec(
        rand.uniform(-SIZE, SIZE),
        rand.uniform(-SIZE, SIZE),
        rand.uniform(-SIZE, SIZE),
    ))
    expected = [
        data
        for a, b, data in points
        if Vec.bbox_intersect(*Vec.bbox(a, b), bb_min, bb_max)
    ]
    found = set(tree.find_bbox(bb_min, bb_max))
    # Order is irrelevant, but duplicates must all match.
    assert sorted(expected) == sorted(found)
