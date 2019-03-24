""" Functions to produce tk-compatible images, using Pillow as a backend.

The image is saved in the dictionary, so it stays in memory. Otherwise
it could get deleted, which will make the rendered image vanish.
"""

from PIL import ImageTk, Image, ImageDraw
import os

from srctools import Vec
from srctools.filesys import FileSystem, RawFileSystem, FileSystemChain
import srctools.logger
import logging
import utils
from tk_tools import TK_ROOT  # Make sure this is initialised!

from typing import Iterable, Union, Dict, Tuple

LOGGER = srctools.logger.get_logger('img')

cached_img = {}  # type: Dict[Tuple[str, int, int], ImageTk.PhotoImage]
# r, g, b, size -> image
cached_squares = {}  # type: Dict[Union[Tuple[float, float, float, int], Tuple[str, int]], ImageTk.PhotoImage]

filesystem = FileSystemChain(
    # Highest priority is the in-built UI images.
    RawFileSystem(str(utils.install_path('images'))),
)

# Silence DEBUG messages from Pillow, they don't help.
logging.getLogger('PIL').setLevel(logging.INFO)


def load_filesystems(systems: Iterable[FileSystem]):
    """Load in the filesystems used in packages."""
    for sys in systems:
        filesystem.add_sys(sys, 'resources/BEE2/')


def tuple_size(size: Union[Tuple[int, int], int]) -> Tuple[int, int]:
    """Return an xy tuple given a size or tuple."""
    if isinstance(size, tuple):
        return size
    return size, size


def color_hex(color: Vec) -> str:
    """Convert a RGB colour to #xxxxxx."""
    r, g, b = color
    return '#{:2X}{:2X}{:2X}'.format(int(r), int(g), int(b))


def png(path: str, resize_to=0, error=None, algo=Image.NEAREST):
    """Loads in an image for use in TKinter.

    - The .png suffix will automatically be added.
    - Images will be loaded from both the inbuilt files and the extracted
    zip cache.
    - If resize_to is set, the image will be resized to that size using the algo
    algorithm.
    - This caches images, so it won't be deleted (Tk doesn't keep a reference
      to the Python object), and subsequent calls don't touch the hard disk.
    """
    path = path.casefold().replace('\\', '/')
    if path[-4:-3] != '.':
        path += ".png"

    orig_path = path

    resize_width, resize_height = resize_to = tuple_size(resize_to)

    try:
        return cached_img[path, resize_width, resize_height]
    except KeyError:
        pass

    with filesystem:
        try:
            img_file = filesystem[path]
        except (KeyError, FileNotFoundError):
            LOGGER.warning('ERROR: "images/{}" does not exist!', orig_path)
            return error or img_error
        with img_file.open_bin() as file:
            image = Image.open(file)  # type: Image.Image
            image.load()

    if resize_to != (0, 0) and resize_to != image.size:
        image = image.resize(resize_to, algo)
        # image.save(img_file._data.sys._resolve_path(img_file._data.path))

    tk_img = ImageTk.PhotoImage(image=image)

    cached_img[orig_path, resize_width, resize_height] = tk_img
    return tk_img


def spr(name, error=None):
    """Load in the property icons with the correct size."""
    # We're doubling the icon size, so use nearest-neighbour to keep
    # image sharpness
    return png('icons/'+name, error=error, resize_to=32, algo=Image.NEAREST)


def icon(name, error=None):
    """Load in a palette icon, using the correct directory and size."""
    return png('items/' + name, error=error, resize_to=64)


def get_app_icon(path: str):
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))


def make_splash_screen(
    max_width: float,
    max_height: float,
    base_height: int,
    text1_bbox: Tuple[int, int, int, int],
    text2_bbox: Tuple[int, int, int, int],
):
    """Create the splash screen image.

    This uses a random screenshot from the splash_screens directory.
    It then adds the gradients on top.
    """
    import random
    folder = str(utils.install_path('images/splash_screen'))
    path = '<nothing>'
    try:
        path = random.choice(os.listdir(folder))
        with open(os.path.join(folder, path), 'rb') as img_file:
            image = Image.open(img_file)
            image.load()
    except (FileNotFoundError, IndexError, IOError):
        # Not found, substitute a gray block.
        LOGGER.warning('No splash screen found (tried "{}")', path)
        image = Image.new(
            mode='RGB',
            size=(round(max_width), round(max_height)),
            color=(128, 128, 128),
        )
    else:
        if image.height > max_height:
            image = image.resize((
                round(image.width / image.height * max_height),
                round(max_height),
            ))
        if image.width > max_width:
            image = image.resize((
                round(max_width),
                round(image.height / image.width * max_width),
            ))

    draw = ImageDraw.Draw(image, 'RGBA')

    rect_top = image.height - base_height - 40
    draw.rectangle(
        (
            0,
            rect_top + 40,
            image.width,
            image.height,
         ),
        fill=(0, 150, 120, 64),
    )
    # Add a gradient above the rectangle..
    for y in range(40):
        draw.rectangle(
            (
                0,
                rect_top + y,
                image.width,
                image.height,
            ),
            fill=(0, 150, 120, int(y * 128/40)),
        )

    # Draw the shadows behind the text.
    # This is done by progressively drawing smaller rectangles
    # with a low alpha. The center is overdrawn more making it thicker.
    for x1, y1, x2, y2 in [text1_bbox, text2_bbox]:
        for border in reversed(range(5)):
            draw.rectangle(
                (
                    x1 - border,
                    y1 - border,
                    x2 + border,
                    y2 + border,
                ),
                fill=(0, 150, 120, 20),
            )

    tk_img = ImageTk.PhotoImage(image=image)
    return tk_img, image.width, image.height


def color_square(color: Vec, size=16):
    """Create a square image of the given size, with the given color."""
    key = color.x, color.y, color.z, size

    try:
        return cached_squares[key]
    except KeyError:
        img = Image.new(
            mode='RGB',
            size=tuple_size(size),
            color=(int(color.x), int(color.y), int(color.z)),
        )
        tk_img = ImageTk.PhotoImage(image=img)
        cached_squares[key] = tk_img
        return tk_img


def invis_square(size):
    """Create a square image of the given size, filled with 0-alpha pixels."""

    try:
        return cached_squares['alpha', size]
    except KeyError:
        img = Image.new(
            mode='RGBA',
            size=tuple_size(size),
            color=(0, 0, 0, 0),
        )
        tk_img = ImageTk.PhotoImage(image=img)
        cached_squares['alpha', size] = tk_img

        return tk_img

# Colour of the palette item background
PETI_ITEM_BG = Vec(229, 232, 233)
PETI_ITEM_BG_HEX = color_hex(PETI_ITEM_BG)


BLACK_64 = color_square(Vec(0, 0, 0), size=64)
BLACK_96 = color_square(Vec(0, 0, 0), size=96)
PAL_BG_64 = color_square(PETI_ITEM_BG, size=64)
PAL_BG_96 = color_square(PETI_ITEM_BG, size=96)

# If image is not readable, use this instead
# If this actually fails, use the black image.
img_error = png('BEE2/error', error=BLACK_64)
