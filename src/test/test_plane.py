"""Test the Plane class."""
from collections import Counter
from typing import List, Tuple, Optional, no_type_check

from plane import Plane
import pytest


@pytest.mark.parametrize('dx, dy', [
    (-2, 0), (2, 0), (0, -2), (0, 2),
    (2, 2), (-2, 2), (2, -2), (-2, -2),
])
def test_insertion(dx, dy) -> None:
    """Simple tests to ensure resizing works in each direction."""
    plane = Plane[object]()
    for i in range(10):
        assert len(plane) == i, f'{dx*i}, {dy*i}'
        plane[dx*i, dy*i] = i
        assert len(plane) == i + 1, f'{dx*i}, {dy*i}'
        try:
            assert plane[dx*i, dy*i] == i
            assert plane.get((dx*i, dy*i)) == i
        except KeyError:
            pytest.fail(f'{dx*i}, {dy*i}')
    expected = {
        (dx*i, dy*i): i
        for i in range(10)
    }
    assert dict(plane.items()) == expected
    # Check other positions are ignored.
    min_x, min_y = plane.mins
    max_x, max_y = plane.maxes
    for x in range(min_x-1, max_x+2):
        for y in range(min_y-1, max_y+2):
            if (x, y) not in expected:
                with pytest.raises(KeyError):
                    _ = plane[x, y]  # type: ignore
                assert plane.get((x, y), 'hi') == 'hi'


def _points(*pattern):
    """Return each coordinate in order in the string map."""
    points = [
        (x, y)
        for x in range(5)
        for y in range(5)
        if pattern[y][x] != '.'
    ]
    points.sort(key=lambda pos: int(pattern[pos[1]][pos[0]]))
    return points


@pytest.mark.parametrize('off_x, off_y', [
    (3, 3), (1, 0), (0, 1), (1, 2), (2, 2), (4, 4), (0, 0), (-2, 10), (10, -5), (50, 50),
])
@pytest.mark.parametrize('pattern', [
    [(x, y) for x in  range(5) for y in range(5)],
    _points(
        '.7..8',
        '..6..',
        '..012',
        '.534.',
        '...9.',
    ), _points(
        '0.4..',
        '.1.9.',
        '.2..8',
        '53.7.',
        '...6.',
    ), _points(
        '...8.',
        '.7..1',
        '.2.6.',
        '..3..',
        '54..0',
    ),
], ids=['order', 'patA', 'patB', 'patC'])
def test_insertion_complex(pattern: List[Tuple[int, int]], off_x: int, off_y: int):
    """Insert in various patterns, to test the dynamic resizing."""
    plane = Plane[object]()
    backup = {}
    # First iteration will update.
    min_x = min_y = +99999
    max_x = max_y = -99999
    for val, (x, y) in enumerate(pattern):
        x -= off_x
        y -= off_y
        plane[x, y] = val
        assert plane[x, y] == val
        backup[x, y] = val
        # Manually track min/max to check validity.
        if x < min_x:
            min_x = x
        if y < min_y:
            min_y = y
        if x > max_x:
            max_x = x
        if y > max_y:
            max_y = y
        assert plane.mins == (min_x, min_y)
        assert plane.maxes == (max_x, max_y)

        assert dict(plane.items()) == backup
        for (chk_x, chk_y), check in backup.items():
            assert plane[chk_x, chk_y] == check, backup


def test_views() -> None:
    """Test the view objects."""
    plane: Plane[Optional[int]] = Plane()
    plane[0, 4] = 1
    plane[2, -5] = None
    plane[0, 5] = 3
    plane[0, 7] = 2
    plane[5, 3] = 2

    assert (0, 4) in plane.keys()
    assert (1, 4) not in plane.keys()
    assert (2, -5) in plane.keys()
    assert set(plane.keys()) == {
        (0, 4), (2, -5), (0, 5), (0, 7), (5, 3),
    }

    # Check illegal values don't error.
    assert "ab" not in plane.keys()
    assert (1, ) not in plane.keys()
    assert (3, 4, 5) not in plane.keys()

    assert 1 in plane.values()
    assert 45 not in plane.values()
    assert None in plane.values()
    assert Counter(plane.values()) == {1: 1, 2: 2, 3: 1, None: 1}

    assert ((0, 5), 3) in plane.items()
    assert ((2, -5), 4) not in plane.items()
    assert ((3, 4), 2) not in plane.items()
    # Check illegal values don't error.
    assert 45 not in plane.items()
    assert (1, ) not in plane.items()
    assert (1, 2, 3, 4) not in plane.items()
    assert set(plane.items()) == {
        ((0, 4), 1), ((2, -5), None), ((0, 5), 3), ((0, 7), 2), ((5, 3), 2),
    }

    # Check keys, values, items is in the same order.
    assert list(zip(plane.keys(), plane.values())) == list(plane.items())


# noinspection PyTypeChecker
@no_type_check
def test_illegal_positions() -> None:
    """Test invalid positions produce a KeyError."""
    plane = Plane()
    plane[1, 2] = 5
    assert plane[1.0, 2.0] == 5
    with pytest.raises(KeyError):
        _ = plane[45, 9, 2]  # type: ignore
    with pytest.raises(KeyError):
        _ = plane[45]  # type: ignore
    with pytest.raises(KeyError):
        _ = plane["blah", 9]  # type: ignore
    with pytest.raises(KeyError):
        _ = plane[9, "blah"]  # type: ignore
    with pytest.raises(KeyError):
        _ = plane[2, 8]  # type: ignore

    assert plane.get((2, 8)) is None
    assert plane.get((2, 8), 45) == 45

    with pytest.raises(KeyError):
        plane[45, 9, 2] = object  # type: ignore
    with pytest.raises(KeyError):
        plane[45] = object  # type: ignore
    with pytest.raises(KeyError):
        plane["blah", 9] = object  # type: ignore
    with pytest.raises(KeyError):
        plane[9, "blah"] = object  # type: ignore

    with pytest.raises(KeyError):
        del plane[45, 9, 2]  # type: ignore
    with pytest.raises(KeyError):
        del plane[45]  # type: ignore
    with pytest.raises(KeyError):
        del plane["blah", 9]  # type: ignore
    with pytest.raises(KeyError):
        del plane[9, "blah"]  # type: ignore


def test_deletion() -> None:
    """Test deleting positions."""
    plane = Plane[int]()
    plane[5, 5] = 4
    plane[4, 5] = 3
    plane[5, 4] = 3
    plane[6, 5] = 3
    plane[5, 6] = 3
    assert len(plane) == 5
    for _ in 1, 2:
        # Test they can be re-deleted.
        del plane[4, 5]
        del plane[5, 4]
        del plane[6, 5]
        del plane[5, 6]
    # Never-set is fine.
    del plane[5, 23]
    del plane[-10, 4]
    # Check we didn't double-count.
    assert len(plane) == 1


def test_defaults() -> None:
    """Test the ability to set a default value for all keys."""
    plane_req = Plane[int]()
    plane_opt = Plane[int](default=45)

    plane_req[2, 5] = plane_opt[2, 5] = 3
    assert plane_req[2, 5] == 3
    assert plane_opt[2, 5] == 3

    for x in range(-10, 10):
        for y in range(-10, 10):
            if x == 2 and y == 5:
                continue
            with pytest.raises(KeyError):
                _ = plane_req[x, y]  # type: ignore
            assert plane_opt[x, y] == 45
