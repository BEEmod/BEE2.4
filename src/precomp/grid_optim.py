"""Optimise brushes or similar things in a 2D grid.

Given a grid of positions, produce a set of rectangular boxes that efficiently cover all
set positions.
"""
from typing import Any
from collections.abc import Mapping, Iterator

from plane import PlaneGrid


__all__ = ['optimise']
VOID: Any = object()  # Sentinel


def optimise[T](
    grid: Mapping[tuple[int, int], T] | PlaneGrid[T],
) -> Iterator[tuple[int, int, int, int, T]]:
    """Given a grid, produce an efficient set of bounding boxes for each value.

    The grid should be a (x, y): T dict.
    This yields (min_x, min_y, max_x, max_y, T) tuples, where this region has the same value.
    The values are compared by identity.
    """
    full_grid: PlaneGrid[T] = PlaneGrid(grid, default=VOID)
    x_min, y_min = full_grid.mins
    x_max, y_max = full_grid.maxes
    x_max += 1
    y_max += 1

    for x in range(x_min, x_max):
        for y in range(y_min, y_max):
            value = full_grid[x, y]
            if value is VOID:
                continue
            yield _do_cell(full_grid, value, x, y, x_max, y_max)

    assert all(v is VOID for v in full_grid.values()), full_grid


def _do_cell[T](
    grid: PlaneGrid[T],
    value: T,
    min_x: int,
    min_y: int,
    max_x: int,
    max_y: int,
) -> tuple[int, int, int, int, T]:
    """From a cell (min x/y) find a good rectangle."""
    # We want to try both x,y and y,x order to see which is better.
    x1 = x2 = min_x
    y1 = y2 = min_y

    # Extend in the x direction until we hit a boundary.
    for x1 in range(min_x, max_x + 1):
        if grid[x1, min_y] is not value:
            break
    # Then in y until we hit a boundary.
    for y1 in range(min_y, max_y + 1):
        if any(grid[x, y1] is not value for x in range(min_x, x1)):
            break

    # Then do it again but the other order.
    for y2 in range(min_y, max_y + 1):
        if grid[min_x, y2] is not value:
            break
    for x2 in range(min_x, max_x + 1):
        if any(grid[x2, y] is not value for y in range(min_y, y2)):
            break

    # Check which has a larger area.
    if (x1 - min_x) * (y1 - min_y) > (x2 - min_x) * (y2 - min_y):
        max_x, max_y = x1, y1
    else:
        max_x, max_y = x2, y2

    # Mark all spots as used.
    for x in range(min_x, max_x):
        for y in range(min_y, max_y):
            del grid[x, y]

    return min_x, min_y, max_x - 1, max_y - 1, value
