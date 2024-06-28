"""Various functions shared among the compiler and application."""
from __future__ import annotations

from typing import (
    Final, NewType, Protocol, TYPE_CHECKING, Any, NoReturn, SupportsInt, Literal, TypeGuard,
    overload,
)
from typing_extensions import deprecated
from collections.abc import (
    Awaitable, Callable, Collection, Generator, Iterable, Iterator, Mapping, Sequence,
)
from collections import deque
from enum import Enum
from pathlib import Path
import functools
import itertools
import copyreg
import logging
import os
import shutil
import stat
import sys
import zipfile
import math

from srctools import Angle, conv_bool
import trio
import trio_util
import aioresult


__all__ = [
    'WIN', 'MAC', 'LINUX', 'STEAM_IDS', 'DEV_MODE', 'CODE_DEV_MODE', 'BITNESS',
    'get_git_version', 'install_path', 'bins_path', 'conf_location', 'fix_cur_directory',
    'run_bg_daemon', 'not_none', 'CONN_LOOKUP', 'CONN_TYPES', 'freeze_enum_props',
    'PackagePath', 'sync_result', 'acompose', 'get_indent', 'iter_grid', 'check_cython',
    'ObjectID', 'SpecialID', 'BlankID', 'ID_EMPTY', 'ID_NONE', 'ID_RANDOM',
    'obj_id', 'special_id', 'obj_id_optional', 'special_id_optional',
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


# Add very common types into the pickle registry, so they can be more directly
# loaded.
# IDs 240 - 255 are available for application uses.
copyreg.add_extension('srctools.math', '_mk_vec', 240)
copyreg.add_extension('srctools.math', '_mk_ang', 241)
copyreg.add_extension('srctools.math', '_mk_mat', 242)
copyreg.add_extension('srctools.math', '_mk_fvec', 243)
copyreg.add_extension('srctools.math', '_mk_fang', 244)
copyreg.add_extension('srctools.math', '_mk_fmat', 245)
copyreg.add_extension('srctools.keyvalues', 'Keyvalues', 246)
copyreg.add_extension('transtoken', 'TransToken', 247)
copyreg.add_extension('transtoken', 'PluralTransToken', 248)
copyreg.add_extension('transtoken', 'JoinTransToken', 249)
copyreg.add_extension('transtoken', 'ListTransToken', 250)
copyreg.add_extension('pathlib', 'Path', 251)
copyreg.add_extension('pathlib', 'PurePosixPath', 252)


# Appropriate locations to store config options for each OS.
_SETTINGS_ROOT: Path | None
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

# Whether we should use WxWidgets instead of TK.
USE_WX = CODE_DEV_MODE and conv_bool(os.environ.get('BEE_USE_WX'))


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
CONN_LOOKUP: Mapping[tuple[int, int, int, int], tuple[CONN_TYPES, Angle]] = {
  #  N  S  E  W : (Type, Rotation)
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


class DecoratorProto(Protocol):
    """A decorator function which returns the callable unchanged."""
    def __call__[Func: Callable[..., object]](self, func: Func, /) -> Func:
        ...


def freeze_enum_props[EnumT: Enum](cls: type[EnumT]) -> type[EnumT]:
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
        data_exc: dict[EnumT, tuple[type[BaseException], tuple[object, ...]]] = {}

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


def _exc_freeze[EnumT: Enum, RetT](
    data: Mapping[EnumT, RetT],
    data_exc: Mapping[EnumT, tuple[type[BaseException], tuple[object, ...]]],
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


# Special ID includes <>/[] names.
SpecialID = NewType("SpecialID", str)
# An object ID, which has been made uppercase. This excludes <> and [] names.
ObjectID = NewType("ObjectID", SpecialID)
BlankID = Literal[""]

ID_NONE: Final[SpecialID] = SpecialID('<NONE>')
ID_RANDOM: Final[SpecialID] = SpecialID('<RANDOM>')
ID_EMPTY: BlankID = ''
# Prohibit a bunch of IDs that keyvalues/dmx/etc might use for other purposes.
PROHIBITED_IDS = {'ID', 'NAME', 'TYPE', 'VERSION'}


def _uppercase_casefold(value: str) -> str:
    """Casefold and uppercase."""
    casefolded = value.casefold().upper()
    if casefolded == value:
        return value
    else:
        return casefolded


@overload
@deprecated('Value is already an ObjectID | BlankID!')
def obj_id_optional(value: ObjectID | BlankID, kind: str = 'object') -> ObjectID | BlankID: ...
@overload
def obj_id_optional(value: str, kind: str = 'object') -> ObjectID | BlankID: ...
def obj_id_optional(value: str, kind: str = 'object') -> ObjectID | BlankID:
    """Parse an object ID, allowing through empty IDs."""
    if (
        value.startswith(('(', '<', '[', ']', '>', ')')) or
        value.endswith(('(', '<', '[', ']', '>', ')'))
    ):
        raise ValueError(f'Invalid {kind} ID "{value}". IDs may not start/end with brackets.')
    if ':' in value:
        raise ValueError(f'Invalid {kind} ID "{value}". IDs may not contain colons.')
    value = _uppercase_casefold(value)
    if value in PROHIBITED_IDS:
        raise ValueError(
            f'Invalid {kind} ID "{value}". '
            f'IDs cannot be any of the following: {", ".join(PROHIBITED_IDS)}'
        )
    return ObjectID(SpecialID(value))


@overload
@deprecated('Value is already an ObjectID!')
def obj_id(value: ObjectID, kind: str = 'object') -> ObjectID: ...
@overload
def obj_id(value: str, kind: str = 'object') -> ObjectID: ...
def obj_id(value: str, kind: str = 'object') -> ObjectID:
    """Parse an object ID."""
    result = obj_id_optional(value, kind)
    if result == "":
        raise ValueError(f'Invalid {kind} ID "{value}". IDs may not be blank.')
    return result


@overload
@deprecated('Value is already a SpecialID | BlankID!')
def special_id_optional(value: SpecialID | BlankID, kind: str = 'object') -> SpecialID | BlankID: ...
@overload
def special_id_optional(value: str, kind: str = 'object') -> SpecialID | BlankID: ...
def special_id_optional(value: str, kind: str = 'object') -> SpecialID | BlankID:
    """Parse an object ID or a <special> name, allowing empty IDs."""
    if value == "":
        return ""
    if value.startswith('<') and value.endswith('>'):
        # Prohibited IDs are fine here, since they're not bare.
        return SpecialID(_uppercase_casefold(value))
    # Ruled out valid combinations, any others are prohibited, it's just an ObjectID now.
    return obj_id_optional(value, kind)


@overload
@deprecated('Value is already a SpecialID!')
def special_id(value: SpecialID, kind: str = 'object') -> SpecialID: ...
@overload
def special_id(value: str, kind: str = 'object') -> SpecialID: ...
def special_id(value: str, kind: str = 'object') -> SpecialID:
    """Parse an object ID or a <special> name."""
    result = special_id_optional(value, kind)
    if result == "":
        raise ValueError(f'Invalid {kind} ID "{value}". IDs may not be blank.')
    return result


def not_special_id(some_id: SpecialID) -> TypeGuard[ObjectID]:
    """Check that an ID does not have brackets, meaning it is a regular ID."""
    return not some_id.startswith('<') and not some_id.endswith('>')


class PackagePath:
    """Represents a file located inside a specific package.

    This can be either resolved later into a file object.
    The string form is "package:path/to/file.ext", with <special> package names
    reserved for app-specific usages (internal or generated paths)
    """
    __slots__ = ['package', 'path']
    package: Final[SpecialID]
    path: Final[str]

    def __init__(self, pack_id: SpecialID, path: str) -> None:
        self.package = pack_id
        self.path = path.replace('\\', '/').lstrip("/")

    @classmethod
    def parse(cls, uri: str | PackagePath, def_package: SpecialID) -> PackagePath:
        """Parse a string into a path. If a package isn't provided, the default is used."""
        if isinstance(uri, PackagePath):
            return uri
        if ':' in uri:
            pack_str, path = uri.split(':', 1)
            return cls(special_id(pack_str), path)
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


def sync_result[*Args, SyncResultT](
    nursery: trio.Nursery,
    func: Callable[[*Args], SyncResultT],
    /, *args: *Args,
    abandon_on_cancel: bool = False,
    limiter: trio.CapacityLimiter | None = None,
) -> aioresult.ResultCapture[SyncResultT]:
    """Wrap a sync task, using to_thread.run_sync()."""
    async def task() -> SyncResultT:
        """Run in a thread."""
        return await trio.to_thread.run_sync(
            func, *args,
            abandon_on_cancel=abandon_on_cancel,
            limiter=limiter,
        )

    return aioresult.ResultCapture.start_soon(nursery, task)


def acompose[**ParamsT, ResultT](
    func: Callable[ParamsT, Awaitable[ResultT]],
    on_completed: Callable[[ResultT], object],
) -> Callable[ParamsT, Awaitable[None]]:
    """Compose an awaitable function with a sync function that recieves the result."""
    async def task(*args: ParamsT.args, **kwargs: ParamsT.kwargs) -> None:
        """Run the func, then call on_completed on the result."""
        res = await func(*args, **kwargs)
        on_completed(res)
    return task


async def run_as_task[*Args](
    func: Callable[[*Args], Awaitable[object]],
    *args: *Args,
) -> None:
    """Run the specified function inside a nursery.

    This ensures it gets detected by Trio's instrumentation as a subtask.
    """
    async with trio.open_nursery() as nursery:  # noqa: ASYNC112
        nursery.start_soon(func, *args)


def not_none[T](value: T | None) -> T:
    """Assert that the value is not None, inline."""
    if value is None:
        raise AssertionError('Value was none!')
    return value


def val_setter[T](aval: trio_util.AsyncValue[T], value: T) -> Callable[[], None]:
    """Create a setter that sets the value when called."""
    def func() -> None:
        """Set the provided value."""
        aval.value = value

    return func


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
    min_x: int = 0,
    min_y: int = 0,
    stride: int = 1,
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


def _append_bothsides[T](deq: deque[T]) -> Generator[None, T, None]:
    """Alternately add to each side of a deque."""
    while True:
        deq.append((yield))
        deq.appendleft((yield))


def get_piece_fitter(sizes: Collection[int]) -> Callable[[SupportsInt], Sequence[int]]:
    """Compute the smallest number of repeated sizes that add up to the specified distance.

    We tend to reuse the set of sizes, so this allows caching some computation.
    """
    size_list = sorted(sizes)

    if not size_list:
        def always_fails(size: SupportsInt) -> NoReturn:
            """No pieces, always fails."""
            raise ValueError(f'No solution to fit {size}, no pieces provided!')

        return always_fails

    # First, for each size other than the largest, calculate the lowest common multiple between
    # it and all larger sizes.
    # That tells us how many of the small one we'd need before it can be matched by the next size up,
    # and more is therefore useless.
    counters: list[range] = []
    for i, small in enumerate(size_list[:-1]):
        multiple = min(math.lcm(small, large) for large in size_list[i+1:])
        counters.append(range(multiple // small))

    *pieces, largest = size_list
    pieces.reverse()
    counters.reverse()

    solutions: dict[int, list[int]] = {}
    largest = size_list[-1]

    # Now, pre-calculate every combination of smaller pieces.
    # That's the hard part, but there's only a smaller amount of those.
    for tup in itertools.product(*counters):
        count = sum(tup)
        result = sum(x * y for x, y in zip(tup, pieces, strict=True))
        try:
            existing = solutions[result]
        except KeyError:
            pass
        else:
            if len(existing) < count:
                continue
        # Otherwise this solution is better, add it.
        solutions[result] = [
            size for size, count in zip(pieces, tup, strict=True)
            for _ in range(count)
        ]

    @functools.lru_cache
    def calculate(size: SupportsInt) -> Sequence[int]:
        """Compute a solution."""
        size = int(size)

        # Figure out how many large pieces are required before we'd overshoot.
        cutoff = math.ceil(size / largest)

        # Try each potential large piece to see if we have a solution
        # for the remaining amount. Start with the most large pieces we can, that should
        # give a more optimal smaller count. If none match, there is no solution.
        best: list[int] | None = None
        for large_count in reversed(range(cutoff + 1)):
            part = size - large_count * largest
            try:
                potential = solutions[part] + [largest] * large_count
            except KeyError:
                continue
            if best is None or len(potential) < len(best):
                best = potential
        if best is not None:
            return best
        else:
            raise ValueError(f'No solution to fit {size} with {size_list}')

    return calculate  # type: ignore[return-value]  # lru_cache issues


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


def group_runs[ValueT](iterable: Iterable[ValueT]) -> Iterator[tuple[ValueT, int, int]]:
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


def quit_app(status: int = 0) -> NoReturn:
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
    copy_function: Callable[[str, str], None] = shutil.copy2,
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
