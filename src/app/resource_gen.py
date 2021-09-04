"""Generates various resources depending on package options."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import colorsys

from srctools.vtf import VTF, ImageFormats
from app.itemconfig import ConfigGroup, parse_color
import srctools.logger

LOGGER = srctools.logger.get_logger(__name__)
# The number of cells to show in each row.
# They're offset halfway for each, this
# adds up to the 28 required and is somewhat
# circular.
COLORIZER_ROWS = [3, 4, 5, 4, 5, 4, 3]
assert sum(COLORIZER_ROWS) == 31 - 3
CELL_SIZE = 96
LEGEND_SIZE = 512


def make_cube_colourizer_legend(bee2_loc: Path) -> None:
    """Create a cube colourizer legend, showing the colours."""
    # Find the colourizer group, and grab its values. If not currently present,
    # we don't need to generate.
    try:
        config = ConfigGroup.by_id('BEE2_CUBE_COLORISER')
    except KeyError:
        LOGGER.debug('No cube colorizer config group!')
        return
    for wid in config.multi_widgets:
        if wid.id == 'color':
            break
    else:
        LOGGER.debug('No COLOR widget in {}', config.multi_widgets)
        return
    colors = {
        int(tim): parse_color(var.get())
        for tim, var in wid.values
    }

    img = Image.new('RGB', (LEGEND_SIZE, LEGEND_SIZE), color=(255, 255, 255))
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

    # Find a nice font.
    for filename in [
        'san fransisco.ttf',
        'segoeui.ttf',
        'lucida sans.ttf',
        'helvetica neue.ttf',
        'tahoma.ttf',
        'ubuntu.ttf',
    ]:
        try:
            font = ImageFont.truetype(filename, 36)
            break
        except IOError:
            pass
    else:
        LOGGER.warning('Failed to find font, add more OS fonts!')
        font = ImageFont.load_default()

    for x, y, tim in cells:
        coords = [
            (x - CELL_SIZE / 2, y),
            (x, y - CELL_SIZE / 2),
            (x + CELL_SIZE / 2, y),
            (x, y + CELL_SIZE / 2),
            (x - CELL_SIZE / 2, y),
        ]
        draw.polygon(coords, fill=colors[tim])
        draw.line(coords, (0, 0, 0), width=4)

        # Check brightness, if dim, switch to white.
        r, g, b = colors[tim]
        bright, i, q = colorsys.rgb_to_yiq(r/255, g/255, b/255)
        txt_color = (255, 255, 255) if bright < 0.5 else (0, 0, 0)

        draw.text((x, y), str(tim), fill=txt_color, font=font, anchor='mm')

    vtf = VTF(LEGEND_SIZE, LEGEND_SIZE, fmt=ImageFormats.DXT1)
    vtf.get().copy_from(img.tobytes(), ImageFormats.RGB888)
    vtf.clear_mipmaps()
    # Fill the small mipmaps with pure white, so when retracted
    # you don't see anything.
    for i in range(3, vtf.mipmap_count+1):
        frame = vtf.get(mipmap=i)
        frame.copy_from(b'\xFF' * (frame.width*frame.height), ImageFormats.I8)

    vtf_loc = bee2_loc / 'materials/BEE2/models/props_map_editor/cube_coloriser_legend.vtf'
    vtf_loc.parent.mkdir(parents=True, exist_ok=True)
    with vtf_loc.open('wb') as f:
        LOGGER.info('Exporting "{}"...', f.name)
        try:
            vtf.save(f)
        except NotImplementedError:
            LOGGER.warning('No DXT compressor, using RGB888.')
            # No libsquish, so DXT compression doesn't work.
            vtf.format = vtf.low_format = ImageFormats.RGB888
            f.truncate(0)
            f.seek(0)
            vtf.save(f)
