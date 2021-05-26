"""Generates various resources depending on package options."""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math
import itertools

# The number of cells to show in each row.
# They're offset halfway for each, this
# adds up to the 28 required and is somewhat
# circular.
COLORIZER_ROWS = [3, 4, 5, 4, 5, 4, 3]
assert sum(COLORIZER_ROWS) == 31 - 3
CELL_SIZE = 96


def make_cube_colourizer_legend(
    bee2_loc: Path,
    colors: dict[int, tuple[int, int, int]],
) -> None:
    """Create a cube colourizer legend, showing the colours."""
    img = Image.new('RGB', (512, 512), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # First, calculate the centers of all the cells.
    timer = 3
    cells = []
    for y, row_count in enumerate(COLORIZER_ROWS):
        y -= len(COLORIZER_ROWS) // 2
        for x, tim_val in enumerate(range(timer, timer + row_count)):
            x -= row_count / 2 - 0.5
            cells.append((256 + x * CELL_SIZE, 256 + y * CELL_SIZE/2, tim_val))

        timer += row_count
    assert timer-1 == 30, f'Last cell = {timer-1}'

