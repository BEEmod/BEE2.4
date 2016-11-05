""" Functions to produce tk-compatible images, using Pillow as a backend.

The image is saved in the dictionary, so it stays in memory. Otherwise
it could get deleted, which will make the rendered image vanish.
"""

from PIL import ImageTk, Image
import os.path

from srctools import Vec
import utils

LOGGER = utils.getLogger('img')

cached_img = {}
cached_squares = {}


def png(path, resize_to=None, error=None, algo=Image.NEAREST):
    """Loads in an image for use in TKinter.

    - The .png suffix will automatically be added.
    - Images will be loaded from both the inbuilt files and the extracted
    zip cache.
    - If resize_to is set, the image will be resized to that size using the algo
    algorithm.
    """
    if not path.casefold().endswith(".png"):
        path += ".png"
    orig_path = path

    if (orig_path, resize_to) in cached_img:
        return cached_img[orig_path, resize_to]

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

        if resize_to:
            image = image.resize((resize_to, resize_to), algo)

        # This also accesses the image file.
        img = ImageTk.PhotoImage(image=image)

    cached_img[path, resize_to] = img
    return img


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
            size=(size, size),
            color=(int(color.x), int(color.y), int(color.z)),
        )
        tk_img = ImageTk.PhotoImage(image=img)
        cached_squares[color.as_tuple(), size] = tk_img

        return tk_img


# If image is not readable, use this instead
img_error = png('BEE2/error')