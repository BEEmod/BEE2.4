import math
import string
import collections.abc as abc
from collections import namedtuple

BEE_VERSION = "2.4"

BOOL_LOOKUP = {
    '1': True,
    '0': False,
    'true': True,
    'false': False,
    'yes': True,
    'no': False,
}

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

FILE_CHARS = string.ascii_letters + string.digits + '-_ .|'


def is_plain_text(name, valid_chars=FILE_CHARS):
    """Check to see if any characters are not in the whitelist.

    """
    for char in name:
        if char not in valid_chars:
            return False
    return True


def get_indent(line):
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


def bool_as_int(val):
    """Convert a True/False value into '1' or '0'.

    Valve uses these strings for True/False in editoritems and other
    config files.
    """
    if val:
        return '1'
    else:
        return '0'


def conv_bool(val, default=False):
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


def conv_int(val, default=0):
    """Converts a string to an integer, using a default if it fails.

    """
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

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

EmptyMapping = EmptyMapping() # We only need the one instance
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
        """
        if isinstance(x, abc.Sequence):
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
        else:
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)

    def copy(self):
        return Vec(self.x, self.y, self.z)

    @classmethod
    def from_str(cls, val, x=0, y=0, z=0):
        """Convert a string in the form '(4 6 -4)' into a vector.

         If the string is unparsable, this uses the defaults (x,y,z).
         The string can start with any of the (), {}, [], <> bracket
         types.
         """
        parts = val.split(' ')
        if len(parts) == 3:
            # strip off the brackets if present
            if parts[0][0] in '({[<':
                parts[0] = parts[0][1:]
            if parts[2][-1] in ')}]>':
                parts[2] = parts[2][:-1]
            try:
                return cls(
                    float(parts[0]),
                    float(parts[1]),
                    float(parts[2]),
                )
            except ValueError:
                return cls(x, y, z)
        else:
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
        return self

    def rotate(self, pitch=0, yaw=0, roll=0):
        """Rotate a vector by a Source rotational angle.
        Returns the vector, so you can use it in the form
        val = Vec(0,1,0).rotate(p, y, r)
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

        return self

    def __add__(self, other):
        """+ operation.

        This additionally works on scalars (adds to all axes).
        """
        if isinstance(other, Vec):
            return Vec(self.x + other.x, self.y + other.y, self.z + other.z)
        else:
            return Vec(self.x + other, self.y + other, self.z + other)

    def __sub__(self, other):
        """- operation.

        This additionally works on scalars (adds to all axes).
        """
        if isinstance(other, Vec):
            return Vec(self.x - other.x, self.y - other.y, self.z - other.z)
        else:
            return Vec(self.x - other, self.y - other, self.z - other)

    def __mul__(self, other):
        """Multiply the Vector by a scalar."""
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x * other, self.y * other, self.z * other)

    def __div__(self, other):
        """Divide the Vector by a scalar.

        If any axis is equal to zero, it will be kept as zero as long
        as the magnitude is greater than zero
        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x / other, self.y / other, self.z / other)

    def __floordiv__(self, other):
        """Divide the Vector by a scalar, discarding the remainder.

        If any axis is equal to zero, it will be kept as zero as long
        as the magnitude is greater than zero
        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x // other, self.y // other, self.z // other)

    def __mod__(self, other):
        """Compute the remainder of the Vector divided by a scalar."""
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x % other, self.y % other, self.z % other)

    def __divmod__(self, other):
        """Divide the vector by a scalar, returning the result and remainder.

        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            x1, x2 = divmod(self.x, other)
            y1, y2 = divmod(self.y, other)
            z1, z2 = divmod(self.y, other)
            return Vec(x1, y1, z1), Vec(x2, y2, z2)

    def __iadd__(self, other):
        """+= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            self.x += other.x
            self.y += other.y
            self.z += other.z
            return self
        else:
            self.x += other
            self.y += other
            self.z += other
            return self

    def __isub__(self, other):
        """-= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            self.x += other.x
            self.y += other.y
            self.z += other.z
            return self
        else:
            self.x += other
            self.y += other
            self.z += other
            return self

    def __imul__(self, other):
        """*= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            self.x *= other
            self.y *= other
            self.z *= other
            return self

    def __idiv__(self, other):
        """/= operation.

        Like the normal one except without duplication.
        """
        if isinstance(other, Vec):
            return NotImplemented
        else:
            self.x /= other
            self.y /= other
            self.z /= other
            return self

    def __bool__(self):
        """Vectors are True if any axis is non-zero."""
        return self.x != 0 or self.y != 0 or self.z != 0

    def __eq__(self, other):
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

    def __lt__(self, other):
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

    def __le__(self, other):
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

    def __gt__(self, other):
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

    def max(self, other):
        """Set this vector's values to the maximum of the two vectors."""
        if self.x < other.x:
            self.x = other.x
        if self.y < other.y:
            self.y = other.y
        if self.z < other.z:
            self.z = other.z

    def min(self, other):
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


    def __iter__(self):
        """Allow iterating through the dimensions."""
        yield self.x
        yield self.y
        yield self.z

    def __getitem__(self, ind):
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

    def __setitem__(self, ind, val):
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

    def norm(self):
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

    len = mag
    mag_sq = len_sq
    __truediv__ = __div__
    __itruediv__ = __idiv__

abc.Mapping.register(Vec)
abc.MutableMapping.register(Vec)