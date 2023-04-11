"""The image system manages all the images packages request.


Handles are automatically deduplicated, and intiaially only contain the 
filename/options, so are cheap to create. Once applied to a UI widget, 
they are loaded in the background, then unloaded if removed from all widgets.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterator, Tuple, TypeVar, Union, Type
from typing_extensions import Self, TypeAlias, Final
from collections.abc import Sequence, Mapping
from weakref import ref as WeakRef
from tkinter import ttk
import tkinter as tk
import abc
import itertools
import logging
import functools

from PIL import ImageFont, ImageTk, Image, ImageDraw
import attrs
import trio

from srctools import Vec, Keyvalues
from srctools.vtf import VTFFlags, VTF
from srctools.filesys import FileSystem, RawFileSystem, FileSystemChain
import srctools.logger

from app import TK_ROOT
from consts import Theme
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
tkImg: TypeAlias = Union[ImageTk.PhotoImage, tk.PhotoImage]
# WeakRef is only generic in stubs!
WidgetWeakRef: TypeAlias = Union[
    'WeakRef[tk.Label]', 'WeakRef[ttk.Label]',
    'WeakRef[tk.Label | ttk.Label]',
    'WeakRef[tk.Button]', 'WeakRef[ttk.Button]',
    'WeakRef[tk.Button | ttk.Button]',
]

# Used to keep track of the used handles, so we can deduplicate them.
_handles: dict[tuple[Type[Handle], tuple, int, int], Handle] = {}
# Matches widgets to the handle they use.
_wid_tk: dict[WidgetWeakRef, Handle] = {}

LOGGER = srctools.logger.get_logger('img')
FSYS_BUILTIN = RawFileSystem(str(utils.install_path('images')))
PACK_SYSTEMS: dict[str, FileSystem] = {}

# Silence DEBUG messages from Pillow, they don't help.
logging.getLogger('PIL').setLevel(logging.INFO)

# The currently selected theme for images.
_current_theme: Theme = Theme.LIGHT

# The UIs we have active. Should only be one.
_UIS: list[UIImage] = []

# Colour of the palette item background
PETI_ITEM_BG: Final = (229, 233, 233)
PETI_ITEM_BG_HEX: Final = '#{:2X}{:2X}{:2X}'.format(*PETI_ITEM_BG)
BACKGROUNDS: Mapping[Theme, Tuple[int, int, int]] = {
    Theme.LIGHT: (229, 233, 233),  # Same as palette items ingame.
    Theme.DARK: (26, 22, 22),
}
FOREGROUNDS: Mapping[Theme, Tuple[int, int, int, int]] = {
    Theme.LIGHT: (0, 0, 0, 255),
    Theme.DARK: (255, 255, 255, 255),
}

# Re-exported from PIL.
FLIP_LEFT_RIGHT: Final = Image.Transpose.FLIP_LEFT_RIGHT
FLIP_TOP_BOTTOM: Final = Image.Transpose.FLIP_TOP_BOTTOM
FLIP_ROTATE: Final = Image.Transpose.ROTATE_180


def _load_special(path: str, theme: Theme) -> Image.Image:
    """Various special images we have to load."""
    img: Image.Image
    try:
        img = Image.open(utils.install_path(f'images/BEE2/{path}.{theme.value}.png'))
        img.load()
        return img.convert('RGBA')
    except Exception:
        LOGGER.warning('"{}" icon could not be loaded!', path, exc_info=True)
        return Image.new('RGBA', (64, 64), (0, 0, 0, 0))

ICONS: Dict[Tuple[str, Theme], Image.Image] = {
    (name, theme): _load_special(name, theme)
    for name in ['error', 'none', 'load']
    for theme in Theme
}
# The icon has 8 parts, with the gap in the 1 pos. So mirror/rotate to
# derive the others.
for _theme in Theme:
    ICONS['load_0', _theme] = _load_icon = ICONS['load', _theme]
    ICONS['load_7', _theme] = _load_icon_flip = _load_icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    ICONS['load_1', _theme] = _load_icon_flip.transpose(Image.Transpose.ROTATE_270)
    ICONS['load_2', _theme] = _load_icon.transpose(Image.Transpose.ROTATE_270)
    ICONS['load_3', _theme] = _load_icon.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    ICONS['load_4', _theme] = _load_icon.transpose(Image.Transpose.ROTATE_180)
    ICONS['load_5', _theme] = _load_icon_flip.transpose(Image.Transpose.ROTATE_90)
    ICONS['load_6', _theme] = _load_icon.transpose(Image.Transpose.ROTATE_90)
# Frame indices in order.
LOAD_FRAME_IND = range(8)

del _load_icon, _load_icon_flip, _theme
# Loader handles, which we want to cycle animate.
# The first icon is the one users use, the others are each frame (manually loaded).
_load_handles: dict[tuple[int, int], tuple[ImgIcon, list[ImgIcon]]] = {}

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


# Special paths which map to various images.
PATH_BLANK = utils.PackagePath('<special>', 'blank')
PATH_ERROR = utils.PackagePath('<special>', 'error')
PATH_LOAD = utils.PackagePath('<special>', 'load')
PATH_NONE = utils.PackagePath('<special>', 'none')
PATH_BG = utils.PackagePath('<special>', 'bg')
PATH_BLACK = utils.PackagePath('<color>', '000')
PATH_WHITE = utils.PackagePath('<color>', 'fff')


def _load_file(
    fsys: FileSystem,
    uri: utils.PackagePath,
    width: int, height: int,
    resize_algo: Image.Resampling,
    check_other_packages: bool=False,
) -> Tuple[Image.Image, bool]:
    """Load an image from a filesystem."""
    path = uri.path.casefold()
    if path[-4:-3] == '.':
        path, ext = path[:-4], path[-3:]
    else:
        ext = "png"

    image: Image.Image
    try:
        img_file = fsys[f'{path}.{_current_theme.value}.{ext}']
        uses_theme = True
    except (KeyError, FileNotFoundError):
        try:
            img_file = fsys[f'{path}.{ext}']
        except (KeyError, FileNotFoundError):
            img_file = None
        uses_theme = False

    # Deprecated behaviour, check the other packages.
    if img_file is None and check_other_packages:
        for pak_id, other_fsys in PACK_SYSTEMS.items():
            try:
                img_file = other_fsys[f'{path}.{ext}']
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
        return Handle.error(width, height).get_pil(), False

    try:
        with img_file.open_bin() as file:
            if ext.casefold() == 'vtf':
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
        return Handle.error(width, height).get_pil(), False

    if width > 0 and height > 0 and (width, height) != image.size:
        image = image.resize((width, height), resample=resize_algo)
    return image, uses_theme


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
    # This is set if a PeTI background was automatically composited behind a transparent image.
    _bg_composited: bool = attrs.field(init=False, default=False)

    # Determines whether `get_pil()` and `get_tk()` can be called directly.
    allow_raw: ClassVar[bool] = False
    # If set, assigning this handle to a widget preserves the alpha. This is only set on UI icons
    # and the like, not packages.
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

    def resize(self, width: int, height: int) -> Self:
        """Return a copy with a different size."""
        raise NotImplementedError

    def _is_themed(self) -> bool:
        """Return if this image may need to reload when the theme changes.

        This only needs to be set after the image is loaded at least once.
        """
        raise NotImplementedError

    def is_themed(self) -> bool:
        """Return if this image may need to reload when the theme changes.

        This only needs to be set after the image is loaded at least once.
        """
        return self._bg_composited or self._is_themed()

    @classmethod
    def _deduplicate(cls, width: int | tuple[int, int], height: int, *args: Any) -> Self:
        if isinstance(width, tuple):
            width, height = width
        key = cls._to_key(args)
        try:
            any_handle = _handles[cls, key, width, height]
            assert isinstance(any_handle, cls)
            return any_handle
        except KeyError:
            handle = _handles[cls, key, width, height] = cls(width, height, *args)
            return handle

    @classmethod
    def parse(
        cls: Type[Handle],
        kv: Keyvalues,
        pack: str,
        width: int,
        height: int,
        *,
        subkey: str='',
        subfolder: str='',
    ) -> Handle:
        """Parse a keyvalue into an image handle.

        If a package isn't specified, the given package will be used.
        Optionally, 'subkey' can be used to use the child key of the passed block.
        An error icon will then be produced automatically.
        If subfolder is specified, files will be relative to this folder.
        The width/height may be zero to indicate it should not be resized.
        """
        if subkey:
            try:
                kv = kv.find_key(subkey)
            except LookupError:
                return cls.error(width, height)
        if kv.has_children():
            children: list[Handle] = []
            for child in kv:
                if child.name in ('noalpha', 'stripalpha'):
                    children.append(cls.parse(
                        child, pack,
                        width, height,
                        subfolder=subfolder,
                    ).with_alpha_stripped())
                elif child.name in ('image', 'img', 'layer'):
                    children.append(cls.parse(
                        child, pack,
                        width, height,
                        subfolder=subfolder,
                    ))
                else:
                    raise ValueError(f'Unknown compound type "{child.real_name}"!')
            return cls.composite(children, width, height)

        return cls.parse_uri(utils.PackagePath.parse(kv.value, pack), width, height, subfolder=subfolder)

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
                    typ = ImgBackground
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
        transpose: Image.Transpose | None = None,
        width: int = 0, height: int = 0,
    ) -> ImgCrop:
        """Wrap a handle to crop it into a smaller size."""
        return ImgCrop._deduplicate(width, height, self, bounds, transpose)

    def with_alpha_stripped(self) -> ImgStripAlpha:
        """Wrap a handle to strip alpha."""
        return ImgStripAlpha._deduplicate(self.width, self.height, self)

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
            return _load_handles[width, height][0]
        except KeyError:
            main_ico = ImgIcon._deduplicate(width, height, 'load')
            # Build an additional load icon for each frame, so that can be cached.
            _load_handles[width, height] = main_ico, [
                ImgIcon._deduplicate(width, height, f'load_{i}')
                for i in LOAD_FRAME_IND
            ]
            return main_ico

    @classmethod
    def blank(cls, width: int, height: int) -> ImgAlpha:
        """Shortcut for getting a handle to an empty image."""
        return ImgAlpha._deduplicate(width, height)

    @classmethod
    def background(cls, width: int, height: int) -> ImgBackground:
        """Shortcut for getting a handle to an image containing the background."""
        return ImgBackground._deduplicate(width, height)

    @classmethod
    def color(cls, color: tuple[int, int, int] | Vec, width: int, height: int) -> ImgColor:
        """Shortcut for getting a handle to a solid color."""
        if isinstance(color, Vec):
            # Convert.
            return ImgColor._deduplicate(width, height, int(color.x), int(color.y), int(color.z))
        else:
            return ImgColor._deduplicate(width, height, *color)

    def overlay_text(self, text: str, size: int) -> Handle:
        """Add a text overlay to the corner."""
        return ImgComposite.composite(
            [self, ImgTextOverlay._deduplicate(self.width, self.height, text, size)],
            self.width, self.height
        )

    def has_users(self) -> bool:
        """Check if this image is being used."""
        return self._force_loaded or bool(self._users)

    def reload(self) -> bool:
        """Reload this handle if permitted to, returning whether it was queued.

        Reloading will not occur if the handle was forced loaded, already loading.
        """
        # If force-loaded it's builtin UI etc we shouldn't reload.
        # If already loading, no point.
        if self._force_loaded or self._loading:
            return False

        self._cached_pil = None
        loading = self._request_load(force=True)
        for label_ref in self._users:
            if isinstance(label_ref, WeakRef):
                label: tkImgWidgets | None = label_ref()
                if label is not None:
                    label['image'] = loading
        return True

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
        return self._load_tk(force=False)

    def _load_pil(self) -> Image.Image:
        """Load the PIL image if required, then return it."""
        if self._cached_pil is None:
            self._cached_pil = self._make_image()
        return self._cached_pil

    def _load_tk(self, force: bool) -> ImageTk.PhotoImage:
        """Load the TK image if required, then return it."""
        if self._cached_tk is None or force:
            # LOGGER.debug('Loading {}', self)
            res = self._load_pil()
            # Except for builtin types (icons), composite onto the PeTI BG.
            if not self.alpha_result and res.mode == 'RGBA':
                bg = Image.new('RGBA', res.size, BACKGROUNDS[_current_theme])
                bg.alpha_composite(res)
                res = bg.convert('RGB')
                self._bg_composited = True
            if self._cached_tk is None:
                self._cached_tk = _TK_BACKEND._get_img(res.width, res.height)
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

    def _request_load(self, force=False) -> ImageTk.PhotoImage:
        """Request a reload of this image.

        If this can be done synchronously, the result is returned.
        Otherwise, this returns the loading icon.
        If force is True, the image will be remade even if cached.
        """
        if self._loading is True:
            return Handle.ico_loading(self.width, self.height).get_tk()
        if self._cached_tk is not None and not force:
            return self._cached_tk
        if self._loading is False:
            self._loading = True
            if _load_nursery is None:
                _early_loads.add(self)
            else:
                _load_nursery.start_soon(self._load_task, force)
        return Handle.ico_loading(self.width, self.height).get_tk()

    async def _load_task(self, force: bool) -> None:
        """Scheduled to load images then apply to the labels."""
        await trio.to_thread.run_sync(self._load_pil)
        self._loading = False
        tk_ico = self._load_tk(force)
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
            _TK_BACKEND._discard_img(self._cached_tk)
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

    def resize(self, width: int, height: int) -> Self:
        """Return the same colour with a different image size."""
        return self._deduplicate(width, height)

    def _is_themed(self) -> bool:
        """This is never themed."""
        return False


@attrs.define(eq=False)
class ImgBackground(Handle):
    """A solid image with the theme-appropriate background."""

    def _make_image(self) -> Image.Image:
        """Directly produce an image of this size with the specified color."""
        return Image.new(
            'RGBA',
            (self.width or 16, self.height or 16),
            BACKGROUNDS[_current_theme],  # This is a 3-tuple, but PIL fills alpha=255.
        )

    def resize(self, width: int, height: int) -> Self:
        """Return a new background with this image size."""
        return self._deduplicate(width, height)

    def _is_themed(self) -> bool:
        """This image must reload when the theme changes."""
        return True


class ImgAlpha(Handle):
    """An image which is entirely transparent."""
    alpha_result: ClassVar[bool] = True

    def _make_image(self) -> Image.Image:
        """Produce an image of this size with transparent pixels."""
        return Image.new('RGBA', (self.width or 16, self.height or 16), (0, 0, 0, 0))

    def resize(self, width: int, height: int) -> ImgAlpha:
        """Return a transparent image with a different size."""
        return self._deduplicate(width, height)

    def _is_themed(self) -> bool:
        """This is never themed."""
        return False


@attrs.define(eq=False)
class ImgStripAlpha(Handle):
    """A wrapper around another image, which converts the alpha to 255."""
    alpha_result: ClassVar[bool] = False
    original: Handle

    def _make_image(self) -> Image.Image:
        """Strip the alpha from our child image."""
        img = self.original._load_pil().convert('RGB')
        if self.width and self.height and img.size != (self.width, self.height):
            img = img.resize((self.width, self.height))
        return img.convert('RGBA')

    def resize(self, width: int, height: int) -> ImgStripAlpha:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.original.resize(width, height))

    # Subclass methods
    def _children(self) -> Iterator[Handle]:
        """Yield all the handles this depends on."""
        yield self.original

    def _is_themed(self) -> bool:
        """This is themed if the original is."""
        return self.original.is_themed()

    @classmethod
    def _to_key(cls, args: tuple) -> tuple:
        """Handles aren't hashable, so we need to use identity."""
        [original] = args
        return (id(original), )


@attrs.define(eq=False)
class ImgFile(Handle):
    """An image loaded from a package."""
    uri: utils.PackagePath
    _uses_theme: bool = False

    def _make_image(self) -> Image.Image:
        """Load from a app package."""
        try:
            fsys = PACK_SYSTEMS[self.uri.package]
        except KeyError:
            LOGGER.warning('Unknown package for loading images: "{}"!', self.uri)
            return Handle.error(self.width, self.height).get_pil()

        img, uses_theme = _load_file(fsys, self.uri, self.width, self.height, Image.Resampling.LANCZOS, True)
        if uses_theme:
            self._uses_theme = True
        return img

    def resize(self, width: int, height: int) -> ImgFile:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)

    def _is_themed(self) -> bool:
        """Return it this uses a themed image."""
        return self._uses_theme


@attrs.define(eq=False)
class ImgBuiltin(Handle):
    """An image loaded from builtin UI resources."""
    uri: utils.PackagePath
    allow_raw: ClassVar[bool] = True
    alpha_result: ClassVar[bool] = True
    resize_mode: ClassVar[Image.Resampling] = Image.Resampling.LANCZOS
    _uses_theme: bool = False

    def _make_image(self) -> Image.Image:
        """Load from the builtin UI resources."""
        img, uses_theme = _load_file(FSYS_BUILTIN, self.uri, self.width, self.height, self.resize_mode)
        if uses_theme:
            self._uses_theme = True
        return img

    def resize(self, width: int, height: int) -> ImgBuiltin:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)

    def _is_themed(self) -> bool:
        """Return it this uses a themed image."""
        return self._uses_theme


class ImgSprite(ImgBuiltin):
    """An image loaded from builtin UI resources, with nearest-neighbour resizing."""
    resize_mode: ClassVar[Image.Resampling] = Image.Resampling.NEAREST


@attrs.define(eq=False)
class ImgComposite(Handle):
    """An image composed of multiple layers composited together."""
    alpha_result: ClassVar[bool] = False
    layers: Sequence[Handle]

    @classmethod
    def _to_key(cls, children: tuple[Handle, ...]) -> tuple:
        """Handles aren't hashable, so we need to use identity."""
        return tuple(map(id, children))

    def _is_themed(self) -> bool:
        """Check if this needs to be updated for theming."""
        return any(layer.is_themed() for layer in self.layers)

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
    transpose: Image.Transpose | None

    def _children(self) -> Iterator[Handle]:
        yield self.source

    @classmethod
    def _to_key(cls, args: tuple) -> tuple:
        """Handles aren't hashable, so we need to use identity."""
        [child, bounds, transpose] = args
        return (id(child), bounds, transpose)

    def _is_themed(self) -> bool:
        return self.source.is_themed()

    def _make_image(self) -> Image.Image:
        """Crop this image down to part of the source."""
        src_w = self.source.width
        src_h = self.source.height

        image = self.source._load_pil()
        # Shrink down the source to the final source so the bounds apply.
        # TODO: Rescale bounds to actual source size to improve result?
        if src_w > 0 and src_h > 0 and (src_w, src_h) != image.size:
            image = image.resize((src_w, src_h), resample=Image.Resampling.LANCZOS)

        if self.bounds is not None:
            image = image.crop(self.bounds)

        if self.transpose is not None:
            image = image.transpose(self.transpose)

        if self.width > 0 and self.height > 0 and (self.width, self.height) != image.size:
            image = image.resize((self.width, self.height), resample=Image.Resampling.LANCZOS)
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
        ico = ICONS[self.icon_name, _current_theme]
        width = self.width or ico.width
        height = self.height or ico.height

        img = Image.new('RGBA', (width, height), BACKGROUNDS[_current_theme])

        if width >= ico.width and height >= ico.height:
            # Center the 64x64 icon.
            img.alpha_composite(ico, ((width - ico.width) // 2, (height - ico.height) // 2))
        # Else, no room, don't bother.

        return img

    def resize(self, width: int, height: int) -> ImgIcon:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.icon_name)

    def _is_themed(self) -> bool:
        """This includes the background."""
        return True


@attrs.define(eq=False)
class ImgTextOverlay(Handle):
    """A transparent image containing text in a corner, for overlaying."""
    text: str
    size: int
    # TODO: If exposed, we might want to specify the quadrant to apply to

    def _make_image(self) -> Image.Image:
        """Construct an image with text in the lower-left."""
        img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = get_pil_font(self.size)
        bbox = draw.textbbox(
            (0, self.height),
            self.text,
            font=font,
            anchor='ld',
        )
        draw.rectangle(bbox, fill=BACKGROUNDS[_current_theme])
        draw.text(
            (0, self.height),
            self.text,
            font=font,
            anchor='ld',
            fill=FOREGROUNDS[_current_theme],
        )
        return img

    def resize(self, width: int, height: int) -> ImgTextOverlay:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.text, self.size)

    def _is_themed(self) -> bool:
        """This includes the background."""
        return True


class UIImage(abc.ABC):
    """Interface for the image code specific to a UI library."""


class TKImages(UIImage):
    """Tk-specific image code."""
    # TK images have unique IDs, so preserve discarded image objects.
    unused_img: dict[tuple[int, int], list[ImageTk.PhotoImage]]

    # Maps a handle to the current image used for it.
    tk_img: dict[Handle, ImageTk.PhotoImage]

    def __init__(self) -> None:
        """Set up the TK code."""
        self.unused_img = {}
        self.tk_img = {}

    def _get_img(self, width: int, height: int) -> ImageTk.PhotoImage:
        """Recycle an old image, or construct a new one."""
        if not width:
            width = 16
        if not height:
            height = 16

        # Use setdefault and pop so each step is atomic.
        img_list = self.unused_img.setdefault((width, height), [])
        try:
            img = img_list.pop()
        except IndexError:
            img = ImageTk.PhotoImage('RGBA', (width, height))
        return img

    def _discard_img(self, img: ImageTk.PhotoImage | None) -> None:
        """Store an unused image so it can be reused."""
        if img is not None:
            # Use setdefault and append so each step is atomic.
            img_list = self.unused_img.setdefault((img.width(), img.height()), [])
            img_list.append(img)


# Todo: add actual initialisation of this.
_TK_BACKEND = TKImages()
_UIS.append(_TK_BACKEND)


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
    for i in itertools.cycle(LOAD_FRAME_IND):
        await trio.sleep(0.125)
        for handle, frames in _load_handles.values():
            # This will keep the frame loaded, so next time it's cheap.
            handle._cached_pil = frames[i].get_pil()
            if handle._cached_tk is not None:
                # This updates the TK widget directly.
                handle._cached_tk.paste(handle._load_pil())
            # Otherwise, this isn't being used.


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
                _load_nursery.start_soon(Handle._load_task, handle, False)
        _load_nursery.start_soon(_spin_load_icons)
        await trio.sleep_forever()


def set_theme(new_theme: Theme) -> None:
    """Change the image theme."""
    global _current_theme
    if _current_theme is not new_theme:
        _current_theme = new_theme
        done = 0

        for handle in list(_handles.values()):
            # noinspection PyProtectedMember
            if (handle._bg_composited or handle.is_themed()) and handle.reload():
                done += 1
        # Invalidate all loading images, these need to be redone.
        for load, load_frames in _load_handles.values():
            for handle in load_frames:
                handle._cached_pil = None
        LOGGER.info('Queued {} images to reload for new theme "{}".', done, new_theme)


def refresh_all() -> None:
    """Force all images to reload."""
    LOGGER.info('Forcing all images to reload!')
    done = 0
    for handle in list(_handles.values()):
        if handle.has_users() and handle.reload():
            done += 1
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


@functools.lru_cache
def get_pil_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Find a nice font for drawing into images."""
    for filename in [
        'san fransisco.ttf',
        'segoeui.ttf',
        'lucida sans.ttf',
        'helvetica neue.ttf',
        'tahoma.ttf',
        'ubuntu.ttf',
    ]:
        try:
            return ImageFont.truetype(filename, size)
        except IOError:
            pass
    else:
        LOGGER.warning('Failed to find font, add more OS fonts!')
        return ImageFont.load_default()


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
