"""Wrapper functions for tkinter_png.

- These just return the converted photoimage.
- The image is saved in the dictionary, so it stays in memory. Otherwise
  it could get deleted, which will make the rendered image vanish.
"""

import os.path
import tkinter_png

loaded_png = {}
loaded_spr = {}

def png(path, error=None):
    """Loads in and converts a png for use in TKinter."""
    if not path.casefold().endswith(".png"):
        path=path+".png"
    orig_path = path
    if path in loaded_png:
        return loaded_png[path]
    else:
        if not os.path.isfile("images/" + path):
            # If not in the main folder, load from the zip-cache
            path = os.path.join("cache/", path)
        path = os.path.normpath(os.path.join("images", path))
        if not os.path.isfile(path):
            print('ERROR: "images\\' + orig_path + '" does not exist!')
            if error is not None:
                return error
            else:
                return img_error
        tmp = tkinter_png.PngImageTk(path)
        tmp.convert()
        loaded_png[orig_path] = tmp.image
        return tmp.image


def spr(name, error=None):
    """Load in the property icons and automatically double the dimensions."""
    if name in loaded_spr:
        return loaded_spr[name]
    else:
        ico = png('icons/'+name, error=error).zoom(2)
        loaded_spr[name] = ico
        return ico


def icon(name, error=None):
    """Load in a palette icon, ensuring the correct size."""
    name = "items/" + name
    img = png(name, error=error)
    if img.width() != 64 or img.height() != 64:
        print("ERROR: \"" + name + "\" is not 64x64!")
        if error is not None:
            return error
        else:
            return img_error
    else:
        return img

# If image is not readable, use this instead
img_error = png('BEE2/error')