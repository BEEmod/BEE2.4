""" Functions to produce tk-compatible images, using Pillow as a backend.

The image is saved in the dictionary, so it stays in memory. Otherwise
it could get deleted, which will make the rendered image vanish.
"""

from PIL import ImageTk, Image, ImageDraw
import os
import weakref
import tkinter as tk
from tkinter import ttk

from srctools import Vec, Property
from srctools.filesys import FileSystem, RawFileSystem, FileSystemChain
from utils import PackagePath
import srctools.logger
import logging
import utils

from typing import (
    Iterable, Union, Dict, Tuple, Callable, Optional, TypeVar,
    Generic, MutableMapping
)

# These are both valid TK image types.
tkImage = Union[ImageTk.PhotoImage, tk.PhotoImage]
# Widgets with an image attribute that can be set.
tkImgWidgets = Union[tk.Label, ttk.Label, tk.Button, ttk.Button]

ArgT = TypeVar('ArgT')

# Used to deduplicate handles.
_handles: Dict[tuple, 'Handle'] = {}
_wid_tk: MutableMapping[tkImgWidgets, 'Handle'] = weakref.WeakKeyDictionary()

LOGGER = srctools.logger.get_logger('img')
FSYS_BUILTIN = RawFileSystem(str(utils.install_path('images')))
FSYS_BUILTIN.open_ref()
PACK_SYSTEMS: Dict[str, FileSystem] = {}

# Silence DEBUG messages from Pillow, they don't help.
logging.getLogger('PIL').setLevel(logging.INFO)

# Colour of the palette item background
PETI_ITEM_BG = (229, 232, 233)
PETI_ITEM_BG_HEX = '#{:2X}{:2X}{:2X}'.format(*PETI_ITEM_BG)


def _load_special(path: str) -> Image.Image:
    """Various special images we have to load."""
    try:
        img = Image.open(utils.install_path(f'images/BEE2/{path}.png'))
        img.load()
        return img
    except Exception:
        LOGGER.warning('Error icon could not be loaded.', exc_info=True)
        return Image.new('RGB', (64, 64), PETI_ITEM_BG)

ICO_ERROR = _load_special('error')
ICO_NONE = _load_special('none')
ICO_LOAD = _load_special('load')


def load_filesystems(systems: Dict[str, FileSystem]):
    """Load in the filesystems used in packages."""
    PACK_SYSTEMS.clear()
    for pak_id, sys in systems.items():
        PACK_SYSTEMS[pak_id] = FileSystemChain(
            (sys, 'resources/BEE2/'),
            (sys, 'resources/materials/models/props_map_editor/'),
        )


def tuple_size(size: Union[Tuple[int, int], int]) -> Tuple[int, int]:
    """Return an xy tuple given a size or tuple."""
    if isinstance(size, tuple):
        return size
    return size, size


# Special paths which map to various images.
PATH_BLANK = PackagePath('special', 'blank')
PATH_ERROR = PackagePath('special', 'error')
PATH_LOAD = PackagePath('special', 'load')
PATH_NONE = PackagePath('special', 'none')
PATH_BG = PackagePath('color', PETI_ITEM_BG_HEX[1:])
PATH_BLACK = PackagePath('color', '000')
PATH_WHITE = PackagePath('color', 'fff')

# TODO: Eradicate usage
BLACK_64 = NotImplemented
BLACK_96 = NotImplemented
PAL_BG_64 = NotImplemented
PAL_BG_96 = NotImplemented
img_error = NotImplemented


class ImageType(Generic[ArgT]):
    """Represents a kind of image that can be loaded or generated.

    This contains callables for generating a PIL or TK image from a specified
    arg type, width and height.
    """
    def __init__(
        self,
        name: str,
        pil_func: Callable[[ArgT, int, int], Image.Image],
        tk_func: Optional[Callable[[ArgT, int, int], tkImage]]=None,
    ) -> None:
        self.name = name
        self.pil_func = pil_func
        self.tk_func = tk_func

    def __repr__(self) -> str:
        return f'<ImageType "{self.name}">'


def _pil_from_color(color: Tuple[int, int, int], width: int, height: int) -> Image.Image:
    """Directly produce an image of this size with the specified color."""
    return Image.new('RGB', (width, height), color)


def _tk_from_color(color: Tuple[int, int, int], width: int, height: int) -> tkImage:
    """Directly produce an image of this size with the specified color."""
    r, g, b = color
    img = tk.PhotoImage(width=width, height=height)
    # Make hex RGB, then set the full image to that.
    img.put(f'#{r:2X}{g:2X}{b:2X}', to=(0, 0, width, height))
    return img


def _pil_empty(arg: object, width: int, height: int) -> Image.Image:
    """Produce an image of this size with transparent pixels."""
    return Image.new('RGBA', (width, height), (0, 0, 0, 0))


def _tk_empty(arg: object, width: int, height: int) -> tkImage:
    """Produce a TK image of this size which is entirely transparent."""
    img = tk.PhotoImage(width=width, height=height)
    img.blank()
    return img


def _pil_from_file(uri: PackagePath, width: int, height: int) -> Image.Image:
    if uri.package == 'bee2':
        fsys = FSYS_BUILTIN
    else:
        try:
            fsys = PACK_SYSTEMS[uri.package]
        except KeyError:
            LOGGER.warning('Unknown package "{}" for loading images!', uri.package)
            return _pil_from_color((0, 0, 0), width, height)
            # TODO: return error or img_error

    path = uri.path.casefold()
    if path[-4:-3] != '.':
        path += ".png"

    image: Image.Image
    with fsys:
        try:
            img_file = fsys[path]
        except (KeyError, FileNotFoundError):
            LOGGER.warning('ERROR: "{}" does not exist!', uri, exc_info=True)
            return _pil_from_color((0, 0, 0), width, height)
            # TODO: return error or img_error
        with img_file.open_bin() as file:
            image = Image.open(file)
            image.load()

    if (width, height) != image.size:
        image = image.resize((width, height))
    return image


def _pil_from_composite(components: Tuple['Handle', ...], width: int, height: int) -> Image.Image:
    """Combine several images into one."""
    img = Image.new('RGB', (width, height))
    for part in components:
        img.paste(part.type.pil_func(part.arg, width, height))
    return img


def _pil_icon(arg: Image.Image, width: int, height: int) -> Image.Image:
    """Construct an image with an overlaid icon."""
    img = Image.new('RGB', (width, height), PETI_ITEM_BG)
    img.paste(
        arg,
        # Center the 64x64 icon.
        (width//2 - 32, height//2 - 32, 64, 64),
    )
    return img


TYP_COLOR = ImageType('color', _pil_from_color, _tk_from_color)
TYP_ALPHA = ImageType('alpha', _pil_empty, _tk_empty)
TYP_FILE = ImageType('file', _pil_from_file)
TYP_ICON = ImageType('icon', _pil_icon)
TYP_COMP = ImageType('composite', _pil_from_composite)


class Handle(Generic[ArgT]):
    """Represents an image that may be reloaded as required.

    The args are dependent on the type, and are used to create the image
    in a background thread.
    """
    _cached_pil: Optional[Image.Image]
    _cached_tk: Optional[tkImage]
    def __init__(
        self,
        typ: ImageType[ArgT],
        args: ArgT,
        width: int,
        height: int,
    ) -> None:
        """Internal use only."""
        self.type = typ
        self.arg = args
        self.width = width
        self.height = height

        self._cached_pil: Optional[Image.Image] = None
        self._cached_tk: Optional[tkImage] = None

    @classmethod
    def _get(cls, typ: ImageType[ArgT], arg: ArgT, width: int, height: int) -> 'Handle[ArgT]':
        try:
            return _handles[typ, arg, width, height]
        except KeyError:
            handle = _handles[typ, arg, width, height] = Handle(typ, arg, width, height)
            return handle

    def __repr__(self) -> str:
        return f'<{self.type.name.title()} image, {self.width}x{self.height}, {self.arg!r}>'

    @classmethod
    def parse(cls, prop: Union[Property, PackagePath], pack: str, width: int, height: int) -> 'Handle':
        """Parse a property into an image handle.

        If a package isn't specified, the given package will be used.
        """
        uri: PackagePath
        if isinstance(prop, Property):
            if prop.has_children():
                raise NotImplementedError('Composite images.')
            uri = PackagePath.parse(prop.value, pack)
        else:
            uri = prop
        return cls.parse_uri(uri, width, height)

    @classmethod
    def parse_uri(cls, uri: PackagePath, width: int, height: int) -> 'Handle':
        """Parse a URI into an image handle.

        parse() should be used wherever possible, since that allows composite
        images.
        """
        uri: PackagePath

        typ: ImageType
        args: object
        if uri.package == 'special':
            args = None
            name = uri.path.casefold()
            if name == 'blank':
                typ = TYP_ALPHA
            elif name == 'error':
                typ = TYP_ICON
                args = ICO_ERROR
            elif name == 'none':
                typ = TYP_ICON
                args = ICO_NONE
            elif name in ('load', 'loading'):
                typ = TYP_ICON
                args = ICO_LOAD
            elif name == 'bg':
                typ = TYP_COLOR
                args = PETI_ITEM_BG
            else:
                raise ValueError(f'Unknown special type "{uri.path}"!')
        elif uri.package in ('color', 'colour', 'rgb'):
            # color:RGB or color:RRGGBB
            try:
                if len(uri.path) == 3:
                    r = int(uri.path[0], 16)
                    g = int(uri.path[1], 16)
                    b = int(uri.path[2], 16)
                elif len(uri.path) == 6:
                    r = int(uri.path[0:2], 16)
                    g = int(uri.path[2:4], 16)
                    b = int(uri.path[4:6], 16)
                else:
                    raise ValueError
            except (ValueError, TypeError, OverflowError):
                raise ValueError('Colors must be RGB or RRGGBB hex values!') from None
            typ = TYP_COLOR
            args = (r, g, b)
        else: # File item
            typ = TYP_FILE
            args = uri
        return cls._get(typ, args, width, height)

    @classmethod
    def builtin(cls, path: str, width: int, height: int) -> 'Handle':
        """Shortcut for getting a handle to a builtin UI image."""
        return cls._get(TYP_FILE, PackagePath('bee2', path + '.png'), width, height)

    @classmethod
    def error(cls, width: int, height: int) -> 'Handle':
        """Shortcut for getting a handle to an error icon."""
        return cls._get(TYP_ICON, ICO_ERROR, width, height)

    @classmethod
    def ico_none(cls, width: int, height: int) -> 'Handle':
        """Shortcut for getting a handle to a 'none' icon."""
        return cls._get(TYP_ICON, ICO_NONE, width, height)

    @classmethod
    def blank(cls, width: int, height: int) -> 'Handle':
        """Shortcut for getting a handle to an empty image."""
        # The argument is irrelevant.
        return cls._get(TYP_ALPHA, None, width, height)

    @classmethod
    def color(cls, color: Tuple[int, int, int], width: int, height: int) -> 'Handle':
        """Shortcut for getting a handle to a solid color."""
        # The argument is irrelevant.
        return cls._get(TYP_COLOR, color, width, height)


def apply(widget: tkImgWidgets, img: Optional[Handle]) -> None:
    """Set the image in a widget.

    This tracks the widget, so later reloads will affect the widget.
    If the image is None, it is instead unset.
    TODO: Loading will happen in the background.
    """
    if img is None:
        widget['image'] = None
        try:
            del _wid_tk[widget]
        except KeyError:
            pass
        return
    if img._cached_tk is None:
        LOGGER.info('Loading {}', img)
        if img.type.tk_func is None:
            if img._cached_pil is None:
                img._cached_pil = img.type.pil_func(img.arg, img.width, img.height)
            img._cached_tk = ImageTk.PhotoImage(image=img._cached_pil)
        else:
            img._cached_tk = img.type.tk_func(img.arg, img.width, img.height)
    widget['image'] = img._cached_tk
    _wid_tk[widget] = img


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
    raise NotImplementedError


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

    logo_img = Image.open(utils.install_path('images/BEE2/splash_logo.png'))
    draw.bitmap((10, 10), logo_img)

    tk_img = ImageTk.PhotoImage(image=image)
    return tk_img, image.width, image.height


def color_square(color: Vec, size=16):
    """Create a square image of the given size, with the given color."""
    return None


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

