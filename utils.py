import math
import string
import collections.abc as abc

def clean_line(line):
    '''Removes extra spaces and comments from the input.'''
    if isinstance(line, bytes):
        line = line.decode() # convert bytes to strings if needed
    if '//' in line:
        line = line.split('//', 1)[0]
    return line.strip()

def is_identifier(name, forbidden='{}\'"'):
    '''Check to see if any forbidden characters are part of a candidate name.'''
    for char in name:
        if char in forbidden:
            return False
    return True

FILE_CHARS = string.ascii_letters + string.digits + '-_ .|'

def is_plain_text(name, valid_chars=FILE_CHARS):
    '''Check to see if any characters are not in the whitelist.'''
    for char in name:
        if char not in valid_chars:
            return False
    return True

def get_indent(line):
    '''Return the whitspace which this line starts with.'''
    white = []
    for char in line:
        if char in ' \t':
            white.append(char)
        else:
            return ''.join(white)

def con_log(*text):
    '''Log text to the screen.

    Portal 2 needs the flush in order to recieve VBSP/VRAD's logged
    output into the developer console and update the progress bars.
    '''
    print(*text, flush=True)

def bool_as_int(val):
    '''Convert a True/False value into the 1/0 strings often appearing in config files.'''
    if val:
        return '1'
    else:
        return '0'

def adjust_inside_screen(x, y, win, horiz_bound=14, vert_bound=45):
    '''Adjust a window position to ensure it fits inside the screen.'''
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

class Vec:
    '''A 3D Vector. This has most standard Vector functions.'''
    __slots__ = ('x', 'y', 'z')

    def __init__(self, x=0, y=0, z=0):
        '''Create a Vector.

        All values are converted to Floats automatically.
        If no value is given, that axis will be set to 0.
        A sequence can be passed in (as the x argument), which will use the three args as x/y/z.
        '''
        if isinstance(x, abc.Sequence):
            length = len(x)
            try:
                self.x = float(x[0])
            except (TypeError, KeyError):
                self.x = 0.0
            try:
                self.y = float(x[1])
            except (TypeError, KeyError):
                self.y = 0.0
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
    def from_ang(cls, pitch, yaw):
        '''Create a unit vector based on a Source rotational angle.'''
        sin_pitch = math.sin(math.radians(pitch))
        cos_pitch = math.cos(math.radians(pitch))
        sin_yaw = math.sin(math.radians(-yaw))
        cos_yaw = math.cos(math.radians(-yaw))
        return cls(
            x=cos_pitch * cos_yaw,
            y=sin_pitch * cos_yaw,
            z=sin_yaw,
            )

    def __add__(self, other):
        '''+ operation. This additionally works on scalars (adds to all axes).'''
        if isinstance(other, Vec):
            return Vec(self.x + other.x, self.y + other.y, self.z + other.z)
        else:
            return Vec(self.x + other, self.y + other, self.z + other)

    def __sub__(self, other):
        '''- operation. This additionally works on scalars (adds to all axes).'''
        if isinstance(other, Vec):
            return Vec(self.x - other.x, self.y - other.y, self.z - other.z)
        else:
            return Vec(self.x - other, self.y - other, self.z - other)

    def __mul__(self, other):
        '''Multiply the Vector by a scalar.'''
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x * other, self.y * other, self.z * other)

    def __div__(self, other):
        '''Divide the Vector by a scalar.'''
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x / other, self.y / other, self.z / other)

    def __floordiv__(self, other):
        '''Divide the Vector by a scalar, discarding the remainder.'''
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x // other, self.y // other, self.z // other)

    def __mod__(self, other):
        '''Compute the remainder of the Vector divided by a scalar.'''
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x % other, self.y % other, self.z % other)

    def __divmod__(self, other):
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return self // other, self % other

    def __iadd__(self, other):
        "+= operation. Like the normal one except without duplication."
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
        "-= operation. Like the normal one except without duplication."
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
        "*= operation. Like the normal one except without duplication."
        if isinstance(other, Vec):
            return NotImplemented
        else:
            self.x *= other
            self.y *= other
            self.z *= other
            return self

    def __idiv__(self, other):
        "/= operation. Like the normal one except without duplication."
        if isinstance(other, Vec):
            return NotImplemented
        else:
            self.x /= other
            self.y /= other
            self.z /= other
            return self

    def __eq__(self, other):
        '''Equality test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        '''
        if isinstance(other, Vec):
            return other.x == self.x and other.y == self.y and other.z == self.z
        elif isinstance(other, tuple):
            return self.x == other[0] and self.y == other[1] and self.z == other[2]
        else:
            try:
                return self.mag() == float(other)
            except ValueError:
                return NotImplemented

    def __lt__(self, other):
        '''A<B test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        '''
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
        '''A<=B test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        '''
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
        '''A>B test.

        Two Vectors are compared based on the axes.
        A Vector can be compared with a 3-tuple as if it was a Vector also.
        Otherwise the other value will be compared with the magnitude.
        '''
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
        "Set this vector's values to be the maximum between ourself and the other vector."
        if self.x < other.x:
            self.x = other.x
        if self.y < other.y:
            self.y = other.y
        if self.z < other.z:
            self.z = other.z


    def min(self, other):
        "Set this vector's values to be the minimum between ourself and the other vector."
        if self.x > other.x:
            self.x = other.x
        if self.y > other.y:
            self.y = other.y
        if self.z > other.z:
            self.z = other.z

    def mag(self):
        '''Compute the distance from the vector and the origin.'''
        if self.z == 0:
            return math.sqrt(self.x**2+self.y**2)
        else:
            return math.sqrt(self.x**2 + self.y**2 + self.z**2)



    def join(self, delim=', '):
        '''Return a string with all numbers joined by the passed delimiter.

        This strips off the .0 if no decimal portion exists.
        '''
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
        return str(x) + delim + str(y) + delim + str(z)

    def __str__(self):
        "Return a user-friendly representation of this vector."
        if self.z == 0:
            return "(" + str(self.x) + ", " + str(self.y) + ")"
        else:
            return "(" + self.join() + ")"


    def __repr__(self):
        "Code required to reproduce this vector."
        return "Vec(" + self.join() + ")"

    def __iter__(self):
        "Allow iterating through the dimensions."
        yield self.x
        yield self.y
        yield self.z

    def __getitem__(self, ind):
        '''Allow reading values by index instead of name if desired.

        This accepts either 0,1,2 or 'x','y','z' to read values.
        Useful in conjunction with a loop to apply commands to all values.
        '''
        if ind == 0 or ind == "x":
            return self.x
        elif ind == 1 or ind == "y":
            return self.y
        elif ind == 2 or ind == "z":
            return self.z
        else:
            return NotImplemented

    def __setitem__(self, ind, val):
        '''Allow editing values by index instead of name if desired.

        This accepts either 0,1,2 or 'x','y','z' to edit values.
        Useful in conjunction with a loop to apply commands to all values.
        '''
        if ind == 0 or ind == "x":
            self.x = float(val)
        elif ind == 1 or ind == "y":
            self.y = float(val)
        elif ind == 2 or ind == "z":
            self.z = float(val)
        else:
            return NotImplemented

    def as_tuple(self):
        "Return the Vector as a tuple."
        return (self.x, self.y, self.z)

    def len_sq(self):
        "Return the magnitude squared, which is slightly faster."
        if self.z == 0:
            return self.x**2 + self.y**2
        else:
            return self.x**2 + self.y**2 + self.z**2

    def __len__(self):
        '''The len() of a vector is the number of non-zero axis.'''
        return sum(1 for axis in (self.x, self.y, self.z) if axis != 0)

    def __contains__(self, key):
        '''Vectors contain the three axes.'''
        return key in 'xyz'

    def __reversed__(self):
        '''The reversed form of a Vector has inverted axes.'''
        return Vec(-self.x, -self.y, -self.z)

    def norm(self):
        "Normalise the Vector by transforming it to have a magnitude of 1 but the same direction."
        print(self.x, self.y, self.z)
        if self.x == 0 and self.y == 0 and self.z == 0:
            # Don't do anything for this, and don't copy
            return self
        else:
            return self / self.mag()

    def dot(self, other):
        '''Return the dot product of both Vectors.'''
        return (
            self.x * other.x +
            self.y * other.y +
            self.z * other.z
            )

    def cross(self, other):
        '''Return the cross product of both Vectors.'''
        return Vec(
            self.y*other.z - self.z*other.y,
            self.z*other.x - self.x*other.z,
            self.x*other.y - self.y*other.x,
            )

    len = mag
    mag_sq = len_sq
    __truediv__ = __div__
    __itruediv__ = __idiv__

abc.Mapping.register(Vec)
abc.MutableMapping.register(Vec)