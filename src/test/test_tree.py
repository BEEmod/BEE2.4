"""Test the tree wrapper."""
from srctools import Vec
from tree import RTree
from random import Random


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
    tree = RTree()
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
