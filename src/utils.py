"""Various functions shared among the compiler and application."""
from __future__ import annotations
from typing import (
    ClassVar, Final, NewType, TYPE_CHECKING, Any, Awaitable, Callable, Generator, Generic,
    ItemsView, Iterable, Iterator, KeysView, Mapping, NoReturn, Optional, Sequence, SupportsInt,
    Tuple, Type, TypeVar, ValuesView,
)

from typing_extensions import ParamSpec, TypeVarTuple, Unpack
from collections import deque
from enum import Enum
from pathlib import Path
import copyreg
import logging
import os
import shutil
import stat
import sys
import types
import zipfile

from srctools.math import AnyVec, Angle, FrozenMatrix, FrozenVec, Vec
import attrs
import trio


__all__ = [
    'WIN', 'MAC', 'LINUX', 'STEAM_IDS', 'DEV_MODE', 'CODE_DEV_MODE', 'BITNESS',
    'get_git_version', 'install_path', 'bins_path', 'conf_location', 'fix_cur_directory',
    'run_bg_daemon', 'not_none', 'CONN_LOOKUP', 'CONN_TYPES', 'freeze_enum_props', 'FuncLookup',
    'PackagePath', 'Result', 'SliceKey', 'acompose', 'get_indent', 'iter_grid', 'check_cython',
    'check_shift', 'fit', 'group_runs', 'restart_app', 'quit_app', 'set_readonly',
    'unset_readonly', 'merge_tree', 'write_lang_pot',
]

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
copyreg.add_extension('srctools.math', '_mk_fvec', 243)
copyreg.add_extension('srctools.math', '_mk_fang', 244)
copyreg.add_extension('srctools.math', '_mk_fmat', 245)
copyreg.add_extension('srctools.keyvalues', 'Keyvalues', 246)


# Appropriate locations to store config options for each OS.
_SETTINGS_ROOT: Optional[Path]
if WIN:
    _SETTINGS_ROOT = Path(os.environ['APPDATA'])
elif MAC:
    _SETTINGS_ROOT = Path('~/Library/Preferences/').expanduser()
elif LINUX:
    _SETTINGS_ROOT = Path('~/.config').expanduser()
else:
    # Defer the error until used, so it goes in logs and whatnot.
    # Utils is early, so it'll get lost in stderr.
    _SETTINGS_ROOT = None

# We always go in a BEE2 subfolder
if _SETTINGS_ROOT is not None:
    _SETTINGS_ROOT /= 'BEEMOD2'

    # If testing, redirect to a subdirectory so the real configs aren't touched.
    if 'pytest' in sys.modules:
        _SETTINGS_ROOT /= 'testing'


def get_git_version(inst_path: Path | str) -> str:
    """Load the version from Git history."""
    import versioningit
    return versioningit.get_version(
        project_dir=inst_path,
        config={
            'vcs': {'method': 'git'},
            'default-version': '(dev)',
            'format': {
                # Ignore dirtyness, we generate the translation files every time.
                'distance': '{base_version}.dev+{rev}',
                'dirty': '{base_version}',
                'distance-dirty': '{base_version}.dev+{rev}',
            },
        },
    )

try:
    # This module is generated when the app is compiled.
    from _compiled_version import (  # type: ignore
        BEE_VERSION as BEE_VERSION,
        HA_VERSION as HA_VERSION,
    )
except ImportError:
    # We're running from src/, so data is in the folder above that.
    # Go up once from us to its containing folder, then to the parent.
    _INSTALL_ROOT = Path(__file__, '..', '..').resolve()
    _BINS_ROOT = _INSTALL_ROOT

    BEE_VERSION = get_git_version(_INSTALL_ROOT)
    HA_VERSION = get_git_version(_INSTALL_ROOT / 'hammeraddons')
    FROZEN = False
    DEV_MODE = True
else:
    FROZEN = True
    # This special attribute is set by PyInstaller to our folder.
    _BINS_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined] # noqa
    # We are in a bin/ subfolder.
    _INSTALL_ROOT = _BINS_ROOT.parent
    # Check if this was produced by above
    DEV_MODE = '#' in BEE_VERSION

# Regular dev mode is enable-able by users, this is only for people editing code.
CODE_DEV_MODE = DEV_MODE
BITNESS = '64' if sys.maxsize > (2 << 48) else '32'
BEE_VERSION += f' {BITNESS}-bit'


def install_path(path: str) -> Path:
    """Return the path to a file inside our installation folder."""
    return _INSTALL_ROOT / path


def bins_path(path: str) -> Path:
    """Return the path to a file inside our binaries folder.

    This is the same as install_path() when unfrozen, but different when frozen.
    """
    return _BINS_ROOT / path


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

# Location of a message shown when user errors occur.
COMPILE_USER_ERROR_PAGE = conf_location('error.html')


def fix_cur_directory() -> None:
    """Change directory to the location of the executable.

    Otherwise, we can't find our files!
    """
    os.chdir(os.path.abspath(os.path.dirname(sys.argv[0])))


if TYPE_CHECKING:
    from bg_daemon import run_background as run_bg_daemon
else:
    def run_bg_daemon(*args: Any) -> None:
        """Helper to make loadScreen not need to import bg_daemon.

        Instead, we can redirect the import through here, which is a module
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

N = Angle(yaw=90)
S = Angle(yaw=270)
E = Angle(yaw=0)
W = Angle(yaw=180)
# Lookup values for joining things together.
CONN_LOOKUP: Mapping[Tuple[int, int, int, int], Tuple[CONN_TYPES, Angle]] = {
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

T = TypeVar('T')
RetT = TypeVar('RetT')
LookupT = TypeVar('LookupT')
EnumT = TypeVar('EnumT', bound=Enum)


def freeze_enum_props(cls: Type[EnumT]) -> Type[EnumT]:
    """Make an enum with property getters more efficent.

    Call the getter on each member, and then replace it with a dict lookup.
    """
    for name, value in list(vars(cls).items()):
        # Ignore non-properties, those with setters or deleters.
        if (
            not isinstance(value, property) or value.fget is None
            or value.fset is not None or value.fdel is not None
        ):
            continue
        data = {}
        data_exc: dict[EnumT, tuple[Type[BaseException], tuple[object, ...]]] = {}

        enum: EnumT
        for enum in cls:
            # Put the class into the globals, so it can refer to itself.
            try:
                value.fget.__globals__[cls.__name__] = cls
            except AttributeError:
                pass
            try:
                res = value.fget(enum)
            except (ValueError, TypeError) as exc:
                # These exceptions can be recreated later by passing *args. That's not possible
                # for arbitrary exceptions, ensure we only do it for known ones.
                data_exc[enum] = type(exc), exc.args
            except Exception as exc:
                # Something else, need to validate it can be recreated.
                raise ValueError(f'{cls}.{name} raised exception! Add this to the above clause!') from exc
            else:
                data[enum] = res
        if data_exc:
            func = _exc_freeze(data, data_exc)
        else:  # If we don't raise, we can use this C function directly.
            func = data.get
        setattr(cls, name, property(fget=func, doc=value.__doc__))
    return cls


def _exc_freeze(
    data: Mapping[EnumT, RetT],
    data_exc: Mapping[EnumT, tuple[Type[BaseException], tuple[object, ...]]],
) -> Callable[[EnumT], RetT]:
    """If the property raises exceptions, we need to reraise them."""
    def getter(value: EnumT) -> RetT:
        """Return the value, or re-raise the original exception."""
        try:
            return data[value]
        except KeyError:
            exc_type, args = data_exc[value]
            raise exc_type(*args) from None
    return getter


# Patch zipfile to fix an issue with it not being threadsafe.
# See https://bugs.python.org/issue42369
if sys.version_info < (3, 9) and hasattr(zipfile, '_SharedFile'):
    # noinspection PyProtectedMember
    class _SharedZipFile(zipfile._SharedFile):  # type: ignore[name-defined]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            # tell() reads the actual file position, but that may have been
            # changed by another thread - instead keep our own private value.
            self.tell = lambda: self._pos

    zipfile._SharedFile = _SharedZipFile


class FuncLookup(Generic[LookupT], Mapping[str, LookupT]):
    """A dict for holding callback functions.

    Functions are added by using this as a decorator. Positional arguments
    are aliases, keyword arguments will set attributes on the functions.
    If casefold is True, this will casefold keys to be case-insensitive.
    Additionally, overwriting names is not allowed.
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
        self._registry: dict[str, LookupT] = {}
        self.allowed_attrs = set(attrs)

    def __call__(self, *names: str, **kwargs: Any) -> Callable[[LookupT], LookupT]:
        """Add a function to the dict."""
        if not names:
            raise TypeError('No names passed!')

        bad_keywords = kwargs.keys() - self.allowed_attrs
        if bad_keywords:
            raise TypeError(
                f'Invalid keywords: {", ".join(bad_keywords)}. '
                f'Allowed: {", ".join(self.allowed_attrs)}'
            )

        def callback(func: LookupT) -> LookupT:
            """Decorator to do the work of adding the function."""
            # Set the name to <dict['name']>
            if isinstance(func, types.FunctionType):
                func.__name__ = f'<{self.__name__}[{names[0]!r}]>'
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

    def __iter__(self) -> Iterator[str]:
        """Yield all the IDs."""
        return iter(self._registry)

    def keys(self) -> KeysView[str]:
        """Yield all the valid IDs."""
        return self._registry.keys()

    def values(self) -> ValuesView[LookupT]:
        """Yield all the functions."""
        return self._registry.values()

    def items(self) -> ItemsView[str, LookupT]:
        """Return pairs of (ID, func)."""
        return self._registry.items()

    def __len__(self) -> int:
        return len(set(self._registry.values()))

    def __getitem__(self, names: str | tuple[str, ...]) -> LookupT:
        if isinstance(names, str):
            names = (names, )

        for name in names:
            if self.casefold:
                name = name.casefold()
            try:
                return self._registry[name]
            except KeyError:
                pass
        else:
            raise KeyError(f'No function with names {", ".join(names)}!')

    def __setitem__(
        self,
        names: str | tuple[str, ...],
        func: LookupT,
    ) -> None:
        if isinstance(names, str):
            names = (names, )

        for name in names:
            if self.casefold:
                name = name.casefold()
            if name in self._registry:
                raise ValueError(f'Overwrote {name!r}!')
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

    def functions(self) -> set[LookupT]:
        """Return the set of functions in this mapping."""
        return set(self._registry.values())

    def clear(self) -> None:
        """Delete all functions."""
        self._registry.clear()


# An object ID, which has been made uppercase. This excludes <> and [] names.
ObjectID = NewType("ObjectID", str)
# Special ID includes <>/[] names, and ''.
SpecialID = NewType("SpecialID", str)

ID_NONE: Final = SpecialID('<NONE>')
ID_EMPTY: Final = SpecialID('')


def parse_obj_id(value: str) -> ObjectID:
    """Parse an object ID."""
    if not value or value.startswith(('(', '<', '[')) or value.endswith((')', '>', ']')):
        raise ValueError(f'Invalid object ID "{value}". IDs may not start/end with brackets.')
    return ObjectID(value.casefold().upper())


def parse_obj_special_id(value: str) -> ObjectID | SpecialID:
    """Parse an object ID or a special name."""
    if not value or value.startswith(('(', '<', '[')) or value.endswith((')', '>', ']')):
        return SpecialID(value.casefold())
    else:
        return ObjectID(value.casefold().upper())


class PackagePath:
    """Represents a file located inside a specific package.

    This can be either resolved later into a file object.
    The string form is "package:path/to/file.ext", with <special> package names
    reserved for app-specific usages (internal or generated paths)
    """
    __slots__ = ['package', 'path']
    package: Final[str]
    path: Final[str]
    def __init__(self, pack_id: str, path: str) -> None:
        self.package = pack_id.casefold()
        self.path = path.replace('\\', '/').lstrip("/")

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

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            other = self.parse(other, self.package)
        elif not isinstance(other, PackagePath):
            return NotImplemented
        return self.package == other.package and self.path == other.path

    def in_folder(self, folder: str) -> PackagePath:
        """Return the package, but inside this subfolder."""
        folder = folder.rstrip('\\/')
        return PackagePath(self.package, f'{folder}/{self.path}')

    def child(self, child: str) -> PackagePath:
        """Return a child file of this package."""
        child = child.rstrip('\\/')
        return PackagePath(self.package, f'{self.path.rstrip("/")}/{child}')


@attrs.frozen(eq=False, hash=False, init=False)
class SliceKey:
    """A hashable key used to identify 2-dimensional plane slices."""
    # Reuse the same instance for the vector, and precompute the hash.
    _norm_cache: ClassVar[Mapping[FrozenVec, Tuple[FrozenVec, int]]] = {
        FrozenVec.N: (FrozenVec.N, hash(b'n')),
        FrozenVec.S: (FrozenVec.S, hash(b's')),
        FrozenVec.E: (FrozenVec.E, hash(b'e')),
        FrozenVec.W: (FrozenVec.W, hash(b'w')),
        FrozenVec.T: (FrozenVec.T, hash(b't')),
        FrozenVec.B: (FrozenVec.B, hash(b'b')),
    }
    # The orientation points Z = normal, X = sideways, Y = upward.
    _orients: ClassVar[Mapping[FrozenVec, FrozenMatrix]] = {
        FrozenVec.N: FrozenMatrix.from_basis(x=Vec(1, 0, 0), y=Vec(0, 0, 1)),
        FrozenVec.S: FrozenMatrix.from_basis(x=Vec(-1, 0, 0), y=Vec(0, 0, 1)),
        FrozenVec.E: FrozenMatrix.from_basis(x=Vec(0, -1, 0), y=Vec(0, 0, 1)),
        FrozenVec.W: FrozenMatrix.from_basis(x=Vec(0, 1, 0), y=Vec(0, 0, 1)),
        FrozenVec.T: FrozenMatrix.from_basis(x=Vec(1, 0, 0), y=Vec(0, 1, 0)),
        FrozenVec.B: FrozenMatrix.from_basis(x=Vec(1, 0, 0), y=Vec(0, -1, 0)),
    }
    _inv_orients: ClassVar[Mapping[FrozenVec, FrozenMatrix]] = {
        norm: orient.transpose()
        for norm, orient in _orients.items()
    }

    normal: FrozenVec
    distance: float
    _hash: int = attrs.field(repr=False)

    def __init__(self, normal: AnyVec, dist: AnyVec | float) -> None:
        try:
            norm, norm_hash = self._norm_cache[FrozenVec(normal)]
        except KeyError:
            raise ValueError(f'{normal!r} is not an on-axis normal!')
        if not isinstance(dist, (int, float)):
            dist = norm.dot(dist)

        self.__attrs_init__(
            norm,
            dist,
            hash(dist) ^ norm_hash,
        )

    @property
    def orient(self) -> FrozenMatrix:
        """Return a matrix with the forward direction facing along the slice."""
        return self._orients[self.normal]

    def left(self) -> Vec:
        """Return the +Y axis for this slice orientation, where +X is along the normal."""
        return self._orients[self.normal].left()

    def up(self) -> Vec:
        """Return the +Z axis for this slice orientation, where +X is along the normal."""
        return self._orients[self.normal].up()

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SliceKey):
            return self.normal is other.normal and self.distance == other.distance
        else:
            return NotImplemented

    def __ne__(self, other: object) -> bool:
        if isinstance(other, SliceKey):
            return self.normal is not other.normal or self.distance != other.distance
        else:
            return NotImplemented

    def plane_to_world(self, x: float, y: float, z: float = 0.0) -> Vec:
        """Return a position relative to this plane."""
        orient = self._orients[self.normal]
        return Vec(x, y, z) @ orient + self.normal * self.distance

    def world_to_plane(self, pos: AnyVec) -> Vec:
        """Take a world position and return the location relative to this plane."""
        orient = self._inv_orients[self.normal]
        return (Vec(pos) - self.normal * self.distance) @ orient


ResultT = TypeVar('ResultT')
SyncResultT = TypeVar('SyncResultT')
PosArgsT = TypeVarTuple('PosArgsT')
ParamsT = ParamSpec('ParamsT')
_NO_RESULT: Any = object()


class Result(Generic[ResultT]):
    """Encasulates an async computation submitted to a nursery.

    Once the nursery has closed, the result is accessible.
    """
    def __init__(
        self,
        nursery: trio.Nursery,
        func: Callable[[Unpack[PosArgsT]], Awaitable[ResultT]],
        /, *args: Unpack[PosArgsT],
        name: object = None,
    ) -> None:
        self._nursery: Optional[trio.Nursery] = nursery
        self._result: ResultT = _NO_RESULT
        if not name:
            name = func
        nursery.start_soon(self._task, func, args, name=name)

    @classmethod
    def sync(
        cls,
        nursery: trio.Nursery,
        func: Callable[[Unpack[PosArgsT]], SyncResultT],
        /, *args: Unpack[PosArgsT],
        abandon_on_cancel: bool = False,
        limiter: trio.CapacityLimiter | None = None,
    ) -> Result[SyncResultT]:
        """Wrap a sync task, using to_thread.run_sync()."""
        async def task() -> SyncResultT:
            """Run in a thread."""
            return await trio.to_thread.run_sync(
                func, *args,
                abandon_on_cancel=abandon_on_cancel,
                limiter=limiter,
            )

        return Result(nursery, task, name=func)

    async def _task(
        self,
        func: Callable[[Unpack[PosArgsT]], Awaitable[ResultT]],
        args: Tuple[Unpack[PosArgsT]],
    ) -> None:
        """The task that is run."""
        self._result = await func(*args)

    def __call__(self) -> ResultT:
        """Fetch the result. The nursery must be closed."""
        if self._nursery is not None and 'exited' not in repr(self._nursery.cancel_scope):
            raise ValueError(f'Result cannot be fetched before nursery has closed! ({self._nursery.cancel_scope!r})')
        self._nursery = None  # The check passed, no need to keep this alive.
        return self._result


def acompose(
    func: Callable[ParamsT, Awaitable[ResultT]],
    on_completed: Callable[[ResultT], object],
) -> Callable[ParamsT, Awaitable[None]]:
    """Compose an awaitable function with a sync function that recieves the result."""
    async def task(*args: ParamsT.args, **kwargs: ParamsT.kwargs) -> None:
        """Run the func, then call on_completed on the result."""
        res = await func(*args, **kwargs)
        on_completed(res)
    return task


def not_none(value: T | None) -> T:
    """Assert that the value is not None, inline."""
    if value is None:
        raise AssertionError('Value was none!')
    return value


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


def check_cython(report: Callable[[str], None] = print) -> None:
    """Check if srctools has its Cython accellerators installed correctly."""
    from srctools import math, tokenizer
    if math.Cy_Vec is math.Py_Vec:
        report('Cythonised vector lib is not installed, expect slow math.')
    if tokenizer.Cy_Tokenizer is tokenizer.Py_Tokenizer:
        report('Cythonised tokeniser is not installed, expect slow parsing.')

    vtf = sys.modules.get('srctools.vtf', None)  # Don't import if not already.
    # noinspection PyProtectedMember, PyUnresolvedReferences
    if vtf is not None and vtf._cy_format_funcs is vtf._py_format_funcs:
        report('Cythonised VTF functions is not installed, no DXT export!')


if WIN:
    def check_shift() -> bool:
        """Check if Shift is currently held."""
        import ctypes

        # https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate
        GetAsyncKeyState = ctypes.windll.User32.GetAsyncKeyState
        GetAsyncKeyState.restype = ctypes.c_short
        GetAsyncKeyState.argtypes = [ctypes.c_int]
        VK_SHIFT = 0x10
        # Most significant bit set if currently held.
        return int(GetAsyncKeyState(VK_SHIFT)) & 0b1000_0000_0000_0000 != 0
else:
    def check_shift() -> bool:
        """Check if Shift is currently held."""
        return False
    print('Need implementation of utils.check_shift()!')


def _append_bothsides(deq: deque[T]) -> Generator[None, T, None]:
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
    logging.root.info(f'Restarting using "{sys.executable}", with args {args!r}')
    logging.shutdown()
    os.execv(sys.executable, args)


def quit_app(status: int=0) -> NoReturn:
    """Quit the application."""
    sys.exit(status)


_flag_writeable = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def set_readonly(file: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
    """Make the given file read-only."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it read-only
    os.chmod(file, flags & ~_flag_writeable)


def unset_readonly(file: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
    """Set the writeable flag on a file."""
    # Get the old flags
    flags = os.stat(file).st_mode
    # Make it writeable
    os.chmod(file, flags | _flag_writeable)


def merge_tree(
    src: str,
    dst: str,
    copy_function: Callable[[str, str], None]=shutil.copy2,
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


def write_lang_pot(path: Path, new_contents: bytes) -> bool:
    """Write out a new POT translations template file.

    This first reads the existing file, so we can avoid writing if only the header (dates/version)
    gets changed.

    It's in this module to allow it to be imported by BEE2.spec.
    """
    new_lines = new_contents.splitlines()
    force_write = False

    try:
        with path.open('rb') as f:
            old_lines = f.read().splitlines()
    except FileNotFoundError:
        force_write = True
    else:
        for lines in [old_lines, new_lines]:
            # Look for the first line with 'msgid "<something>"'.
            for i, line in enumerate(lines):
                if line.startswith(b'msgid') and b'""' not in line:
                    # Found. Ignore comments directly before also, since that's the location etc.
                    while i > 0 and lines[i-1].startswith(b'#'):
                        i -= 1
                    del lines[:i]
                    break
            else:  # Not present? Force it to be written out.
                force_write = True

    if force_write or old_lines != new_lines:
        with path.open('wb') as f:
            f.write(new_contents)
        return True
    return False
