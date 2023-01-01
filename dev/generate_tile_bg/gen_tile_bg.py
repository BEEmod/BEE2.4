"""Generate a randomised tile background, for the error window."""
import random

from PIL import Image

# The first (full tile) panel is more often used.
tile_full = Image.open('ui_tile_128_interior1.tga')
tiles = [tile_full] * 4 + [
    Image.open('ui_tile_128_interior2.tga'),
    Image.open('ui_tile_128_interior3.tga'),
]

SIZE = 1024

img = Image.new('RGB', (SIZE, SIZE))
tile_size = tiles[0].width

for y in range(0, SIZE, tile_size):
    for x in range(0, SIZE, tile_size):
        img.paste(random.choice(tiles), (x, y))

img.save('../../error_display/static/tile_bg.png')
