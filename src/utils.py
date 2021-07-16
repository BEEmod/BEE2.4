"""Various functions shared among the compiler and application."""
from __future__ import annotations
from collections import deque
from typing import (
    TypeVar, Any, NoReturn, Generic, Type,
    SupportsInt, Union, Callable,
    Sequence, Iterator, Iterable, Mapping,
    KeysView, ValuesView, ItemsView, Generator,
)
import logging
import os
import stat
import shutil
import copyreg
import sys
from pathlib import Path
from enum import Enum
from types import TracebackType


try:
    # This module is generated when cx_freeze compiles the app.
    from BUILD_CONSTANTS import BEE_VERSION  # type: ignore
except ImportError:
    # We're running from source!
    BEE_VERSION = "(dev)"
    FROZEN = False
    DEV_MODE = True
else:
    FROZEN = True
    # If blank, in dev mode.
    DEV_MODE = not BEE_VERSION

WIN = sys.platform.startswith('win')
MAC = sys.platform.startswith('darwin')
LINUX = sys.platform.startswith('linux')

# App IDs for various games. Used to determine which game we're modding
# and activate special support for them
STEAM_IDS = {
    'PORTAL2': '620',

    'APTAG': '280740',
    'APERTURE TAG': '280740',
    'ALATAG': '280740',
    'TAG': '280740',

    'TWTM': '286080',
    'THINKING WITH TIME MACHINE': '286080',

    'MEL': '317400',  # Note - no workshop

    'DEST_AP': '433970',
    'DESTROYED_APERTURE': '433970',

    # Others:
    # 841: P2 Beta
    # 213630: Educational
    # 247120: Sixense
    # 211480: 'In Motion'
}


# Add core srctools types into the pickle registry, so they can be more directly
# loaded.
# IDs 240 - 255 are available for application uses.
copyreg.add_extension('srctools.math', '_mk_vec', 240)
copyreg.add_extension('srctools.math', '_mk_ang', 241)
copyreg.add_extension('srctools.math', '_mk_mat', 242)
copyreg.add_extension('srctools.math', 'Vec_tuple', 243)
copyreg.add_extension('srctools.property_parser', 'Property', 244)


# Appropriate locations to store config options for each OS.
if WIN:
    _SETTINGS_ROOT = Path(os.environ['APPDATA'])
elif MAC:
    _SETTINGS_ROOT = Path('~/Library/Preferences/').expanduser()
elif LINUX:
    _SETTINGS_ROOT = Path('~/.config').expanduser()
else:
    # Defer the error until used, so it goes in logs and whatnot.
    # Utils is early, so it'll get lost in stderr.
    _SETTINGS_ROOT = None  # type: ignore

# We always go in a BEE2 subfolder
if _SETTINGS_ROOT:
    _SETTINGS_ROOT /= 'BEEMOD2'

if FROZEN:
    # This special attribute is set by PyInstaller to our folder.
    _INSTALL_ROOT = Path(getattr(sys, '_MEIPASS'))
else:
    # We're running from src/, so data is in the folder above that.
    # Go up once from the file to its containing folder, then to the parent.
    _INSTALL_ROOT = Path(sys.argv[0]).resolve().parent.parent


def install_path(path: str) -> Path:
    """Return the path to a file inside our installation folder."""
    return _INSTALL_ROOT / path


def conf_location(path: str) -> Path:
    """Return the full path to save settings to.

    The passed-in path is relative to the settings folder.
    Any additional subfolders will be created if necessary.
    If it ends with a '/' or '\', it is treated as a folder.
    """
    if _SETTINGS_ROOT is None:
        raise FileNotFoundError("Don't know a good config directory!")

    loc = _SETTINGS_ROOT / path

    if path.endswith(('\\', '/')) and not loc.suffix:
        folder = loc
    else:
        folder = loc.parent
    # Create folders if needed.
    folder.mkdir(parents=True, exist_ok=True)
    return loc


def fix_cur_directory() -> None:
    """Change directory to the location of the executable.

    Otherwise we can't find our files!
    """
    os.chdir(os.path.abspath(os.path.dirname(sys.argv[0])))


def _run_bg_daemon(*args) -> None:
    """Helper to make loadScreen not need to import bg_daemon.

    Instead we can redirect the import through here, which is a module
    both processes need to import. Then the main process doesn't need
    to import bg_daemon, and the daemon doesn't need to import loadScreen.
    """
    import bg_daemon
    bg_daemon.run_background(*args)


class CONN_TYPES(Enum):
    """Possible connections when joining things together.

    Used for things like catwalks, and bottomless pit sides.
    """
    none = 0
    side = 1  # Points E
    straight = 2  # Points E-W
    corner = 3  # Points N-W
    triple = 4  # Points N-S-W
    all = 5  # Points N-S-E-W

N = "0 90 0"
S = "0 270 0"
E = "0 0 0"
W = "0 180 0"
# Lookup values for joining things together.
CONN_LOOKUP = {
    #N  S  E  W : (Type, Rotation)
    (1, 0, 0, 0): (CONN_TYPES.side, N),
    (0, 1, 0, 0): (CONN_TYPES.side, S),
    (0, 0, 1, 0): (CONN_TYPES.side, E),
    (0, 0, 0, 1): (CONN_TYPES.side, W),

    (1, 1, 0, 0): (CONN_TYPES.straight, S),
    (0, 0, 1, 1): (CONN_TYPES.straight, E),

    (0, 1, 0, 1): (CONN_TYPES.corner, N),
    (1, 0, 1, 0): (CONN_TYPES.corner, S),
    (1, 0, 0, 1): (CONN_TYPES.corner, E),
    (0, 1, 1, 0): (CONN_TYPES.corner, W),

    (0, 1, 1, 1): (CONN_TYPES.triple, N),
    (1, 0, 1, 1): (CONN_TYPES.triple, S),
    (1, 1, 0, 1): (CONN_TYPES.triple, E),
    (1, 1, 1, 0): (CONN_TYPES.triple, W),

    (1, 1, 1, 1): (CONN_TYPES.all, E),

    (0, 0, 0, 0): (CONN_TYPES.none, E),
}

del N, S, E, W

RetT = TypeVar('RetT')
FuncT = TypeVar('FuncT', bound=Callable)
EnumT = TypeVar('EnumT', bound=Enum)
EnumTypeT = TypeVar('EnumTypeT', bound=Type[Enum])


def freeze_enum_props(cls: EnumTypeT) -> EnumTypeT:
    """Make a enum with property getters more efficent.

    Call the getter on each member, and then replace it with a dict lookup.
    """
    ns = vars(cls)
    for name, value in list(ns.items()):
        if not isinstance(value, property) or value.fset is not None or value.fdel is not None:
            continue
        data = {}
        data_exc = {}

        exc: Exception
        for enum in cls:
            try:
                res = value.fget(enum)
            except Exception as exc:
                # The getter raised an exception, so we want to replicate
                # that. So grab the traceback, and go back one frame to exclude
                # ourselves from that. Then we can reraise making it look like
                # it came from the original getter.
                data_exc[enum] = (exc, exc.__traceback__.tb_next)
                exc.__traceback__ = None
            else:
                data[enum] = res
        if data_exc:
            func = _exc_freeze(data, data_exc)
        else:  # If we don't raise, we can use the C-func
            func = data.get
        setattr(cls, name, property(fget=func, doc=value.__doc__))
    return cls


def _exc_freeze(
    data: Mapping[EnumT, RetT],
    data_exc: Mapping[EnumT, tuple[BaseException, TracebackType]],
) -> Callable[[EnumT], RetT]:
    """If the property raises exceptions, we need to reraise them."""
    def getter(value: EnumT) -> RetT:
        """Return the value, or re-raise the original exception."""
        try:
            return data[value]
        except KeyError:
            exc, tb = data_exc[value]
            raise exc.with_traceback(tb) from None
    return getter


class FuncLookup(Generic[FuncT], Mapping[str, Callable[..., FuncT]]):
    """A dict for holding callback functions.

    Functions are added by using this as a decorator. Positional arguments
    are aliases, keyword arguments will set attributes on the functions.
    If casefold is True, this will casefold keys to be case-insensitive.
    Additionally overwriting names is not allowed.
    Iteration yields all functions.
    """
    def __init__(
        self,
        name: str,
        *,
        casefold: bool=True,
        attrs: Iterable[str]=(),
    ) -> None:
        self.casefold = casefold
        self.__name__ = name
        self._registry: dict[str, FuncT] = {}
        self.allowed_attrs = set(attrs)

    def __call__(self, *names: str, **kwargs) -> Callable[[FuncT], FuncT]:
        """Add a function to the dict."""
        if not names:
            raise TypeError('No names passed!')

        bad_keywords = kwargs.keys() - self.allowed_attrs
        if bad_keywords:
            raise TypeError('Invalid keywords: ' + ', '.join(bad_keywords))

        def callback(func: FuncT) -> FuncT:
            """Decorator to do the work of adding the function."""
            # Set the name to <dict['name']>
            func.__name__ = '<{}[{!r}]>'.format(self.__name__, names[0])
            for name, value in kwargs.items():
                setattr(func, name, value)
            self.__setitem__(names, func)
            return func

        return callback

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, FuncLookup):
            return self._registry == other._registry
        try:
            conv = dict(other.items())
        except (AttributeError, TypeError):
            return NotImplemented
        return self._registry == conv

    def __iter__(self) -> Iterator[FuncT]:
        """Yield all the functions."""
        return iter(self.values())

    def keys(self) -> KeysView[str]:
        """Yield all the valid IDs."""
        return self._registry.keys()

    def values(self) -> ValuesView[FuncT]:
        """Yield all the functions."""
        return self._registry.values()

    def items(self) -> ItemsView[str, FuncT]:
        """Return pairs of (ID, func)."""
        return self._registry.items()

    def __len__(self) -> int:
        return len(set(self._registry.values()))

    def __getitem__(self, names: Union[str, tuple[str]]) -> FuncT:
        if isinstance(names, str):
            names = names,

        for name in names:
            if self.casefold:
                name = name.casefold()
            try:
                return self._registry[name]
            except KeyError:
                pass
        else:
            raise KeyError('No function with names {}!'.format(
                ', '.join(names),
            ))

    def __setitem__(
        self,
        names: Union[str, tuple[str, ...]],
        func: FuncT,
    ) -> None:
        if isinstance(names, str):
            names = names,

        for name in names:
            if self.casefold:
                name = name.casefold()
            if name in self._registry:
                raise ValueError('Overwrote {!r}!'.format(name))
            self._registry[name] = func

    def __delitem__(self, name: str) -> None:
        if not isinstance(name, str):
            raise KeyError(name)
        if self.casefold:
            name = name.casefold()
        del self._registry[name]

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        if self.casefold:
            name = name.casefold()
        return name in self._registry

    def functions(self) -> set[FuncT]:
        """Return the set of functions in this mapping."""
        return set(self._registry.values())

    def clear(self) -> None:
        """Delete all functions."""
        self._registry.clear()


class PackagePath:
    """Represents a file located inside a specific package.

    This can be either resolved later into a file object.
    The string form is "package:path/to/file.ext", with <special> package names
    reserved for app-specific usages (internal or generated paths)
    """
    __slots__ = ['package', 'path']
    def __init__(self, pack_id: str, path: str) -> None:
        self.package = pack_id.casefold()
        self.path = path.replace('\\', '/')

    @classmethod
    def parse(cls, uri: str | PackagePath, def_package: str) -> PackagePath:
        """Parse a string into a path. If a package isn't provided, the default is used."""
        if isinstance(uri, PackagePath):
            return uri
        if ':' in uri:
            return cls(*uri.split(':', 1))
        else:
            return cls(def_package, uri)

    def __str__(self) -> str:
        return f'{self.package}:{self.path}'

    def __repr__(self) -> str:
        return f'PackagePath({self.package!r}, {self.path!r})'

    def __hash__(self) -> int:
        return hash((self.package, self.path))

    def __eq__(self, other) -> bool:
        if isinstance(other, str):
            other = self.parse(other, self.package)
        elif not isinstance(other, PackagePath):
            return NotImplemented
        return self.package == other.package and self.path == other.path

    def in_folder(self, folder: str) -> PackagePath:
        """Return the package, but inside this subfolder."""
        return PackagePath(self.package, f'{folder}/{self.path}')

    def child(self, child: str) -> PackagePath:
        """Return a child file of this package."""
        return PackagePath(self.package, f'{self.path}/{child}')


def get_indent(line: str) -> str:
    """Return the whitespace which this line starts with.

    """
    white = []
    for char in line:
        if char in ' \t':
            white.append(char)
        else:
            return ''.join(white)
    return ''


def iter_grid(
    max_x: int,
    max_y: int,
    min_x: int=0,
    min_y: int=0,
    stride: int=1,
) -> Iterator[tuple[int, int]]:
    """Loop over a rectangular grid area."""
    for x in range(min_x, max_x, stride):
        for y in range(min_y, max_y, stride):
            yield x, y


DISABLE_ADJUST = False


def adjust_inside_screen(
    x: int,
    y: int,
    win,
    horiz_bound: int=14,
    vert_bound: int=45,
) -> tuple[int, int]:
    """Adjust a window position to ensure it fits inside the screen.

    The new value is returned.
    If utils.DISABLE_ADJUST is set to True, this is disabled.
    """
    if DISABLE_ADJUST:  # Allow disabling this adjustment
        return x, y     # for multi-window setups
    max_x = win.winfo_screenwidth() - win.winfo_width() - horiz_bound
    max_y = win.winfo_screenheight() - win.winfo_height() - vert_bound

    if x < horiz_bound:
        x = horiz_bound
    elif x > max_x:
        x = max_x

    if y < vert_bound:
        y = vert_bound
    elif y > max_y:
        y = max_y
    return x, y


def center_win(window, parent=None) -> None:
    """Center a subwindow to be inside a parent window."""
    if parent is None:
        parent = window.nametowidget(window.winfo_parent())

    x = parent.winfo_rootx() + (parent.winfo_width()-window.winfo_width())//2
    y = parent.winfo_rooty() + (parent.winfo_height()-window.winfo_height())//2

    x, y = adjust_inside_screen(x, y, window)

    window.geometry('+' + str(x) + '+' + str(y))


def _append_bothsides(deq: deque) -> Generator[None, Any, None]:
    """Alternately add to each side of a deque."""
    while True:
        deq.append((yield))
        deq.appendleft((yield))


def fit(dist: SupportsInt, obj: Sequence[int]) -> list[int]:
    """Figure out the smallest number of parts to stretch a distance.

    The list should be a series of sizes, from largest to smallest.
    """
    # If dist is a float the outputs will become floats as well
    # so ensure it's an int.
    dist = int(dist)
    if dist <= 0:
        return []
    orig_dist = dist
    smallest = obj[-1]
    items: deque[int] = deque()

    # We use this so the small sections appear on both sides of the area.
    adder = _append_bothsides(items)
    next(adder)
    while dist >= smallest:
        for item in obj:
            if item <= dist:
                adder.send(item)
                dist -= item
                break
        else:
            raise ValueError(f'No section for dist of {dist}!')
    if dist > 0:
        adder.send(dist)

    assert sum(items) == orig_dist
    return list(items)  # Dump the deque


ValueT = TypeVar('ValueT')


def group_runs(iterable: Iterable[ValueT]) -> Iterator[tuple[ValueT, int, int]]:
    """Group runs of equal values.

    Yields (value, min_ind, max_ind) tuples, where all of iterable[min:max+1]
    is equal to value.
    """
    it = iter(iterable)
    min_ind = max_ind = 0
    try:
        obj = next(it)
    except StopIteration:
        return
    for next_obj in it:
        if next_obj == obj:
            max_ind += 1
        else:
            yield obj, min_ind, max_ind
            obj = next_obj
            min_ind = max_ind = max_ind + 1
    yield obj, min_ind, max_ind


def restart_app() -> NoReturn:
    """Restart this python application.

    This will not return!
    """
    # sys.executable is the program which ran us - when frozen,
    # it'll our program.
    # We need to add the program to the arguments list, since python
    # strips that off.
    args = [sys.executable] + sys.argv
    logging.root.info('Restarting using "{}", with args {!r}'.format(
        sys.executable,
        args,
    ))
    logging.shutdown()
    os.execv(sys.executable, args)


def quit_app(status=0) -> NoReturn:
    """Quit the application."""
    sys.exit(status)


def set_readonly(file: Union[bytes, str]) -> None:
    """Make the given file read-only."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it read-only
    os.chmod(
        file,
        flags & ~
        stat.S_IWUSR & ~
        stat.S_IWGRP & ~
        stat.S_IWOTH
    )


def unset_readonly(file: os.PathLike) -> None:
    """Set the writeable flag on a file."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it writeable
    os.chmod(
        file,
        flags |
        stat.S_IWUSR |
        stat.S_IWGRP |
        stat.S_IWOTH
    )


def merge_tree(
    src: str,
    dst: str,
    copy_function=shutil.copy2,
) -> None:
    """Recursively copy a directory tree to a destination, which may exist.

    This is a modified version of shutil.copytree(), with the difference that
    if the directory exists new files will overwrite existing ones.

    If exception(s) occur, a shutil.Error is raised with a list of reasons.

    The optional copy_function argument is a callable that will be used
    to copy each file. It will be called with the source path and the
    destination path as arguments. By default, shutil.copy2() is used, but any
    function that supports the same signature (like shutil.copy()) can be used.
    """
    names = os.listdir(src)

    os.makedirs(dst, exist_ok=True)
    errors: list[tuple[str, str, str]] = []
    for name in names:
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if os.path.islink(srcname):
                # Let the copy occur. copy2 will raise an error.
                if os.path.isdir(srcname):
                    merge_tree(srcname, dstname, copy_function)
                else:
                    copy_function(srcname, dstname)
            elif os.path.isdir(srcname):
                merge_tree(srcname, dstname, copy_function)
            else:
                # Will raise a SpecialFileError for unsupported file types
                copy_function(srcname, dstname)
        # catch the Error from the recursive copytree so that we can
        # continue with other files
        except shutil.Error as err:
            errors.extend(err.args[0])
        except OSError as why:
            errors.append((srcname, dstname, str(why)))
    try:
        shutil.copystat(src, dst)
    except OSError as why:
        # Copying file access times may fail on Windows
        if getattr(why, 'winerror', None) is None:
            errors.append((src, dst, str(why)))
    if errors:
        raise shutil.Error(errors)


def setup_localisations(logger: logging.Logger) -> None:
    """Setup gettext localisations."""
    from srctools.property_parser import PROP_FLAGS_DEFAULT
    import gettext
    import locale

    # Get the 'en_US' style language code
    lang_code = locale.getdefaultlocale()[0]

    # Allow overriding through command line.
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.casefold().startswith('lang='):
                lang_code = arg[5:]
                break

    # Expands single code to parent categories.
    expanded_langs = gettext._expand_lang(lang_code)

    logger.info('Language: {!r}', lang_code)
    logger.debug('Language codes: {!r}', expanded_langs)

    # Add these to Property's default flags, so config files can also
    # be localised.
    for lang in expanded_langs:
        PROP_FLAGS_DEFAULT['lang_' + lang] = True

    lang_folder = install_path('i18n')

    trans: gettext.NullTranslations

    for lang in expanded_langs:
        try:
            file = open(lang_folder / (lang + '.mo').format(lang), 'rb')
        except FileNotFoundError:
            continue
        with file:
            trans = gettext.GNUTranslations(file)
            break
    else:
        # To help identify missing translations, replace everything with
        # something noticeable.
        if lang_code == 'dummy':
            class DummyTranslations(gettext.NullTranslations):
                """Dummy form for identifying missing translation entries."""
                def gettext(self, message: str) -> str:
                    """Generate placeholder of the right size."""
                    # We don't want to leave {arr} intact.
                    return ''.join([
                        '#' if s.isalnum() or s in '{}' else s
                        for s in message
                    ])

                def ngettext(self, msgid1: str, msgid2: str, n: int) -> str:
                    """Generate placeholder of the right size for plurals."""
                    return self.gettext(msgid1 if n == 1 else msgid2)

                lgettext = gettext
                lngettext = ngettext

            trans = DummyTranslations()
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
        else:
            if 'en' not in expanded_langs:
                logger.warning(
                    "Can't find translation for codes: {!r}!",
                    expanded_langs,
                )
            trans = gettext.NullTranslations()

    # Add these functions to builtins, plus _=gettext
    trans.install(['gettext', 'ngettext'])

    # Some lang-specific overrides..

    if trans.gettext('__LANG_USE_SANS_SERIF__') == 'YES':
        # For Japanese/Chinese, we want a 'sans-serif' / gothic font
        # style.
        try:
            from tkinter import font
        except ImportError:
            return
        font_names = [
            'TkDefaultFont',
            'TkHeadingFont',
            'TkTooltipFont',
            'TkMenuFont',
            'TkTextFont',
            'TkCaptionFont',
            'TkSmallCaptionFont',
            'TkIconFont',
            # Note - not fixed-width...
        ]
        for font_name in font_names:
            font.nametofont(font_name).configure(family='sans-serif')
