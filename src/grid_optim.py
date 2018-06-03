"""Optimise brushes or similar things in a 2D grid.

Given a grid of on/off positions, produce a set of rectangular boxes that
efficiently cover the True positions without the False ones.
"""
from typing import Tuple, Dict

from enum import Enum


__all__ = ['optimise']


class Pos(Enum):
    """Internal enum for representing the position status."""
    VOID = False  # Shouldn't be filled
    TO_SET = True  # Should be filled, but not yet
    SET = 2  # Should be filled, and is already

    @property
    def no_fill(self):
        """Is filling disallowed here?"""
        return self.value is not True

    def __str__(self):
        return '-x#'[self.value]


def optimise(grid: Dict[Tuple[int, int], bool]):
    """Given a grid, return min, max pairs which fill the space.

    The grid should be a (x, y): bool dict.
    This yields (min_x, min_y, max_x, max_y) tuples.
    """
    x_len = y_len = 0
    for x, y in grid:
        x_len = max(x, x_len)
        y_len = max(y, y_len)
    # Force to int if they're floats.
    x_len = int(x_len) + 1
    y_len = int(y_len) + 1

    full_grid = {
        (x, y): Pos(bool(grid.get((x, y), False)))
        for x in range(x_len)
        for y in range(y_len)
    }  # type: Dict[Tuple[int, int], Pos]

    # Add guard data at the edge of the grid.
    for x in range(x_len):
        full_grid[x, y_len] = Pos.VOID
    for y in range(y_len):
        full_grid[x_len, y] = Pos.VOID

    for x in range(x_len):
        for y in range(y_len):
            if full_grid[x, y] is not Pos.TO_SET:
                continue
            yield _do_cell(full_grid, x, y, x_len, y_len)

    assert all(v is not Pos.TO_SET for v in full_grid.values())


def _do_cell(
    grid: Dict[Tuple[int, int], Pos],
    min_x: int,
    min_y: int,
    max_x: int,
    max_y: int,
):
    """From a cell (min x/y) find a good rectangle."""
    # We want to try both x,y and y,x order to see which is better.
    x1 = x2 = min_x
    y1 = y2 = min_y

    # Extend in the x direction until we hit a boundary.
    for x1 in range(min_x, max_x + 1):
        if grid[x1, min_y].no_fill:
            break
    # Then in y until we hit a boundary.
    for y1 in range(min_y, max_y + 1):
        if any(grid[x, y1].no_fill for x in range(min_x, x1)):
            break

    # Then do it again but the other order.
    for y2 in range(min_y, max_y + 1):
        if grid[min_x, y2].no_fill:
            break
    for x2 in range(min_x, max_x + 1):
        if any(grid[x2, y].no_fill for y in range(min_y, y2)):
            break

    # Check which has a larger area.
    if (x1 - min_x) * (y1 - min_y) > (x2 - min_x) * (y2 - min_y):
        max_x, max_y = x1, y1
    else:
        max_x, max_y = x2, y2

    # Mark all spots as used.
    for x in range(min_x, max_x):
        for y in range(min_y, max_y):
            grid[x, y] = Pos.SET

    return min_x, min_y, max_x - 1, max_y - 1
