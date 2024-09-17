"""The image system manages all the images packages request.


Handles are automatically deduplicated, and intiaially only contain the 
filename/options, so are cheap to create. Once applied to a UI widget, 
they are loaded in the background, then unloaded if removed from all widgets.
"""
from __future__ import annotations
from typing import Any, ClassVar, Final, Literal, override
from typing_extensions import Self

from abc import abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from contextlib import aclosing
from fractions import Fraction
from pathlib import Path, PurePath
import abc
import functools
import itertools
import logging
import weakref

from PIL import Image, ImageColor, ImageDraw, ImageFont
from srctools import Keyvalues, Vec
from srctools.filesys import (
    File as FSFile, FileSystem, FileSystemChain, RawFileSystem,
)
from srctools.vtf import VTF
import attrs
import srctools.logger
import trio

from consts import Theme
import utils


# Used to deduplicate handles with existing ones. But if they're totally unused, let them die.
_handles: weakref.WeakValueDictionary[
    tuple[type[Handle], tuple[object, ...], int, int],
    Handle,
] = weakref.WeakValueDictionary()

LOGGER = srctools.logger.get_logger('img')
LOGGER.setLevel('INFO')

FOLDER_PROPS_MAP_EDITOR = PurePath('resources', 'materials', 'models', 'props_map_editor')
FSYS_BUILTIN = RawFileSystem(str(utils.install_path('images')))
PACK_SYSTEMS: dict[str, FileSystem[Any]] = {}
# Force-loaded handles must be kept alive.
_force_loaded_handles: list[Handle] = []

# Silence DEBUG messages from Pillow, they don't help.
logging.getLogger('PIL').setLevel(logging.INFO)

# The currently selected theme for images.
_current_theme: Theme = Theme.LIGHT

# The implementation for the UI. This allows this module to be library-independent.
_UI_IMPL: UIImage | None = None

# Colour of the palette item background
PETI_ITEM_BG: Final = (229, 233, 233)
PETI_ITEM_BG_HEX: Final = '#{:2X}{:2X}{:2X}'.format(*PETI_ITEM_BG)
BACKGROUNDS: Mapping[Theme, tuple[int, int, int]] = {
    Theme.LIGHT: (229, 233, 233),  # Same as palette items ingame.
    Theme.DARK: (26, 22, 22),
}
FOREGROUNDS: Mapping[Theme, tuple[int, int, int, int]] = {
    Theme.LIGHT: (0, 0, 0, 255),
    Theme.DARK: (255, 255, 255, 255),
}

# Re-exported from PIL.
ROTATE_CW: Final = Image.Transpose.ROTATE_270
ROTATE_CCW: Final = Image.Transpose.ROTATE_90
FLIP_LEFT_RIGHT: Final = Image.Transpose.FLIP_LEFT_RIGHT
FLIP_TOP_BOTTOM: Final = Image.Transpose.FLIP_TOP_BOTTOM
FLIP_ROTATE: Final = Image.Transpose.ROTATE_180

type DefaultExt = Literal['png', 'vtf']


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


def _build_icons() -> dict[tuple[str, Theme], Image.Image]:
    icons = {
        (name, theme): _load_special(name, theme)
        for name in ['error', 'none', 'load']
        for theme in Theme
    }
    # The icon has 8 parts, with the gap in the 1 pos. So mirror/rotate to
    # derive the others.
    for _theme in Theme:
        icons['load_0', _theme] = _load_icon = icons['load', _theme]
        icons['load_7', _theme] = _load_icon_flip = _load_icon.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        icons['load_1', _theme] = _load_icon_flip.transpose(Image.Transpose.ROTATE_270)
        icons['load_2', _theme] = _load_icon.transpose(Image.Transpose.ROTATE_270)
        icons['load_3', _theme] = _load_icon.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        icons['load_4', _theme] = _load_icon.transpose(Image.Transpose.ROTATE_180)
        icons['load_5', _theme] = _load_icon_flip.transpose(Image.Transpose.ROTATE_90)
        icons['load_6', _theme] = _load_icon.transpose(Image.Transpose.ROTATE_90)
    return icons


ICONS: Mapping[tuple[str, Theme], Image.Image] = _build_icons()
# Frame indices in order.
LOAD_FRAME_IND = range(8)
# Once initialised, schedule here.
_load_nursery: trio.Nursery | None = None
# Load calls occurring before init. This is done so apply() can be called during import etc,
# and it'll be deferred till later.
_early_loads: set[Handle] = set()


# Special paths which map to various images.
PAK_SPECIAL = utils.special_id('<special>')
PAK_COLOR = utils.special_id('<color>')
PAK_BEE2 = utils.special_id('<bee2>')

PATH_BLANK = utils.PackagePath(PAK_SPECIAL, 'blank')
PATH_ERROR = utils.PackagePath(PAK_SPECIAL, 'error')
PATH_LOAD = utils.PackagePath(PAK_SPECIAL, 'load')
PATH_NONE = utils.PackagePath(PAK_SPECIAL, 'none')
PATH_BG = utils.PackagePath(PAK_SPECIAL, 'bg')
PATH_BLACK = utils.PackagePath(PAK_COLOR, '000')
PATH_WHITE = utils.PackagePath(PAK_COLOR, 'fff')


def current_theme() -> Theme:
    """Retrieve the currently selected theme."""
    return _current_theme


def _find_file(
    fsys: FileSystem[Any],
    uri: utils.PackagePath,
    default_ext: DefaultExt,
    check_other_packages: bool = False,
) -> tuple[FSFile | None, bool]:
    """Locate an image within the filesystem."""
    path = uri.path.casefold()
    if path[-4:-3] == '.':
        path, ext = path[:-4], path[-3:]
    else:
        ext = default_ext

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
    return img_file, uses_theme


def _load_file(
    file: FSFile,
    uri: utils.PackagePath,
    width: int, height: int,
) -> Image.Image:
    """Load an image, given the filesystem reference."""
    try:
        with file.open_bin() as stream:
            if file.path.endswith('.vtf'):
                image = VTF.read(stream).get().to_PIL()
            else:
                image = Image.open(stream)
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
    return image


class User:
    """A user is something that can contain an image, like a widget.

    These are UI-library specific, except for handles themselves.
    """


@attrs.define(eq=False)
class Handle(User):
    """Represents an image that may be reloaded as required.

    The args are dependent on the type, and are used to create the image
    in a background thread.
    """
    width: int
    height: int

    _cached_pil: Image.Image | None = attrs.field(init=False, default=None, repr=False)

    _users: set[User] = attrs.field(init=False, factory=set, repr=False)
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
    # If image needs to be scaled, whether to use nearest-neighbour.
    resize_pixel: ClassVar[bool] = False
    # Track how many are loading.
    _currently_loading: ClassVar[int] = 0

    @property
    def resampling_algo(self) -> Image.Resampling:
        """The appropriate resampling mode to use."""
        return Image.Resampling.NEAREST if self.resize_pixel else Image.Resampling.LANCZOS

    # Subclass methods
    def _children(self) -> Iterator[Handle]:
        """Yield all the handles this depends on."""
        return iter(())

    @abstractmethod
    def _make_image(self) -> Image.Image:
        """Construct the image data, must be implemented by subclass."""
        raise NotImplementedError

    @classmethod
    def _to_key(cls, args: tuple[Any, ...], /) -> tuple[Any, ...]:
        """Override in subclasses to convert mutable attributes to deduplicate."""
        return args

    @abstractmethod
    def resize(self, width: int, height: int) -> Self:
        """Return a copy with a different size."""
        raise NotImplementedError

    @abstractmethod
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

    @abstractmethod
    def uses_packsys(self) -> bool:
        """Returns whether this image uses package resources."""
        return False

    @classmethod
    def _deduplicate(cls, width: int | tuple[int, int], height: int, *args: Any) -> Self:
        """Reuse an existing handle instance if possible. Args are passed to the constructor."""
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
        cls,
        kv: Keyvalues,
        pack: utils.ObjectID,
        width: int,
        height: int,
        *,
        subkey: str = '',
        subfolder: str = '',
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
        subfolder: str = '',
        default_ext: DefaultExt = 'png',
    ) -> Handle:
        """Parse a URI into an image handle.

        parse() should be used wherever possible, since that allows composite
        images.
        If subfolder is specified, files will be relative to this folder.
        The width/height may be zero to indicate it should not be resized.
        """
        if uri.path.casefold() == '<black>':  # Old special case name.
            LOGGER.warning(
                'Using "{}" for a black icon is deprecated, use "<color>:black", '
                '"<color>:#000" or "<rgb>:rgb(0,0,0)".',
                uri,
            )
            return cls.color((0, 0, 0), width, height)
        elif uri.package.startswith('<') and uri.package.endswith('>'):  # Special names.
            match uri.package[1:-1]:
                case 'SPECIAL':
                    match uri.path.casefold():
                        case 'blank':
                            return ImgAlpha._deduplicate(width, height)
                        case 'error' | 'none' as icon:
                            return ImgIcon._deduplicate(width, height, icon)
                        case 'bg':
                            return ImgBackground._deduplicate(width, height)
                        case _:
                            raise ValueError(f'Unknown special type "{uri.path}"!')
                case 'COLOR' | 'COLOUR' | 'RGB':
                    color = uri.path
                    try:
                        if ',' in color:  # <color>:R,G,B
                            r, g, b = map(int, color.split(','))
                        elif len(color) == 3:  # RGB
                            r = int(color[0] * 2, 16)
                            g = int(color[1] * 2, 16)
                            b = int(color[2] * 2, 16)
                        elif len(color) == 6:  # RRGGBB
                            r = int(color[0:2], 16)
                            g = int(color[2:4], 16)
                            b = int(color[4:6], 16)
                        else:
                            raise ValueError
                    except (ValueError, TypeError, OverflowError):
                        try:
                            # <color>:#RRGGBB, :rgb(RR, GG, BB), :hsv(HH, SS, VV) etc
                            r, g, b, *a = ImageColor.getrgb(color)
                            if len(a) not in (0, 1):
                                raise ValueError
                        except ValueError:
                            raise ValueError(
                                f'Colors must be #RGB, #RRGGBB hex values, '
                                f'or R,G,B decimal, not {uri}'
                            ) from None
                    return cls.color((r, g, b), width, height)
                case 'BEE' | 'BEE2':  # Builtin resources.
                    if subfolder:
                        uri = uri.in_folder(subfolder)
                    return cls.builtin(uri, width, height)
                case _:
                    raise ValueError(f'Unknown special icon type "{uri}"!')
        else:  # File item
            if subfolder:
                uri = uri.in_folder(subfolder)
            return cls.file(uri, width, height, default_ext)

    @classmethod
    def builtin(cls, path: utils.PackagePath | str, width: int = 0, height: int = 0) -> ImgBuiltin:
        """Shortcut for getting a handle to a builtin UI image."""
        if isinstance(path, str):
            path = utils.PackagePath(PAK_BEE2, path + '.png')
        return ImgBuiltin._deduplicate(width, height, path)

    @classmethod
    def sprite(cls, path: utils.PackagePath | str, width: int = 0, height: int = 0) -> ImgSprite:
        """Shortcut for getting a handle to a builtin UI image, but with nearest-neighbour rescaling."""
        if isinstance(path, str):
            path = utils.PackagePath(PAK_BEE2, path + '.png')
        return ImgSprite._deduplicate(width, height, path)

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

    def transform(
        self,
        ratio: tuple[int, int] | None = None,
        transpose: Image.Transpose | None = None,
        width: int = 0, height: int = 0,
    ) -> ImgTransform:
        """Wrap a handle to change the ratio, or do flips."""
        return ImgTransform._deduplicate(width, height, self, ratio, transpose)

    def with_alpha_stripped(self) -> ImgStripAlpha:
        """Wrap a handle to strip alpha."""
        return ImgStripAlpha._deduplicate(self.width, self.height, self)

    @classmethod
    def file(
        cls,
        path: utils.PackagePath,
        width: int, height: int,
        default_ext: DefaultExt = 'png',
    ) -> ImgFile:
        """Shortcut for getting a handle to a file path."""
        return ImgFile._deduplicate(width, height, path, default_ext)

    @classmethod
    def error(cls, width: int, height: int) -> ImgIcon:
        """Shortcut for getting a handle to an error icon."""
        return ImgIcon._deduplicate(width, height, 'error')

    @classmethod
    def ico_none(cls, width: int, height: int) -> ImgIcon:
        """Shortcut for getting a handle to a 'none' icon."""
        return ImgIcon._deduplicate(width, height, 'none')

    @classmethod
    def ico_loading(cls, width: int, height: int) -> Handle:
        """Retrieve a handle to a 'loading' icon."""
        if width < 64 or height < 64:
            # Too small to show the icon, just use a blank image.
            return ImgBackground._deduplicate(width, height)
        try:
            return ImgLoading.load_anims[width, height][0]
        except KeyError:
            main_ico = ImgLoading._deduplicate(width, height, 'load')
            # Build an additional load icon for each frame, so that can be cached.
            ImgLoading.load_anims[width, height] = main_ico, [
                ImgLoading._deduplicate(width, height, f'load_{i}')
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

        Reloading will not occur if the handle was forced loaded or already loading.
        """
        # If force-loaded it's builtin UI etc we shouldn't reload.
        # If already loading, no point.
        if self._force_loaded or self._loading:
            return False

        self._cached_pil = None
        self._request_load(force=True)
        if _UI_IMPL is not None:
            _UI_IMPL.ui_force_load(self)
        return True

    def get_pil(self) -> Image.Image:
        """Load the PIL image if required, then return it."""
        if self.allow_raw:
            # Force load, so it's always ready.
            self.force_load()
        elif not self._users and _load_nursery is not None:
            # Loading something unused, schedule it to be cleaned soon.
            try:
                trio.lowlevel.current_task()
            except Exception:
                # We're in a thread, do this back on the main thread.
                trio.from_thread.run_sync(self._schedule_cleanup)
            else:
                self._schedule_cleanup()
        return self._load_pil()

    def force_load(self) -> None:
        """Set this image as force-loaded.

        This is only allowed on BUILTIN images, that don't come from packages.
        """
        if not self.allow_raw:
            raise ValueError(f'Cannot force-load handle with non-builtin type {self!r}!')
        if not self._force_loaded:
            LOGGER.debug('Force loading: {!r}', self)
            _force_loaded_handles.append(self)
            self._force_loaded = True

    def _load_pil(self) -> Image.Image:
        """Load the PIL image if required, then return it."""
        if self._cached_pil is None:
            self._cached_pil = self._make_image()
        return self._cached_pil

    def _decref(self, ref: User) -> None:
        """A user no longer requires this handle."""
        if self._force_loaded:
            return
        self._users.discard(ref)
        for child in self._children():
            child._decref(self)
        if _load_nursery is None:
            return  # Not loaded, can't unload.
        if not self._users and self._cached_pil is not None:
            # Schedule this handle to be cleaned up.
            self._schedule_cleanup()

    def _incref(self, ref: User) -> None:
        """Add some user to the list of those controlled by us."""
        if self._force_loaded:
            return
        self._users.add(ref)
        # Abort cleaning up if we were planning to.
        self._cancel_cleanup.cancel()
        for child in self._children():
            child._incref(self)

    def _schedule_cleanup(self) -> None:
        """Schedule this handle to be cleaned up."""
        if self._users:
            return  # We do have users.
        self._cancel_cleanup.cancel()
        self._cancel_cleanup = trio.CancelScope()
        if _load_nursery is not None:
            _load_nursery.start_soon(self._cleanup_task, self._cancel_cleanup)

    def _request_load(self, force: bool = False) -> Handle:
        """Request a reload of this image.

        If this can be done synchronously, the result is returned.
        Otherwise, this returns the loading icon.
        If force is True, the image will be remade even if cached.
        """
        load_handle = Handle.ico_loading(self.width, self.height)
        if self._loading:
            return load_handle
        else:
            self._loading = True
            if _load_nursery is None:
                _early_loads.add(self)
            else:
                _load_nursery.start_soon(self._load_task, load_handle, force)
        return load_handle

    async def _load_task(self, load_handle: Handle, force: bool) -> None:
        """Scheduled to load images then apply to the widgets."""
        Handle._currently_loading += 1
        try:
            if isinstance(load_handle, ImgLoading):
                load_handle.load_targs.add(self)
                if Handle._currently_loading == 1:
                    # First to load, so wake up the anim.
                    ImgLoading.trigger_wakeup()
            await trio.to_thread.run_sync(self._load_pil)
        finally:
            if isinstance(load_handle, ImgLoading):
                load_handle.load_targs.discard(self)
            Handle._currently_loading -= 1
        self._loading = False
        if _UI_IMPL is not None:
            _UI_IMPL.ui_load_users(self, force)

    async def _cleanup_task(self, scope: trio.CancelScope) -> None:
        """Wait for the time to elapse, then clear the contents."""
        with scope:
            await trio.sleep(5)
        # We weren't cancelled and are empty, cleanup.
        if not scope.cancel_called and not self.has_users():
            if _UI_IMPL is not None:
                _UI_IMPL.ui_clear_handle(self)
            LOGGER.debug('Clear handle: {}', self)
            self._cached_pil = None


@attrs.define(eq=False)
class ImgColor(Handle):
    """An image containing a solid color."""
    red: int
    green: int
    blue: int

    @override
    def _make_image(self) -> Image.Image:
        """Directly produce an image of this size with the specified color."""
        return Image.new(
            'RGBA',
            (self.width or 16, self.height or 16),
            (self.red, self.green, self.blue, 255),
        )

    @override
    def resize(self, width: int, height: int) -> Self:
        """Return the same colour with a different image size."""
        return self._deduplicate(width, height)

    @override
    def _is_themed(self) -> bool:
        """This is never themed."""
        return False

    @override
    def uses_packsys(self) -> bool:
        """This doesn't use package resources."""
        return False


@attrs.define(eq=False)
class ImgBackground(Handle):
    """A solid image with the theme-appropriate background."""

    @override
    def _make_image(self) -> Image.Image:
        """Directly produce an image of this size with the specified color."""
        return Image.new(
            'RGBA',
            (self.width or 16, self.height or 16),
            BACKGROUNDS[_current_theme],  # This is a 3-tuple, but PIL fills alpha=255.
        )

    @override
    def resize(self, width: int, height: int) -> Self:
        """Return a new background with this image size."""
        return self._deduplicate(width, height)

    @override
    def _is_themed(self) -> bool:
        """This image must reload when the theme changes."""
        return True

    @override
    def uses_packsys(self) -> bool:
        """This doesn't use package resources."""
        return False


class ImgAlpha(Handle):
    """An image which is entirely transparent."""
    alpha_result: ClassVar[bool] = True

    @override
    def _make_image(self) -> Image.Image:
        """Produce an image of this size with transparent pixels."""
        return Image.new('RGBA', (self.width or 16, self.height or 16), (0, 0, 0, 0))

    @override
    def resize(self, width: int, height: int) -> ImgAlpha:
        """Return a transparent image with a different size."""
        return self._deduplicate(width, height)

    @override
    def _is_themed(self) -> bool:
        """This is never themed."""
        return False

    @override
    def uses_packsys(self) -> bool:
        """This doesn't use package resources."""
        return False


@attrs.define(eq=False)
class ImgStripAlpha(Handle):
    """A wrapper around another image, which converts the alpha to 255."""
    alpha_result: ClassVar[bool] = False
    original: Handle

    @override
    def _make_image(self) -> Image.Image:
        """Strip the alpha from our child image."""
        img = self.original._load_pil().convert('RGB')
        if self.width and self.height and img.size != (self.width, self.height):
            img = img.resize((self.width, self.height))
        return img.convert('RGBA')

    @override
    def resize(self, width: int, height: int) -> ImgStripAlpha:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.original.resize(width, height))

    @override
    def _children(self) -> Iterator[Handle]:
        """Yield all the handles this depends on."""
        yield self.original

    @override
    def _is_themed(self) -> bool:
        """This is themed if the original is."""
        return self.original.is_themed()

    @override
    def uses_packsys(self) -> bool:
        return self.original.uses_packsys()

    @classmethod
    @override
    def _to_key(cls, args: tuple[object, ...], /) -> tuple[object, ...]:
        """Handles aren't hashable, so we need to use identity."""
        [original] = args
        return (id(original), )


@attrs.define(eq=False)
class ImgFile(Handle):
    """An image loaded from a package."""
    uri: utils.PackagePath
    _uses_theme: bool = False
    default_ext: DefaultExt = 'png'

    @override
    def _make_image(self) -> Image.Image:
        """Load from a app package."""
        try:
            fsys = PACK_SYSTEMS[self.uri.package]
        except KeyError:
            LOGGER.warning('Unknown package for loading images: "{}"!', self.uri)
            return Handle.error(self.width, self.height).get_pil()

        file, uses_theme = _find_file(fsys, self.uri, self.default_ext, True)
        if file is not None:
            img = _load_file(file, self.uri, self.width, self.height)
        else:
            img = Handle.error(self.width, self.height).get_pil()
        if uses_theme:
            self._uses_theme = True
        return img

    @override
    def resize(self, width: int, height: int) -> ImgFile:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)

    @override
    def _is_themed(self) -> bool:
        """Return it this uses a themed image."""
        return self._uses_theme

    @override
    def uses_packsys(self) -> bool:
        """This always uses package resources."""
        return True

    def palette_filename(self) -> PurePath | None:
        """Determine if this image can be directly referenced by the puzzlemaker.

        If so, return the filename to use.
        """
        try:
            fsys = PACK_SYSTEMS[self.uri.package]
        except KeyError:
            return None
        file, uses_theme = _find_file(fsys, self.uri, self.default_ext, True)
        if uses_theme or file is None:
            return None
        path = PurePath(file.path)
        try:
            return path.relative_to(FOLDER_PROPS_MAP_EDITOR).with_suffix('.png')
        except ValueError:
            return None


@attrs.define(eq=False)
class ImgBuiltin(Handle):
    """An image loaded from builtin UI resources."""
    uri: utils.PackagePath
    allow_raw: ClassVar[bool] = True
    alpha_result: ClassVar[bool] = True
    _uses_theme: bool = False

    @override
    def _make_image(self) -> Image.Image:
        """Load from the builtin UI resources."""
        file, uses_theme = _find_file(FSYS_BUILTIN, self.uri, 'png')
        if uses_theme:
            self._uses_theme = True
        if file is not None:
            return _load_file(file, self.uri, self.width, self.height)
        else:
            return Handle.error(self.width, self.height).get_pil()

    @override
    def resize(self, width: int, height: int) -> ImgBuiltin:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.uri)

    @override
    def _is_themed(self) -> bool:
        """Return if this uses a themed image."""
        return self._uses_theme

    @override
    def uses_packsys(self) -> bool:
        """This doesn't use package resources."""
        return False


class ImgSprite(ImgBuiltin):
    """An image loaded from builtin UI resources, with nearest-neighbour resizing."""
    resize_pixel: ClassVar[bool] = True


@attrs.define(eq=False)
class ImgComposite(Handle):
    """An image composed of multiple layers composited together."""
    alpha_result: ClassVar[bool] = False
    layers: Sequence[Handle]

    @classmethod
    @override
    def _to_key(cls, children: tuple[Handle, ...], /) -> tuple[int, ...]:
        """Handles aren't hashable, so we need to use identity."""
        return tuple(map(id, children))

    @override
    def _is_themed(self) -> bool:
        """Check if this needs to be updated for theming."""
        return any(layer.is_themed() for layer in self.layers)

    @override
    def _children(self) -> Iterator[Handle]:
        """Yield the children this depends on."""
        yield from self.layers

    @override
    def uses_packsys(self) -> bool:
        """Check if any children use package resources."""
        return any(layer.uses_packsys() for layer in self.layers)

    @override
    def _make_image(self) -> Image.Image:
        """Combine several images into one."""
        children = [
            layer._load_pil() for layer in self.layers
        ]
        size = (
            max(child.width for child in children),
            max(child.height for child in children)
        )
        ratio = Fraction(*size)
        img = Image.new('RGBA', size)
        for layer, child in zip(self.layers, children, strict=True):
            if Fraction(child.width, child.height) != ratio:
                LOGGER.warning(
                    'Mismatch in layered image ratios: target={}x{}, '
                    'layer={}x{} for {!r}',
                    *size, *child.size, layer,
                )
                return Handle.error(self.width, self.height).get_pil()
            # noinspection PyProtectedMember
            if child.mode != 'RGBA':
                LOGGER.warning('Layered image does not have alpha: {!r}', layer)
                child = child.convert('RGBA')
            img.alpha_composite(child.resize(size, layer.resampling_algo))
        return img

    @override
    def resize(self, width: int, height: int) -> ImgComposite:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, [
            img.resize(width, height)
            for img in self.layers
        ])


@attrs.define(eq=False)
class ImgTransform(Handle):
    """An image that crops another down to only show part."""
    alpha_result: ClassVar[bool] = True
    source: Handle
    # The target aspect ratio to produce
    ratio: tuple[int, int] | None
    transpose: Image.Transpose | None

    @override
    def _children(self) -> Iterator[Handle]:
        yield self.source

    @classmethod
    @override
    def _to_key(
        cls,
        args: tuple[Handle, tuple[int, int] | None, Image.Transpose | None],
        /,
    ) -> tuple[int, tuple[int, int] | None, Image.Transpose | None]:
        """Handles aren't hashable, so we need to use identity."""
        [child, bounds, transpose] = args
        return (id(child), bounds, transpose)

    @override
    def _is_themed(self) -> bool:
        return self.source.is_themed()

    @override
    def uses_packsys(self) -> bool:
        return self.source.uses_packsys()

    def _crop(self, ratio: Fraction, image: Image.Image) -> Image.Image:
        # Alter the image to have the specified ratio.
        width = image.width
        height = image.height
        if ratio == Fraction(width, height):
            return image

        # One direction requires expanding,
        # the other requires cropping. We use the latter.
        crop_width = (width - (height * ratio)) / 2
        crop_height = (height - (width / ratio)) / 2
        # First, we might need to scale up to keep the pixel counts.
        # That could cause extreme sizes, so guard against that.
        scale = max(crop_width, crop_height).denominator
        if scale != 1:
            width *= scale
            height *= scale
            if width > 512 or height > 512:
                LOGGER.warning('Cropped image too big at {}x{}!', width, height)
                # Just give up, rescale to the target ratio.
                return image.resize((384, int(384 * ratio)))

            image = image.resize((width, height), self.source.resampling_algo)
            crop_width *= scale
            crop_height *= scale

        if crop_width > crop_height:
            crop_dist = crop_width.numerator * crop_width.denominator
            return image.crop((crop_dist, 0, width - crop_dist, height))
        else:
            crop_dist = crop_height.numerator * crop_height.denominator
            return image.crop((0, crop_dist, width, height - crop_dist))

    @override
    def _make_image(self) -> Image.Image:
        """Crop this image down to part of the source."""

        image = self.source._load_pil()
        if self.ratio is not None:
            image = self._crop(Fraction(*self.ratio), image)

        if self.transpose is not None:
            image = image.transpose(self.transpose)
        return image

    @override
    def resize(self, width: int, height: int) -> ImgTransform:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.source, self.ratio, self.transpose)


@attrs.define(eq=False)
class ImgIcon(Handle):
    """An image containing the PeTI background with a centered icon."""
    icon_name: str
    allow_raw: ClassVar[bool] = True

    @override
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

    @override
    def resize(self, width: int, height: int) -> ImgIcon:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.icon_name)

    @override
    def _is_themed(self) -> bool:
        """This includes the background."""
        return True

    @override
    def uses_packsys(self) -> bool:
        """This doesn't use package resources."""
        return False


@attrs.define(eq=False)
class ImgLoading(ImgIcon):
    """Special behaviour for the animated loading icon."""
    # Loader handles, which we want to cycle animate.
    # The first icon is the one users use, the others are each frame (manually loaded).
    load_anims: ClassVar[dict[tuple[int, int], tuple[ImgLoading, list[ImgLoading]]]] = {}

    # If all loading images stop, the animation task sleeps forever. This event wakes it up.
    _wakeup: ClassVar[trio.Event] = trio.Event()

    # Currently loading handles using this icon.
    load_targs: set[Handle] = attrs.field(init=False, factory=set)

    @classmethod
    def trigger_wakeup(cls) -> None:
        """Begin the animation."""
        cls._wakeup.set()
        cls._wakeup = trio.Event()

    @classmethod
    async def anim_task(cls, ui: UIImage) -> None:
        """Cycle loading icons."""
        await trio.lowlevel.checkpoint()
        for i in itertools.cycle(LOAD_FRAME_IND):
            await trio.sleep(0.125)
            for handle, frames in cls.load_anims.values():
                # This will keep the frame loaded, so next time it's cheap.
                handle._cached_pil = pil_img = frames[i].get_pil()
                ui.ui_apply_load(handle, frames[i], pil_img)
            if Handle._currently_loading == 0:
                await cls._wakeup.wait()


@attrs.define(eq=False)
class ImgTextOverlay(Handle):
    """A transparent image containing text in a corner, for overlaying."""
    text: str
    size: int
    # TODO: If exposed, we might want to specify the quadrant to apply to

    @override
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

    @override
    def resize(self, width: int, height: int) -> ImgTextOverlay:
        """Return a copy with a different size."""
        return self._deduplicate(width, height, self.text, self.size)

    @override
    def _is_themed(self) -> bool:
        """This includes the background."""
        return True

    @override
    def uses_packsys(self) -> bool:
        """This only uses UI resources."""
        return False


class UIImage(abc.ABC):
    """Interface for the image code specific to a UI library."""
    @abc.abstractmethod
    def ui_clear_handle(self, handle: Handle) -> None:
        """The handle is no longer used, release resources it uses."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_load_users(self, handle: Handle, force: bool) -> None:
        """The PIL image is ready, apply it to the widgets using this handle."""
        raise NotImplementedError

    @abc.abstractmethod
    def ui_force_load(self, handle: Handle) -> None:
        """Called when this handle is reloading, and should update all its widgets."""
        raise NotImplementedError

    def ui_apply_load(self, handle: ImgLoading, frame_handle: ImgLoading, frame_pil: Image.Image) -> None:
        """Copy the loading icon to all users of the main image.

        Tk applies the PIL image to the Tk image directly, while Wx needs to set each widget.
        """
        raise NotImplementedError


async def _load_fsys_task(*, task_status: trio.TaskStatus = trio.TASK_STATUS_IGNORED) -> None:
    """When packages change, reload images."""
    # Circular import
    from packages import LOADED, PackagesSet
    props_map_editor = FOLDER_PROPS_MAP_EDITOR.as_posix()

    global PACK_SYSTEMS
    async with aclosing(LOADED.eventual_values()) as agen:
        packset: PackagesSet
        async for packset in agen:
            PACK_SYSTEMS = {
                pack.id: FileSystemChain(
                    (pack.fsys, 'resources/bee2/'),
                    (pack.fsys, 'resources/materials/'),
                    (pack.fsys, props_map_editor),
                )
                for pack in packset.packages.values()
            }
            done = 0
            for handle in list(_handles.values()):
                if handle.uses_packsys() and handle.has_users() and handle.reload():
                    done += 1
            LOGGER.info('Reloaded {} handles that use packages.', done)

            task_status.started()
            # Real task statuses raises if called multiple twice.
            task_status = trio.TASK_STATUS_IGNORED


# noinspection PyProtectedMember
async def init(
    implementation: UIImage,
    *, task_status: trio.TaskStatus[None] = trio.TASK_STATUS_IGNORED,
) -> None:
    """Start the background loading of images, using the specified filesystem and implementation.
    """
    global _load_nursery, _UI_IMPL

    try:
        async with trio.open_nursery() as nursery:
            if _load_nursery is not None or _UI_IMPL is not None:
                raise AssertionError('Only one image system can be run at a time!')
            _load_nursery = nursery
            _UI_IMPL = implementation

            await nursery.start(_load_fsys_task)

            LOGGER.debug('Early loads: {}', _early_loads)
            while _early_loads:
                handle = _early_loads.pop()
                if handle._users:
                    load_handle = Handle.ico_loading(handle.width, handle.height)
                    nursery.start_soon(Handle._load_task, handle, load_handle, False)
            nursery.start_soon(ImgLoading.anim_task, implementation)
            task_status.started()
            # Sleep, until init() is potentially cancelled.
            await trio.sleep_forever()
    finally:
        # Unset and clear everything, for the benefit of test code.
        _UI_IMPL = None
        _load_nursery = None
        PACK_SYSTEMS.clear()
        ImgLoading.load_anims.clear()
        _early_loads.clear()


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
        for load, load_frames in ImgLoading.load_anims.values():
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


def stats() -> str:
    """Fetch various debugging stats."""
    # noinspection PyProtectedMember
    return f'''
Handles: {len(_handles)}, loading={Handle._currently_loading}
Theme: {_current_theme}
Force-loaded: {len(_force_loaded_handles)}
Tasks: {len(_load_nursery.child_tasks) if _load_nursery is not None else '<N/A>'}
'''


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
        except OSError:
            pass
    LOGGER.warning('Failed to find font, add more OS fonts!')
    return ImageFont.load_default()


def make_splash_screen(
    max_width: float,
    max_height: float,
    base_height: int,
    text1_bbox: tuple[int, int, int, int],
    text2_bbox: tuple[int, int, int, int],
) -> Image.Image:
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
    except (FileNotFoundError, IndexError, OSError):
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

    return image
