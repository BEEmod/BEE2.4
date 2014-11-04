import math

from property_parser import Property

def clean_line(dirty_line):
    "Removes extra spaces and comments from the input."
    if isinstance(dirty_line, bytes):
        dirty_line=dirty_line.decode() # convert bytes to strings if needed
    line = dirty_line.strip()
    if line.startswith("\\\\") or line.startswith("//"):
        line = ""
    # TODO: Actually strip comments off of the end of all lines
    return line
    
def is_identifier(name, forbidden='{}\'"'):
    "Check to see if any forbidden characters are part of a canidate name."
    for t in name:
        if t in forbidden:
            return False
    return True
    
def con_log(*text):
    print(*text, flush=True) 

# VMF specific        


class Vec:
    "A 3D Vector. This has most standard Vector functions."
    __slots__ = ('x', 'y', 'z')
    
    def __init__(self, x = 0, y=0, z=0):
        if isinstance(x, tuple) or isinstance(x, list):
            self.x = float(x[0])
            self.y = float(x[1])
            self.z = float(x[2])
        else:
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)
        
    def copy(self):
        return Vec(self.x, self.y, self.z)
    
    def __add__(self,other):
        "+ operation. This works on numbers (adds to all axes), or other Vectors (adds to just our one)."
        if isinstance(other, Vec):
            return Vec(self.x+other.x, self.y+other.y, self.z+other.z)
        else:
            return Vec(self.x+other, self.y+other,self.z+other)
            

            
    def __sub__(self,other):
        "- operation. This works on numbers (adds to all axes), or other Vectors (adds to just our one)."
        if isinstance(other, Vec):
            return Vec(self.x-other.x, self.y-other.y, self.y+other.y, self.z+other.z)
        else:
            return Vec(self.x-other, self.y-other)
            
    
    def __mul__(self, other):
        "Multiply the Vector by a scalar."
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x * other, self.y * other, self.z * other)
            
    def __div__(self, other):
        "Divide the Vector by a scalar."
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x / other, self.y / other, self.z / other)
            
    def __floordiv__(self, other):
        "Divide the Vector by a scalar, discarding the remainder."
        if isinstance(other, Vec):
            return NotImplemented
        else:
            return Vec(self.x // other, self.y // other, self.z // other)
            
    def __mod__(self, other):
        "Compute the remainder of the Vector divided by a scalar."
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
        if isinstance(other, Vec):
            return other.x == self.x and other.y==self.y and other.z == self.z
        elif isinstance(other, tuple):
            return self.x == other[0] and self.y == other[1] and self.z == other[2]
        else:
            try:
                return self.mag() == float(other)
            except ValueError:
                return NotImplemented
                
    def __lt__(self, other):
        if isinstance(other, Vec):
            return self.x < other.x and self.y < other.y and self.z < other.z
        elif isinstance(other, tuple):
            return self.x < other[0] and self.y < other[1] and self.z < other[2]
        else:
            try:
                return self.mag() < float(other)
            except ValueError:
                return NotImplemented
                
    def __le__(self, other):
        if isinstance(other, Vec):
            return self.x <= other.x and self.y <= other.y and self.z <= other.z
        elif isinstance(other, tuple):
            return self.x <= other[0] and self.y <= other[1] and self.z <= other[2]
        else:
            try:
                return self.mag() <= float(other)
            except ValueError:
                return NotImplemented
                
    def __gt__(self, other):
        if isinstance(other, Vec):
            return self.x>other.x and self.y.other.y and self.z<other.z
        elif isinstance(other, tuple):
            return self.x>other[0] and self.y>other[1] and self.z>other[2]
        else:
            try:
                return self.mag() > float(other)
            except ValueError:
                return NotImplemented    

    def max(self, other):
        "Set this vector's values to be the maximum between ourself and the other vector."
        if self.x > other.x:
            self.x = other.x
        if self.y > other.y:
            self.y = other.y
        if self.z > other.z:
            self.z = other.z
            
            
    def min(self, other):
        "Set this vector's values to be the minimum between ourself and the other vector."
        if self.x < other.x:
            self.x = other.x
        if self.y < other.y:
            self.y = other.y
        if self.z < other.z:
            self.z = other.z
                
    def mag(self):
        if self.z == 0:
            return math.sqrt(self.x**2+self.y**2)
        else:
            return math.sqrt(self.x**2 + self.y**2 + self.z**2)
            
    def __len__(self):
        "Length gives the magnitude."
        return int(self.mag())
        
    def join(self, delim=', '):
        "Return a string with all numbers joined by the passed delimiter."
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
        "Allow referencing by index instead of name if desired."
        if ind == 0 or ind == "x":
            return self.x
        elif ind == 1 or ind == "y":
            return self.y
        elif ind == 2 or ind == "z":
            return self.z
        else:
            return NotImplemented
    
    def __setitem__(self, ind, val):
        "Allow referencing by index instead of name if desired."
        if ind == 0 or ind == "x":
            self.x = float(val)
        elif ind == 1 or ind == "y":
            self.y = float(val)
        elif ind == 2 or ind == "z":
            self.y = float(val)
        else:
            return NotImplemented
            
    def as_tuple(self):
        "return the Vector as a tuple."
        return (self.x, self.y, self.z)
            
    def len_sq(self):
        "Return the magnitude squared, which is slightly faster."
        if self.z == 0:
            return self.x**2 + self.y**2
        else:
            return self.x**2 + self.y**2 + self.z**2
            
    def keys(self):
        return "x", "y", "z"
        
    def norm(self):
        "Normalise the Vector by transforming it to have a magnitude of 1 but the same direction."
        if self.x == 0 and self.y==0 and self.z == 0:
            # Don't do anything for this, and don't copy
            return self
        else:
            return self / len(self)
    
    def dot(a, b):
        "Return the dot product of both Vectors."
        return a.x*b.x + a.y*b.y + a.z*b.z
        
    def cross(a,b):
        "Return the cross product of both Vectors."
        return Vec(a.y*b.z - a.z*b.y,
                   a.z*b.x - a.x*b.z,
                   a.x*b.y - a.y*b.x)
    len = mag
    mag_sq = len_sq
    __truediv__ = __div__
    __itruediv__ = __idiv__