""" Functions to produce tk-compatible images, using Pillow as a backend.

The image is saved in the dictionary, so it stays in memory. Otherwise
it could get deleted, which will make the rendered image vanish.
"""

import os.path
from PIL import ImageTk, Image

cached_img = {}

def png(path, resize_to=None, error=None, algo=Image.LANCZOS):
    """Loads in an image for use in TKinter.

    - The .png suffix will automatically be added.
    - Images will be loaded from both the inbuilt files and the extracted
    zip cache.
    - If resize_to is set, the image will be resized to that size using the algo
    algorithm.
    """
    if not path.casefold().endswith(".png"):
        path = path + ".png"
    orig_path = path

    if (orig_path, resize_to) in cached_img:
        return cached_img[orig_path, resize_to]

    if not os.path.isfile(os.path.join("../images", path)):
        # If not in the main folder, load from the zip-cache
        path = os.path.join("../images/cache/", path)
    path = os.path.join("../images", path)

    if os.path.isfile(path):
        image = Image.open(path)
    else:
        print('ERROR: "images\\' + orig_path + '" does not exist!')
        return error or img_error

    if resize_to:
        image = image.resize((resize_to, resize_to), algo)

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
    return png("items/" + name, error=error, resize_to=64)


# If image is not readable, use this instead
img_error = png('BEE2/error')