"""Various functions shared among the compiler and application."""
import collections
import functools
import logging
import os
import stat
import shutil
import sys
from pathlib import Path
from enum import Enum

from typing import (
    Tuple, List, Set, Sequence,
    Iterator, Iterable, SupportsInt, Mapping,
    TypeVar, Any,
    Union, Callable, Generator,
    KeysView, ValuesView, ItemsView,
)

try:
    from typing import NoReturn
except ImportError:  # py < 3.6.5
    NoReturn = None  # type: ignore


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
    _SETTINGS_ROOT = None
    
# We always go in a BEE2 subfolder
if _SETTINGS_ROOT:
    _SETTINGS_ROOT /= 'BEEMOD2'


def install_path(path: str) -> Path:
    """Return the path to a file inside our installation folder."""
    if FROZEN:
        # This special attribute is set by PyInstaller to our folder.
        return Path(sys._MEIPASS) / path
    else:
        # We're running from src/, so data is in the folder above that.
        return (Path('../') / path).resolve()


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


if WIN:
    # Some events differ on different systems, so define them here.
    EVENTS = {
        'LEFT': '<Button-1>',
        'LEFT_DOUBLE': '<Double-Button-1>',
        'LEFT_CTRL': '<Control-Button-1>',
        'LEFT_SHIFT': '<Shift-Button-1>',
        'LEFT_RELEASE': '<ButtonRelease-1>',
        'LEFT_MOVE': '<B1-Motion>',

        'RIGHT': '<Button-3>',
        'RIGHT_DOUBLE': '<Double-Button-3>',
        'RIGHT_CTRL': '<Control-Button-3>',
        'RIGHT_SHIFT': '<Shift-Button-3>',
        'RIGHT_RELEASE': '<ButtonRelease-3>',
        'RIGHT_MOVE': '<B3-Motion>',

        'KEY_EXPORT': '<Control-e>',
        'KEY_SAVE_AS': '<Control-s>',
        'KEY_SAVE': '<Control-Shift-s>',
    }
    # The text used to show shortcuts in menus.
    KEY_ACCEL = {
        'KEY_EXPORT': 'Ctrl-E',
        'KEY_SAVE': 'Ctrl-S',
        'KEY_SAVE_AS': 'Ctrl-Shift-S',
    }

    CURSORS = {
        'regular': 'arrow',
        'link': 'hand2',
        'wait': 'watch',
        'stretch_vert': 'sb_v_double_arrow',
        'stretch_horiz': 'sb_h_double_arrow',
        'move_item': 'plus',
        'destroy_item': 'x_cursor',
        'invalid_drag': 'no',
    }

    def add_mousewheel(target, *frames, orient='y'):
        """Add events so scrolling anywhere in a frame will scroll a target.

        frames should be the TK objects to bind to - mainly Frame or
        Toplevel objects.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - Windows needs the delta value to be divided by 120.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def mousewheel_handler(event):
            scroll_func(int(event.delta / -120), "units")
        for frame in frames:
            frame.bind('<MouseWheel>', mousewheel_handler, add='+')

elif MAC:
    EVENTS = {
        'LEFT': '<Button-1>',
        'LEFT_DOUBLE': '<Double-Button-1>',
        'LEFT_CTRL': '<Control-Button-1>',
        'LEFT_SHIFT': '<Shift-Button-1>',
        'LEFT_RELEASE': '<ButtonRelease-1>',
        'LEFT_MOVE': '<B1-Motion>',

        'RIGHT': '<Button-2>',
        'RIGHT_DOUBLE': '<Double-Button-2>',
        'RIGHT_CTRL': '<Control-Button-2>',
        'RIGHT_SHIFT': '<Shift-Button-2>',
        'RIGHT_RELEASE': '<ButtonRelease-2>',
        'RIGHT_MOVE': '<B2-Motion>',

        'KEY_EXPORT': '<Command-e>',
        'KEY_SAVE_AS': '<Command-s>',
        'KEY_SAVE': '<Command-Shift-s>',
    }

    KEY_ACCEL = {
        # tkinter replaces Command- with the special symbol automatically.
        'KEY_EXPORT': 'Command-E',
        'KEY_SAVE': 'Command-S',
        'KEY_SAVE_AS': 'Command-Shift-S',
    }

    CURSORS = {
        'regular': 'arrow',
        'link': 'pointinghand',
        'wait': 'spinning',
        'stretch_vert': 'resizeupdown',
        'stretch_horiz': 'resizeleftright',
        'move_item': 'plus',
        'destroy_item': 'poof',
        'invalid_drag': 'notallowed',
    }

    def add_mousewheel(target, *frames, orient='y'):
        """Add events so scrolling anywhere in a frame will scroll a target.

        frame should be a sequence of any TK objects, like a Toplevel or Frame.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - OS X needs the delta value passed unmodified.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def mousewheel_handler(event):
            scroll_func(-event.delta, "units")
        for frame in frames:
            frame.bind('<MouseWheel>', mousewheel_handler, add='+')
elif LINUX:
    EVENTS = {
        'LEFT': '<Button-1>',
        'LEFT_DOUBLE': '<Double-Button-1>',
        'LEFT_CTRL': '<Control-Button-1>',
        'LEFT_SHIFT': '<Shift-Button-1>',
        'LEFT_RELEASE': '<ButtonRelease-1>',
        'LEFT_MOVE': '<B1-Motion>',

        'RIGHT': '<Button-3>',
        'RIGHT_DOUBLE': '<Double-Button-3>',
        'RIGHT_CTRL': '<Control-Button-3>',
        'RIGHT_SHIFT': '<Shift-Button-3>',
        'RIGHT_RELEASE': '<ButtonRelease-3>',
        'RIGHT_MOVE': '<B3-Motion>',

        'KEY_EXPORT': '<Control-e>',
        'KEY_SAVE_AS': '<Control-s>',
        'KEY_SAVE': '<Control-Shift-s>',
    }
    KEY_ACCEL = {
        'KEY_EXPORT': 'Ctrl+E',
        'KEY_SAVE': 'Ctrl+S',
        'KEY_SAVE_AS': 'Shift+Ctrl+S',
    }

    CURSORS = {
        'regular': 'arrow',
        'link': 'hand1',
        'wait': 'watch',
        'stretch_vert': 'bottom_side',
        'stretch_horiz': 'right_side',
        'move_item': 'crosshair',
        'destroy_item': 'X_cursor',
        'invalid_drag': 'circle',
    }

    def add_mousewheel(target, *frames, orient='y'):
        """Add events so scrolling anywhere in a frame will scroll a target.

        frame should be a sequence of any TK objects, like a Toplevel or Frame.
        Set orient to 'x' or 'y'.
        This is needed since different platforms handle mousewheel events
        differently - Linux uses Button-4 and Button-5 events instead of
        a MouseWheel event.
        """
        scroll_func = getattr(target, orient + 'view_scroll')

        def scroll_up(_):
            scroll_func(-1, "units")

        def scroll_down(_):
            scroll_func(1, "units")

        for frame in frames:
            frame.bind('<Button-4>', scroll_up, add='+')
            frame.bind('<Button-5>', scroll_down, add='+')


def bind_event_handler(bind_func):
    """Decorator for the bind_click functions.

    This allows calling directly, or decorating a function with just wid and add
    attributes.
    """
    def deco(wid, func=None, add='+'):
        """Decorator or normal interface, func is optional to be a decorator."""
        if func is None:
            def deco_2(func):
                """Used as a decorator - must be called second with the function."""
                bind_func(wid, func, add)
                return func
            return deco_2
        else:
            # Normally, call directly
            return bind_func(wid, func, add)
    return functools.update_wrapper(deco, bind_func)

if MAC:
    # On OSX, make left-clicks switch to a rightclick when control is held.
    @bind_event_handler
    def bind_leftclick(wid, func, add='+'):
        """On OSX, left-clicks are converted to right-clicks

        when control is held.
        """
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func(e)
        wid.bind(EVENTS['LEFT'], event_handler, add=add)

    @bind_event_handler
    def bind_leftclick_double(wid, func, add='+'):
        """On OSX, left-clicks are converted to right-clicks

        when control is held."""
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func(e)
        wid.bind(EVENTS['LEFT_DOUBLE'], event_handler, add=add)

    @bind_event_handler
    def bind_rightclick(wid, func, add='+'):
        """On OSX, we need to bind to both rightclick and control-leftclick."""
        wid.bind(EVENTS['RIGHT'], func, add=add)
        wid.bind(EVENTS['LEFT_CTRL'], func, add=add)
else:
    @bind_event_handler
    def bind_leftclick(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT'], func, add=add)

    @bind_event_handler
    def bind_leftclick_double(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT_DOUBLE'], func, add=add)

    @bind_event_handler
    def bind_rightclick(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['RIGHT'], func, add=add)

USE_SIZEGRIP = not MAC  # On Mac, we don't want to use the sizegrip widget.


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


class FuncLookup(Mapping[str, Callable[..., Any]]):
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
        self._registry = {}
        self.allowed_attrs = set(attrs)

    def __call__(self, *names: str, **kwargs) -> Callable[[Callable[..., RetT]], Callable[..., RetT]]:
        """Add a function to the dict."""
        if not names:
            raise TypeError('No names passed!')

        bad_keywords = kwargs.keys() - self.allowed_attrs
        if bad_keywords:
            raise TypeError('Invalid keywords: ' + ', '.join(bad_keywords))

        def callback(func: 'Callable[..., RetT]') -> 'Callable[..., RetT]':
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
        if not isinstance(other, collections.Mapping):
            return NotImplemented
        return self._registry == dict(other.items())

    def __iter__(self) -> Iterator[Callable[..., Any]]:
        """Yield all the functions."""
        return iter(self.values())

    def keys(self) -> KeysView[str]:
        """Yield all the valid IDs."""
        return self._registry.keys()

    def values(self) -> ValuesView[Callable[..., Any]]:
        """Yield all the functions."""
        return self._registry.values()

    def items(self) -> ItemsView[str, Callable[..., Any]]:
        """Return pairs of (ID, func)."""
        return self._registry.items()

    def __len__(self) -> int:
        return len(set(self._registry.values()))

    def __getitem__(self, names: Union[str, Tuple[str]]) -> Callable[..., Any]:
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
        names: Union[str, Tuple[str]],
        func: Callable[..., Any],
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
        if self.casefold:
            name = name.casefold()
        del self._registry[name]

    def __contains__(self, name: str) -> bool:
        if self.casefold:
            name = name.casefold()
        return name in self._registry

    def functions(self) -> Set[Callable[..., Any]]:
        """Return the set of functions in this mapping."""
        return set(self._registry.values())

    def clear(self) -> None:
        """Delete all functions."""
        self._registry.clear()


def get_indent(line: str) -> str:
    """Return the whitespace which this line starts with.

    """
    white = []
    for char in line:
        if char in ' \t':
            white.append(char)
        else:
            return ''.join(white)


def iter_grid(
    max_x: int,
    max_y: int,
    min_x: int=0,
    min_y: int=0,
    stride: int=1,
) -> Iterator[Tuple[int, int]]:
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
) -> Tuple[int, int]:
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


def center_win(window, parent=None):
    """Center a subwindow to be inside a parent window."""
    if parent is None:
        parent = window.nametowidget(window.winfo_parent())

    x = parent.winfo_rootx() + (parent.winfo_width()-window.winfo_width())//2
    y = parent.winfo_rooty() + (parent.winfo_height()-window.winfo_height())//2

    x, y = adjust_inside_screen(x, y, window)

    window.geometry('+' + str(x) + '+' + str(y))


def _append_bothsides(deq: collections.deque) -> Generator[None, Any, None]:
    """Alternately add to each side of a deque."""
    while True:
        deq.append((yield))
        deq.appendleft((yield))


def fit(dist: SupportsInt, obj: Sequence[int]) -> List[int]:
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
    items = collections.deque()

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
    logging.shutdown()
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
    errors = []  # type: List[Tuple[str, str, str]]
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

    for lang in expanded_langs:
        try:
            file = open(lang_folder / (lang + '.mo').format(lang), 'rb')
        except FileNotFoundError:
            continue
        with file:
            trans = gettext.GNUTranslations(file)  # type: gettext.NullTranslations
            break
    else:
        # No translations, fallback to English.
        # That's fine if the user's language is actually English.
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
