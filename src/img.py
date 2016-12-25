""" Functions to produce tk-compatible images, using Pillow as a backend.

The image is saved in the dictionary, so it stays in memory. Otherwise
it could get deleted, which will make the rendered image vanish.
"""

from PIL import ImageTk, Image
import os.path

from srctools import Vec
import utils

from typing import Union, Dict, Tuple

LOGGER = utils.getLogger('img')

cached_img = {}  # type: Dict[Tuple[str, int], ImageTk.PhotoImage]
# r, g, b, size -> image
cached_squares = {}  # type: Dict[Union[Tuple[float, float, float, int], Tuple[str, int]], ImageTk.PhotoImage]

# Colour of the palette item background
PETI_ITEM_BG = Vec(229, 232, 233)


def tuple_size(size: Union[Tuple[int, int], int]) -> Tuple[int, int]:
    """Return an xy tuple given a size or tuple."""
    if isinstance(size, tuple):
        return size
    return size, size


def png(path, resize_to=0, error=None, algo=Image.NEAREST):
    """Loads in an image for use in TKinter.

    - The .png suffix will automatically be added.
    - Images will be loaded from both the inbuilt files and the extracted
    zip cache.
    - If resize_to is set, the image will be resized to that size using the algo
    algorithm.
    - This caches images, so it won't be deleted (Tk doesn't keep a reference
      to the Python object), and subsequent calls don't touch the hard disk.
    """
    if not path.casefold().endswith(".png"):
        path += ".png"
    orig_path = path

    try:
        return cached_img[path, resize_to]
    except KeyError:
        pass

    base_path = os.path.abspath(
        os.path.join(
            os.getcwd(),
            "../",
            "images",
            path,
        )
    )
    cache_path = os.path.abspath(
        os.path.join(
            os.getcwd(),
            "../",
            "images",
            "cache",
            path,
        )
    )

    if os.path.isfile(base_path):
        path = base_path
    else:
        # If not in the main folder, load from the zip-cache
        path = cache_path

    try:
        img_file = open(path, 'rb')
    except FileNotFoundError:
        LOGGER.warning('ERROR: "images/{}" does not exist!', orig_path)
        return error or img_error
    with img_file:
        image = Image.open(img_file)
        image.load()

    if resize_to:
        image = image.resize(tuple_size(resize_to), algo)

    tk_img = ImageTk.PhotoImage(image=image)

    cached_img[orig_path, resize_to] = tk_img
    return tk_img


def spr(name, error=None):
    """Load in the property icons with the correct size."""
    # We're doubling the icon size, so use nearest-neighbour to keep
    # image sharpness
    return png('icons/'+name, error=error, resize_to=32, algo=Image.NEAREST)


def icon(name, error=None):
    """Load in a palette icon, using the correct directory and size."""
    return png(os.path.join("items", name), error=error, resize_to=64)


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

BLACK_64 = color_square(Vec(0, 0, 0), size=64)
BLACK_96 = color_square(Vec(0, 0, 0), size=96)
PAL_BG_64 = color_square(PETI_ITEM_BG, size=64)
PAL_BG_96 = color_square(PETI_ITEM_BG, size=96)

# If image is not readable, use this instead
# If this actually fails, use the black image.
img_error = png('BEE2/error', error=BLACK_64)