# coding=utf-8
import math
import string
import collections.abc as abc
from collections import namedtuple, deque
from sys import platform
from enum import Enum

from typing import (
    Union,
    Tuple,
    SupportsFloat, Iterator,
)

try:
    # This module is generated when cx_freeze compiles the app.
    from BUILD_CONSTANTS import BEE_VERSION
except ImportError:
    # We're running from source!
    BEE_VERSION = "(dev)"
    FROZEN = False
else:
    FROZEN = True

WIN = platform.startswith('win')
MAC = platform.startswith('darwin')
LINUX = platform.startswith('linux')

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

    # Others:
    # 841: P2 Beta
    # 213630: Educational
    # 247120: Sixense
    # 211480: 'In Motion'
    # 317400: PS Mel - No workshop
}

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
            scroll_func(event.delta, "units")
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

if MAC:
    # On OSX, make left-clicks switch to a rightclick when control is held.
    def bind_leftclick(wid, func, add='+'):
        """On OSX, left-clicks are converted to right-clicks

        when control is held.
        """
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func()
        wid.bind(EVENTS['LEFT'], event_handler, add=add)

    def bind_leftclick_double(wid, func, add='+'):
        """On OSX, left-clicks are converted to right-clicks

        when control is held."""
        def event_handler(e):
            # e.state is a set of binary flags
            # Don't run the event if control is held!
            if e.state & 4 == 0:
                func()
        wid.bind(EVENTS['LEFT_DOUBLE'], event_handler, add=add)

    def bind_rightclick(wid, func):
        """On OSX, we need to bind to both rightclick and control-leftclick."""
        wid.bind(EVENTS['RIGHT'], func)
        wid.bind(EVENTS['LEFT_CTRL'], func)
else:
    def bind_leftclick(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT'], func, add=add)

    def bind_leftclick_double(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['LEFT_DOUBLE'], func, add=add)

    def bind_rightclick(wid, func, add='+'):
        """Other systems just bind directly."""
        wid.bind(EVENTS['RIGHT'], func, add=add)

USE_SIZEGRIP = not MAC  # On Mac, we don't want to use the sizegrip widget

BOOL_LOOKUP = {
    '1': True,
    '0': False,
    'true': True,
    'false': False,
    'yes': True,
    'no': False,
}


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
    # N S  E  W : (Type, Rotation)
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


def clean_line(line: str):
    """Removes extra spaces and comments from the input."""
    if isinstance(line, bytes):
        line = line.decode()  # convert bytes to strings if needed
    if '//' in line:
        line = line.split('//', 1)[0]
    return line.strip()


def is_identifier(name, forbidden='{}\'"'):
    """Check to see if any forbidden characters are part of a candidate name.

    """
    for char in name:
        if char in forbidden:
            return False
    return True

FILE_CHARS = set(string.ascii_letters + string.digits + '-_ .|')


def is_plain_text(name, valid_chars=FILE_CHARS):
    """Check to see if any characters are not in the whitelist.

    """
    for char in name:
        if char not in valid_chars:
            return False
    return True


def whitelist(string, valid_chars=FILE_CHARS, rep_char='_'):
    """Replace any characters not in the whitelist with the replacement char."""
    chars = list(string)
    for ind, char in enumerate(chars):
        if char not in valid_chars:
            chars[ind] = rep_char
    return ''.join(chars)


def blacklist(string, invalid_chars='', rep_char='_'):
    """Replace any characters in the blacklist with the replacement char."""
    chars = list(string)
    for ind, char in enumerate(chars):
        if char in invalid_chars:
            chars[ind] = rep_char
    return ''.join(chars)


def get_indent(line: str):
    """Return the whitespace which this line starts with.

    """
    white = []
    for char in line:
        if char in ' \t':
            white.append(char)
        else:
            return ''.join(white)


def con_log(*text):
    """Log text to the screen.

    Portal 2 needs the flush in order to receive VBSP/VRAD's logged
    output into the developer console and update the progress bars.
    """
    print(*text, flush=True)


def bool_as_int(val: bool):
    """Convert a True/False value into '1' or '0'.

    Valve uses these strings for True/False in editoritems and other
    config files.
    """
    if val:
        return '1'
    else:
        return '0'


def conv_bool(val: Union[str, int, bool, None], default=False):
    """Converts a string to a boolean, using a default if it fails.

    Accepts any of '0', '1', 'false', 'true', 'yes', 'no', 0 and 1, None.
    """
    if val is False:
        return False
    elif val is True:
        return True
    elif val is None:
        return default
    elif isinstance(val, int):
        return bool(val)
    else:
        return BOOL_LOOKUP.get(val.casefold(), default)


def conv_float(val, default=0.0):
    """Converts a string to an float, using a default if it fails.

    """
    try:
        return float(val)
    except ValueError:
        return default


def conv_int(val: str, default=0):
    """Converts a string to an integer, using a default if it fails.

    """
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def parse_str(val: str, x=0.0, y=0.0, z=0.0) -> Tuple[int, int, int]:
    """Convert a string in the form '(4 6 -4)' into a set of floats.

     If the string is unparsable, this uses the defaults (x,y,z).
     The string can start with any of the (), {}, [], <> bracket
     types.
     """
    parts = val.split(' ')
    if len(parts) == 3:
        # Strip off the brackets if present
        if parts[0][0] in '({[<':
            parts[0] = parts[0][1:]
        if parts[2][-1] in ')}]>':
            parts[2] = parts[2][:-1]
        try:
            return (
                float(parts[0]),
                float(parts[1]),
                float(parts[2]),
            )
        except ValueError:
            return x, y, z
    else:
        return x, y, z


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


def adjust_inside_screen(x, y, win, horiz_bound=14, vert_bound=45):
    """Adjust a window position to ensure it fits inside the screen."""
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


def append_bothsides(deq):
    """Alternately add to each side of a deque."""
    while True:
        deq.append((yield))
        deq.appendleft((yield))


def fit(dist, obj):
    """Figure out the smallest number of parts to stretch a distance."""
    # If dist is a float the outputs will become floats as well
    # so ensure it's an int.
    dist = int(dist)
    if dist <= 0:
        return []
    orig_dist = dist
    smallest = obj[-1]
    items = deque()

    # We use this so the small sections appear on both sides of the area.
    adder = append_bothsides(items)
    next(adder)
    while dist >= smallest:
        for item in obj:
            if item <= dist:
                adder.send(item)
                dist -= item
                break
    if dist > 0:
        adder.send(dist)

    assert sum(items) == orig_dist
    return list(items)  # Dump the deque


class EmptyMapping(abc.Mapping):
    """A Mapping class which is always empty."""
    __slots__ = []

    def __call__(self):
        # Just in case someone tries to instantiate this
        return self

    def __getitem__(self, item):
        raise KeyError

    def __contains__(self, item):
        return False

    def get(self, item, default=None):
        return default

    def __bool__(self):
        return False

    def __next__(self):
        raise StopIteration

    def __len__(self):
        return 0

    def __iter__(self):
        return self

    def items(self):
        return self

    def values(self):
        return self

    def keys(self):
        return self

EmptyMapping = EmptyMapping()  # We only need the one instance


Vec_tuple = namedtuple('Vec_tuple', ['x', 'y', 'z'])


class Vec:
    """A 3D Vector. This has most standard Vector functions.

    Many of the functions will accept a 3-tuple for comparison purposes.
    """
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0.0, y=0.0, z=0.0):
        """Create a Vector.

        All values are converted to Floats automatically.
        If no value is given, that axis will be set to 0.
        A sequence can be passed in (as the x argument), which will use
        the three args as x/y/z.
        :type x: int | float | Vec | list[float]
        """
        if isinstance(x, (int, float)):
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)
        elif isinstance(x, Vec):
            self.x, self.y, self.z = x
        else:
            try:
                self.x = float(x[0])
            except (TypeError, KeyError):
                self.x = 0.0
            else:
                try:
                    self.y = float(x[1])
                except (TypeError, KeyError):
                    self.y = 0.0
                else:
                    try:
                        self.z = float(x[2])
                    except (TypeError, KeyError):
                        self.z = 0.0

    def copy(self):
        return Vec(self.x, self.y, self.z)

    @classmethod
    def from_str(cls, val: str, x=0.0, y=0.0, z=0.0):
        """Convert a string in the form '(4 6 -4)' into a Vector.

         If the string is unparsable, this uses the defaults (x,y,z).
         The string can start with any of the (), {}, [], <> bracket
         types.
         """
        x, y, z = parse_str(val, x, y, z)
        return cls(x, y, z)

    def mat_mul(self, matrix):
        """Multiply this vector by a 3x3 rotation matrix.

        Used for Vec.rotate().
        """
        [a, b, c], [d, e, f], [g, h, i] = matrix
        x, y, z = self.x, self.y, self.z

        self.x = x*a + y*b + z*c
        self.y = x*d + y*e + z*f
        self.z = x*g + y*h + z*i

    def rotate(self, pitch=0.0, yaw=0.0, roll=0.0, round_vals=True):
        """Rotate a vector by a Source rotational angle.
        Returns the vector, so you can use it in the form
        val = Vec(0,1,0).rotate(p, y, r)

        If round is True, all values will be rounded to 3 decimals
        (since these calculations always have small inprecision.)
        """
        # pitch is in the y axis
        # yaw is the z axis
        # roll is the x axis

        rad_pitch = math.radians(pitch)
        rad_yaw = math.radians(yaw)
        rad_roll = math.radians(roll)
        cos_p = math.cos(rad_pitch)
        cos_y = math.cos(rad_yaw)
        cos_r = math.cos(rad_roll)

        sin_p = math.sin(rad_pitch)
        sin_y = math.sin(rad_yaw)
        sin_r = math.sin(rad_roll)

        mat_roll = (  # X
            (1, 0, 0),
            (0, cos_r, -sin_r),
            (0, sin_r, cos_r),
        )
        mat_yaw = (  # Z
            (cos_y, -sin_y, 0),
            (sin_y, cos_y, 0),
            (0, 0, 1),
        )

        mat_pitch = (  # Y
            (cos_p, 0, sin_p),
            (0, 1, 0),
            (-sin_p, 0, cos_p),
        )

        # Need to do transformations in roll, pitch, yaw order
        self.mat_mul(mat_roll)
        self.mat_mul(mat_pitch)
        self.mat_mul(mat_yaw)

        if round_vals:
            self.x = round(self.x, 3)
            self.y = round(self.y, 3)
            self.z = round(self.z, 3)

        return self

    def rotate_by_str(self, ang, pitch=0.0, yaw=0.0, roll=0.0, round_vals=True):
        """Rotate a vector, using a string instead of a vector."""
        pitch, yaw, roll = parse_str(ang, pitch, yaw, roll)
        return self.rotate(
            pitch,
            yaw,
            roll,
            round_vals,
        )

    @staticmethod
    def bbox(*points):
        """Compute the bounding box for a set of points."""
        first, *points = points
        bbox_min = Vec(first)
        bbox_max = Vec(first)
        for point in points:
            bbox_min.min(point)
            bbox_max.max(point)
        return bbox_min, bbox_max

    def __add__(self, other: Union['Vec', Vec_tuple, float]) -> 'Vec':
        """+ operation.

        This additionally works on scalars (adds to all axes).
        """
        if isinstance(other, Vec):
            return Vec(self.x + other.x, self.y + other.y, self.z + other.z)
        elif isinstance(other, tuple):
            return Vec(self.x + other[0], self.y + other[1], self.z + other[2])
        else:
            return Vec(self.x + other, self.y + other, self.z + other)
    __radd__ = __add__

    def __sub__(self, other) -> 'Vec':
        """- operation.

        This additionally works on scalars (adds to all axes).
        """
        if isinstance(other, Vec):
            return Vec(
                self.x - other.x,
                self.y - other.y,
                self.z - other.z
            )

        try:
            if isinstance(other, tuple):
                x = self.x - other[0]
                y = self.y - other[1]
                z = self.z - other[2]
            else:
                x = self.x - other
                y = self.y - other
                z = self.z - other
        except TypeError:
            return NotImplemented
        else:
            return Vec(x, y, z)

    def __rsub__(self, other) -> 'Vec':
        """- operation.

        This additionally works on scalars (adds to all axes).
        """

        if isinstance(other, Vec):
            return Vec(
                other.x - self.x,
                other.y - self.x,
                other.z - self.z
            )

        try:
            if isinstance(other, tuple):
                x = other[0] - self.x
                y = other[1] - self.y
                z = other[2] - self.z
            else:
                x = other - self.x
                y = other - self.y
                z = other - self.z
        except TypeError:
            return NotImplemented
        else:
            return Vec(x, y, z)

    def __mul__(self, other) -> 'Vec':
        """Multiply the Vector by a scalar."""
        if isinstance(other, Vec):
            return NotImplemented
        else:
            try:
                return Vec(
                    self.x * other,
                    self.y * other,
                    self.z * other,
                )
            except TypeError:
                return NotImplemented
    __rmul__ = __mul__

    def __div__(self, other: float) -> 'Vec':
        """Divide the Vector by a scalar."""
        if isinstance(other, Vec):
            return NotImplemented
        else:
            try:
                return Vec(
                    self.x / other,
                    self.y / other,
                    self.z / other,
                )
            except TypeError:
                return NotImplemented

    def __rdiv__(self, other: float) -> 'Vec':
        """Divide a scalar by a Vector.

        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            try:
                return Vec(
                    other / self.x,
                    other / self.y,
                    other / self.z,
                )
            except TypeError:
                return NotImplemented

    def __floordiv__(self, other) -> 'Vec':
        """Divide the Vector by a scalar, discarding the remainder.

        If any axis is equal to zero, it will be kept as zero as long
        as the magnitude is greater than zero
        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            try:
                return Vec(
                    self.x // other,
                    self.y // other,
                    self.z // other,
                )
            except TypeError:
                return NotImplemented

    def __mod__(self, other) -> 'Vec':
        """Compute the remainder of the Vector divided by a scalar."""
        if isinstance(other, Vec):
            return NotImplemented
        else:
            try:
                return Vec(
                    self.x % other,
                    self.y % other,
                    self.z % other,
                )
            except TypeError:
                return NotImplemented

    def __divmod__(self, other) -> Tuple['Vec', 'Vec']:
        """Divide the vector by a scalar, returning the result and remainder.

        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            try:
                x1, x2 = divmod(self.x, other)
                y1, y2 = divmod(self.y, other)
                z1, z2 = divmod(self.y, other)
            except TypeError:
                return NotImplemented
            else:
                return Vec(x1, y1, z1), Vec(x2, y2, z2)

    def __iadd__(self, other) -> 'Vec':
        """+= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            self.x += other.x
            self.y += other.y
            self.z += other.z
            return self
        else:
            orig = self.x, self.y, self.z
            try:
                self.x += other
                self.y += other
                self.z += other
            except TypeError as e:
                self.x, self.y, self.z = orig
                raise TypeError(
                    'Cannot add ' + type(other) + ' to Vector!'
                ) from e
            return self

    def __isub__(self, other) -> 'Vec':
        """-= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            self.x -= other.x
            self.y -= other.y
            self.z -= other.z
            return self
        else:
            orig = self.x, self.y, self.z
            try:
                self.x -= other
                self.y -= other
                self.z -= other
            except TypeError as e:
                self.x, self.y, self.z = orig
                raise TypeError(
                    'Cannot subtract ' + type(other) + ' from Vector!'
                ) from e
            return self

    def __imul__(self, other) -> 'Vec':
        """*= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            raise TypeError("Cannot multiply 2 Vectors.")
        else:
            self.x *= other
            self.y *= other
            self.z *= other
            return self

    def __idiv__(self, other) -> 'Vec':
        """/= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            raise TypeError("Cannot divide 2 Vectors.")
        else:
            self.x /= other
            self.y /= other
            self.z /= other
            return self

    def __ifloordiv__(self, other) -> 'Vec':
        """//= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            raise TypeError("Cannot divide 2 Vectors.")
        else:
            self.x //= other
            self.y //= other
            self.z //= other
            return self

    def __imod__(self, other) -> 'Vec':
        """%= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            raise TypeError("Cannot modulus 2 Vectors.")
        else:
            self.x %= other
            self.y %= other
            self.z %= other
            return self

    def __bool__(self) -> bool:
        """Vectors are True if any axis is non-zero."""
        return self.x != 0 or self.y != 0 or self.z != 0

    def __eq__(
            self,
            other: Union['Vec', abc.Sequence, SupportsFloat],
            ) -> bool:
        """== test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        """
        if isinstance(other, Vec):
            return other.x == self.x and other.y == self.y and other.z == self.z
        elif isinstance(other, abc.Sequence):
            return (
                self.x == other[0] and
                self.y == other[1] and
                self.z == other[2]
            )
        else:
            try:
                return self.mag() == float(other)
            except ValueError:
                return NotImplemented

    def __lt__(
            self,
            other: Union['Vec', abc.Sequence, SupportsFloat],
            ) -> bool:
        """A<B test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        """
        if isinstance(other, Vec):
            return (
                self.x < other.x and
                self.y < other.y and
                self.z < other.z
                )
        elif isinstance(other, abc.Sequence):
            return (
                self.x < other[0] and
                self.y < other[1] and
                self.z < other[2]
                )
        else:
            try:
                return self.mag() < float(other)
            except ValueError:
                return NotImplemented

    def __le__(
            self,
            other: Union['Vec', abc.Sequence, SupportsFloat],
            ) -> bool:
        """A<=B test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        """
        if isinstance(other, Vec):
            return (
                self.x <= other.x and
                self.y <= other.y and
                self.z <= other.z
                )
        elif isinstance(other, abc.Sequence):
            return (
                self.x <= other[0] and
                self.y <= other[1] and
                self.z <= other[2]
                )
        else:
            try:
                return self.mag() <= float(other)
            except ValueError:
                return NotImplemented

    def __gt__(
            self,
            other: Union['Vec', abc.Sequence, SupportsFloat],
            ) -> bool:
        """A>B test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        """
        if isinstance(other, Vec):
            return (
                self.x > other.x and
                self.y > other.y and
                self.z > other.z
                )
        elif isinstance(other, abc.Sequence):
            return (
                self.x > other[0] and
                self.y > other[1] and
                self.z > other[2]
                )
        else:
            try:
                return self.mag() > float(other)
            except ValueError:
                return NotImplemented

    def max(self, other: Union['Vec', Vec_tuple]):
        """Set this vector's values to the maximum of the two vectors."""
        if self.x < other.x:
            self.x = other.x
        if self.y < other.y:
            self.y = other.y
        if self.z < other.z:
            self.z = other.z

    def min(self, other: Union['Vec', Vec_tuple]):
        """Set this vector's values to be the minimum of the two vectors."""
        if self.x > other.x:
            self.x = other.x
        if self.y > other.y:
            self.y = other.y
        if self.z > other.z:
            self.z = other.z

    def __round__(self, n=0):
        return Vec(
            round(self.x, n),
            round(self.y, n),
            round(self.z, n),
        )

    def mag(self):
        """Compute the distance from the vector and the origin."""
        if self.z == 0:
            return math.sqrt(self.x**2+self.y**2)
        else:
            return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def join(self, delim=', '):
        """Return a string with all numbers joined by the passed delimiter.

        This strips off the .0 if no decimal portion exists.
        """
        if self.x.is_integer():
            x = int(self.x)
        else:
            x = self.x
        if self.y.is_integer():
            y = int(self.y)
        else:
            y = self.y
        if self.z.is_integer():
            z = int(self.z)
        else:
            z = self.z
        # convert to int to strip off .0 at end if whole number
        return '{x!s}{delim}{y!s}{delim}{z!s}'.format(
            x=x,
            y=y,
            z=z,
            delim=delim,
        )

    def __str__(self):
        """Return a user-friendly representation of this vector."""
        return "(" + self.join() + ")"

    def __repr__(self):
        """Code required to reproduce this vector."""
        return self.__class__.__name__ + "(" + self.join() + ")"

    def __iter__(self) -> Iterator[float]:
        """Allow iterating through the dimensions."""
        yield self.x
        yield self.y
        yield self.z

    def __getitem__(self, ind: Union[str, int]) -> float:
        """Allow reading values by index instead of name if desired.

        This accepts either 0,1,2 or 'x','y','z' to read values.
        Useful in conjunction with a loop to apply commands to all values.
        """
        if ind == 0 or ind == "x":
            return self.x
        elif ind == 1 or ind == "y":
            return self.y
        elif ind == 2 or ind == "z":
            return self.z
        else:
            return NotImplemented

    def __setitem__(self, ind: Union[str, int], val: float):
        """Allow editing values by index instead of name if desired.

        This accepts either 0,1,2 or 'x','y','z' to edit values.
        Useful in conjunction with a loop to apply commands to all values.
        """
        if ind == 0 or ind == "x":
            self.x = float(val)
        elif ind == 1 or ind == "y":
            self.y = float(val)
        elif ind == 2 or ind == "z":
            self.z = float(val)
        else:
            return NotImplemented

    def as_tuple(self):
        """Return the Vector as a tuple."""
        return Vec_tuple(self.x, self.y, self.z)

    def len_sq(self):
        """Return the magnitude squared, which is slightly faster."""
        if self.z == 0:
            return self.x**2 + self.y**2
        else:
            return self.x**2 + self.y**2 + self.z**2

    def __len__(self):
        """The len() of a vector is the number of non-zero axes."""
        return sum(1 for axis in (self.x, self.y, self.z) if axis != 0)

    def __contains__(self, val):
        """Check to see if an axis is set to the given value.
        """
        return val == self.x or val == self.y or val == self.z

    def __neg__(self):
        """The inverted form of a Vector has inverted axes."""
        return Vec(-self.x, -self.y, -self.z)

    def __pos__(self):
        """+ on a Vector simply copies it."""
        return Vec(self.x, self.y, self.z)

    def norm(self) -> 'Vec':
        """Normalise the Vector.

         This is done by transforming it to have a magnitude of 1 but the same
         direction.
         The vector is left unchanged if it is equal to (0,0,0)
         """
        if self.x == 0 and self.y == 0 and self.z == 0:
            # Don't do anything for this - otherwise we'd get
            return self.copy()
        else:
            return self / self.mag()

    def dot(self, other):
        """Return the dot product of both Vectors."""
        return (
            self.x * other.x +
            self.y * other.y +
            self.z * other.z
            )

    def cross(self, other):
        """Return the cross product of both Vectors."""
        return Vec(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
            )

    def localise(
            self,
            origin: Union['Vec', Vec_tuple],
            angles: Union['Vec', Vec_tuple]=None
            ):
        """Shift this point to be local to the given position and angles

        """
        if angles is not None:
            self.rotate(angles.x, angles.y, angles.z)
        self.__iadd__(origin)

    len = mag
    mag_sq = len_sq
    __truediv__ = __div__
    __itruediv__ = __idiv__

abc.Mapping.register(Vec)
abc.MutableMapping.register(Vec)
