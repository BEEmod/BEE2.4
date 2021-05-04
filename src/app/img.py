"""The image system manages all the images packages request.

It handles loading them from disk and converting them to TK versions, and
caching images so repeated requests are cheap.
"""
from __future__ import annotations
import time
import threading
from queue import Queue, Empty as EmptyQueue
from PIL import ImageTk, Image, ImageDraw
import os
from weakref import ref as WeakRef
import tkinter as tk
from tkinter import ttk
from typing import Generic, TypeVar, Union, Callable, Optional, Mapping
from app import TK_ROOT

from srctools import Vec, Property
from srctools.filesys import FileSystem, RawFileSystem, FileSystemChain
from utils import PackagePath
import srctools.logger
import logging
import utils

# These are both valid TK image types.
tkImage = Union[ImageTk.PhotoImage, tk.PhotoImage]
# Widgets with an image attribute that can be set.
tkImgWidgets = Union[tk.Label, ttk.Label, tk.Button, ttk.Button]

ArgT = TypeVar('ArgT')

# Used to keep track of the used handles, so we can deduplicate them.
_handles: dict[tuple, Handle] = {}
# Matches widgets to the handle they use.
_wid_tk: dict[WeakRef[tkImgWidgets], Handle] = {}
# Records handles with a loaded image, but no labels using it.
# These will be cleaned up after some time passes.
_pending_cleanup: dict[int, tuple[Handle, float]] = {}

LOGGER = srctools.logger.get_logger('img')
FSYS_BUILTIN = RawFileSystem(str(utils.install_path('images')))
FSYS_BUILTIN.open_ref()
PACK_SYSTEMS: dict[str, FileSystem] = {}

# Silence DEBUG messages from Pillow, they don't help.
logging.getLogger('PIL').setLevel(logging.INFO)

# Colour of the palette item background
PETI_ITEM_BG = (229, 232, 233)
PETI_ITEM_BG_HEX = '#{:2X}{:2X}{:2X}'.format(*PETI_ITEM_BG)

_queue_load: Queue[Handle] = Queue()
_queue_ui: Queue[Handle] = Queue()


def _load_special(path: str) -> Image.Image:
    """Various special images we have to load."""
    img: Image.Image
    try:
        img = Image.open(utils.install_path(f'images/BEE2/{path}.png'))
        img.load()
        return img.convert('RGBA')
    except Exception:
        LOGGER.warning('"{}" icon could not be loaded!', path, exc_info=True)
        return Image.new('RGBA', (64, 64), PETI_ITEM_BG)

ICONS: dict[str, Image.Image] = {
    name: _load_special(name)
    for name in ['error', 'none', 'load']
}


def load_filesystems(systems: Mapping[str, FileSystem]) -> None:
    """Load in the filesystems used in packages."""
    PACK_SYSTEMS.clear()
    for pak_id, sys in systems.items():
        PACK_SYSTEMS[pak_id] = FileSystemChain(
            (sys, 'resources/BEE2/'),
            (sys, 'resources/materials/models/props_map_editor/'),
        )


def tuple_size(size: Union[tuple[int, int], int]) -> tuple[int, int]:
    """Return an xy tuple given a size or tuple."""
    if isinstance(size, tuple):
        return size
    return size, size


# Special paths which map to various images.
PATH_BLANK = PackagePath('<special>', 'blank')
PATH_ERROR = PackagePath('<special>', 'error')
PATH_LOAD = PackagePath('<special>', 'load')
PATH_NONE = PackagePath('<special>', 'none')
PATH_BG = PackagePath('color', PETI_ITEM_BG_HEX[1:])
PATH_BLACK = PackagePath('<color>', '000')
PATH_WHITE = PackagePath('<color>', 'fff')


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
        allow_raw: bool=False,
    ) -> None:
        self.name = name
        self.pil_func = pil_func
        self.tk_func = tk_func
        self.allow_raw = allow_raw

    def __repr__(self) -> str:
        return f'<ImageType "{self.name}">'


def _pil_from_color(color: tuple[int, int, int], width: int, height: int) -> Image.Image:
    """Directly produce an image of this size with the specified color."""
    return Image.new('RGB', (width or 16, height or 16), color)


def _tk_from_color(color: tuple[int, int, int], width: int, height: int) -> tkImage:
    """Directly produce an image of this size with the specified color."""
    r, g, b = color
    img = tk.PhotoImage(width=width or 16, height=height or 16)
    # Make hex RGB, then set the full image to that.
    img.put(f'{{#{r:02X}{g:02X}{b:02X}}}', to=(0, 0, width or 16, height or 16))
    return img


def _pil_empty(arg: object, width: int, height: int) -> Image.Image:
    """Produce an image of this size with transparent pixels."""
    return Image.new('RGBA', (width or 16, height or 16), (0, 0, 0, 0))


def _tk_empty(arg: object, width: int, height: int) -> tkImage:
    """Produce a TK image of this size which is entirely transparent."""
    img = tk.PhotoImage(width=width or 16, height=height or 16)
    img.blank()
    return img


def _load_file(
    fsys: FileSystem,
    uri: PackagePath,
    width: int, height: int,
    resize_algo: int,
    check_other_packages: bool=False,
) -> Image.Image:
    """Load an image from a filesystem."""
    path = uri.path.casefold()
    if path[-4:-3] != '.':
        path += ".png"

    image: Image.Image
    with fsys:
        try:
            img_file = fsys[path]
        except (KeyError, FileNotFoundError):
            img_file = None

    # Deprecated behaviour, check the other packages.
    if img_file is None and check_other_packages:
        for pak_id, other_fsys in PACK_SYSTEMS.items():
            with other_fsys:
                try:
                    img_file = other_fsys[path]
                    LOGGER.warning(
                        'Image "{}" was found in package "{}", '
                        'fix the reference.',
                        uri, pak_id,
                    )
                    break
                except (KeyError, FileNotFoundError):
                    pass

    if img_file is None:
        LOGGER.error('"{}" does not exist!', uri)
        return Handle.error(width, height).get_pil()

    with img_file.sys, img_file.open_bin() as file:
        image = Image.open(file)
        image.load()

    if width > 0 and height > 0 and (width, height) != image.size:
        image = image.resize((width, height), resample=resize_algo)
    return image


def _pil_from_package(uri: PackagePath, width: int, height: int) -> Image.Image:
    """Load from a app package."""
    try:
        fsys = PACK_SYSTEMS[uri.package]
    except KeyError:
        LOGGER.warning('Unknown package "{}" for loading images!', uri.package)
        return Handle.error(width, height).load_pil()

    return _load_file(fsys, uri, width, height, Image.BILINEAR, True)


def _pil_load_builtin(uri: PackagePath, width: int, height: int) -> Image.Image:
    """Load from the builtin UI resources."""
    return _load_file(FSYS_BUILTIN, uri, width, height, Image.BILINEAR)


def _pil_load_builtin_sprite(uri: PackagePath, width: int, height: int) -> Image.Image:
    """Load from the builtin UI resources, but use nearest-neighbour resizing."""
    return _load_file(FSYS_BUILTIN, uri, width, height, Image.NEAREST)


def _pil_from_composite(components: tuple[Handle, ...], width: int, height: int) -> Image.Image:
    """Combine several images into one."""
    img = Image.new('RGBA', (width, height))
    for part in components:
        img.paste(part.type.pil_func(part.arg, width, height))
    return img


def _pil_icon(arg: str, width: int, height: int) -> Image.Image:
    """Construct an image with an overlaid icon."""
    ico = ICONS[arg]
    if width == 0:
        width = ico.width
    if height == 0:
        height = ico.height

    img = Image.new('RGBA', (width, height), PETI_ITEM_BG)

    if width < ico.width or height < ico.height:
        # Crop to the middle part.
        img.alpha_composite(ico, source=((ico.width - width) // 2, (ico.height - height) // 2))
    else:
        # Center the 64x64 icon.
        img.alpha_composite(ico, ((width - ico.width) // 2, (height - ico.height) // 2))

    return img


TYP_COLOR = ImageType('color', _pil_from_color, _tk_from_color)
TYP_ALPHA = ImageType('alpha', _pil_empty, _tk_empty)
TYP_FILE = ImageType('file', _pil_from_package)
TYP_BUILTIN_SPR = ImageType('sprite', _pil_load_builtin_sprite, allow_raw=True)
TYP_BUILTIN = ImageType('builtin', _pil_load_builtin, allow_raw=True)
TYP_ICON = ImageType('icon', _pil_icon, allow_raw=True)
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

        self._cached_pil = None
        self._cached_tk = None
        self._force_loaded = False
        self._labels: set[WeakRef[tkImgWidgets]] = set()
        # If None, get_tk()/get_pil() was used.
        # If true, this is in the queue to load. Setting this requires
        # the loading lock.
        self._loading = False
        self.lock = threading.Lock()

    @classmethod
    def _get(cls, typ: ImageType[ArgT], arg: ArgT, width: Union[int, tuple[int, int]], height: int) -> Handle[ArgT]:
        if isinstance(width, tuple):
            width, height = width
        try:
            return _handles[typ, arg, width, height]
        except KeyError:
            handle = _handles[typ, arg, width, height] = Handle(typ, arg, width, height)
            return handle

    def __repr__(self) -> str:
        return f'<{self.type.name.title()} image, {self.width}x{self.height}, {self.arg!r}>'

    @classmethod
    def parse(
        cls,
        prop: Property,
        pack: str,
        width: int,
        height: int,
        *,
        subkey: str='',
        subfolder: str='',
    ) -> Handle:
        """Parse a property into an image handle.

        If a package isn't specified, the given package will be used.
        Optionally, 'subkey' can be used to specifiy that the property is a subkey.
        An error icon will then be produced automatically.
        If subfolder is specified, files will be relative to this folder.
        The width/height may be zero to indicate it should not be resized.
        """
        if subkey:
            try:
                prop = prop.find_key(subkey)
            except LookupError:
                return cls.error(width, height)
        if prop.has_children():
            raise NotImplementedError('Composite images.')

        return cls.parse_uri(PackagePath.parse(prop.value, pack), width, height, subfolder=subfolder)

    @classmethod
    def parse_uri(
        cls,
        uri: PackagePath,
        width: int = 0, height: int = 0,
        *,
        subfolder: str='',
    ) -> Handle:
        """Parse a URI into an image handle.

        parse() should be used wherever possible, since that allows composite
        images.
        If subfolder is specified, files will be relative to this folder.
        The width/height may be zero to indicate it should not be resized.
        """
        uri: PackagePath
        if subfolder:
            uri = uri.in_folder(subfolder)

        typ: ImageType
        args: object
        if uri.path.casefold() == '<black>':  # Old special case name.
            LOGGER.warning('Using "{}" for a black icon is deprecated, use "<color>:000" or "<rgb>:000".', uri)
            typ = TYP_COLOR
            args = (0, 0, 0)
        elif uri.package.startswith('<') and uri.package.endswith('>'):  # Special names.
            special_name = uri.package[1:-1]
            if special_name == 'special':
                args = None
                name = uri.path.casefold()
                if name == 'blank':
                    typ = TYP_ALPHA
                elif name in ('error', 'none', 'load'):
                    typ = TYP_ICON
                    args = name
                elif name == 'bg':
                    typ = TYP_COLOR
                    args = PETI_ITEM_BG
                else:
                    raise ValueError(f'Unknown special type "{uri.path}"!')
            elif special_name in ('color', 'colour', 'rgb'):
                # color:RGB or color:RRGGBB
                try:
                    if len(uri.path) == 3:
                        r = int(uri.path[0] * 2, 16)
                        g = int(uri.path[1] * 2, 16)
                        b = int(uri.path[2] * 2, 16)
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
            elif special_name in ('bee', 'bee2'):  # Builtin resources.
                typ = TYP_BUILTIN
                args = uri
            else:
                raise ValueError(f'Unknown special icon type "{uri}"!')
        else:  # File item
            typ = TYP_FILE
            args = uri
        return cls._get(typ, args, width, height)

    @classmethod
    def builtin(cls, path: str, width: int = 0, height: int = 0) -> Handle:
        """Shortcut for getting a handle to a builtin UI image."""
        return cls._get(TYP_BUILTIN, PackagePath('<bee2>', path + '.png'), width, height)

    @classmethod
    def sprite(cls, path: str, width: int = 0, height: int = 0) -> Handle:
        """Shortcut for getting a handle to a builtin UI image, but with nearest-neighbour rescaling."""
        return cls._get(TYP_BUILTIN_SPR, PackagePath('<bee2>', path + '.png'), width, height)

    @classmethod
    def error(cls, width: int, height: int) -> Handle:
        """Shortcut for getting a handle to an error icon."""
        return cls._get(TYP_ICON, 'error', width, height)

    @classmethod
    def ico_none(cls, width: int, height: int) -> Handle:
        """Shortcut for getting a handle to a 'none' icon."""
        return cls._get(TYP_ICON, 'none', width, height)

    @classmethod
    def ico_loading(cls, width: int, height: int) -> Handle:
        """Shortcut for getting a handle to a 'loading' icon."""
        return cls._get(TYP_ICON, 'load', width, height)

    @classmethod
    def blank(cls, width: int, height: int) -> Handle:
        """Shortcut for getting a handle to an empty image."""
        # The argument is irrelevant.
        return cls._get(TYP_ALPHA, None, width, height)

    @classmethod
    def color(cls, color: Union[tuple[int, int, int], Vec], width: int, height: int) -> Handle:
        """Shortcut for getting a handle to a solid color."""
        if isinstance(color, Vec):
            # Convert.
            color = tuple(map(int, color))
        return cls._get(TYP_COLOR, color, width, height)

    def get_pil(self) -> Image.Image:
        """Load the PIL image if required, then return it.

        Only available on BUILTIN type images since they cannot then be
        reloaded.
        """
        if not self.type.allow_raw:
            raise ValueError('Cannot use get_tk() on non-builtin types!')
        self._force_loaded = True
        return self._load_pil()

    def get_tk(self) -> tkImage:
        """Load the TK image if required, then return it.

        Only available on BUILTIN type images since they cannot then be
        reloaded.
        """
        if not self.type.allow_raw:
            raise ValueError('Cannot use get_tk() on non-builtin types!')
        self._force_loaded = True
        return self._load_tk()

    def _load_pil(self) -> Image.Image:
        if self._cached_pil is None:
            self._cached_pil = self.type.pil_func(self.arg, self.width, self.height)
        return self._cached_pil

    def _load_tk(self) -> tkImage:
        """Load the TK image if required, then return it.

        Should not be used if possible, to allow deferring loads to the
        background.
        """
        if self._cached_tk is None:
            # LOGGER.debug('Loading {}', self)
            if self.type.tk_func is None:
                self._cached_tk = ImageTk.PhotoImage(image=self._load_pil())
            else:
                self._cached_tk = self.type.tk_func(self.arg, self.width, self.height)
        return self._cached_tk

    def _decref(self, ref: 'WeakRef[tkImgWidgets]') -> None:
        """A label was no longer set to this handle."""
        if self._force_loaded or (self._cached_tk is None and self._cached_pil is None):
            return
        self._labels.discard(ref)
        if not self._labels:
            _pending_cleanup[id(self)] = (self, time.monotonic())

    def _incref(self, ref: 'WeakRef[tkImgWidgets]') -> None:
        """Add a label to the list of those controlled by us."""
        if self._force_loaded:
            return
        self._labels.add(ref)
        _pending_cleanup.pop(id(self), None)

    def _request_load(self) -> tkImage:
        """Request a reload of this image.

        If this can be done synchronously, the result is returned.
        Otherwise, this returns the loading icon.
        """
        if self._loading is True:
            return Handle.ico_loading(self.width, self.height).get_tk()
        with self.lock:
            if self._cached_tk is not None:
                return self._cached_tk
            if self._loading is False:
                self._loading = True
                _queue_load.put(self)
        return Handle.ico_loading(self.width, self.height).get_tk()


def _label_destroyed(ref: WeakRef[tkImgWidgets]) -> None:
    """Finaliser for _wid_tk keys.

    Removes them from the dict, and decreases the usage count on the handle.
    """
    try:
        handle = _wid_tk.pop(ref)
    except (KeyError, TypeError):
        pass
    else:
        handle._decref(ref)


# noinspection PyProtectedMember
def _background_task() -> None:
    """Background task doing the actual loading."""
    while True:
        handle = _queue_load.get()
        with handle.lock:
            if handle._loading is True:
                handle._load_pil()
                handle._loading = False
        _queue_ui.put(handle)


# noinspection PyProtectedMember
def _ui_task() -> None:
    """Background task which does TK calls.

    TK must run in the main thread, so we do UI loads here.
    """
    timeout = time.monotonic()
    # Run, but if we go over 100ms, abort so the rest of the UI loop can run.
    while time.monotonic() - timeout < 0.1:
        try:
            handle = _queue_ui.get_nowait()
        except EmptyQueue:
            break
        tk_ico = handle._load_tk()
        for label_ref in handle._labels:
            label: tkImgWidgets = label_ref()
            if label is not None:
                label['image'] = tk_ico
                label.update_idletasks()

    for handle, use_time in list(_pending_cleanup.values()):
        with handle.lock:
            if use_time < timeout - 5.0 and handle._loading is not None and not handle._labels:
                del _pending_cleanup[id(handle)]
                handle._cached_tk = handle._cached_pil = None
    TK_ROOT.tk.call(_ui_task_cmd)

# Cache the registered ID, so we don't have to re-register.
_ui_task_cmd = ('after', 100, TK_ROOT.register(_ui_task))
_bg_thread = threading.Thread(name='imghandle_load', target=_background_task)
_bg_thread.daemon = True


def start_loading() -> None:
    """Start the background loading threads."""
    _bg_thread.start()
    TK_ROOT.tk.call(_ui_task_cmd)


# noinspection PyProtectedMember
def apply(widget: tkImgWidgets, img: Optional[Handle]) -> tkImgWidgets:
    """Set the image in a widget.

    This tracks the widget, so later reloads will affect the widget.
    If the image is None, it is instead unset.
    """
    ref = WeakRef(widget, _label_destroyed)
    if img is None:
        widget['image'] = None
        try:
            old = _wid_tk.pop(ref)
        except KeyError:
            pass
        else:
            old._decref(ref)
        return widget
    try:
        old = _wid_tk[ref]
    except KeyError:
        pass
    else:
        old._decref(ref)
    img._incref(ref)
    _wid_tk[ref] = img
    cached_img = img._cached_tk
    if cached_img is not None:
        widget['image'] = cached_img
    else:  # Need to load.
        widget['image'] = img._request_load()
    return widget


def get_app_icon(path: str):
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))


def make_splash_screen(
    max_width: float,
    max_height: float,
    base_height: int,
    text1_bbox: tuple[int, int, int, int],
    text2_bbox: tuple[int, int, int, int],
) -> tuple[tk.PhotoImage, int, int]:
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
