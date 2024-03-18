"""Test the Grid class."""
from typing import List, Optional, Tuple, no_type_check
from collections import Counter

import pytest

from plane import PlaneGrid


@pytest.mark.parametrize('dx, dy', [
    (-2, 0), (2, 0), (0, -2), (0, 2),
    (2, 2), (-2, 2), (2, -2), (-2, -2),
])
def test_insertion(dx: int, dy: int) -> None:
    """Simple tests to ensure resizing works in each direction."""
    grid = PlaneGrid[object]()
    for i in range(10):
        assert len(grid) == i, f'{dx * i}, {dy * i}'
        grid[dx * i, dy * i] = i
        assert len(grid) == i + 1, f'{dx * i}, {dy * i}'
        try:
            assert grid[dx * i, dy * i] == i
            assert grid.get((dx * i, dy * i)) == i
        except KeyError:
            pytest.fail(f'{dx*i}, {dy*i}')
    expected = {
        (dx*i, dy*i): i
        for i in range(10)
    }
    assert dict(grid.items()) == expected
    # Check other positions are ignored.
    min_x, min_y = grid.mins
    max_x, max_y = grid.maxes
    for x in range(min_x-1, max_x+2):
        for y in range(min_y-1, max_y+2):
            if (x, y) not in expected:
                with pytest.raises(KeyError):
                    _ = grid[x, y]
                assert grid.get((x, y), 'hi') == 'hi'


def _points(*pattern: str) -> List[Tuple[int, int]]:
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
def test_insertion_complex(pattern: List[Tuple[int, int]], off_x: int, off_y: int) -> None:
    """Insert in various patterns, to test the dynamic resizing."""
    grid = PlaneGrid[object]()
    backup = {}
    # First iteration will update.
    min_x = min_y = +99999
    max_x = max_y = -99999
    for val, (x, y) in enumerate(pattern):
        x -= off_x
        y -= off_y
        grid[x, y] = val
        assert grid[x, y] == val
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
        assert grid.mins == (min_x, min_y)
        assert grid.maxes == (max_x, max_y)
        assert grid.dimensions == (max_x - min_x, max_y - min_y)

        assert dict(grid.items()) == backup
        for (chk_x, chk_y), check in backup.items():
            assert grid[chk_x, chk_y] == check, backup


def test_views() -> None:
    """Test the view objects."""
    grid: PlaneGrid[Optional[int]] = PlaneGrid()
    grid[0, 4] = 1
    grid[2, -5] = None
    grid[0, 5] = 3
    grid[0, 7] = 2
    grid[5, 3] = 2

    assert (0, 4) in grid.keys()
    assert (1, 4) not in grid.keys()
    assert (2, -5) in grid.keys()
    assert set(grid.keys()) == {
        (0, 4), (2, -5), (0, 5), (0, 7), (5, 3),
    }

    # Check illegal values don't error.
    assert "ab" not in grid.keys()
    assert (1, ) not in grid.keys()
    assert (3, 4, 5) not in grid.keys()

    assert 1 in grid.values()
    assert 45 not in grid.values()
    assert None in grid.values()
    assert Counter(grid.values()) == {1: 1, 2: 2, 3: 1, None: 1}

    assert ((0, 5), 3) in grid.items()
    assert ((2, -5), 4) not in grid.items()
    assert ((3, 4), 2) not in grid.items()
    # Check illegal values don't error.
    assert 45 not in grid.items()
    assert (1, ) not in grid.items()
    assert (1, 2, 3, 4) not in grid.items()
    assert set(grid.items()) == {
        ((0, 4), 1), ((2, -5), None), ((0, 5), 3), ((0, 7), 2), ((5, 3), 2),
    }

    # Check keys, values, items is in the same order.
    assert list(zip(grid.keys(), grid.values())) == list(grid.items())


# noinspection PyTypeChecker
@no_type_check
def test_illegal_positions() -> None:
    """Test invalid positions produce a KeyError."""
    grid = PlaneGrid()
    grid[1, 2] = 5
    assert grid[1.0, 2.0] == 5
    with pytest.raises(KeyError):
        _ = grid[45, 9, 2]
    with pytest.raises(KeyError):
        _ = grid[45]
    with pytest.raises(KeyError):
        _ = grid["blah", 9]
    with pytest.raises(KeyError):
        _ = grid[9, "blah"]
    with pytest.raises(KeyError):
        _ = grid[2, 8]

    assert grid.get((2, 8)) is None
    assert grid.get((2, 8), 45) == 45

    with pytest.raises(KeyError):
        grid[45, 9, 2] = object
    with pytest.raises(KeyError):
        grid[45] = object
    with pytest.raises(KeyError):
        grid["blah", 9] = object
    with pytest.raises(KeyError):
        grid[9, "blah"] = object

    with pytest.raises(KeyError):
        del grid[45, 9, 2]
    with pytest.raises(KeyError):
        del grid[45]
    with pytest.raises(KeyError):
        del grid["blah", 9]
    with pytest.raises(KeyError):
        del grid[9, "blah"]


def test_deletion() -> None:
    """Test deleting positions."""
    grid = PlaneGrid[int]()
    grid[5, 5] = 4
    grid[4, 5] = 3
    grid[5, 4] = 3
    grid[6, 5] = 3
    grid[5, 6] = 3
    assert len(grid) == 5
    for _ in 1, 2:
        # Test they can be re-deleted.
        del grid[4, 5]
        del grid[5, 4]
        del grid[6, 5]
        del grid[5, 6]
    # Never-set is fine.
    del grid[5, 23]
    del grid[-10, 4]
    # Check we didn't double-count.
    assert len(grid) == 1


def test_defaults() -> None:
    """Test the ability to set a default value for all keys."""
    grid_req = PlaneGrid[int]()
    grid_opt = PlaneGrid[int](default=45)

    grid_req[2, 5] = grid_opt[2, 5] = 3
    assert grid_req[2, 5] == 3
    assert grid_opt[2, 5] == 3

    for x in range(-10, 10):
        for y in range(-10, 10):
            if x == 2 and y == 5:
                continue
            with pytest.raises(KeyError):
                _ = grid_req[x, y]
            assert grid_opt[x, y] == 45
