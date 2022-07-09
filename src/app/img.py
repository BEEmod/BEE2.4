"""The image system manages all the images packages request.

It handles loading them from disk and converting them to TK versions, and
caching images so repeated requests are cheap.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Iterator, Literal, TypeVar, Union, Type, cast
from typing_extensions import TypeAlias, Final
from collections.abc import Sequence, Mapping
from weakref import ref as WeakRef
from tkinter import ttk
import tkinter as tk
import itertools
import logging

from PIL import ImageTk, Image, ImageDraw
import attrs
import trio

from srctools import Vec, Property
from srctools.vtf import VTFFlags, VTF
from srctools.filesys import FileSystem, RawFileSystem, FileSystemChain
import srctools.logger

from app import TK_ROOT
import utils

# Widgets with an image attribute that can be set.
tkImgWidgets: TypeAlias = Union[tk.Label, ttk.Label, tk.Button, ttk.Button]
tkImgWidgetsT = TypeVar(
    'tkImgWidgetsT',
    tk.Label, ttk.Label,
    Union[tk.Label, ttk.Label],
    tk.Button, ttk.Button,
    Union[tk.Button, ttk.Button],
)
# WeakRef is only generic in stubs!
WidgetWeakRef: TypeAlias = Union[
    'WeakRef[tk.Label]', 'WeakRef[ttk.Label]',
    'WeakRef[tk.Label | ttk.Label]',
    'WeakRef[tk.Button]', 'WeakRef[ttk.Button]',
    'WeakRef[tk.Button | ttk.Button]',
]

HandleT = TypeVar('HandleT', bound='Handle')

# Used to keep track of the used handles, so we can deduplicate them.
_handles: dict[tuple[Type[Handle], tuple, int, int], Handle] = {}
# Matches widgets to the handle they use.
_wid_tk: dict[WidgetWeakRef, Handle] = {}

# TK images have unique IDs, so preserve discarded image objects.
_unused_tk_img: dict[tuple[int, int], list[tk.PhotoImage]] = {}

LOGGER = srctools.logger.get_logger('img')
FSYS_BUILTIN = RawFileSystem(str(utils.install_path('images')))
PACK_SYSTEMS: dict[str, FileSystem] = {}

# Silence DEBUG messages from Pillow, they don't help.
logging.getLogger('PIL').setLevel(logging.INFO)

# Colour of the palette item background
PETI_ITEM_BG: Final = (229, 232, 233)
PETI_ITEM_BG_HEX: Final = '#{:2X}{:2X}{:2X}'.format(*PETI_ITEM_BG)

FLIP_LEFT_RIGHT: Final = Image.FLIP_LEFT_RIGHT
FLIP_TOP_BOTTOM: Final = Image.FLIP_TOP_BOTTOM
FLIP_ROTATE: Final = Image.ROTATE_180


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
# The icon has 8 parts, with the gap in the 1 pos. So mirror/rotate to
# derive the others.

ICONS['load_0'] = _load_icon = ICONS['load']
ICONS['load_7'] = _load_icon_flip = _load_icon.transpose(Image.FLIP_LEFT_RIGHT)
ICONS['load_1'] = _load_icon_flip.transpose(Image.ROTATE_270)
ICONS['load_2'] = _load_icon.transpose(Image.ROTATE_270)
ICONS['load_3'] = _load_icon.transpose(Image.FLIP_TOP_BOTTOM)
ICONS['load_4'] = _load_icon.transpose(Image.ROTATE_180)
ICONS['load_5'] = _load_icon_flip.transpose(Image.ROTATE_90)
ICONS['load_6'] = _load_icon.transpose(Image.ROTATE_90)

del _load_icon, _load_icon_flip
# Loader handles, which we want to cycle animate.
_load_handles: dict[tuple[int, int], ImgIcon] = {}

# Once initialised, schedule here.
_load_nursery: trio.Nursery | None = None
# Load calls occurring before init. This is done so apply() can be called during import etc,
# and it'll be deferred till later.
_early_loads: set[Handle] = set()


def tuple_size(size: tuple[int, int] | int) -> tuple[int, int]:
    """Return a xy tuple given a size or tuple."""
    if isinstance(size, tuple):
        return size
    return size, size


def _get_tk_img(width: int, height: int) -> ImageTk.PhotoImage:
    """Recycle an old image, or construct a new one."""
    if not width:
        width = 16
    if not height:
        height = 16

    # Use setdefault and pop so each step is atomic.
    img_list = _unused_tk_img.setdefault((width, height), [])
    try:
        img = img_list.pop()
    except IndexError:
        img = ImageTk.PhotoImage('RGBA', (width, height))
    return img


def _discard_tk_img(img: ImageTk.PhotoImage | None) -> None:
    """Store an unused image so it can be reused."""
    if img is not None:
        # Use setdefault and append so each step is atomic.
        img_list = _unused_tk_img.setdefault((img.width(), img.height()), [])
        img_list.append(img)


# Special paths which map to various images.
PATH_BLANK = utils.PackagePath('<special>', 'blank')
PATH_ERROR = utils.PackagePath('<special>', 'error')
PATH_LOAD = utils.PackagePath('<special>', 'load')
PATH_NONE = utils.PackagePath('<special>', 'none')
PATH_BG = utils.PackagePath('color', PETI_ITEM_BG_HEX[1:])
PATH_BLACK = utils.PackagePath('<color>', '000')
PATH_WHITE = utils.PackagePath('<color>', 'fff')


def _load_file(
    fsys: FileSystem,
    uri: utils.PackagePath,
    width: int, height: int,
    resize_algo: Literal[0, 1, 2, 3, 4, 5],
    check_other_packages: bool=False,
) -> Image.Image:
    """Load an image from a filesystem."""
    path = uri.path.casefold()
    if path[-4:-3] != '.':
        path += ".png"

    image: Image.Image
    try:
        img_file = fsys[path]
    except (KeyError, FileNotFoundError):
        img_file = None

    # Deprecated behaviour, check the other packages.
    if img_file is None and check_other_packages:
        for pak_id, other_fsys in PACK_SYSTEMS.items():
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

    try:
        with img_file.open_bin() as file:
            if path.casefold().endswith('.vtf'):
                vtf = VTF.read(file)
                mipmap = 0
                # If resizing, pick the mipmap equal to or slightly larger than
                # the desired size. With powers of two, most cases we don't
                # need to resize at all.
                if width > 0 and height > 0 and VTFFlags.NO_MIP not in vtf.flags:
                    for mipmap in range(vtf.mipmap_count):
                        mip_width = max(vtf.width >> mipmap, 1)
                        mip_height = max(vtf.height >> mipmap, 1)
                        if mip_width < width or mip_height < height:
                            mipmap = max(0, mipmap - 1)
                            break
                image = vtf.get(mipmap=mipmap).to_PIL()
            else:
                image = Image.open(file)
                image.load()
                if image.mode != 'RGBA':
                    image = image.convert('RGBA')
    except Exception:
        LOGGER.warning(
            'Could not parse image file {}:',
            uri,
            exc_info=True,
        )
        return Handle.error(width, height).get_pil()

    if width > 0 and height > 0 and (width, height) != image.size:
        image = image.resize((width, height), resample=resize_algo)
    return image


@attrs.define(eq=False)
class Handle:
    """Represents an image that may be reloaded as required.

    The args are dependent on the type, and are used to create the image
    in a background thread.
    """
    width: int
    height: int

    _cached_pil: Image.Image | None = attrs.field(init=False, default=None, repr=False)
    _cached_tk: ImageTk.PhotoImage | None = attrs.field(init=False, default=None, repr=False)

    _users: set[WidgetWeakRef | Handle] = attrs.field(init=False, factory=set, repr=False)
    # If set, get_tk()/get_pil() was used.
    _force_loaded: bool = attrs.field(init=False, default=False)
    # If true, this is in the queue to load.
    _loading: bool = attrs.field(init=False, default=False)
    # When no users are present, schedule cleaning up the handle's data to reuse.
    _cancel_cleanup: trio.CancelScope = attrs.field(init=False, factory=trio.CancelScope, repr=False)

    # Determines whether `get_pil()` and `get_tk()` can be called directly.
    allow_raw: ClassVar[bool] = False
    # Whether the result can be transparent.
    alpha_result: ClassVar[bool] = False

    # Subclass methods
    def _children(self) -> Iterator[Handle]:
        """Yield all the handles this depends on."""
        return iter(())

    def _make_image(self) -> Image.Image:
        """Construct the image data, must be implemented by subclass."""
        raise NotImplementedError

    @classmethod
    def _to_key(cls, args: tuple) -> tuple:
        """Override in subclasses to convert mutable attributes to deduplicate."""
        return args

    def resize(self: HandleT, width: int, height: int) -> HandleT:
        """Return a copy with a different size."""
        raise NotImplementedError

    @classmethod
    def _deduplicate(cls: Type[HandleT], width: int | tuple[int, int], height: int, *args: Any) -> HandleT:
        if isinstance(width, tuple):
            width, height = width
        key = cls._to_key(args)
        try:
            return cast(HandleT, _handles[cls, key, width, height])
        except KeyError:
            handle = _handles[cls, key, width, height] = cls(width, height, *args)
            return handle

    @classmethod
    def parse(
        cls: Type[Handle],
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
            children = []
            for child in prop:
                if child.name not in ('image', 'img', 'layer'):
                    raise ValueError(f'Unknown compound type "{child}"!')
                children.append(cls.parse(
                    child, pack,
                    width, height,
                    subfolder=subfolder
                ))
            return cls.composite(children, width, height)

        return cls.parse_uri(utils.PackagePath.parse(prop.value, pack), width, height, subfolder=subfolder)

    @classmethod
    def parse_uri(
        cls,
        uri: utils.PackagePath,
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
        if subfolder:
            uri = uri.in_folder(subfolder)

        typ: Type[Handle]
        args: list
        if uri.path.casefold() == '<black>':  # Old special case name.
            LOGGER.warning('Using "{}" for a black icon is deprecated, use "<color>:000" or "<rgb>:000".', uri)
            typ = ImgColor
            args = [0, 0, 0]
        elif uri.package.startswith('<') and uri.package.endswith('>'):  # Special names.
            special_name = uri.package[1:-1]
            if special_name == 'special':
                args = []
                name = uri.path.casefold()
                if name == 'blank':
                    typ = ImgAlpha
                elif name in ('error', 'none', 'load'):
                    typ = ImgIcon
                    args = [name]
                elif name == 'bg':
                    typ = ImgColor
                    args = [PETI_ITEM_BG]
                else:
                    raise ValueError(f'Unknown special type "{uri.path}"!')
            elif special_name in ('color', 'colour', 'rgb'):
                # <color>:#RGB, <color>:#RRGGBB, <color>:R,G,B
                color = uri.path
                if color.startswith('#'):
                    color = color[1:]
                try:
                    if ',' in color:
                        r, g, b = map(int, color.split(','))
                    elif len(color) == 3:
                        r = int(color[0] * 2, 16)
                        g = int(color[1] * 2, 16)
                        b = int(color[2] * 2, 16)
                    elif len(color) == 6:
                        r = int(color[0:2], 16)
                        g = int(color[2:4], 16)
                        b = int(color[4:6], 16)
                    else:
                        raise ValueError
                except (ValueError, TypeError, OverflowError):
                    # Try to grab from TK's colour list.
                    try:
                        r, g, b = TK_ROOT.winfo_rgb(color)
                        # They're full 16-bit colors, we don't want that.
                        r >>= 8
                        g >>= 8
                        b >>= 8
                    except tk.TclError:
                        raise ValueError(f'Colors must be RGB, RRGGBB hex values, or R,G,B decimal!, not {uri}') from None
                typ = ImgColor
                args = [r, g, b]
            elif special_name in ('bee', 'bee2'):  # Builtin resources.
                typ = ImgBuiltin
                args = [uri]
            else:
                raise ValueError(f'Unknown special icon type "{uri}"!')
        else:  # File item
            typ = ImgFile
            args = [uri]
        return typ._deduplicate(width, height, *args)

    @classmethod
    def builtin(cls, path: str, width: int = 0, height: int = 0) -> ImgBuiltin:
        """Shortcut for getting a handle to a builtin UI image."""
        return ImgBuiltin._deduplicate(width, height, utils.PackagePath('<bee2>', path + '.png'))

    @classmethod
    def sprite(cls, path: str, width: int = 0, height: int = 0) -> ImgSprite:
        """Shortcut for getting a handle to a builtin UI image, but with nearest-neighbour rescaling."""
        return ImgSprite._deduplicate(width, height, utils.PackagePath('<bee2>', path + '.png'))

    @classmethod
    def composite(cls, children: Sequence[Handle], width: int = 0, height: int = 0) -> Handle:
        """Return a handle composed of several images layered on top of each other."""
        if not children:
            return cls.error(width, height)
        if not width:
            width = children[0].width
        if not height:
            height = children[0].height

        return ImgComposite._deduplicate(width, height, children)

    def crop(
        self,
        bounds: tuple[int, int, int, int] | None = None,
        transpose: int | None = None,
        width: int = 0, height: int = 0,
    ) -> ImgCrop:
        """Wrap a handle to crop it into a smaller size."""
        return ImgCrop._deduplicate(width, height, self, bounds, transpose)

    @classmethod
    def file(cls, path: utils.PackagePath, width: int, height: int) -> ImgFile:
        """Shortcut for getting a handle to file path."""
        return ImgFile._deduplicate(width, height, path)

    @classmethod
    def error(cls, width: int, height: int) -> ImgIcon:
        """Shortcut for getting a handle to an error icon."""
        return ImgIcon._deduplicate(width, height,  'error')

    @classmethod
    def ico_none(cls, width: int, height: int) -> ImgIcon:
        """Shortcut for getting a handle to a 'none' icon."""
        return ImgIcon._deduplicate(width, height, 'none')

    @classmethod
    def ico_loading(cls, width: int, height: int) -> ImgIcon:
        """Shortcut for getting a handle to a 'loading' icon."""
        try:
            return _load_handles[width, height]
        except KeyError:
            res = _load_handles[width, height] = ImgIcon._deduplicate(width, height, 'load')
            return res

    @classmethod
    def blank(cls, width: int, height: int) -> ImgAlpha:
        """Shortcut for getting a handle to an empty image."""
        return ImgAlpha._deduplicate(width, height)

    @classmethod
    def color(cls, color: tuple[int, int, int] | Vec, width: int, height: int) -> ImgColor:
        """Shortcut for getting a handle to a solid color."""
        if isinstance(color, Vec):
            # Convert.
            return ImgColor._deduplicate(width, height, int(color.x), int(color.y), int(color.z))
        else:
            return ImgColor._deduplicate(width, height, *color)

    def get_pil(self) -> Image.Image:
        """Load the PIL image if required, then return it."""
        if self.allow_raw:
            # Force load, so it's always ready.
            self._force_loaded = True
        elif not self._users and _load_nursery is not None:
            # Loading something unused, schedule it to be cleaned soon.
            self._cancel_cleanup.cancel()
            self._cancel_cleanup = trio.CancelScope()
            _load_nursery.start_soon(self._cleanup_task, self._cancel_cleanup)
        return self._load_pil()

    def get_tk(self) -> ImageTk.PhotoImage:
        """Load the TK image if required, then return it.

        Only available on BUILTIN type images since they cannot then be
        reloaded.
        """
        if not self.allow_raw:
            raise ValueError(f'Cannot use get_tk() on non-builtin type {self!r}!')
        self._force_loaded = True
        return self._load_tk()

    def _load_pil(self) -> Image.Image:
        """Load the PIL image if required, then return it."""
        if self._cached_pil is None:
            self._cached_pil = self._make_image()
        return self._cached_pil

    def _load_tk(self) -> ImageTk.PhotoImage:
        """Load the TK image if required, then return it."""
        if self._cached_tk is None:
            # LOGGER.debug('Loading {}', self)
            res = self._load_pil()
            # Except for builtin types (icons), strip alpha.
            if not self.alpha_result:
                res = res.convert('RGB')
            self._cached_tk = _get_tk_img(res.width, res.height)
            self._cached_tk.paste(res)
        return self._cached_tk

    def _decref(self, ref: 'WidgetWeakRef | Handle') -> None:
        """A label was no longer set to this handle."""
        if self._force_loaded:
            return
        self._users.discard(ref)
        for child in self._children():
            child._decref(self)
        if _load_nursery is None:
            return  # Not loaded, can't unload.
        if not self._users and (self._cached_tk is not None or self._cached_pil is not None):
            # Schedule this handle to be cleaned up, and store a cancel scope so that
            # can be aborted.
            self._cancel_cleanup = trio.CancelScope()
            _load_nursery.start_soon(self._cleanup_task, self._cancel_cleanup)

    def _incref(self, ref: 'WidgetWeakRef | Handle') -> None:
        """Add a label to the list of those controlled by us."""
        if self._force_loaded:
            return
        self._users.add(ref)
        # Abort cleaning up if we were planning to.
        self._cancel_cleanup.cancel()
        for child in self._children():
            child._incref(self)

    def _request_load(self) -> ImageTk.PhotoImage:
        """Request a reload of this image.

        If this can be done synchronously, the result is returned.
        Otherwise, this returns the loading icon.
        """
        if self._loading is True:
            return Handle.ico_loading(self.width, self.height).get_tk()
        if self._cached_tk is not None:
            return self._cached_tk
        if self._loading is False:
            self._loading = True
            if _load_nursery is None:
                _early_loads.add(self)
            else:
                _load_nursery.start_soon(self._load_task)
        return Handle.ico_loading(self.width, self.height).get_tk()

    async def _load_task(self) -> None:
        """Scheduled to load images then apply to the labels."""
        await trio.to_thread.run_sync(self._load_pil)
        self._loading = False
        tk_ico = self._load_tk()
        for label_ref in self._users:
            if isinstance(label_ref, WeakRef):
                label: tkImgWidgets | None = label_ref()
                if label is not None:
                    try:
                        label['image'] = tk_ico
                    except tk.TclError:
                        # Can occur if the image has been removed/destroyed, but
                        # the Python object still exists. Ignore, should be
                        # cleaned up shortly.
                        pass

    async def _cleanup_task(self, scope: trio.CancelScope) -> None:
        """Wait for the time to elapse, then clear the contents."""
        with scope:
            await trio.sleep(5)
        # We weren't cancelled and are empty, cleanup.
        if not scope.cancel_called and self._loading is not None and not self._users:
            _discard_tk_img(self._cached_tk)
            self._cached_tk = self._cached_pil = None


@attrs.define(eq=False)
class ImgColor(Handle):
    """An image containing a solid color."""
    red: int
    green: int
    blue: int

    def _make_image(self) -> Image.Image:
        """Directly produce an image of this size with the specified color."""
        return Image.new(
            'RGBA',
            (self.width or 16, self.height or 16),
            (self.red, self.green, self.blue, 255),
        )


class ImgAlpha(Handle):
    """An image which is entirely transparent."""
    alpha_result: ClassVar[bool] = True

    def _make_image(self) -> Image.Image:
        """Produce an image of this size with transparent pixels."""
        return Image.new('RGBA', (self.width or 16, self.height or 16), (0, 0, 0, 0))

    def resize(self, width: int, height: int) -> ImgAlpha:
        """Return a copy with a different size."""
        return self._deduplicate(width, height)


@attrs.define(eq=False)
class ImgFile(Handle):
    """An image loaded from a package."""
    uri: utils.PackagePath

    def _make_image(self) -> Image.Image:
        """Load from a app package."""
        try:
            fsys = PACK_SYSTEMS[self.uri.package]
        except KeyError:
            LOGGER.warning('Unknown package for loading images: "{}"!', self.uri)
            return Handle.error(self.width, self.height).get_pil()

        return _load_file(fsys, self.uri, self.width, self.height, Image.ANTIALIAS, True)

    def resize(self, width: int, height: int) -> ImgFile:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)


@attrs.define(eq=False)
class ImgBuiltin(Handle):
    """An image loaded from builtin UI resources."""
    uri: utils.PackagePath
    allow_raw: ClassVar[bool] = True
    alpha_result: ClassVar[bool] = True

    def _make_image(self) -> Image.Image:
        """Load from the builtin UI resources."""
        return _load_file(FSYS_BUILTIN, self.uri, self.width, self.height, Image.ANTIALIAS)

    def resize(self, width: int, height: int) -> ImgBuiltin:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)


@attrs.define(eq=False)
class ImgSprite(Handle):
    """An image loaded from builtin UI resources, with nearest-neighbour resizing."""
    uri: utils.PackagePath
    allow_raw: ClassVar[bool] = True
    alpha_result: ClassVar[bool] = True

    def _make_image(self) -> Image.Image:
        """Load from the builtin UI resources, but use nearest-neighbour resizing."""
        return _load_file(FSYS_BUILTIN, self.uri, self.width, self.height, Image.NEAREST)

    def resize(self, width: int, height: int) -> ImgSprite:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)


@attrs.define(eq=False)
class ImgComposite(Handle):
    """An image composed of multiple layers composited together."""
    alpha_result: ClassVar[bool] = True
    layers: Sequence[Handle]

    @classmethod
    def _to_key(cls, children: tuple[Handle, ...]) -> tuple:
        """Handles aren't hashable, so we need to use identity."""
        return tuple(map(id, children))

    def _make_image(self) -> Image.Image:
        """Combine several images into one."""
        width = self.width or self.layers[0].width
        height = self.height or self.layers[0].height
        img = Image.new('RGBA', (width, height))
        for part in self.layers:
            if part.width != img.width or part.height != img.height:
                raise ValueError(f'Mismatch in image sizes: {width}x{height} != {self.layers}')
            # noinspection PyProtectedMember
            child = part._load_pil()
            if child.mode != 'RGBA':
                LOGGER.warning('Image {} did not use RGBA mode!', child)
                child = child.convert('RGBA')
            img.alpha_composite(child)
        return img

    def resize(self, width: int, height: int) -> ImgComposite:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, [
            img.resize(width, height)
            for img in self.layers
        ])


@attrs.define(eq=False)
class ImgCrop(Handle):
    """An image that crops another down to only show part."""
    alpha_result: ClassVar[bool] = True
    source: Handle
    bounds: tuple[int, int, int, int] | None  # left, top, right, bottom coords.
    # Image.FLIP_TOP_BOTTOM | Image.FLIP_LEFT_RIGHT | Image.ROTATE_180 | None
    transpose: Literal[0, 1, 3] | None

    def _children(self) -> Iterator[Handle]:
        yield self.source

    @classmethod
    def _to_key(cls, args: tuple) -> tuple:
        """Handles aren't hashable, so we need to use identity."""
        [child, bounds, transpose] = args
        return (id(child), bounds, transpose)

    def _make_image(self) -> Image.Image:
        """Crop this image down to part of the source."""
        src_w = self.source.width
        src_h = self.source.height

        image = self.source._load_pil()
        # Shrink down the source to the final source so the bounds apply.
        # TODO: Rescale bounds to actual source size to improve result?
        if src_w > 0 and src_h > 0 and (src_w, src_h) != image.size:
            image = image.resize((src_w, src_h), resample=Image.ANTIALIAS)

        if self.bounds is not None:
            image = image.crop(self.bounds)

        if self.transpose is not None:
            image = image.transpose(self.transpose)

        if self.width > 0 and self.height > 0 and (self.width, self.height) != image.size:
            image = image.resize((self.width, self.height), resample=Image.ANTIALIAS)
        return image

    def resize(self, width: int, height: int) -> ImgCrop:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.source, self.bounds, self.transpose)


@attrs.define(eq=False)
class ImgIcon(Handle):
    """An image containing the PeTI background with a centered icon."""
    icon_name: str
    allow_raw: ClassVar[bool] = True

    def _make_image(self) -> Image.Image:
        """Construct an image with an overlaid icon."""
        ico = ICONS[self.icon_name]
        width = self.width or ico.width
        height = self.height or ico.height

        img = Image.new('RGBA', (width, height), PETI_ITEM_BG)

        if width >= ico.width and height >= ico.height:
            # Center the 64x64 icon.
            img.alpha_composite(ico, ((width - ico.width) // 2, (height - ico.height) // 2))
        # Else, no room, don't bother.

        return img

    def resize(self, width: int, height: int) -> ImgIcon:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.icon_name)


def _label_destroyed(ref: WeakRef[tkImgWidgetsT]) -> None:
    """Finaliser for _wid_tk keys.

    Removes them from the dict, and decreases the usage count on the handle.
    """
    try:
        handle = _wid_tk.pop(ref)
    except (KeyError, TypeError, NameError):
        # Interpreter could be shutting down and deleted globals, or we were
        # called twice, etc. Just ignore.
        pass
    else:
        # noinspection PyProtectedMember
        handle._decref(ref)


# noinspection PyProtectedMember
async def _spin_load_icons() -> None:
    """Cycle loading icons."""
    fnames = [
        f'load_{i}'
        for i in range(8)
    ]
    for load_name in itertools.cycle(fnames):
        await trio.sleep(0.125)
        for handle in _load_handles.values():
            handle.icon_name = load_name
            handle._cached_pil = None
            if handle._cached_tk is not None:
                # This updates the TK widget directly.
                handle._cached_tk.paste(handle._load_pil())


# noinspection PyProtectedMember
async def init(filesystems: Mapping[str, FileSystem]) -> None:
    """Load in the filesystems used in package and start the background loading."""
    global _load_nursery

    PACK_SYSTEMS.clear()
    for pak_id, sys in filesystems.items():
        PACK_SYSTEMS[pak_id] = FileSystemChain(
            (sys, 'resources/BEE2/'),
            (sys, 'resources/materials/'),
            (sys, 'resources/materials/models/props_map_editor/'),
        )

    async with trio.open_nursery() as _load_nursery:
        LOGGER.debug('Early loads: {}', _early_loads)
        while _early_loads:
            handle = _early_loads.pop()
            if handle._users:
                _load_nursery.start_soon(Handle._load_task, handle)
        _load_nursery.start_soon(_spin_load_icons)
        await trio.sleep_forever()


# noinspection PyProtectedMember
def refresh_all() -> None:
    """Force all images to reload."""
    LOGGER.info('Forcing all images to reload!')
    done = 0
    for handle in list(_handles.values()):
        # If force-loaded it's builtin UI etc we shouldn't reload.
        # If already loading, no point.
        if handle._force_loaded:
            LOGGER.warning('Could not reload force-loaded {!r}', handle)
            continue
        if not handle._loading:
            _discard_tk_img(handle._cached_tk)
            handle._cached_tk = handle._cached_pil = None
            loading = handle._request_load()
            done += 1
            for label_ref in handle._users:
                if isinstance(label_ref, WeakRef):
                    label: tkImgWidgets | None = label_ref()
                    if label is not None:
                        label['image'] = loading
    LOGGER.info('Queued {} images to reload.', done)


# noinspection PyProtectedMember
def apply(widget: tkImgWidgetsT, img: Handle | None) -> tkImgWidgetsT:
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
        if old is img:
            # Unchanged.
            return widget
        old._decref(ref)
    img._incref(ref)
    _wid_tk[ref] = img
    cached_img = img._cached_tk
    if cached_img is not None:
        widget['image'] = cached_img
    else:  # Need to load.
        widget['image'] = img._request_load()
    return widget


def get_app_icon(path: str) -> ImageTk.PhotoImage:
    """On non-Windows, retrieve the application icon."""
    with open(path, 'rb') as f:
        return ImageTk.PhotoImage(Image.open(f))


def make_splash_screen(
    max_width: float,
    max_height: float,
    base_height: int,
    text1_bbox: tuple[int, int, int, int],
    text2_bbox: tuple[int, int, int, int],
) -> tuple[ImageTk.PhotoImage, int, int]:
    """Create the splash screen image.

    This uses a random screenshot from the splash_screens directory.
    It then adds the gradients on top.
    """
    import random
    folder = utils.install_path('images/splash_screen')
    user_folder = folder / 'user'
    path = Path('<nothing>')
    if user_folder.exists():
        folder = user_folder
    try:
        path = random.choice(list(folder.iterdir()))
        with path.open('rb') as img_file:
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
