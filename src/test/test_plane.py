"""Test the Plane class."""
from typing import List, Tuple

from plane import Plane
import pytest


@pytest.mark.parametrize('dx, dy', [
    (-2, 0), (2, 0), (0, -2), (0, 2),
    (2, 2), (-2, 2), (2, -2), (-2, -2),
])
def test_insertion(dx, dy) -> None:
    """Simple tests to ensure resizing works in each direction."""
    plane = Plane()
    for i in range(10):
        assert len(plane) == i, f'{dx*i}, {dy*i}'
        plane[dx*i, dy*i] = i
        assert len(plane) == i + 1, f'{dx*i}, {dy*i}'
        try:
            assert plane[dx*i, dy*i] == i
        except KeyError:
            pytest.fail(f'{dx*i}, {dy*i}')

    assert dict(plane.items()) == {
        (dx*i, dy*i): i
        for i in range(10)
    }


def _points(*pattern):
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
    plane = Plane()
    backup = {}
    min_x = min_y = max_x = max_y = 0
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
    plane: Plane[int] = Plane()
    plane[0, 4] = 1
    plane[2, -5] = 2
    plane[0, 5] = 3
    plane[0, 7] = 2

    assert (0, 4) in plane.keys()
    assert (1, 4) not in plane.keys()
    assert set(plane.keys()) == {
        (0, 4), (2, -5), (0, 5), (0, 7),
    }

    # Check illegal values don't error.
    assert "ab" not in plane.keys()
    assert (1, ) not in plane.keys()
    assert (3, 4, 5) not in plane.keys()

    assert 1 in plane.values()
    assert 45 not in plane.values()
    assert None not in plane.values()  # Special case
    assert sorted(plane.values()) == [1, 2, 2, 3]

    assert ((0, 5), 3) in plane.items()
    assert ((2, -5), 4) not in plane.items()
    assert ((3, 4), 2) not in plane.items()
    # Check illegal values don't error.
    assert 45 not in plane.items()
    assert (1, ) not in plane.items()
    assert (1, 2, 3, 4) not in plane.items()

    # Check keys, values, items is in the same order.
    assert list(zip(plane.keys(), plane.values())) == list(plane.items())


# noinspection PyTypeChecker
def test_illegal_positions() -> None:
    """Test invalid positions produce a KeyError."""
    plane = Plane()
    plane[1, 2] = 5
    assert plane[1.0, 2.0] == 5
    with pytest.raises(KeyError):
        _ = plane[45, 9, 2]
    with pytest.raises(KeyError):
        _ = plane[45]
    with pytest.raises(KeyError):
        _ = plane["blah", 9]
    with pytest.raises(KeyError):
        _ = plane[9, "blah"]

    with pytest.raises(KeyError):
        plane[45, 9, 2] = object
    with pytest.raises(KeyError):
        plane[45] = object
    with pytest.raises(KeyError):
        plane["blah", 9] = object
    with pytest.raises(KeyError):
        plane[9, "blah"] = object
